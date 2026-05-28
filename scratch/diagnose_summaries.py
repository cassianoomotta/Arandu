"""
Diagnostic script to check the state of all news summaries in the database.
Shows which articles have bad/missing summaries and what they look like.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import get_db_session
from database.models import News, Source

def count_bullet_points(summary: str) -> int:
    """Count the number of bullet points in a summary."""
    if not summary:
        return 0
    lines = summary.strip().split('\n')
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('-') or stripped.startswith('•') or stripped.startswith('*'):
            count += 1
    return count

def is_bad_summary_enhanced(summary: str) -> tuple[bool, str]:
    """Enhanced check that returns (is_bad, reason)."""
    if not summary:
        return True, "VAZIO"
    
    s = summary.strip()
    s_lower = s.lower()
    
    if len(s) < 120:
        return True, f"CURTO ({len(s)} chars)"
    
    bullets = count_bullet_points(s)
    if bullets == 0:
        return True, "SEM BULLETS"
    if bullets < 3:
        return True, f"POUCOS BULLETS ({bullets}/3)"
    
    # Check for overly long bullets (paragraphs instead of 2 sentences)
    lines = s.split('\n')
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('-') or stripped.startswith('•') or stripped.startswith('*'):
            # Remove bullet prefix
            content = stripped.lstrip('-•* ').strip()
            if len(content) > 300:
                return True, f"BULLET MUITO LONGO ({len(content)} chars)"
    
    bad_patterns = [
        "resumo automático indisponível",
        "coleta executada com sucesso",
        "notícia de tecnologia relevante reportada",
        "aqui está o resumo",
        "resumo executivo",
        "segue abaixo",
        "requer análise manual",
        "assunto principal:",
    ]
    for pattern in bad_patterns:
        if pattern in s_lower:
            return True, f"PADRÃO RUIM: '{pattern}'"
    
    # Check for numbered list format instead of bullets (e.g. "1. blah" or "1 (blah)")
    import re
    if re.match(r'^\d+[\.\)\s]', s):
        return True, "FORMATO NUMERADO (não é bullet)"
    
    return False, "OK"

def main():
    with get_db_session() as session:
        sources_map = {s.id: s.name for s in session.query(Source).all()}
        all_news = session.query(News).order_by(News.created_at.desc()).all()
        
        total = len(all_news)
        bad_count = 0
        ok_count = 0
        reasons_count = {}
        
        print(f"\n{'='*80}")
        print(f"DIAGNÓSTICO DE RESUMOS - {total} artigos no banco de dados")
        print(f"{'='*80}\n")
        
        bad_articles = []
        
        for item in all_news:
            is_bad, reason = is_bad_summary_enhanced(item.ai_summary)
            if is_bad:
                bad_count += 1
                reasons_count[reason] = reasons_count.get(reason, 0) + 1
                title = item.translated_title or item.original_title
                source = sources_map.get(item.source_id, "?")
                bad_articles.append((item.id, title[:60], source, reason, (item.ai_summary or "")[:100]))
            else:
                ok_count += 1
        
        print(f"[OK] Resumos OK:     {ok_count}/{total}")
        print(f"[BAD] Resumos RUINS:  {bad_count}/{total}")
        print(f"\n--- Distribuição por tipo de problema ---")
        for reason, count in sorted(reasons_count.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
        
        print(f"\n--- Artigos com resumos ruins ---")
        for article_id, title, source, reason, preview in bad_articles:
            print(f"\n  ID {article_id} [{source}] - {reason}")
            print(f"    Título: {title}")
            print(f"    Preview: {preview.replace(chr(10), ' | ')}")
        
        print(f"\n{'='*80}")
        print(f"TOTAL: {bad_count} artigos precisam de healing")
        print(f"{'='*80}")

if __name__ == "__main__":
    main()
