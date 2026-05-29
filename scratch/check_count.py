import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.connection import get_db_session
from database.models import News

def run():
    sys.stdout.reconfigure(encoding='utf-8')
    with get_db_session() as session:
        count = session.query(News).count()
        print(f"Total News: {count}")
        
        curated_count = session.query(News).filter(News.is_curated == True).count()
        print(f"Curated News: {curated_count}")
        
        editorial_pub = session.query(News).filter(News.editorial_status == 'publicado').count()
        print(f"Editorial Published News: {editorial_pub}")
        
        if count > 0:
            print("\nAll news articles in database:")
            all_articles = session.query(News).order_by(News.created_at.desc()).all()
            for art in all_articles:
                print(f"- ID: {art.id} | Curated: {art.is_curated} | Editorial Status: {art.editorial_status} | Title: {art.translated_title or art.original_title}")

if __name__ == "__main__":
    run()
