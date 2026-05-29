import logging
from typing import List, Dict, Any
from .config import agent_settings
from core.processor import is_relevant_article, is_similar_to_recent, get_recent_titles_from_db

logger = logging.getLogger("news_agent.filters")

class LocalFilter:
    @staticmethod
    def filter_and_deduplicate(
        news_items: List[Dict[str, Any]], 
        recent_titles: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Filters out low-quality, blacklisted, or duplicate articles locally before calling the LLM.
        This minimizes tokens and API calls.
        """
        logger.info(f"Starting local filtering on {len(news_items)} news items...")
        
        if recent_titles is None:
            try:
                recent_titles = get_recent_titles_from_db(hours_limit=24)
            except Exception as e:
                logger.error(f"Failed to fetch recent titles: {e}")
                recent_titles = []
                
        filtered_items = []
        for item in news_items:
            # We prioritize translated title if available, otherwise original title
            title = item.get("translated_title") or item.get("original_title") or ""
            source_name = item.get("source_name") or ""
            
            # 1. Minimum length validation
            if len(title.strip()) < agent_settings.MIN_TITLE_LENGTH:
                logger.debug(f"Filtered (too short): '{title}'")
                continue
                
            # 2. Blacklist / Whitelist Heuristic checks (reusing existing codebase rules)
            if not is_relevant_article(title, source_name):
                logger.debug(f"Filtered (heuristic irrelevant): '{title}' (Source: {source_name})")
                continue
                
            # 3. Deduplication checks
            if is_similar_to_recent(title, recent_titles, threshold=agent_settings.SIMILARITY_THRESHOLD):
                logger.debug(f"Filtered (duplicate): '{title}'")
                continue
                
            # Keep track of this title in the memory list during this run to prevent duplicates within the same batch
            recent_titles.append(title)
            filtered_items.append(item)
            
        logger.info(f"Local filtering complete. {len(filtered_items)}/{len(news_items)} items retained.")
        return filtered_items
