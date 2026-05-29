import os
import sys
import asyncio

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import AgentOrchestrator, EditorExecutivoOrchestrator
from database.connection import get_db_session
from database.models import News

def test_chain():
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== STARTING AGENT PIPELINE TEST ===")
    
    # 1. Run Curation Agent pipeline
    print("\n[1/2] Running Curation Agent (Curador de Notícias)...")
    curator = AgentOrchestrator()
    # run_curation_pipeline is synchronous (run in thread pool inside scraper)
    curation_report = curator.run_curation_pipeline()
    print("Curation Agent finished!")
    print(curation_report)
    
    # Check if we have curated articles
    with get_db_session() as session:
        curated_articles = session.query(News).filter(News.is_curated == True).all()
        print(f"\nCurrently curated articles in DB: {len(curated_articles)}")
        for art in curated_articles:
            print(f"- ID: {art.id} | Title: {art.translated_title or art.original_title} | Curated: {art.is_curated} | Status: {art.editorial_status}")
            # Reset status to pendente for testing
            art.editorial_status = "pendente"
        session.commit()
        print("Reset all curated articles' editorial_status to 'pendente' for testing.")
            
    # 2. Run Editorial Agent pipeline
    print("\n[2/2] Running Editorial Agent (Editor Executivo)...")
    editor = EditorExecutivoOrchestrator()
    editorial_report = editor.run_editorial_pipeline()
    print("Editorial Agent finished!")
    print(editorial_report)
    
    # Check finished state
    with get_db_session() as session:
        published_articles = session.query(News).filter(News.editorial_status == "publicado").all()
        print(f"\nPublished premium articles in DB: {len(published_articles)}")
        for art in published_articles:
            print(f"\n--- PREMIUM ARTICLE ID {art.id} ---")
            print(f"Title: {art.editorial_title}")
            print(f"Category: {art.editorial_category}")
            print(f"Scores: {art.editorial_scores}")
            print(f"Meta Description: {art.meta_description}")
            print(f"Summary JSON: {art.editorial_summary}")
            
if __name__ == "__main__":
    test_chain()
