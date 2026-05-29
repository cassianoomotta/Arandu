import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger("news_agent.utils")

# Set of buzzwords/hype indicators to penalize in the heuristic score
HYPE_WORDS = {
    "revolucionar", "revolucionário", "revoluciona", "matador de", "choca", "assustador", 
    "surpreende", "inacreditável", "você não vai acreditar", "promete",
    "destruir", "fim do", "morte do", "hype", "segredo", "revelado", "bomba"
}

# Whitelist fields keywords for weighting
TECH_IA_KEYWORDS = {
    "ia", "ai", "llm", "gpt", "gemini", "claude", "nvidia", "openai", "copilot", 
    "robô", "robot", "automação", "chip", "semicondutor", "deep learning", 
    "neural", "algoritmo", "computador", "quantum", "quântico", "cibersegurança", 
    "hacker", "cloud", "nuvem", "hardware", "open source", "linux", "git", 
    "python", "banco de dados", "rust", "c++", "apple", "microsoft", "google",
    "inteligência", "artificial", "tecnologia", "tecnológica", "tecnológico", 
    "desenvolvimento", "software", "dev"
}

BUSINESS_KEYWORDS = {
    "startup", "startups", "venture capital", "saas", "aporte", "captou", "investimento",
    "investidores", "fintech", "aquisição", "m&a", "fusão", "ceo", "funding", "rodada",
    "valuation", "ipca", "bolsa", "mercado", "negócio", "negócios", "bilhão", "milhão"
}

SCIENCE_KEYWORDS = {
    "pesquisa", "cientistas", "universidade", "paper", "descoberta", "estudo", "científico",
    "mit", "harvard", "stanford", "nature", "science", "revista", "avancem", "física",
    "química", "medicina", "disruptivo", "breakthrough"
}

def calculate_local_heuristic_score(title: str) -> int:
    """
    Calculates a quick local score (0 to 10) based on keyword matching.
    Helps to prioritize which news items are sent to Phase 1 first if the pool is large.
    """
    score = 5  # Base score
    normalized_title = title.lower()
    words = set(re.findall(r'\b\w+\b', normalized_title))
    
    # 1. Tech & IA matching
    tech_matches = words.intersection(TECH_IA_KEYWORDS)
    score += min(3, len(tech_matches))
    
    # 2. Business matching
    biz_matches = words.intersection(BUSINESS_KEYWORDS)
    score += min(2, len(biz_matches))
    
    # 3. Science matching
    science_matches = words.intersection(SCIENCE_KEYWORDS)
    score += min(2, len(science_matches))
    
    # 4. Hype penalties
    hype_matches = words.intersection(HYPE_WORDS)
    score -= min(3, len(hype_matches) * 2)
    
    # Ensure score is strictly between 0 and 10
    return max(0, min(10, score))


class ExecutionMetrics:
    """Utility to track time, costs, and token usage during an agent run."""
    def __init__(self):
        self.start_time = 0.0
        self.end_time = 0.0
        self.api_calls = 0
        self.filtered_locally = 0
        self.processed_p1 = 0
        self.processed_p2 = 0
        self.success = True
        self.errors = []

    def start(self):
        import time
        self.start_time = time.time()

    def stop(self, success: bool = True):
        import time
        self.end_time = time.time()
        self.success = success

    @property
    def duration(self) -> float:
        if self.start_time == 0.0:
            return 0.0
        end = self.end_time if self.end_time > 0.0 else time.time()
        return round(end - self.start_time, 2)

    def report(self) -> str:
        status_str = "SUCCESS" if self.success else "FAILED"
        return (
            f"--- Execution Report [{status_str}] ---\n"
            f"Duration: {self.duration}s\n"
            f"API Calls made: {self.api_calls}\n"
            f"News filtered locally: {self.filtered_locally}\n"
            f"News scored in Phase 1: {self.processed_p1}\n"
            f"News detailed in Phase 2: {self.processed_p2}\n"
            f"Errors encountered: {len(self.errors)}"
        )
