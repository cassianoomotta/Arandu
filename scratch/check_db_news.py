import os
import sys
import json

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.connection import get_db_session
from database.models import News

def run():
    sys.stdout.reconfigure(encoding='utf-8')
    with get_db_session() as session:
        published = (
            session.query(News)
            .filter(News.editorial_status == "publicado")
            .order_by(News.created_at.desc())
            .all()
        )
        print(f"Total published articles: {len(published)}")
        for idx, art in enumerate(published):
            print(f"\n--- Article {idx+1} (ID: {art.id}) ---")
            print(f"Title: {art.editorial_title}")
            print(f"Link: {art.link}")
            print(f"editorial_summary type: {type(art.editorial_summary)}")
            print(f"editorial_summary raw: {art.editorial_summary}")
            try:
                if art.editorial_summary:
                    summary_obj = json.loads(art.editorial_summary) if isinstance(art.editorial_summary, str) else art.editorial_summary
                    print(f"Parsed keys: {list(summary_obj.keys())}")
                    print(f"key_points type: {type(summary_obj.get('key_points'))}")
            except Exception as e:
                print(f"ERROR parsing: {e}")

if __name__ == "__main__":
    run()
