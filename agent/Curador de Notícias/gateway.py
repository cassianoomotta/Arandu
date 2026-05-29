import logging
import httpx
import time
import json
from typing import Dict, Any, List, Optional
from database.config import settings
from .schemas import get_gemini_schema
from core.processor import (
    get_gemini_usage_today,
    increment_gemini_usage,
    record_rate_limit_hit,
    _gemini_api_lock,
    _last_gemini_call_time
)

logger = logging.getLogger("news_agent.gateway")

class GeminiGateway:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.default_models = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
        
    def _verify_quota(self):
        """Verifies if the daily token/request cota has been reached."""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")
        try:
            usage = get_gemini_usage_today()
            if usage >= settings.GEMINI_DAILY_LIMIT:
                logger.warning(f"Daily API limit reached: {usage}/{settings.GEMINI_DAILY_LIMIT}")
                raise ValueError(f"Gemini API daily limit of {settings.GEMINI_DAILY_LIMIT} reached.")
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to check daily quota: {e}")

    def _enforce_rate_limit(self):
        """Enforces a strict 12-second delay between calls for the free tier."""
        global _last_gemini_call_time
        with _gemini_api_lock:
            now = time.time()
            elapsed = now - _last_gemini_call_time
            required_gap = 12.0
            if elapsed < required_gap:
                sleep_needed = required_gap - elapsed
                logger.info(f"Rate limiter: sleeping for {sleep_needed:.2f}s to respect RPM...")
                time.sleep(sleep_needed)
            _last_gemini_call_time = time.time()

    def call_structured_api(
        self, 
        prompt: str, 
        system_instruction: str, 
        response_model: Any,
        temperature: float = 0.2,
        max_tokens: int = 2048
    ) -> Dict[str, Any]:
        """
        Sends a request to the Gemini API requesting a structured JSON response
        matching the provided Pydantic schema model.
        """
        self._verify_quota()
        self._enforce_rate_limit()
        
        try:
            increment_gemini_usage()
        except Exception as e:
            logger.error(f"Failed to log usage: {e}")

        # Generate the JSON schema from the Pydantic model
        schema = get_gemini_schema(response_model)

        last_error = None
        for model in self.default_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    "responseMimeType": "application/json",
                    "responseSchema": schema
                }
            }
            
            headers = {"Content-Type": "application/json"}
            max_attempts = 4
            base_delay = 3.0
            
            for attempt in range(max_attempts):
                try:
                    with httpx.Client(timeout=45.0) as client:
                        response = client.post(url, json=payload, headers=headers)
                        
                        if response.status_code == 429:
                            record_rate_limit_hit()
                            delay = base_delay * (2 ** attempt)
                            logger.warning(f"Rate limit (429) hit for {model}. Retrying in {delay:.1f}s...")
                            time.sleep(delay)
                            continue
                            
                        response.raise_for_status()
                        data = response.json()
                        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                        
                        # Validate that it is valid JSON
                        parsed_json = json.loads(raw_text.strip())
                        logger.info(f"Successfully received and parsed structured output using model: {model}")
                        return parsed_json
                        
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed for model {model}: {e}")
                    if attempt == max_attempts - 1:
                        last_error = e
                    else:
                        time.sleep(2.0)
            
        if last_error:
            raise last_error
        raise ValueError("Failed to obtain a structured response from all models.")
