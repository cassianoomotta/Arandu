import sys
import time
sys.path.append('.')

from database.connection import get_db_session
from database.models import News, Source
from core.processor import generate_ai_summary, translate_text, SourceType

def enrich_news():
    print("Connecting to database...")
    with get_db_session() as session:
        news_items = session.query(News).all()
        print(f"Analyzing {len(news_items)} news items in database...\n")
        
        updated_count = 0
        
        for idx, item in enumerate(news_items, 1):
            source = session.query(Source).filter(Source.id == item.source_id).first()
            source_name = source.name if source else "Unknown"
            
            # Check if summary needs regeneration
            needs_enrichment = False
            if not item.ai_summary:
                needs_enrichment = True
            elif "Resumo automático indisponível" in item.ai_summary:
                needs_enrichment = True
            elif len(item.ai_summary.strip()) < 50:
                needs_enrichment = True
                
            if needs_enrichment:
                print(f"[{idx}/{len(news_items)}] Enriching article: '{item.original_title}'")
                
                # 1. Translation if international
                translated_title = item.translated_title
                if source and source.type == SourceType.INTERNACIONAL and (not translated_title or translated_title == item.original_title):
                    print("   Translating title...")
                    try:
                        translated_title = translate_text(item.original_title, target_lang="pt")
                        item.translated_title = translated_title
                        time.sleep(2)
                    except Exception as e:
                        print(f"   Translation error: {str(e)}")
                
                # 2. AI Summary Generation
                seed_title = translated_title or item.original_title
                print("   Generating summary...")
                try:
                    summary = generate_ai_summary(title=seed_title, source_name=source_name)
                    if summary and "Resumo automático indisponível" not in summary:
                        item.ai_summary = summary
                        item.reduced_key = " ".join([word.lower() for word in seed_title.split() if len(word) > 3])[:255]
                        session.commit()
                        print("   Successfully updated!")
                        updated_count += 1
                    else:
                        print("   Failed to get a valid summary.")
                except Exception as e:
                    print(f"   Summary error: {str(e)}")
                
                # Wait 5 seconds between requests to respect rate limits
                time.sleep(5)
            else:
                print(f"[{idx}/{len(news_items)}] Article already has valid summary: '{item.original_title[:50]}...'")
                
        print(f"\nDone! Updated {updated_count} articles with premium summaries.")

if __name__ == "__main__":
    enrich_news()
