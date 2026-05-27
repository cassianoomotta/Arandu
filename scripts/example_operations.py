import sys
import os

# Add project root to sys.path for standalone execution
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import hashlib
from datetime import datetime
import logging
from sqlalchemy.exc import IntegrityError
from database.connection import get_db_session
from database.models import Source, News, SendStatus

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def generate_title_hash(title: str) -> str:
    """
    Generates a SHA-256 hash of the title (normalized to lowercase) for exact duplicate detection.
    """
    normalized_title = title.strip().lower()
    return hashlib.sha256(normalized_title.encode('utf-8')).hexdigest()

def insert_news_article(
    source_rss_url: str,
    original_title: str,
    translated_title: str,
    link: str,
    ai_summary: str,
    image_url: str,
    reduced_key: str,
    similarity_vector: list = None
) -> bool:
    """
    Safely inserts a news article, generating its hash and relating it to its Source.
    Returns True if successfully inserted, False otherwise.
    """
    hash_title = generate_title_hash(original_title)
    
    try:
        with get_db_session() as session:
            # 1. Retrieve the source by RSS URL
            source = session.query(Source).filter(Source.rss_url == source_rss_url).first()
            if not source:
                logger.error(f"Source with RSS {source_rss_url} not found. Cannot insert article.")
                return False
            
            # 2. Check if hash_title or link already exists (Proactive check for custom logging)
            duplicate_news = session.query(News).filter(
                (News.hash_title == hash_title) | (News.link == link)
            ).first()
            
            if duplicate_news:
                logger.warning(
                    f"Deduplication triggered! Article '{original_title[:40]}...' "
                    f"already exists in DB (ID: {duplicate_news.id}). Skipping."
                )
                return False

            # 3. Create news instance
            new_article = News(
                source_id=source.id,
                original_title=original_title,
                translated_title=translated_title,
                link=link,
                ai_summary=ai_summary,
                image_url=image_url,
                original_published_at=datetime.utcnow(),
                hash_title=hash_title,
                reduced_key=reduced_key,
                similarity_vector=similarity_vector,
                send_status=SendStatus.PENDENTE
            )
            
            session.add(new_article)
            # When the with-block exits, session.commit() is called automatically by the context manager.
            logger.info(f"Article successfully inserted: '{original_title[:40]}...'")
            return True

    except IntegrityError as ie:
        # Handles concurrent write collisions or edge-case constraints
        logger.error(f"Database integrity violation occurred: {str(ie)}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while inserting article: {str(e)}")
        return False

def update_telegram_status(news_id: int, status: SendStatus) -> bool:
    """
    Updates the telegram sending status of a news item.
    """
    try:
        with get_db_session() as session:
            news_item = session.query(News).filter(News.id == news_id).first()
            if news_item:
                news_item.send_status = status
                logger.info(f"Updated News ID {news_id} status to '{status.value}'")
                return True
            logger.warning(f"News with ID {news_id} not found.")
            return False
    except Exception as e:
        logger.error(f"Failed to update send status: {str(e)}")
        return False

def get_pending_news_to_send() -> list:
    """
    Retrieves all pending news articles using the 'ix_news_send_status' index.
    """
    try:
        with get_db_session() as session:
            pending_articles = (
                session.query(News)
                .filter(News.send_status == SendStatus.PENDENTE)
                .order_by(News.original_published_at.desc())
                .all()
            )
            # Expelling news objects from session so they can be read outside context safely
            session.expunge_all()
            return pending_articles
    except Exception as e:
        logger.error(f"Failed to fetch pending news: {str(e)}")
        return []

if __name__ == "__main__":
    logger.info("Starting Example Operations demonstration...")
    
    # URL of TechCrunch which was seeded in init_db
    source_url = "https://techcrunch.com/feed/"
    
    # 1. Attempt to insert a new article
    insert_news_article(
        source_rss_url=source_url,
        original_title="AI is changing entrepreneurship in 2026",
        translated_title="A IA está mudando o empreendedorismo em 2026",
        link="https://techcrunch.com/2026/05/27/ai-entrepreneurship",
        ai_summary="Um resumo gerado por IA indicando o crescimento do empreendedorismo aliado a IA.",
        image_url="https://techcrunch.com/wp-content/uploads/2026/05/ai.jpg",
        reduced_key="ai entrepreneurship 2026 technology start ups",
        similarity_vector=[0.12, -0.45, 0.78, 0.99]  # Example embedding vector
    )
    
    # 2. Attempt to insert the exact same article (Triggering deduplication)
    insert_news_article(
        source_rss_url=source_url,
        original_title="AI is changing entrepreneurship in 2026",
        translated_title="A IA está mudando o empreendedorismo em 2026",
        link="https://techcrunch.com/2026/05/27/ai-entrepreneurship",
        ai_summary="Duplicate attempt.",
        image_url="https://techcrunch.com/wp-content/uploads/2026/05/ai.jpg",
        reduced_key="ai entrepreneurship 2026 technology start ups"
    )
    
    # 3. Retrieve pending articles
    pending = get_pending_news_to_send()
    logger.info(f"Currently pending articles to send: {len(pending)}")
    for item in pending:
        logger.info(f"- ID: {item.id} | Title: {item.original_title} | Hash: {item.hash_title}")
        
        # 4. Simulating sending to telegram and updating status
        update_telegram_status(item.id, SendStatus.ENVIADO_TELEGRAM)
        
    logger.info("Demo operations completed successfully!")
