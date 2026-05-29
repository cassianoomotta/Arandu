import abc
import logging
from typing import Optional
import httpx

from database.config import settings
from database.connection import get_db_session
from database.models import News, SendStatus

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("news_notifier")


class BaseNotifier(abc.ABC):
    """
    Abstract Base Class (Interface) representing the Notification Strategy.
    """
    @abc.abstractmethod
    async def send_notification(
        self, 
        title: str, 
        summary: str, 
        link: str, 
        image_url: Optional[str] = None
    ) -> bool:
        """
        Sends a news notification using the concrete channel strategy.
        Returns True if sent successfully, False otherwise.
        """
        pass


class TelegramNotifier(BaseNotifier):
    """
    Concrete Notification Strategy for Telegram Channels/Groups.
    """
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"

    async def send_notification(
        self, 
        title: str, 
        summary: str, 
        link: str, 
        image_url: Optional[str] = None
    ) -> bool:
        """
        Sends a styled HTML notification via Telegram Bot API.
        Attempts sendPhoto first, falls back to sendMessage on failure.
        """
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram Notifier: Bot token or Chat ID not configured. Skipping.")
            return False

        # Format Telegram HTML payload (bullet points, bold title, link)
        caption = (
            f"<b>{title}</b>\n\n"
            f"{summary}\n\n"
            f"<a href='{link}'>Leia a notícia completa</a>"
        )
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # 1. Attempt sending cover image + text caption
                if image_url:
                    photo_payload = {
                        "chat_id": self.chat_id,
                        "photo": image_url,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }
                    response = await client.post(
                        f"{self.api_url}/sendPhoto", 
                        json=photo_payload
                    )
                    if response.status_code == 200:
                        logger.info("Telegram Notifier: Sent successfully with photo.")
                        return True
                    else:
                        logger.warning(
                            f"Telegram Notifier: sendPhoto failed (HTTP {response.status_code}). "
                            "Retrying with text-only message..."
                        )

                # 2. Text-only fallback message
                text_payload = {
                    "chat_id": self.chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                }
                response = await client.post(
                    f"{self.api_url}/sendMessage", 
                    json=text_payload
                )
                if response.status_code == 200:
                    logger.info("Telegram Notifier: Sent successfully as text-only.")
                    return True
                else:
                    logger.error(
                        f"Telegram Notifier: sendMessage failed with code {response.status_code}: {response.text}"
                    )
                    return False
                    
            except httpx.RequestError as e:
                logger.error(f"Telegram Notifier: Connection error: {str(e)}")
                return False
            except Exception as e:
                logger.error(f"Telegram Notifier: Unexpected error: {str(e)}")
                return False


class WhatsAppNotifier(BaseNotifier):
    """
    Future Notification Strategy for WhatsApp Channels/Numbers.
    Implemented as a skeleton to support easy substitution without modifying core logic.
    """
    async def send_notification(
        self, 
        title: str, 
        summary: str, 
        link: str, 
        image_url: Optional[str] = None
    ) -> bool:
        """
        Interface definition for future WhatsApp dispatch.
        
        Integration Guide for Meta Cloud API:
        1. Config: Require WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.
        2. Format: Meta Cloud API requires pre-approved templates or session messages.
           For templates: send JSON payload specifying template name, language,
           and variables (header: image link, body: title and bullet-points).
        3. Send: POST request to 'https://graph.facebook.com/v18.0/{phone_number_id}/messages'.
        
        Integration Guide for Evolution API (Unofficial API):
        1. Config: Require EVOLUTION_API_URL, EVOLUTION_API_KEY, and INSTANCE_NAME.
        2. Send Media: Call POST '{api_url}/message/sendMedia/{instance_name}' sending
           the image_url as media and formatting the caption as text message.
        3. Send Text: Call POST '{api_url}/message/sendText/{instance_name}' with body.
        """
        logger.info(
            f"WhatsAppNotifier: Skeleton triggered for '{title[:30]}...'. "
            "Meta Cloud API / Evolution API implementation is ready for deployment."
        )
        # Return False by default as this is a placeholder interface
        return False


# Controller function
async def dispatch_pending_notifications(notifier: BaseNotifier) -> int:
    """
    Controller function that:
    1. Queries database for news articles with 'pendente' status.
    2. Sends them using the selected Notifier Strategy.
    3. Updates database status to 'enviado_telegram' (on success) or 'falha' (on error).
    
    Returns the count of successfully sent articles.
    """
    logger.info("Ingestion Dispatcher: Checking for pending news notifications...")
    
    try:
        with get_db_session() as session:
            # Query oldest pending articles first
            pending_items = (
                session.query(News)
                .filter(News.send_status == SendStatus.PENDENTE)
                .order_by(News.original_published_at.asc())
                .all()
            )
            # Expunge objects so we can read them asynchronously
            session.expunge_all()
    except Exception as e:
        logger.error(f"Ingestion Dispatcher: Failed to retrieve pending news: {str(e)}")
        return 0

    if not pending_items:
        logger.info("Ingestion Dispatcher: No pending news found to dispatch.")
        return 0

    logger.info(f"Ingestion Dispatcher: Found {len(pending_items)} news articles to process.")
    sent_count = 0

    for news in pending_items:
        title = news.editorial_title or news.translated_title or news.original_title
        summary = news.ai_summary or "Resumo não disponível."
        
        # If processed by Editor Executivo, format premium summary for Telegram
        if news.editorial_status == "publicado" and news.editorial_summary:
            import json
            try:
                summary_dict = json.loads(news.editorial_summary) if isinstance(news.editorial_summary, str) else news.editorial_summary
                if isinstance(summary_dict, dict):
                    what_happened = summary_dict.get("what_happened", "")
                    why_it_matters = summary_dict.get("why_it_matters", "")
                    key_points = summary_dict.get("key_points", [])
                    
                    bullets = "\n".join([f"• {pt}" for pt in key_points])
                    summary = (
                        f"🔍 <b>O que aconteceu:</b> {what_happened}\n\n"
                        f"💡 <b>Por que importa:</b> {why_it_matters}\n\n"
                        f"📌 <b>Pontos-chave:</b>\n{bullets}"
                    )
            except Exception as e:
                logger.warning(f"Failed to parse editorial_summary for Telegram: {str(e)}")
                
        link = news.link
        image_url = news.image_url
        
        # Dispatch notification using our strategy interface
        success = await notifier.send_notification(
            title=title,
            summary=summary,
            link=link,
            image_url=image_url
        )
        
        # Decide new status
        new_status = SendStatus.ENVIADO_TELEGRAM if success else SendStatus.FALHA
        if success:
            sent_count += 1
            
        # Update database item
        try:
            with get_db_session() as session:
                db_item = session.query(News).filter(News.id == news.id).first()
                if db_item:
                    db_item.send_status = new_status
            logger.info(
                f"Ingestion Dispatcher: News ID {news.id} status updated to '{new_status.value}'."
            )
        except Exception as e:
            logger.error(
                f"Ingestion Dispatcher: Failed to update DB status for news ID {news.id}: {str(e)}"
            )

    logger.info(f"Ingestion Dispatcher: Cycle completed. Sent {sent_count} notifications.")
    return sent_count
