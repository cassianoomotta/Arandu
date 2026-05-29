import os
import sys
import json
from datetime import datetime

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.connection import get_db_session
from database.models import News

def serialize_datetime(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def backup_and_clear():
    print("Connecting to database...")
    with get_db_session() as session:
        # 1. Fetch all news articles
        articles = session.query(News).all()
        print(f"Found {len(articles)} news articles in the database.")
        
        # 2. Serialize and backup
        backup_data = []
        for art in articles:
            # Get dict representation
            d = {c.name: getattr(art, c.name) for c in art.__table__.columns}
            backup_data.append(d)
            
        backup_file = os.path.join("scratch", "postgres_news_backup.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, default=serialize_datetime, ensure_ascii=False, indent=2)
        print(f"Backup saved successfully to: {backup_file}")
        
        # 3. Clear the news table
        print("Clearing all articles in news table...")
        deleted_count = session.query(News).delete()
        session.commit()
        print(f"Successfully deleted {deleted_count} news articles from database.")

if __name__ == "__main__":
    backup_and_clear()
