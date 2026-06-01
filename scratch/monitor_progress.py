import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.connection import get_db_session
from database.models import News

def monitor():
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== MONITOR DE INGESTÃO EDITORIAL ===")
    
    last_pub = -1
    last_pend = -1
    
    while True:
        try:
            with get_db_session() as session:
                all_curated = session.query(News).filter(News.is_curated == True).all()
                
                status_counts = {}
                for art in all_curated:
                    status = art.editorial_status or "None"
                    status_counts[status] = status_counts.get(status, 0) + 1
                    
                pub = status_counts.get("publicado", 0)
                pend = status_counts.get("pendente", 0)
                proc = status_counts.get("processando", 0)
                fail = status_counts.get("falha", 0)
                
                if pub != last_pub or pend != last_pend:
                    timestamp = time.strftime("%H:%M:%S")
                    print(f"[{timestamp}] Publicados: {pub} | Pendentes: {pend} | Processando: {proc} | Falhados: {fail}")
                    last_pub = pub
                    last_pend = pend
                    
                if pend == 0 and proc == 0:
                    print("\nTodo o processamento editorial foi concluído!")
                    break
        except Exception as e:
            print(f"Erro ao monitorar: {e}")
            
        time.sleep(15)

if __name__ == "__main__":
    monitor()
