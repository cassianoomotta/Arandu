import logging
import importlib
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy import or_
from difflib import SequenceMatcher

from database.connection import get_db_session
from database.models import News
from .config import editor_settings
from .scraper_cleaner import fetch_and_clean_content
from .compressor import compress_text
from .schemas import EditorialResponse
from .prompts import EDITORIAL_SYSTEM_PROMPT

logger = logging.getLogger("news_agent.editor.orchestrator")

# Dynamically import GeminiGateway to handle the folder name space
try:
    curador_gateway_mod = importlib.import_module("agent.Curador de Notícias.gateway")
    GeminiGateway = curador_gateway_mod.GeminiGateway
except Exception as e:
    logger.error(f"Failed to dynamically import Curador GeminiGateway: {e}")
    # Local fallback/stub if not found
    class GeminiGateway:
        def call_structured_api(self, *args, **kwargs):
            raise NotImplementedError("GeminiGateway not loaded.")

class EditorExecutivoOrchestrator:
    def __init__(self):
        self.gateway = GeminiGateway()

    def run_editorial_pipeline(self, limit: int = 10) -> str:
        """
        Runs the full editorial processing pipeline synchronously.
        Runs in a dedicated thread to avoid conflicting with existing running event loops.
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.run_editorial_pipeline_async(limit=limit))
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result()

    async def run_editorial_pipeline_async(self, limit: int = 10) -> str:
        logger.info("Initializing Editorial Agent (Editor Executivo) Pipeline...")
        
        try:
            # Clean up stuck 'processando' statuses from crashed runs (older than 2 hours)
            with get_db_session() as session:
                stuck_cutoff = datetime.utcnow() - timedelta(hours=2)
                stuck_count = (
                    session.query(News)
                    .filter(
                        News.editorial_status == "processando",
                        News.updated_at < stuck_cutoff
                    )
                    .update({"editorial_status": "pendente"}, synchronize_session=False)
                )
                if stuck_count > 0:
                    logger.info(f"Reset {stuck_count} stuck articles in 'processando' state back to 'pendente'.")
                    session.commit()

            total_processed = 0
            total_duplicate = 0
            total_failed = 0
            attempted_ids = set()
            daily_limit_hit = False

            while True:
                with get_db_session() as session:
                    # 1. Fetch news articles that are curated and pending editorial processing
                    query = session.query(News).filter(
                        News.is_curated == True,
                        or_(
                            News.editorial_status == "pendente",
                            News.editorial_status == "falha",
                            News.editorial_status == None
                        )
                    )
                    
                    if attempted_ids:
                        query = query.filter(~News.id.in_(list(attempted_ids)))
                        
                    pending_news = (
                        query.order_by(News.created_at.desc())
                        .limit(limit)
                        .all()
                    )
                    
                    if not pending_news:
                        logger.info("No more pending news articles for editorial processing.")
                        break
                    
                    # Fetch recently published articles for theme deduplication (last 48 hours)
                    recent_published = (
                        session.query(News)
                        .filter(
                            News.editorial_status == "publicado",
                            News.created_at >= datetime.utcnow() - timedelta(days=2)
                        )
                        .all()
                    )
                    
                    # Copy properties into simple dicts to avoid DetachedInstanceError outside session
                    pending_data = []
                    for item in pending_news:
                        pending_data.append({
                            "id": item.id,
                            "title": item.translated_title or item.original_title,
                            "link": item.link,
                            "ai_summary": item.ai_summary,
                            "source_name": item.source.name if item.source else "Desconhecida"
                        })
                    
                    recent_published_data = []
                    for pub in recent_published:
                        recent_published_data.append({
                            "id": pub.id,
                            "title": pub.editorial_title or pub.translated_title or pub.original_title
                        })
                    
                    logger.info(f"Batch loaded: found {len(pending_data)} articles pending editorial processing.")
                
                for news_item in pending_data:
                    news_id = news_item["id"]
                    attempted_ids.add(news_id)
                    
                    # Update status to processando to prevent concurrent execution picking it up.
                    # Only proceed if the editorial_status is still 'pendente', 'falha' or None.
                    with get_db_session() as session:
                        db_item = session.query(News).filter(News.id == news_id).first()
                        if db_item and db_item.editorial_status in ["pendente", "falha", None]:
                            db_item.editorial_status = "processando"
                            session.commit()
                        else:
                            logger.info(f"Article ID {news_id} already being processed or completed elsewhere. Skipping.")
                            continue
                    
                    title = news_item["title"]
                    logger.info(f"Processing editorial for: '{title[:50]}...'")
                    
                    # A. Theme Deduplication Check
                    is_duplicate = False
                    for pub in recent_published_data:
                        pub_title = pub["title"]
                        similarity = SequenceMatcher(None, title.lower(), pub_title.lower()).ratio()
                        if similarity >= editor_settings.THEME_SIMILARITY_THRESHOLD:
                            logger.warning(
                                f"Skipping article ID {news_id} - detected high similarity "
                                f"({similarity:.2f}) with published article ID {pub['id']}: '{pub_title[:40]}'"
                            )
                            is_duplicate = True
                            break
                            
                    if is_duplicate:
                        with get_db_session() as session:
                            db_item = session.query(News).filter(News.id == news_id).first()
                            if db_item:
                                db_item.editorial_status = "duplicado"
                                db_item.send_status = "falha"  # Skip Telegram notifications
                                session.commit()
                        total_duplicate += 1
                        continue

                    # Process the article with retry logic and abort on final failure
                    max_retries = 3
                    retry_delay = 2.0
                    success = False
                    is_daily_limit = False
                    
                    for attempt in range(1, max_retries + 1):
                        try:
                            # B. Scraping and Cleaning
                            logger.info(f"Scraping full-text content from: {news_item['link']} (Attempt {attempt}/{max_retries})")
                            clean_content = await fetch_and_clean_content(news_item["link"])
                            
                            # If scraping returns empty content, fall back to title + short RSS summary
                            if not clean_content or len(clean_content.strip()) < 200:
                                logger.warning(f"Scraping returned insufficient text. Falling back to RSS metadata.")
                                clean_content = (
                                    f"Título: {title}\n\n"
                                    f"Resumo do RSS: {news_item['ai_summary'] or ''}"
                                )
                            
                            # C. Local Semantic Compression
                            compressed = compress_text(
                                clean_content, 
                                min_words=editor_settings.MIN_COMPRESSION_WORDS, 
                                max_words=editor_settings.MAX_COMPRESSION_WORDS
                            )
                            logger.info(f"Compressed content to {len(compressed.split())} words.")

                            # D. Gemini Call
                            prompt = (
                                f"Notícia Original para Processamento Editorial:\n\n"
                                f"Fonte original: {news_item['source_name']}\n"
                                f"Título da notícia: {title}\n\n"
                                f"Conteúdo do Artigo:\n{compressed}"
                            )
                            
                            logger.info("Calling Gemini API for editorial synthesis...")
                            response = self.gateway.call_structured_api(
                                prompt=prompt,
                                system_instruction=EDITORIAL_SYSTEM_PROMPT,
                                response_model=EditorialResponse
                            )
                            
                            # E. Database Persistence
                            headline = response.get("headline", title)
                            summary_dict = response.get("summary", {})
                            category = response.get("category", "Tecnologia")
                            tags = response.get("tags", [])
                            meta_desc = response.get("meta_description", "")
                            scores = response.get("scores", {})
                            
                            # Format markdown summary for fallback and existing layouts
                            formatted_summary = self._format_summary_as_markdown(summary_dict)
                            
                            with get_db_session() as session:
                                db_item = session.query(News).filter(News.id == news_id).first()
                                if db_item:
                                    # Update specific premium fields
                                    db_item.editorial_title = headline
                                    db_item.editorial_summary = json.dumps(summary_dict, ensure_ascii=False)
                                    db_item.editorial_category = category
                                    db_item.editorial_tags = json.dumps(tags, ensure_ascii=False)
                                    db_item.meta_description = meta_desc
                                    db_item.editorial_scores = scores
                                    db_item.editorial_status = "publicado"
                                    
                                    # Overwrite standard fields so the existing UI/Telegram gets the premium version
                                    db_item.translated_title = headline
                                    db_item.ai_summary = formatted_summary
                                    db_item.category = category
                                    
                                    session.commit()
                                    
                            logger.info(f"Successfully published premium editorial for article ID {news_id}")
                            total_processed += 1
                            success = True
                            break  # Break retry loop on success
                            
                        except Exception as e:
                            logger.warning(f"Attempt {attempt} failed for article ID {news_id}: {str(e)}")
                            # Stop processing further items if the daily API limit is reached
                            is_daily_limit = "daily limit" in str(e).lower() or "cota diária" in str(e).lower() or "quota" in str(e).lower()
                            if is_daily_limit:
                                logger.warning("Gemini daily API limit reached. Stopping further editorial processing.")
                                with get_db_session() as session:
                                    db_item = session.query(News).filter(News.id == news_id).first()
                                    if db_item:
                                        db_item.editorial_status = "falha"
                                        session.commit()
                                total_failed += 1
                                break
                                
                            if attempt < max_retries:
                                # Wait with backoff before retrying
                                await asyncio.sleep(retry_delay * attempt)
                            else:
                                # Final attempt failed
                                logger.error(f"All {max_retries} attempts failed to generate editorial for article ID {news_id}: {str(e)}")
                                with get_db_session() as session:
                                    db_item = session.query(News).filter(News.id == news_id).first()
                                    if db_item:
                                        db_item.editorial_status = "falha"
                                        session.commit()
                                total_failed += 1
                    
                    if not success:
                        if is_daily_limit:
                            daily_limit_hit = True
                            logger.error(f"Aborting entire editorial processing because Gemini API limit was hit.")
                            break
                        else:
                            logger.warning(f"Skipping article ID {news_id} due to processing failure, continuing to next article.")
                            continue
                            
                    # Small courtesy delay between successive API calls to respect rate limits (RPM)
                    await asyncio.sleep(2.0)
                
                if daily_limit_hit:
                    break
                
                # Small pause between batches
                await asyncio.sleep(3.0)
                
            report = (
                f"Editorial processing completed: "
                f"{total_processed} published, "
                f"{total_duplicate} duplicates skipped, "
                f"{total_failed} failures."
            )
            logger.info(report)
            return report
            
        except Exception as e:
            logger.exception(f"Critical error in editorial pipeline: {e}")
            return f"Critical failure: {e}"

    def _format_summary_as_markdown(self, summary_dict: Dict[str, Any]) -> str:
        """Formats the structured executive summary dict into a clean Markdown block."""
        what_happened = summary_dict.get("what_happened", "").strip()
        why_it_matters = summary_dict.get("why_it_matters", "").strip()
        possible_impacts = summary_dict.get("possible_impacts", "").strip()
        key_points = summary_dict.get("key_points", [])
        
        md_parts = []
        if what_happened:
            md_parts.append(f"🔍 **O que aconteceu?**\n{what_happened}")
        if why_it_matters:
            md_parts.append(f"💡 **Por que isso importa?**\n{why_it_matters}")
        if possible_impacts:
            md_parts.append(f"⚡ **Possíveis impactos**\n{possible_impacts}")
        if key_points:
            points_str = "\n".join([f"- {kp}" for kp in key_points if kp.strip()])
            md_parts.append(f"📌 **Pontos-chave**\n{points_str}")
            
        return "\n\n".join(md_parts)
