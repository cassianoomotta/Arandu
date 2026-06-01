import os
import sys

# Add workspace directory to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.connection import get_db_session
from database.models import News, Source

with get_db_session() as session:
    # Get count of news
    count = session.query(News).count()
    print("Total news in news table:", count)

    # Get count by editorial_status
    from sqlalchemy import func
    status_counts = session.query(News.editorial_status, func.count(News.id)).group_by(News.editorial_status).all()
    print("News by editorial_status:", status_counts)

    # Get some recent news
    recent_news = session.query(News).order_by(News.id.desc()).limit(10).all()
    print("\nRecent news:")
    for row in recent_news:
        print(f"ID: {row.id} | Title: {row.original_title[:50]} | Translated: {row.translated_title[:50] if row.translated_title else None} | Score: {row.relevance_score} | Status: {row.editorial_status} | Created: {row.created_at}")
