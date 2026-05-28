from database.connection import get_db_session
from database.models import News, Source
from sqlalchemy import text

with get_db_session() as session:
    print("News count:", session.query(News).count())
    print("Sources count:", session.query(Source).count())
    active_sources = session.query(Source).filter(Source.active == True).all()
    print("Active sources count:", len(active_sources))
    try:
        log_count = session.execute(text("SELECT COUNT(*) FROM gemini_usage_log")).scalar()
        print("Gemini usage logs count:", log_count)
    except Exception as e:
        print("Error reading gemini_usage_log:", e)
