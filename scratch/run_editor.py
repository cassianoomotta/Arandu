"""
Run Editor Executivo pipeline on all curated articles with editorial_status = pendente.
This script runs independently from the full pipeline to generate editorial summaries.
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from agent import EditorExecutivoOrchestrator
from database.connection import get_db_session
from database.models import News

def main():
    # Show current state
    with get_db_session() as session:
        pending = session.query(News).filter(
            News.is_curated == True,
            News.editorial_status == "pendente"
        ).count()
        print(f"=== Editor Executivo Pipeline ===")
        print(f"Artigos curados pendentes de editorial: {pending}")
    
    if pending == 0:
        print("Nenhum artigo para processar.")
        return
    
    # Run the editorial pipeline
    print(f"\nIniciando processamento editorial de {pending} artigos...")
    print("(Cada artigo leva ~15-30s por conta do rate limit do Gemini gratuito)\n")
    
    editor = EditorExecutivoOrchestrator()
    report = editor.run_editorial_pipeline()
    print(f"\n=== Relatório Final ===")
    print(report)
    
    # Show final state
    with get_db_session() as session:
        published = session.query(News).filter(News.editorial_status == "publicado").count()
        failed = session.query(News).filter(News.editorial_status == "falha").count()
        still_pending = session.query(News).filter(
            News.is_curated == True,
            News.editorial_status == "pendente"
        ).count()
        
        print(f"\n=== Estado Final ===")
        print(f"Publicados: {published}")
        print(f"Falhas: {failed}")
        print(f"Ainda pendentes: {still_pending}")
        
        if published > 0:
            print(f"\n=== Artigos Publicados ===")
            pub_articles = session.query(News).filter(News.editorial_status == "publicado").all()
            for art in pub_articles:
                print(f"\n--- ID {art.id} ---")
                print(f"  Título Editorial: {art.editorial_title}")
                print(f"  Categoria: {art.editorial_category}")
                print(f"  Meta Desc: {art.meta_description}")

if __name__ == "__main__":
    main()
