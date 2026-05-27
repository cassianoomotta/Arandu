import asyncio
import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any, Set
import feedparser
import httpx
from bs4 import BeautifulSoup

from database.connection import get_db_session
from database.models import Source, News, SendStatus
from core.processor import get_recent_titles_from_db, process_article, is_similar_to_recent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("news_scraper")

# Constants
DEFAULT_FALLBACK_IMAGE = "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?q=800"
REQUEST_TIMEOUT = 10.0
CONCURRENT_REQUESTS_LIMIT = 5
MAX_ITEMS_PER_FEED = 15  # Limit processing to latest 15 entries per run

# Realistic User-Agent header to avoid blockages from Cloudflare or Web Application Firewalls
USER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Semaphore to restrict the number of concurrent outgoing HTTP requests
sem = asyncio.Semaphore(CONCURRENT_REQUESTS_LIMIT)


def generate_title_hash(title: str) -> str:
    """
    Generates a unique SHA-256 hash of the title (normalized to lowercase) 
    for exact duplicate prevention.
    """
    normalized_title = title.strip().lower()
    return hashlib.sha256(normalized_title.encode("utf-8")).hexdigest()


def extract_og_image(html_content: str) -> str | None:
    """
    Extracts the image URL from Open Graph or Twitter metadata tags in the HTML.
    """
    try:
        soup = BeautifulSoup(html_content, "lxml")
    except Exception:
        # Fallback parser if lxml is not fully loaded/available
        soup = BeautifulSoup(html_content, "html.parser")

    # 1. Check Open Graph image tag
    og_tag = soup.find("meta", property="og:image")
    if og_tag and og_tag.get("content"):
        return og_tag["content"].strip()

    # 2. Check Twitter Card image tag
    twitter_tag = soup.find("meta", name="twitter:image")
    if twitter_tag and twitter_tag.get("content"):
        return twitter_tag["content"].strip()

    # 3. Check Schema.org image tag
    schema_tag = soup.find("meta", itemprop="image")
    if schema_tag and schema_tag.get("content"):
        return schema_tag["content"].strip()

    return None


async def fetch_og_image_with_fallback(
    client: httpx.AsyncClient, 
    url: str
) -> str:
    """
    Asynchronously requests the article's web page, parses its HTML,
    and returns its og:image. In case of network error, HTTP error, 
    or parsing failure, returns the fallback image url.
    """
    async with sem:  # Throttles requests based on semaphore limit
        try:
            logger.debug(f"Fetching URL: {url}")
            response = await client.get(
                url, 
                headers=USER_HEADERS, 
                timeout=REQUEST_TIMEOUT, 
                follow_redirects=True
            )
            
            if response.status_code == 200:
                img_url = extract_og_image(response.text)
                if img_url:
                    logger.debug(f"Found image: {img_url} for URL: {url}")
                    return img_url
                logger.debug(f"No meta image found for {url}. Using fallback.")
            else:
                logger.warning(
                    f"HTTP status {response.status_code} while fetching {url}"
                )
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error for {url}: {str(e)}")
        except httpx.RequestError as e:
            logger.warning(f"Connection/Network error for {url}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error parsing page {url}: {str(e)}")
            
        return DEFAULT_FALLBACK_IMAGE


async def fetch_rss_feed(
    client: httpx.AsyncClient, 
    source_name: str, 
    rss_url: str
) -> str | None:
    """
    Fetches the raw XML/RSS content from a feed URL asynchronously.
    """
    try:
        response = await client.get(
            rss_url, 
            headers=USER_HEADERS, 
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True
        )
        if response.status_code == 200:
            return response.text
        logger.error(
            f"Failed to fetch feed {source_name} ({rss_url}): HTTP {response.status_code}"
        )
    except Exception as e:
        logger.error(
            f"Error fetching feed {source_name} ({rss_url}): {str(e)}"
        )
    return None


async def process_source(
    client: httpx.AsyncClient, 
    source: Source, 
    existing_hashes: Set[str], 
    existing_links: Set[str]
) -> List[Dict[str, Any]]:
    """
    Fetches and parses a single source feed. Identifies new articles,
    and returns a list of dictionaries with parsed metadata.
    """
    logger.info(f"Processing feed for: {source.name}...")
    
    xml_content = await fetch_rss_feed(client, source.name, source.rss_url)
    if not xml_content:
        return []

    # Parse RSS using feedparser (parse in-memory string safely)
    feed = feedparser.parse(xml_content)
    new_articles = []

    # Limit entries to prevent overloading/duplicate historic runs
    entries = feed.entries[:MAX_ITEMS_PER_FEED]
    
    for entry in entries:
        title = entry.get("title")
        link = entry.get("link")
        
        if not title or not link:
            continue
            
        # 1. Deduplication checking in memory
        hash_title = generate_title_hash(title)
        if hash_title in existing_hashes or link in existing_links:
            continue  # Already exists, skip scraping page and DB queries
            
        # Parse published date
        published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if published_parsed:
            published_at = datetime(*published_parsed[:6])
        else:
            published_at = datetime.utcnow()
            
        new_articles.append({
            "source_id": source.id,
            "original_title": title,
            "link": link,
            "original_published_at": published_at,
            "hash_title": hash_title
        })
        
    logger.info(
        f"Feed {source.name} has {len(new_articles)} new articles to process."
    )
    return new_articles


