import os
import sys
import json
from datetime import datetime

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.connection import get_db_session
from database.models import News

def run():
    print("Connecting to database...")
    with get_db_session() as session:
        # Check if we have an article to update, or create a new one
        article = session.query(News).filter(News.id == 744).first()
        if not article:
            article = session.query(News).first()
            
        if not article:
            print("No articles found in DB. Creating a new mock article...")
            # We need a source
            from database.models import Source
            source = session.query(Source).first()
            if not source:
                source = Source(name="TechCrunch", url="https://techcrunch.com", is_active=True)
                session.add(source)
                session.commit()
                
            article = News(
                original_title="OpenAI launches Gemini-killer search engine SearchGPT",
                link="https://techcrunch.com/searchgpt",
                source_id=source.id,
                is_curated=True
            )
            session.add(article)
            session.commit()
            
        print(f"Updating article ID {article.id}: '{article.original_title}'")
        
        # Populate premium fields
        article.is_curated = True
        article.editorial_status = "publicado"
        article.editorial_title = "OpenAI Lança SearchGPT: O Novo Mecanismo de Busca Baseado em IA Inteligente"
        
        summary_dict = {
            "what_happened": "A OpenAI anunciou oficialmente o SearchGPT, um protótipo de mecanismo de busca voltado para responder perguntas de forma rápida e contextualizada com links diretos para fontes.",
            "why_it_matters": "Esta iniciativa representa uma concorrência direta ao monopólio do Google Search e ao avanço da Perplexity no setor de buscas alimentadas por inteligência artificial.",
            "possible_impacts": "Mudança estrutural no tráfego de blogs e portais de notícias, além de potencial redução de cliques em links tradicionais.",
            "key_points": [
                "Interface limpa focada em respostas diretas e conversacionais.",
                "Parcerias estratégicas com grandes portais de notícias para exibição de atribuições corretas.",
                "Recurso será integrado futuramente de forma nativa ao ChatGPT."
            ]
        }
        article.editorial_summary = json.dumps(summary_dict, ensure_ascii=False)
        article.editorial_category = "IA/Automação"
        article.editorial_tags = json.dumps(["OpenAI", "SearchGPT", "Google", "Mecanismo de Busca"], ensure_ascii=False)
        article.meta_description = "OpenAI desafia o Google com o lançamento do SearchGPT, um buscador inteligente em tempo real."
        
        article.editorial_scores = {
            "clarity_score": 95,
            "impact_score": 98,
            "innovation_score": 90
        }
        
        # Overwrite standard fields so fallback UI renders it
        article.translated_title = article.editorial_title
        
        # Format the markdown summary
        md_parts = [
            f"🔍 **O que aconteceu?**\n{summary_dict['what_happened']}",
            f"💡 **Por que isso importa?**\n{summary_dict['why_it_matters']}",
            f"⚡ **Possíveis impactos**\n{summary_dict['possible_impacts']}",
            f"📌 **Pontos-chave**\n" + "\n".join([f"- {kp}" for kp in summary_dict['key_points']])
        ]
        article.ai_summary = "\n\n".join(md_parts)
        article.category = article.editorial_category
        
        session.commit()
        print("Mock premium article saved successfully!")

if __name__ == "__main__":
    run()
