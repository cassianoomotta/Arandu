import os
import sys
import time

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import EditorExecutivoOrchestrator
from database.connection import get_db_session
from database.models import News
from sqlalchemy import or_

def run():
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== INICIANDO PROCESSAMENTO FORÇADO DE TODOS OS RESUMOS PENDENTES ===")
    
    # 1. Reset ONLY failed or stuck articles back to 'pendente'
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
        print(f"\nArtigos curados travados/falhados encontrados para reset: {len(curated_stuck)}")
        for art in curated_stuck:
            print(f"- ID: {art.id} | Titulo: {art.translated_title or art.original_title} | Status Anterior: {art.editorial_status}")
            art.editorial_status = "pendente"
        session.commit()
        print("Reset finalizado. Todos os artigos curados com problemas foram marcados como 'pendente'.")
        
        # Display count of all curated items and their statuses before starting
        all_curated = session.query(News).filter(News.is_curated == True).all()
        status_counts = {}
        for art in all_curated:
            status = art.editorial_status or "None"
            status_counts[status] = status_counts.get(status, 0) + 1
        print(f"\nResumo de status dos artigos curados antes de rodar: {status_counts}")
        
    # 2. Run the Editorial Agent (Editor Executivo) with high limit
    limit = 250
    print(f"\nExecutando EditorExecutivoOrchestrator com limite de {limit}...")
    start_time = time.time()
    
    editor = EditorExecutivoOrchestrator()
    report = editor.run_editorial_pipeline(limit=limit)
    
    duration = time.time() - start_time
    print(f"\nExecução do Editor Executivo finalizada em {duration:.1f} segundos!")
    print("Relatório retornado:")
    print(report)
    
    # 3. Check and display results
    with get_db_session() as session:
        all_curated = session.query(News).filter(News.is_curated == True).all()
        status_counts = {}
        for art in all_curated:
            status = art.editorial_status or "None"
            status_counts[status] = status_counts.get(status, 0) + 1
        print(f"\nResumo de status FINAL dos artigos curados no banco: {status_counts}")

if __name__ == "__main__":
    run()
