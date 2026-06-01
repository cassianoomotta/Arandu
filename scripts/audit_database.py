import os
import sys
import logging
import importlib
from datetime import datetime
from collections import defaultdict

# Add parent folder (project root) to sys.path to allow standalone execution
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database.connection import get_db_session
from database.models import News, Source, NoticiasRejeitadas
from pydantic import BaseModel, Field
from typing import List

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("news_audit")

# Dynamic imports for Curador de Notícias modules
curador_gateway = importlib.import_module("agent.Curador de Notícias.gateway")
GeminiGateway = curador_gateway.GeminiGateway

class CurationItem(BaseModel):
    id: int
    status: str = Field(..., description="APROVADA ou REPROVADA. Adote uma postura conservadora e reprove se houver dúvida.")
    justificativa: str = Field(..., description="Justificativa concisa da classificação (máximo 15 palavras).")
    categoria_identificada: str = Field(..., description="Categoria principal (deve ser exatamente uma das 16 listadas).")
    score: int = Field(..., description="Score de relevância de 1 a 5.")

class CurationResponse(BaseModel):
    items: List[CurationItem]

SYSTEM_AUDIT_PROMPT_TEMPLATE = """Você é um Agente Especialista em Curadoria de Conteúdo Estratégico para o Portal Arandu.
Sua missão é manter a qualidade, relevância e integridade da base de notícias, garantindo exclusivamente notícias de alto valor sobre Ciência, Tecnologia, Inteligência Artificial, Inovação, Empreendedorismo, Mercado e Negócios.

Você analisará um lote de notícias (com ID, título e resumo/conteúdo) e, para cada uma, determinará se deve ser APROVADA ou REPROVADA.

CRITÉRIOS DE ESCOPO E CLASSIFICAÇÃO:
1. APROVADA: Quando estiver claramente relacionada a:
   - Ciência, Tecnologia, Inteligência Artificial, Agentes de IA, Robótica, Computação Quântica, Biotecnologia, Nanotecnologia, Ciência de Dados, Sustentabilidade/Energias Renováveis, Saúde e Inovação Médica, Espaço/Astronomia, Inovação Industrial.
   - Startups, Venture Capital, Investimentos, Fusões e Aquisições, Novos Modelos de Negócios, Economia Digital, Fintechs/Agrotechs/Healthtechs, Inovação Corporativa, Mercado Financeiro, Escalabilidade de Negócios.
2. REPROVADA: Quando tratar de:
   - Política/Eleições, Futebol/Esportes, Celebridades/Fofocas/Reality Shows, Violência/Crimes/Acidentes/Tragédias, Opiniões Ideológicas, Religião, Sensacionalismo, Notícias Locais sem impacto em inovação, Promoções de produtos comuns (cupons de desconto, ofertas de lojas, etc.).
   * Em situações de dúvida, adote uma postura conservadora e REPROVE a notícia.

Para cada notícia APROVADA, defina:
- Categoria Principal (deve ser EXATAMENTE uma destas 16 opções):
  * Inteligência Artificial
  * Tecnologia
  * Ciência
  * Robótica
  * Biotecnologia
  * Computação Quântica
  * Saúde e Inovação
  * Energia
  * Espaço
  * Startups
  * Investimentos
  * Mercado
  * Negócios
  * Empreendedorismo
  * Transformação Digital
  * Cibersegurança
- Score de Relevância (de 1 a 5):
  * 1/5: Baixa relevância (pouco impactante ou interesse muito limitado)
  * 2/5: Relevância moderada (útil, sem impacto significativo)
  * 3/5: Boa relevância (importante para profissionais/entusiastas do setor)
  * 4/5: Alta relevância (inovação ou movimento de mercado com potencial relevante de transformação)
  * 5/5: Relevância excepcional (descoberta, inovação ou movimento capaz de impactar mercados/pesquisas inteiras)
- Justificativa: Explicação concisa da classificação (máximo 15 palavras).

{reference_examples}

Retorne um objeto JSON contendo o campo "items" como uma lista que obedece ao esquema fornecido."""

