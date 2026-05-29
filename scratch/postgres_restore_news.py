import os
import sys
import json
from datetime import datetime

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.connection import get_db_session
from database.models import News

def parse_datetime(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return val

def restore():
    backup_file = os.path.join("scratch", "postgres_news_backup.json")
    if not os.path.exists(backup_file):
        print(f"Backup file not found: {backup_file}")
        return
        
    print(f"Reading backup data from {backup_file}...")
    with open(backup_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Loaded {len(data)} articles. Restoring to database...")
    with get_db_session() as session:
        # Clear existing
        session.query(News).delete()
        
        for item in data:
            # Parse datetime fields
            for key in ["original_published_at", "created_at", "curated_at"]:
                if key in item and item[key]:
                    item[key] = parse_datetime(item[key])
            
            # Recreate News instance
            # Exclude id to let DB auto-increment or preserve it if needed
            # We can preserve it if we want exact IDs, but let's exclude it or set it
            news_id = item.pop("id", None)
            news_obj = News(**item)
            if news_id is not None:
                news_obj.id = news_id
            session.add(news_obj)
            
        session.commit()
    print("Database restored successfully!")

if __name__ == "__main__":
    restore()
