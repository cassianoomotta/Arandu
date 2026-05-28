"""
Fix bad summaries in the database.
Identifies articles with:
  - Empty/null summaries
  - Fallback placeholder text ("Resumo automático indisponível")
  - Truncated preambles ("Aqui está o resumo executivo")
  - Summaries shorter than 50 chars
Then regenerates them one-by-one with a 8s delay to avoid rate limits.
"""
import sys
import time
sys.path.append('.')

from database.connection import get_db_session
from database.models import News, Source
from core.processor import generate_ai_summary, _clean_summary_preamble

BAD_PATTERNS = [
    "Resumo automático indisponível",
    "Coleta executada com sucesso",
    "Notícia de tecnologia relevante reportada",
    "Aqui está o resumo execut",
    "Aqui está o resumo",
]

def is_bad_summary(summary: str) -> bool:
    if not summary or len(summary.strip()) < 50:
        return True
    for pattern in BAD_PATTERNS:
        if pattern in summary:
            return True
    return False

def main():
    with get_db_session() as session:
        news_items = session.query(News).order_by(News.created_at.desc()).all()
        sources_map = {s.id: s.name for s in session.query(Source).all()}
        
        bad_articles = [(n, sources_map.get(n.source_id, "Desconhecido")) for n in news_items if is_bad_summary(n.ai_summary)]
        
        print(f"Total articles: {len(news_items)}")
        print(f"Articles with bad summaries: {len(bad_articles)}\n")
        
        if not bad_articles:
            print("All summaries are OK!")
            return
        
        for idx, (article, source_name) in enumerate(bad_articles, 1):
            title = article.translated_title or article.original_title
            print(f"[{idx}/{len(bad_articles)}] Fixing: '{title[:60]}...'")
            print(f"  Old summary: '{(article.ai_summary or '')[:80]}...'")
            
            try:
                new_summary = generate_ai_summary(title=title, source_name=source_name)
                
                # Check if the new summary is actually good
                if not is_bad_summary(new_summary):
                    article.ai_summary = new_summary
                    session.commit()
                    print(f"  ✓ New summary: '{new_summary[:80]}...'")
                else:
                    print(f"  ✗ Still bad (rate limited?), skipping.")
            except Exception as e:
                print(f"  ✗ Error: {str(e)}")
            
            # Wait 8 seconds between requests to respect rate limits
            if idx < len(bad_articles):
                print(f"  Waiting 8s before next request...")
                time.sleep(8)
        
        print(f"\nDone! Check the results.")

if __name__ == "__main__":
    main()