DEFAULT_REFERENCES = """Exemplos de Referência (Score 4 e 5):
- Título: OpenAI lança GPT-4o, novo modelo capaz de raciocinar em tempo real por voz e visão | Categoria: Inteligência Artificial | Score: 5 | Justificativa: Avanço altamente disruptivo no campo de IA generativa e modelos multimodais.
- Título: Nvidia ultrapassa Apple como segunda empresa mais valiosa com chips de IA | Categoria: Investimentos | Score: 4 | Justificativa: Movimentação de mercado significativa impulsionada pela demanda global de infraestrutura de IA.
- Título: Cientistas conseguem fazer o primeiro teleporte quântico estável de longa distância | Categoria: Computação Quântica | Score: 5 | Justificativa: Breakthrough científico na computação quântica com impacto de longo prazo.
"""

def get_dynamic_reference_examples(session, limit=5) -> str:
    """
    Step 7: Fetches dynamically reference examples from database (curated with score 4 or 5)
    to refine future classification prompt.
    """
    examples = (
        session.query(News)
        .filter(News.is_curated == True)
        .filter(News.relevance_score.in_([4, 5]))
        .order_by(News.curated_at.desc())
        .limit(limit)
        .all()
    )
    if not examples:
        return DEFAULT_REFERENCES
    
    examples_str = "Exemplos de Referência (Score 4 e 5) obtidos da base:\n"
    for ex in examples:
        title = ex.translated_title or ex.original_title
        examples_str += f"- Título: {title} | Categoria: {ex.category} | Score: {ex.relevance_score} | Justificativa: {ex.ai_justification}\n"
    return examples_str

def deduplicate_existing_news(session) -> tuple[int, int]:
    """
    Step 4: Scans the database for duplicate or highly similar news.
    Keeps the best one (composite sort key) and moves others to noticias_rejeitadas.
    Returns (total_found, total_removed).
    """
    from core.processor import calculate_similarity
    
    logger.info("Etapa 4: Iniciando detecção de duplicidades na base...")
    all_news = session.query(News).order_by(News.created_at.desc()).all()
    
    total_found = 0
    total_removed = 0
    processed_ids = set()
    
    for i, item_a in enumerate(all_news):
        if item_a.id in processed_ids:
            continue
            
        title_a = item_a.translated_title or item_a.original_title or ""
        if not title_a:
            continue
            
        group = [item_a]
        processed_ids.add(item_a.id)
        
        # Compare with subsequent items to find duplicates
        for item_b in all_news[i+1:]:
            if item_b.id in processed_ids:
                continue
                
            title_b = item_b.translated_title or item_b.original_title or ""
            if not title_b:
                continue
                
            # Identical links or high sequence similarity
            if item_a.link == item_b.link or calculate_similarity(title_a, title_b) >= 0.8:
                group.append(item_b)
                processed_ids.add(item_b.id)
                
        if len(group) > 1:
            total_found += len(group) - 1
            # Sort the group: highest score, is_curated, has summary, newer date
            def get_sort_key(item):
                score = item.relevance_score or 0
                has_summary = 1 if item.ai_summary else 0
                is_curated_flag = 1 if item.is_curated else 0
                date_val = item.original_published_at or item.created_at or datetime.min
                return (score, is_curated_flag, has_summary, date_val)
                
            group.sort(key=get_sort_key, reverse=True)
            keep_item = group[0]
            discard_items = group[1:]
            
            logger.info(f"Grupo de duplicidade identificado: Mantendo ID {keep_item.id} | Removendo {len(discard_items)} duplicados.")
            
            for discard in discard_items:
                rejected = NoticiasRejeitadas(
                    id_noticia=discard.id,
                    titulo=discard.translated_title or discard.original_title,
                    link=discard.link,
                    motivo_rejeicao="DUPLICIDADE",
                    data_rejeicao=datetime.utcnow(),
                    categoria_identificada=discard.category or "Outros"
                )
                session.add(rejected)
                session.delete(discard)
                total_removed += 1
                
    session.commit()
    logger.info(f"Deduplicação concluída: {total_removed} duplicidades removidas de {total_found} encontradas.")
    return total_found, total_removed

