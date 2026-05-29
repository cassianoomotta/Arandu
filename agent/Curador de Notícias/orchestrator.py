import logging
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy import or_

from database.connection import get_db_session
from database.models import News, Source
from .config import agent_settings
from .filters import LocalFilter
from .gateway import GeminiGateway
from .schemas import Phase1Response, Phase2Response
from .utils import calculate_local_heuristic_score, ExecutionMetrics

logger = logging.getLogger("news_agent.orchestrator")

class AgentOrchestrator:
    def __init__(self):
        self.gateway = GeminiGateway()
        
    def run_curation_pipeline(self) -> str:
        """
        Runs the full AI News Curation Pipeline:
        1. Fetch uncurated news from the database.
        2. Filter out junk and duplicate news locally.
        3. Score articles locally with heuristics and sort.
        4. Phase 1: Coarse classification in batches of 20.
        5. Phase 2: Fine-grained classification of the top 50 in micro-batches of 5.
        6. Select top 5 (up to 7 exceptional) for final publishing.
        7. Mark all processed articles as curated.
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
            
            # Mark filtered items as curated in DB so they aren't processed again
            filtered_ids = {item["id"] for item in raw_items} - {item["id"] for item in filtered_items}
            if filtered_ids:
                logger.info(f"Marking {len(filtered_ids)} locally filtered items as processed (score=0).")
                with get_db_session() as session:
                    session.query(News).filter(News.id.in_(filtered_ids)).update(
                        {"is_curated": True, "relevance_score": 0, "curated_at": datetime.utcnow()},
                        synchronize_session=False
                    )
                    session.commit()
            
            if not filtered_items:
                logger.info("No articles remained after local filtering. Exiting pipeline.")
                metrics.stop(success=True)
                return metrics.report()
                
            # 3. Calculate local heuristic scores and sort
            for item in filtered_items:
                title = item.get("translated_title") or item.get("original_title") or ""
                item["heuristic_score"] = calculate_local_heuristic_score(title)
                
            # Sort by heuristic score descending
            filtered_items.sort(key=lambda x: x["heuristic_score"], reverse=True)
            
            # Cap at 200 items to avoid token overload
            if len(filtered_items) > 200:
                discarded_items = filtered_items[200:]
                filtered_items = filtered_items[:200]
                discarded_ids = [item["id"] for item in discarded_items]
                logger.info(f"Capped news pool to 200 items. Marking {len(discarded_ids)} extra items as processed.")
                with get_db_session() as session:
                    session.query(News).filter(News.id.in_(discarded_ids)).update(
                        {"is_curated": True, "relevance_score": 0, "curated_at": datetime.utcnow()},
                        synchronize_session=False
                    )
                    session.commit()

            # 4. Phase 1: Coarse Classification in Batches of 20
            logger.info(f"Starting Phase 1 (Coarse Classification) for {len(filtered_items)} items...")
            from .prompts import PHASE1_SYSTEM_PROMPT
            
            phase1_results = {}  # Map id -> score (0-10)
            
            # Batch the items
            batch_size = agent_settings.PHASE1_BATCH_SIZE
            for i in range(0, len(filtered_items), batch_size):
                chunk = filtered_items[i:i+batch_size]
                
                # Format chunk for prompt
                news_list_str = ""
                for item in chunk:
                    title = item.get("translated_title") or item.get("original_title") or ""
                    news_list_str += f"- ID: {item['id']} | Título: {title}\n"
                    
                prompt = f"Por favor, classifique a relevância preliminar das seguintes notícias:\n\n{news_list_str}"
                
                try:
                    logger.info(f"Calling Gemini Phase 1 API for batch {i//batch_size + 1}...")
                    response = self.gateway.call_structured_api(
                        prompt=prompt,
                        system_instruction=PHASE1_SYSTEM_PROMPT,
                        response_model=Phase1Response
                    )
                    metrics.api_calls += 1
                    
                    # Store results
                    for classification in response.get("classifications", []):
                        item_id = classification["id"]
                        score = classification["score"]
                        phase1_results[item_id] = score
                        
                except Exception as e:
                    logger.error(f"Error in Phase 1 batch {i//batch_size + 1}: {e}")
                    metrics.errors.append(f"Phase 1 error: {e}")
                    # Fallback to local heuristic score for this batch
                    for item in chunk:
                        phase1_results[item["id"]] = item["heuristic_score"]

            metrics.processed_p1 = len(phase1_results)
            
            # Attach Phase 1 score to filtered_items
            for item in filtered_items:
                item["phase1_score"] = phase1_results.get(item["id"], 0)
                
            # Sort items by Phase 1 score descending
            filtered_items.sort(key=lambda x: x.get("phase1_score", 0), reverse=True)
            
            # Select the top 50 candidates for Phase 2
            top_50 = filtered_items[:agent_settings.TOP_N_SELECTION]
            logger.info(f"Phase 1 complete. Selected Top {len(top_50)} candidates for Phase 2 detailed classification.")
            
            # Mark the remaining candidates (not in top 50) as curated with their low score
            remaining_ids = [item["id"] for item in filtered_items[agent_settings.TOP_N_SELECTION:]]
            if remaining_ids:
                logger.info(f"Marking {len(remaining_ids)} remaining Phase 1 low-score items as processed.")
                with get_db_session() as session:
                    for item_id in remaining_ids:
                        score = phase1_results.get(item_id, 0)
                        session.query(News).filter(News.id == item_id).update({
                            "is_curated": True,
                            "relevance_score": score * 10,  # Scale to 100
                            "curated_at": datetime.utcnow()
                        })
                    session.commit()
            
            if not top_50:
                logger.info("No candidates reached Phase 2. Exiting pipeline.")
                metrics.stop(success=True)
                return metrics.report()

            # 5. Phase 2: Fine-Grained Classification in Micro-Batches of 5
            logger.info(f"Starting Phase 2 (Fine Classification) for {len(top_50)} items...")
            from .prompts import PHASE2_SYSTEM_PROMPT
            
            phase2_results = {}  # Map id -> detailed classification dict
            
            # Micro-batches of 5
            micro_batch_size = 5
            for i in range(0, len(top_50), micro_batch_size):
                chunk = top_50[i:i+micro_batch_size]
                
                # Format chunk for prompt
                news_list_str = ""
                for item in chunk:
                    title = item.get("translated_title") or item.get("original_title") or ""
                    summary = item.get("ai_summary") or "Resumo indisponível"
                    source = item.get("source_name") or "Desconhecido"
                    news_list_str += f"- ID: {item['id']} | Título: {title} | Fonte: {source} | Resumo: {summary}\n"
                    
                prompt = (
                    "Por favor, execute a classificação detalhada para as seguintes notícias pré-selecionadas:\n\n"
                    f"{news_list_str}"
                )
                
                try:
                    logger.info(f"Calling Gemini Phase 2 API for micro-batch {i//micro_batch_size + 1}...")
                    response = self.gateway.call_structured_api(
                        prompt=prompt,
                        system_instruction=PHASE2_SYSTEM_PROMPT,
                        response_model=Phase2Response
                    )
                    metrics.api_calls += 1
                    
                    # Store results
                    for classification in response.get("items", []):
                        item_id = classification["id"]
                        phase2_results[item_id] = {
                            "relevance_score": classification["score_relevance"],
                            "ai_justification": classification["justification"],
                            "category": classification["category"],
                            "priority": classification["priority"]
                        }
                        
                except Exception as e:
                    logger.error(f"Error in Phase 2 micro-batch {i//micro_batch_size + 1}: {e}")
                    metrics.errors.append(f"Phase 2 error: {e}")
                    # Fallback values for this micro-batch
                    for item in chunk:
                        phase2_results[item["id"]] = {
                            "relevance_score": item.get("phase1_score", 0) * 10,
                            "ai_justification": "Classificação automática simplificada devido a falha da API.",
                            "category": "Tecnologia",
                            "priority": "Média"
                        }

            metrics.processed_p2 = len(phase2_results)
            
            # Update DB with Phase 2 results for these 50 news items
            logger.info("Writing Phase 2 detailed curations to database...")
            with get_db_session() as session:
                for item_id, details in phase2_results.items():
                    session.query(News).filter(News.id == item_id).update({
                        "relevance_score": details["relevance_score"],
                        "ai_justification": details["ai_justification"],
                        "category": details["category"],
                        "priority": details["priority"],
                        "is_curated": True,
                        "curated_at": datetime.utcnow()
                    })
                
                # Fallback curation for any top_50 item that was missed/omitted in Phase 2 response
                missed_ids = [item["id"] for item in top_50 if item["id"] not in phase2_results]
                if missed_ids:
                    logger.warning(f"{len(missed_ids)} items were missed in Phase 2 response. Applying fallback curation.")
                    for item_id in missed_ids:
                        p1_score = phase1_results.get(item_id, 0)
                        session.query(News).filter(News.id == item_id).update({
                            "relevance_score": p1_score * 10,
                            "ai_justification": "Classificação detalhada indisponível (omitida pela IA).",
                            "category": "Tecnologia",
                            "priority": "Baixa",
                            "is_curated": True,
                            "curated_at": datetime.utcnow()
                        })
                session.commit()
                
            # 6. Apply Curation Publishing Rules (Top 5 to 7)
            # Fetch all top_50 news items (including fallback ones) to ensure consistency
            top_ids = [item["id"] for item in top_50]
            with get_db_session() as session:
                scored_news = session.query(News).filter(News.id.in_(top_ids)).all()
                
                # Sort by score descending
                scored_news.sort(key=lambda x: x.relevance_score or 0, reverse=True)
                
                # Reset send_status of all scored news in this batch to PENDENTE or keep it
                # To publish, we select the top 5, plus up to 2 exceptional (score >= 90)
                selected_news = []
                for idx, news_item in enumerate(scored_news):
                    if idx < agent_settings.FINAL_MIN_NEWS:
                        selected_news.append(news_item)
                    elif idx < agent_settings.FINAL_MAX_NEWS:
                        if (news_item.relevance_score or 0) >= agent_settings.EXCEPTIONAL_SCORE_THRESHOLD:
                            selected_news.append(news_item)
                            logger.info(f"Including exceptional article ID {news_item.id} with score {news_item.relevance_score}.")
                        else:
                            # Not selected, set send_status to FALHA or another state so it's not dispatched, 
                            # or just leave it. Let's make sure only selected ones are dispatched.
                            news_item.send_status = "falha"  # Mark as failed/not selected to prevent Telegram dispatch
                    else:
                        news_item.send_status = "falha"  # Mark as failed/not selected to prevent Telegram dispatch
                
                # Mark selected news items as send_status = PENDENTE
                for news_item in selected_news:
                    news_item.send_status = "pendente"  # Ensure it is pending for Telegram dispatch
                    
                session.commit()
                logger.info(f"Curation complete. Published {len(selected_news)} articles to portal / notification dispatcher.")
                
            metrics.stop(success=True)
            return metrics.report()
            
        except Exception as e:
            logger.exception("Critical error in Curation Pipeline Orchestrator:")
            metrics.stop(success=False)
            metrics.errors.append(f"Critical orchestrator error: {e}")
            return metrics.report()
