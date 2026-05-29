import os
import sys
import asyncio

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.connection import get_db_session
from database.models import News, SendStatus
from agent import EditorExecutivoOrchestrator

async def run():
    print("Connecting to DB and finding an article...")
    with get_db_session() as session:
        # Find a curated article or any article
        article = session.query(News).filter(News.is_curated == True).first()
        if not article:
            article = session.query(News).first()
            if article:
                print("No curated article found, marking the first article as curated for testing...")
                article.is_curated = True
                session.commit()
        
        if not article:
            print("No articles found in the database. Ingest some news first!")
            return
            
        print(f"Found article ID {article.id}: '{article.original_title}'")
        print(f"Original Link: {article.link}")
        print("Running Editor Executivo Orchestrator on this article...")
        
        # Initialize orchestrator
        orchestrator = EditorExecutivoOrchestrator()
        
        # Run the pipeline for this specific article
        # We temporarily set the article's editorial_status to 'pendente' to force processing
        article.editorial_status = "pendente"
        session.commit()
        
        # We trigger the pipeline runner which processes all 'pendente' articles
        # To avoid making real external Gemini calls if API keys are not fully configured or to test the fallback,
        # we let it run. If it fails due to Gemini credentials, the orchestrator has robust fallbacks.
        print("Executing pipeline...")
        await orchestrator.run_editorial_pipeline_async()
        
        # Reload article to verify status
        session.refresh(article)
        print(f"Processing complete! Article editorial_status: {article.editorial_status}")
        print(f"Editorial Title: {article.editorial_title}")
        print(f"Editorial Summary: {article.editorial_summary}")
        print(f"Editorial Scores: {article.editorial_scores}")

if __name__ == "__main__":
    asyncio.run(run())