async def main():
    logger.info("Initializing async news scraper...")
    
    # 1. Retrieve Active Sources and existing keys from Database
    try:
        with get_db_session() as session:
            active_sources = (
                session.query(Source)
                .filter(Source.active == True)
                .all()
            )
            # Expunge sources so we can read them asynchronously outside transaction
            session.expunge_all()
            
            # Fetch existing hashes and links to avoid duplicating
            db_news = session.query(News.hash_title, News.link).all()
            existing_hashes = {n.hash_title for n in db_news}
            existing_links = {n.link for n in db_news}
            
            # Load recent titles for deduplication (last 24 hours)
            recent_titles = get_recent_titles_from_db()
    except Exception as e:
        logger.critical(f"Database error during initialization: {str(e)}")
        return

    if not active_sources:
        logger.warning("No active news sources found in the database. Exiting.")
        return

    logger.info(f"Loaded {len(active_sources)} active sources from database.")
    
    # Map sources by ID for quick lookup
    sources_by_id = {src.id: src for src in active_sources}
    
    # 2. Asynchronously fetch all RSS feeds
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # Create tasks to fetch all feeds concurrently
        feed_tasks = [
            process_source(client, src, existing_hashes, existing_links)
            for src in active_sources
        ]
        
        # Await all feeds to finish processing
        feed_results = await asyncio.gather(*feed_tasks)
        
        # Flatten the list of new articles
        all_new_articles = [art for sublist in feed_results for art in sublist]
        
        if not all_new_articles:
            logger.info("No new articles discovered. Crawling cycle completed.")
            return
            
        logger.info(
            f"Discovered a total of {len(all_new_articles)} new articles. "
            "Filtering duplicates in current batch..."
        )
        
        # 3. Filter duplicates in the current batch (in-feed deduplication)
        unique_new_articles = []
        for art in all_new_articles:
            current_batch_titles = [u["original_title"] for u in unique_new_articles]
            if is_similar_to_recent(art["original_title"], current_batch_titles, threshold=0.8):
                logger.info(f"In-feed duplicate skipped: '{art['original_title'][:50]}'")
                continue
            unique_new_articles.append(art)
            
        if not unique_new_articles:
            logger.info("All new articles were duplicate. Crawling cycle completed.")
            return

        logger.info(
            f"Processing and enriching {len(unique_new_articles)} articles concurrently..."
        )
        
        # 4. Asynchronously enrich each article (fetch og:image + process metadata)
        async def enrich_item(article: dict) -> dict | None:
            # A. Fetch og:image asynchronously
            img_url = await fetch_og_image_with_fallback(client, article["link"])
            article["image_url"] = img_url
            
            # Get matching source model
            source = sources_by_id[article["source_id"]]
            
            # B. Run CPU-bound or blocking API operations (translation, similarity against DB, AI summary) in a thread pool
            processed = await asyncio.to_thread(process_article, article, source, recent_titles)
            return processed

        # Gather results concurrently
        enrich_tasks = [enrich_item(art) for art in unique_new_articles]
        enriched_results = await asyncio.gather(*enrich_tasks)
        
        # Filter out None values (e.g. articles skipped due to similarity to DB articles)
        final_articles = [art for art in enriched_results if art is not None]
        
        if not final_articles:
            logger.info("No new articles remained after processing and similarity checks.")
            return

        # 5. Insert processed articles into database in a single transaction
        try:
            with get_db_session() as session:
                news_objects = []
                for art in final_articles:
                    # Construct SQLAlchemy model instance
                    news_obj = News(
                        source_id=art["source_id"],
                        original_title=art["original_title"],
                        translated_title=art["translated_title"],
                        link=art["link"],
                        ai_summary=art["ai_summary"],
                        image_url=art["image_url"],
                        original_published_at=art["original_published_at"],
                        hash_title=art["hash_title"],
                        reduced_key=art["reduced_key"],
                        send_status=SendStatus.PENDENTE
                    )
                    news_objects.append(news_obj)
                
                session.add_all(news_objects)
                # Commit is executed automatically upon exiting the context manager
                
            logger.info(
                f"Successfully processed and saved {len(final_articles)} new news articles to the database."
            )
        except Exception as e:
            logger.error(f"Failed to bulk write news to database: {str(e)}")

        # 6. Dispatch pending notifications to Telegram
        logger.info("Scraper Dispatcher: Dispatching pending notifications...")
        try:
            from core.notifier import TelegramNotifier, dispatch_pending_notifications
            notifier = TelegramNotifier()
            sent_count = await dispatch_pending_notifications(notifier)
            logger.info(f"Scraper Dispatcher: Successfully dispatched {sent_count} notifications.")
        except Exception as e:
            logger.error(f"Scraper Dispatcher: Notification dispatch failed: {str(e)}")

        # 7. Database news cleanup (purge articles older than 20 days)
        logger.info("Scraper Cleanup: Starting old news purge (retention: 20 days)...")
        try:
            from datetime import timedelta
            with get_db_session() as session:
                cutoff_date = datetime.utcnow() - timedelta(days=20)
                deleted_count = session.query(News).filter(
                    News.created_at < cutoff_date
                ).delete(synchronize_session="fetch")
                logger.info(f"Scraper Cleanup: Purged {deleted_count} news articles older than 20 days.")
        except Exception as e:
            logger.error(f"Scraper Cleanup: News cleanup failed: {str(e)}")


if __name__ == "__main__":
    # Standard entry point to execute async main loop
    asyncio.run(main())
