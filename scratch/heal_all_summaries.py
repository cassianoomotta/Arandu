"""
Batch healing script to regenerate all bad/missing AI summaries in the database.
This runs locally and processes ALL articles that need healing, not just the 
limited 3-per-run that the automated pipeline does.
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import get_db_session
from database.models import News, Source
from core.processor import generate_ai_summary, is_bad_summary

def main():
    print("\n" + "="*70)
    print("BATCH HEALING - Regenerando resumos ruins no banco de dados")
    print("="*70 + "\n")
    
    with get_db_session() as session:
        sources_map = {s.id: s.name for s in session.query(Source).all()}
        all_news = session.query(News).order_by(News.created_at.desc()).all()
        
        bad_articles = []
        for item in all_news:
            if is_bad_summary(item.ai_summary):
                bad_articles.append(item)
        
        total = len(all_news)
        bad_count = len(bad_articles)
        
        print(f"Total de artigos: {total}")
        print(f"Artigos com resumos ruins: {bad_count}")
        
        if bad_count == 0:
            print("\nTodos os artigos ja tem resumos validos!")
            return
        
        print(f"\nIniciando healing de {bad_count} artigos...\n")
        
        healed = 0
        failed = 0
        skipped = 0
        
        for i, article in enumerate(bad_articles, 1):
            title = article.translated_title or article.original_title
            source_name = sources_map.get(article.source_id, "Desconhecido")
            
            print(f"[{i}/{bad_count}] ID {article.id}: {title[:55]}...")
            
            try:
                new_summary = generate_ai_summary(title=title, source_name=source_name)
                
                if not is_bad_summary(new_summary):
                    article.ai_summary = new_summary
                    session.commit()
                    healed += 1
                    # Show first bullet as preview
                    first_line = new_summary.split('\n')[0][:80]
                    print(f"  [OK] {first_line}...")
                else:
                    skipped += 1
                    print(f"  [SKIP] Resumo gerado ainda eh invalido")
            except Exception as e:
                failed += 1
                err_msg = str(e)[:80]
                print(f"  [FAIL] {err_msg}")
                
                # If we hit the daily limit, stop
                if "daily quota limit" in str(e).lower() or "daily usage limit" in str(e).lower():
                    print(f"\n--- Limite diario da API atingido. Parando. ---")
                    break
                
                # If rate limited, wait and continue
                if "429" in str(e) or "rate limit" in str(e).lower():
                    print(f"  Aguardando 60s pelo rate limit...")
                    time.sleep(60)
        
        print(f"\n{'='*70}")
        print(f"RESULTADO DO HEALING:")
        print(f"  Corrigidos:  {healed}")
        print(f"  Falhas:      {failed}")
        print(f"  Pulados:     {skipped}")
        print(f"  Restantes:   {bad_count - healed - failed - skipped}")
        print(f"{'='*70}")

if __name__ == "__main__":
    main()
