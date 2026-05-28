import sys
sys.path.append('.')
from database.connection import get_db_session
from database.models import News, Source

with get_db_session() as session:
    news_items = session.query(News).order_by(News.created_at.desc()).all()
    print(f"Total News in DB: {len(news_items)}\n")
    for idx, item in enumerate(news_items, 1):
        source = session.query(Source).filter(Source.id == item.source_id).first()
        source_name = source.name if source else "Unknown"
        print(f"{idx}. [{source_name}] Original: {item.original_title}")
        print(f"   Translated: {item.translated_title}")
        print(f"   Summary: {item.ai_summary}")
        print("-" * 50)
