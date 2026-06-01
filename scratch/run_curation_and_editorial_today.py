import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import AgentOrchestrator, EditorExecutivoOrchestrator
from database.connection import get_db_session
from database.models import News
from sqlalchemy import or_

def run():
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== INICIANDO PIPELINE COMPLETO DE CURADORIA E EDITORIAL PARA ARTIGOS NOVOS ===")
    
    # 1. Run Curation Pipeline
    print("\n[Passo 1] Executando AgentOrchestrator (Curador de Notícias) para classificar os novos artigos...")
    curator = AgentOrchestrator()
    curation_report = curator.run_curation_pipeline()
    print("\nRelatório do Curador:")
    print(curation_report)
    
    # 2. Run Editorial Pipeline
    print("\n[Passo 2] Executando EditorExecutivoOrchestrator (Editor Executivo) para gerar os resumos premium...")
    editor = EditorExecutivoOrchestrator()
    # Process up to 20 articles
    editorial_report = editor.run_editorial_pipeline(limit=20)
    print("\nRelatório do Editor Executivo:")
    print(editorial_report)
    
    # 3. Check and display results
    with get_db_session() as session:
        published = (
            session.query(News)
            .filter(News.editorial_status == "publicado")
            .order_by(News.created_at.desc())
            .limit(10)
            .all()
        )
        print(f"\nTotal de Artigos Premium Publicados no Banco: {session.query(News).filter(News.editorial_status == 'publicado').count()}")
        print("\nÚltimos 10 artigos publicados:")
        for art in published:
            print(f"- ID: {art.id} | Título: {art.editorial_title or art.translated_title} | Categoria: {art.editorial_category} | Score: {art.relevance_score}")

if __name__ == "__main__":
    run()