def run_database_audit():
    logger.info("Iniciando auditoria completa da base de notícias...")
    
    # Statistics variables
    stats = {
        "analisadas": 0,
        "aprovadas": 0,
        "rejeitadas": 0,
        "duplicidades_encontradas": 0,
        "duplicidades_removidas": 0,
        "score_distribution": defaultdict(int),
        "category_distribution": defaultdict(int),
    }
    
    gateway = GeminiGateway()
    
    with get_db_session() as session:
        # Step 4: Identificação de duplicidades
        found, removed = deduplicate_existing_news(session)
        stats["duplicidades_encontradas"] = found
        stats["duplicidades_removidas"] = removed
        
        # Load all remaining news items to audit
        db_news = session.query(News).all()
        total_news = len(db_news)
        stats["analisadas"] = total_news
        
        if total_news == 0:
            logger.info("Nenhuma notícia encontrada na base para auditoria.")
            return stats
            
        logger.info(f"Total de notícias a classificar/auditar após deduplicação: {total_news}")
        
        # Group news by batches of 15 to remain within Gemini API limitations
        batch_size = 15
        for i in range(0, total_news, batch_size):
            chunk = db_news[i:i+batch_size]
            logger.info(f"Auditando lote {i//batch_size + 1} de {((total_news - 1)//batch_size) + 1} ({len(chunk)} notícias)...")
            
            # Format chunk items for prompt
            news_list_str = ""
            for item in chunk:
                title = item.translated_title or item.original_title or ""
                summary = item.ai_summary or "Sem resumo disponível."
                news_list_str += f"- ID: {item.id} | Título: {title} | Resumo: {summary}\n"
            
            # Step 7: Get dynamic reference examples
            ref_examples = get_dynamic_reference_examples(session, limit=5)
            system_prompt = SYSTEM_AUDIT_PROMPT_TEMPLATE.format(reference_examples=ref_examples)
            prompt = f"Por favor, audite e classifique o seguinte lote de notícias:\n\n{news_list_str}"
            
            try:
                # Call Gemini structured API
                response = gateway.call_structured_api(
                    prompt=prompt,
                    system_instruction=system_prompt,
                    response_model=CurationResponse
                )
                
                # Process each classification response item
                for item_resp in response.get("items", []):
                    item_id = item_resp["id"]
                    status_val = item_resp["status"].upper() # APROVADA or REPROVADA
                    justificativa = item_resp["justificativa"]
                    categoria = item_resp["categoria_identificada"]
                    score = item_resp["score"]
                    
                    # Fetch database record
                    db_item = session.query(News).filter(News.id == item_id).first()
                    if not db_item:
                        continue
                        
                    # Handle rejection or approval
                    if status_val == "REPROVADA":
                        # Move to rejected
                        rejected = NoticiasRejeitadas(
                            id_noticia=db_item.id,
                            titulo=db_item.translated_title or db_item.original_title,
                            link=db_item.link,
                            motivo_rejeicao=justificativa or "REPROVADA POR ESCOPO",
                            data_rejeicao=datetime.utcnow(),
                            categoria_identificada=categoria or "Política/Outros"
                        )
                        session.add(rejected)
                        session.delete(db_item)
                        stats["rejeitadas"] += 1
                    else:
                        # APROVADA
                        # Check relevance score (Etapa 6)
                        if score in (1, 2):
                            reason = "BAIXA RELEVÂNCIA" if score == 1 else "RELEVÂNCIA INSUFICIENTE"
                            rejected = NoticiasRejeitadas(
                                id_noticia=db_item.id,
                                titulo=db_item.translated_title or db_item.original_title,
                                link=db_item.link,
                                motivo_rejeicao=reason,
                                data_rejeicao=datetime.utcnow(),
                                categoria_identificada=categoria
                            )
                            session.add(rejected)
                            session.delete(db_item)
                            stats["rejeitadas"] += 1
                            stats["score_distribution"][score] += 1
                        else:
                            # Keep in main base (score 3, 4, 5)
                            db_item.relevance_score = score
                            db_item.category = categoria
                            db_item.ai_justification = justificativa
                            db_item.is_curated = True
                            db_item.curated_at = datetime.utcnow()
                            
                            # Rules of priority/highlight
                            if score == 3:
                                db_item.priority = "baixa"
                                db_item.destaque = False
                            elif score == 4:
                                db_item.priority = "media"
                                db_item.destaque = False
                            elif score == 5:
                                db_item.priority = "alta"
                                db_item.destaque = True
                            
                            stats["aprovadas"] += 1
                            stats["score_distribution"][score] += 1
                            stats["category_distribution"][categoria] += 1
                
                # Commit after each batch to avoid transaction lock or massive rollback in case of error
                session.commit()
                
            except Exception as e:
                logger.error(f"Erro ao processar lote {i//batch_size + 1}: {e}")
                session.rollback()
                
        # Generate and save final report
        generate_audit_report(session, stats)
        
    return stats

