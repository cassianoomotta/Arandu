import os
import sys
from datetime import datetime, timedelta
from sqlalchemy import text

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database.connection import get_db_session
from database.models import News, Source

def run_check():
    print("Connecting to Supabase Database...")
    with get_db_session() as session:
        # Check active sources
        sources = session.query(Source).all()
        print(f"Sources in DB: {len(sources)}")
        for s in sources:
            print(f"- Source ID {s.id}: {s.name} ({s.type.value}), Active: {s.active}")

        # Check total news count
        total_news = session.query(News).count()
        print(f"\nTotal news articles: {total_news}")

        # Check recent news with short summaries
        recent = session.query(News).order_by(News.created_at.desc()).limit(15).all()
        print("\nLatest 15 News Articles:")
        for idx, item in enumerate(recent):
            source_name = next((s.name for s in sources if s.id == item.source_id), "Unknown")
            summary_len = len(item.ai_summary) if item.ai_summary else 0
            print(f"{idx+1}. ID: {item.id} | Title: {item.original_title[:40]}... | Source: {source_name} | Summary length: {summary_len}")
            print(f"   Summary: {repr(item.ai_summary)}")
            # Check if is_bad_summary logic evaluates to True
            from core.processor import is_bad_summary
            is_bad = is_bad_summary(item.ai_summary)
            print(f"   is_bad_summary: {is_bad}")

        # Check usage today
        from core.processor import get_gemini_usage_today, get_rate_limit_info
        usage = get_gemini_usage_today()
        rate_limit = get_rate_limit_info()
        print(f"\nGemini usage today: {usage}")
        print(f"Rate limit info: {rate_limit}")

if __name__ == "__main__":
    run_check()
