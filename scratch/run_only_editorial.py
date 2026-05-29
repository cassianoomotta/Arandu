import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import EditorExecutivoOrchestrator
from database.connection import get_db_session
from database.models import News
from sqlalchemy import or_

def run():
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== INICIANDO EDITOR EXECUTIVO EM ARTIGOS PENDENTES/FALHADOS ===")
    
    # 1. Reset ONLY failed or stuck articles back to 'pendente', keep 'publicado' and 'duplicado' intact
    with get_db_session() as session:
        curated_stuck = (
            session.query(News)
            .filter(
                News.is_curated == True,
                or_(
                    News.editorial_status == "falha",
                    News.editorial_status == "processando"
                )
            )
            .all()
        )
        print(f"\nArtigos curados travados/falhados encontrados: {len(curated_stuck)}")
        for art in curated_stuck:
            print(f"- ID: {art.id} | Titulo: {art.translated_title or art.original_title} | Status Anterior: {art.editorial_status}")
            art.editorial_status = "pendente"
        session.commit()
        print("Resetado status de artigos travados/falhados para 'pendente'.")
        
        # Display summary of all curated items and their statuses
        all_curated = session.query(News).filter(News.is_curated == True).all()
        status_counts = {}
        for art in all_curated:
            status = art.editorial_status or "None"
            status_counts[status] = status_counts.get(status, 0) + 1
        print(f"\nResumo de status dos artigos curados no banco: {status_counts}")
        
    # 2. Run the Editorial Agent (Editor Executivo)
    print("\nExecutando EditorExecutivoOrchestrator...")
    editor = EditorExecutivoOrchestrator()
    report = editor.run_editorial_pipeline()
    print("\nExecução do Editor Executivo finalizada!")
    print(report)
    
    # 3. Check and display results
    with get_db_session() as session:
        published = session.query(News).filter(News.editorial_status == "publicado").all()
        print(f"\nTotal de Artigos Premium Publicados no Banco: {len(published)}")
        # Print top 5 published to keep output clean but verified
        for art in published[-5:]:
            print(f"\n=================== ARTIGO PREMIUM ID {art.id} ===================")
            print(f"Título Editorial: {art.editorial_title}")
            print(f"Categoria: {art.editorial_category}")
            print(f"Pontuações: {art.editorial_scores}")
            print(f"Meta Description: {art.meta_description}")

if __name__ == "__main__":
    run()
