import logging
import time
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy import or_

from database.connection import get_db_session
from database.models import News, Source, NoticiasRejeitadas
from .config import agent_settings
from .filters import LocalFilter
from .gateway import GeminiGateway
from .schemas import CurationResponse
from .prompts import SYSTEM_CURATION_PROMPT_TEMPLATE
from .utils import ExecutionMetrics

logger = logging.getLogger("news_agent.orchestrator")

class AgentOrchestrator:
    def __init__(self):
        self.gateway = GeminiGateway()
        
    def run_curation_pipeline(self) -> str:
        """
        Runs the full AI News Curation Pipeline (Step 8: Triagem de novas notícias):
        1. Fetch uncurated news from the database.
        2. Filter out junk and duplicate news locally.
        3. Fetch dynamic reference examples (Step 7: learning from score 4/5 items).
        4. Curation & Classification: Call Gemini in batches to decide APROVADA/REPROVADA, category, score, justification.
        5. For rejected or score < 3, move to noticias_rejeitadas and delete from news.
        6. For approved (score >= 3): update news model, set priority and destaque flags.
        7. Select top 5 (up to 7 if score is 4 or 5) for final publishing (Telegram notifications). Set others to falha.
        """
        metrics = ExecutionMetrics()
        metrics.start()
        
        logger.info("Initializing Agent Curation Pipeline...")
        
        try:
            # 1. Fetch uncurated news from database
            with get_db_session() as session:
                # Load all news where is_curated is False or None
                db_news = (
                    session.query(News)
                    .filter(or_(News.is_curated == False, News.is_curated == None))
                    .all()
                )
                
                if not db_news:
                    logger.info("No uncurated news found in the database. Exiting pipeline.")
                    metrics.stop(success=True)
                    return metrics.report()
                    
                # Cache source names
                sources = session.query(Source).all()
                source_lookup = {src.id: src.name for src in sources}
                
                # Map db models to dictionaries
                raw_items = []
                for item in db_news:
                    raw_items.append({
                        "id": item.id,
                        "original_title": item.original_title,
                        "translated_title": item.translated_title,
                        "source_name": source_lookup.get(item.source_id, "Desconhecido"),
                        "ai_summary": item.ai_summary
                    })
                    
            logger.info(f"Loaded {len(raw_items)} uncurated articles from DB.")
            
            # 2. Local Filtering & Deduplication
            filtered_items = LocalFilter.filter_and_deduplicate(raw_items)
            metrics.filtered_locally = len(raw_items) - len(filtered_items)
            
            # Move locally filtered items (rejected by heuristic or duplicate) to noticias_rejeitadas
            filtered_ids = {item["id"] for item in raw_items} - {item["id"] for item in filtered_items}
            if filtered_ids:
                logger.info(f"Moving {len(filtered_ids)} locally filtered items to noticias_rejeitadas.")
                with get_db_session() as session:
                    for item_id in filtered_ids:
                        db_item = session.query(News).filter(News.id == item_id).first()
                        if db_item:
                            title = db_item.translated_title or db_item.original_title or ""
                            rejected = NoticiasRejeitadas(
                                id_noticia=db_item.id,
                                titulo=title,
                                link=db_item.link,
                                motivo_rejeicao="FILTRADO LOCALMENTE (DUPLICIDADE OU FORA DE ESCOPO)",
                                data_rejeicao=datetime.utcnow(),
                                categoria_identificada="Outros"
                            )
                            session.add(rejected)
                            session.delete(db_item)
                    session.commit()
            
            if not filtered_items:
                logger.info("No articles remained after local filtering. Exiting pipeline.")
                metrics.stop(success=True)
                return metrics.report()
                
            # 3. Fetch dynamic reference examples (Step 7: Learning from score 4/5)
            with get_db_session() as session:
                examples = (
                    session.query(News)
                    .filter(News.is_curated == True)
                    .filter(News.relevance_score.in_([4, 5]))
                    .order_by(News.curated_at.desc())
                    .limit(5)
                    .all()
                )
                if examples:
                    examples_str = "Exemplos de Referência (Score 4 e 5) obtidos da base:\n"
                    for ex in examples:
                        title = ex.translated_title or ex.original_title
                        examples_str += f"- Título: {title} | Categoria: {ex.category} | Score: {ex.relevance_score} | Justificativa: {ex.ai_justification}\n"
                else:
                    # Default static examples
                    examples_str = """Exemplos de Referência (Score 4 e 5):
- Título: OpenAI lança GPT-4o, novo modelo capaz de raciocinar em tempo real por voz e visão | Categoria: Inteligência Artificial | Score: 5 | Justificativa: Avanço altamente disruptivo no campo de IA generativa e modelos multimodais.
- Título: Nvidia ultrapassa Apple como segunda empresa mais valiosa com chips de IA | Categoria: Investimentos | Score: 4 | Justificativa: Movimentação de mercado significativa impulsionada pela demanda global de infraestrutura de IA.
- Título: Cientistas conseguem fazer o primeiro teleporte quântico estável de longa distância | Categoria: Computação Quântica | Score: 5 | Justificativa: Breakthrough científico na computação quântica com impacto de longo prazo.
"""
            
            system_prompt = SYSTEM_CURATION_PROMPT_TEMPLATE.format(reference_examples=examples_str)
            
            # 4. Batch Curation
            approved_count = 0
            rejected_count = 0
            approved_news_ids = []
            
            batch_size = 15
            for i in range(0, len(filtered_items), batch_size):
                chunk = filtered_items[i:i+batch_size]
                
                # Format chunk for prompt
                news_list_str = ""
                for item in chunk:
                    title = item.get("translated_title") or item.get("original_title") or ""
                    summary = item.get("ai_summary") or "Sem resumo disponível."
                    news_list_str += f"- ID: {item['id']} | Título: {title} | Resumo: {summary}\n"
                    
                prompt = f"Por favor, classifique a relevância e escopo do seguinte lote de notícias:\n\n{news_list_str}"
                
                try:
                    logger.info(f"Calling Gemini Curation API for batch {i//batch_size + 1}...")
                    response = self.gateway.call_structured_api(
                        prompt=prompt,
                        system_instruction=system_prompt,
                        response_model=CurationResponse
                    )
                    metrics.api_calls += 1
                    
                    # 5. Process responses and update DB
                    with get_db_session() as session:
                        for classification in response.get("items", []):
                            item_id = classification["id"]
                            status_val = classification["status"].upper() # APROVADA or REPROVADA
                            justificativa = classification["justificativa"]
                            categoria = classification["categoria_identificada"]
                            score = classification["score"]
                            
                            db_item = session.query(News).filter(News.id == item_id).first()
                            if not db_item:
                                continue
                                
                            if status_val == "REPROVADA":
                                rejected = NoticiasRejeitadas(
                                    id_noticia=db_item.id,
                                    titulo=db_item.translated_title or db_item.original_title,
                                    link=db_item.link,
                                    motivo_rejeicao=justificativa or "REPROVADA POR ESCOPO",
                                    data_rejeicao=datetime.utcnow(),
                                    categoria_identificada=categoria or "Outros"
                                )
                                session.add(rejected)
                                session.delete(db_item)
                                rejected_count += 1
                            else:
                                # APROVADA
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
                                    rejected_count += 1
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
                                        
                                    approved_count += 1
                                    approved_news_ids.append(db_item.id)
                                    
                        session.commit()
                        
                except Exception as e:
                    logger.error(f"Error in curation batch {i//batch_size + 1}: {e}")
                    metrics.errors.append(f"Curation error: {e}")
                    # Fallback
                    with get_db_session() as session:
                        for item in chunk:
                            db_item = session.query(News).filter(News.id == item["id"]).first()
                            if db_item:
                                db_item.relevance_score = 3
                                db_item.category = "Tecnologia"
                                db_item.ai_justification = "Classificação automática simplificada devido a falha da API."
                                db_item.is_curated = True
                                db_item.curated_at = datetime.utcnow()
                                db_item.priority = "baixa"
                                db_item.destaque = False
                                approved_count += 1
                                approved_news_ids.append(db_item.id)
                        session.commit()
                        
            metrics.processed_p1 = len(filtered_items)
            metrics.processed_p2 = approved_count
            
            # 6. Apply Curation Publishing Rules for Telegram (Top 5 to 7)
            if approved_news_ids:
                with get_db_session() as session:
                    scored_news = session.query(News).filter(News.id.in_(approved_news_ids)).all()
                    scored_news.sort(key=lambda x: x.relevance_score or 0, reverse=True)
                    
                    selected_news = []
                    for idx, news_item in enumerate(scored_news):
                        if idx < agent_settings.FINAL_MIN_NEWS:
                            selected_news.append(news_item)
                        elif idx < agent_settings.FINAL_MAX_NEWS:
                            if (news_item.relevance_score or 0) >= 4:
                                selected_news.append(news_item)
                                logger.info(f"Including exceptional article ID {news_item.id} with score {news_item.relevance_score} for Telegram.")
                            else:
                                news_item.send_status = "falha"
                        else:
                            news_item.send_status = "falha"
                            
                    for news_item in selected_news:
                        news_item.send_status = "pendente"
                        
                    session.commit()
                    logger.info(f"Curation complete. Selected {len(selected_news)} articles to Telegram dispatch. Total approved in DB: {approved_count}.")
                    
            metrics.stop(success=True)
            return metrics.report()
            
        except Exception as e:
            logger.exception("Critical error in Curation Pipeline Orchestrator:")
            metrics.stop(success=False)
            metrics.errors.append(f"Critical orchestrator error: {e}")
            return metrics.report()
