import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional

from deep_translator import GoogleTranslator
from openai import OpenAI

from database.config import settings
from database.connection import get_db_session
from database.models import News, Source, SourceType

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("news_processor")

# Initialize OpenAI client if API key is provided
openai_client = None
if settings.OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")


def get_recent_titles_from_db(hours_limit: int = 24) -> List[str]:
    """
    Retrieves all news titles processed in the last 24 hours for similarity checks.
    """
    since_time = datetime.utcnow() - timedelta(hours=hours_limit)
    try:
        with get_db_session() as session:
            recent_news = (
                session.query(News.original_title)
                .filter(News.created_at >= since_time)
                .all()
            )
            return [news.original_title for news in recent_news]
    except Exception as e:
        logger.error(f"Failed to fetch recent titles from database: {str(e)}")
        # In case of DB failure, return empty list to not halt the pipeline
        return []


def calculate_similarity(title_a: str, title_b: str) -> float:
    """
    Computes a simple ratio of similarity between two strings using SequenceMatcher.
    Normalized to lowercase and stripped.
    """
    str_a = title_a.strip().lower()
    str_b = title_b.strip().lower()
    return SequenceMatcher(None, str_a, str_b).ratio()


def is_similar_to_recent(
    title: str, 
    recent_titles: List[str], 
    threshold: float = 0.8
) -> bool:
    """
    Compares the current title against the list of recently scraped titles.
    Returns True if similarity exceeds the threshold percentage.
    """
    for recent in recent_titles:
        similarity = calculate_similarity(title, recent)
        if similarity >= threshold:
            logger.warning(
                f"Similarity match found! '{title[:35]}...' "
                f"is {similarity:.2%} similar to recent '{recent[:35]}...'."
            )
            return True
    return False


def translate_text(text: str, target_lang: str = "pt") -> str:
    """
    Translates a title into Portuguese using deep-translator (Google Translator API).
    Includes failure fallback that returns the original text to prevent execution stops.
    """
    if not text:
        return ""
    try:
        logger.info(f"Translating: '{text[:40]}...'")
        translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
        return translated
    except Exception as e:
        logger.error(f"Translation API failed for text '{text[:40]}...': {str(e)}")
        # Fallback: Return original text to keep the news moving
        return text


def generate_ai_summary(title: str, source_name: str) -> str:
    """
    Generates a 3-bullet-point executive summary focusing on business and tech using OpenAI LLM.
    If the OpenAI API fails or is unconfigured, falls back to a clean mock summary.
    """
    # 1. Check if client is initialized
    if not openai_client:
        logger.warning("OpenAI API key is missing. Using fallback summary generator.")
        return (
            f"- Notícia originada do portal {source_name}.\n"
            f"- Requer análise manual devido à ausência de chaves de API de IA.\n"
            f"- Título do Artigo: {title}"
        )

    # Prompt Engineering for curation
    system_prompt = (
        "Você é um engenheiro de dados e analista de inteligência de negócios. "
        "Sua tarefa é gerar um resumo executivo curto de no máximo 3 pontos-chave (bullet points), "
        "focado em tecnologia e oportunidades de negócios, baseado no título da notícia fornecido. "
        "O formato de saída deve conter estritamente 3 marcadores usando hífen ('-'). Seja claro e objetivo."
    )
    
    try:
        response = openai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Título da notícia: {title}"}
            ],
            max_tokens=150,
            temperature=0.3
        )
        summary = response.choices[0].message.content
        if summary:
            return summary.strip()
            
    except Exception as e:
        logger.error(f"OpenAI API call failed for '{title[:40]}...': {str(e)}")
        
    # Fallback in case of call errors (rate limit, credit expiration, connection issues)
    return (
        f"- Notícia de tecnologia relevante reportada por {source_name}.\n"
        f"- Coleta executada com sucesso. Resumo automático indisponível (limite de API/Timeout).\n"
        f"- Assunto principal: {title}"
    )


def process_article(
    article_data: Dict[str, Any], 
    source: Source, 
    recent_titles: List[str]
) -> Dict[str, Any] | None:
    """
    Applies the full processing pipeline to a newly scraped news item:
    1. Check for similarity deduplication.
    2. Check source type; translate title if SourceType.INTERNACIONAL.
    3. Generate executive summary using LLM.
    
    Returns the processed dictionary ready for DB save, or None if skipped.
    """
    title = article_data["original_title"]
    
    # 1. Deduplication check (Similarity > 80%)
    if is_similar_to_recent(title, recent_titles, threshold=0.8):
        logger.info(f"Skipping article (similar news exists): '{title[:50]}'")
        return None

    processed_data = article_data.copy()
    
    # 2. Translation logic
    if source.type == SourceType.INTERNACIONAL:
        translated_title = translate_text(title, target_lang="pt")
        processed_data["translated_title"] = translated_title
    else:
        # For national news, translated title can be the original or empty
        processed_data["translated_title"] = title

    # 3. AI Summary Generation
    # Uses translated title for better prompt context if available
    summary_seed_title = processed_data.get("translated_title") or title
    processed_data["ai_summary"] = generate_ai_summary(
        title=summary_seed_title, 
        source_name=source.name
    )
    
    # Define placeholder reduced key for search terms
    processed_data["reduced_key"] = " ".join(
        [word.lower() for word in summary_seed_title.split() if len(word) > 3]
    )[:255]

    return processed_data