def generate_audit_report(session, stats):
    """
    Step 9: Generate final markdown report
    """
    logger.info("Gerando relatório final de auditoria...")
    
    # Load top 20 highlights (highest relevance)
    top_highlights = (
        session.query(News)
        .filter(News.is_curated == True)
        .order_by(News.relevance_score.desc(), News.original_published_at.desc())
        .limit(20)
        .all()
    )
    
    report_content = []
    report_content.append("# RELATÓRIO FINAL DE AUDITORIA, SANEAMENTO E CLASSIFICAÇÃO")
    report_content.append(f"**Data da Auditoria:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
    
    report_content.append("## Estatísticas Gerais")
    report_content.append(f"- **Total de notícias analisadas:** {stats['analisadas']}")
    report_content.append(f"- **Total de notícias aprovadas:** {stats['aprovadas']}")
    report_content.append(f"- **Total de notícias rejeitadas/movidas:** {stats['rejeitadas']}")
    report_content.append(f"- **Total de duplicidades encontradas:** {stats['duplicidades_encontradas']}")
    report_content.append(f"- **Total de duplicidades removidas:** {stats['duplicidades_removidas']}\n")
    
    report_content.append("## Distribuição por Relevância")
    for score in range(1, 6):
        count = stats["score_distribution"][score]
        stars = "⭐" * score
        report_content.append(f"- {stars} (Score {score}): {count}")
    report_content.append("")
    
    report_content.append("## Distribuição por Categoria")
    total_approved = stats["aprovadas"]
    if total_approved > 0:
        for cat, count in sorted(stats["category_distribution"].items(), key=lambda x: x[1], reverse=True):
            pct = (count / total_approved) * 100
            report_content.append(f"- **{cat}:** {count} ({pct:.1f}%)")
    else:
        report_content.append("- Nenhuma notícia aprovada.")
    report_content.append("")
    
    report_content.append("## Destaques (Top 20 notícias com maior relevância)")
    if top_highlights:
        report_content.append("| Título | Categoria | Score | Fonte | Data de Publicação |")
        report_content.append("| :--- | :--- | :---: | :--- | :---: |")
        
        # Load sources for name resolution
        sources = session.query(Source).all()
        sources_lookup = {s.id: s.name for s in sources}
        
        for news in top_highlights:
            title = news.translated_title or news.original_title
            source_name = sources_lookup.get(news.source_id, "Desconhecido")
            pub_date = news.original_published_at.strftime('%d/%m/%Y') if news.original_published_at else "N/A"
            stars = "⭐" * (news.relevance_score or 3)
            report_content.append(f"| {title} | {news.category} | {stars} ({news.relevance_score}/5) | {source_name} | {pub_date} |")
    else:
        report_content.append("- Nenhuma notícia de destaque disponível.")
    
    report_markdown = "\n".join(report_content)
    
    # Save to project root or artifacts directory
    # Note: We will write this file as an artifact separately, but we also save it in the project for reference.
    project_artifacts_dir = os.path.join(project_root, "artifacts")
    os.makedirs(project_artifacts_dir, exist_ok=True)
    report_file_path = os.path.join(project_artifacts_dir, "relatorio_auditoria.md")
    
    with open(report_file_path, "w", encoding="utf-8") as f:
        f.write(report_markdown)
        
    logger.info(f"Relatório de auditoria gerado com sucesso em: {report_file_path}")
    print("\n" + "="*50)
    print("APLICAÇÃO DO RELATÓRIO FINAL:")
    print("="*50)
    try:
        print(report_markdown)
    except UnicodeEncodeError:
        print(report_markdown.encode('ascii', errors='replace').decode('ascii'))

    print("="*50 + "\n")

if __name__ == "__main__":
    run_database_audit()
