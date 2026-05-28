import logging
import os
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional, Set

from deep_translator import GoogleTranslator
from openai import OpenAI

from database.config import settings
from database.connection import get_db_session
from database.models import News, Source, SourceType

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("news_processor")

import httpx

# Initialize AI client: OpenAI fallback
openai_client = None
if settings.OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info(f"OpenAI Client initialized using {settings.OPENAI_MODEL}")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")


def call_gemini_api(prompt: str, system_instruction: str = None, max_tokens: int = 150, temperature: float = 0.3) -> str:
    """
    Direct HTTP request to Google Gemini API (bypassing OpenAI compatibility layer to avoid version/v1main errors).
    Tries multiple active models (gemini-3.5-flash, gemini-2.5-flash-lite) to avoid deprecation/quota failures,
    with exponential backoff for rate limits (HTTP 429).
    """
    import time
    key = settings.GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY is not configured.")
        
    models = ["gemini-3.5-flash", "gemini-2.5-flash-lite"]
    last_error = None
    
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
            
        payload["generationConfig"] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        max_attempts = 4
        base_delay = 3.0
        
        for attempt in range(max_attempts):
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(url, json=payload, headers=headers)
                    
                    if response.status_code == 429:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Gemini API rate limit (429) hit for model {model}. Retrying in {delay:.1f}s...")
                        if attempt == max_attempts - 1:
                            last_error = httpx.HTTPStatusError(
                                "Rate limit exceeded (429)", 
                                request=response.request, 
                                response=response
                            )
                        else:
                            time.sleep(delay)
                        continue
                        
                    response.raise_for_status()
                    data = response.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                if attempt == max_attempts - 1:
                    logger.warning(f"Failed to call Gemini using model {model} after {max_attempts} attempts: {str(e)}")
                    last_error = e
                else:
                    time.sleep(1.0)
                    
    if last_error is None:
        raise ValueError("All Gemini models were rate limited or failed to respond.")
    raise last_error


def get_recent_titles_from_db(hours_limit: int = 24) -> List[str]:
    """
    Retrieves all news titles processed in the last 24 hours for similarity checks.
    """
    since_time = datetime.utcnow() - timedelta(hours=hours_limit)
    try:
        with get_db_session() as session:
            recent_news = (
                session.query(News.original_title)
                .filter(News.created_at >= since_time)
                .all()
            )
            return [news.original_title for news in recent_news]
    except Exception as e:
        logger.error(f"Failed to fetch recent titles from database: {str(e)}")
        # In case of DB failure, return empty list to not halt the pipeline
        return []


def calculate_similarity(title_a: str, title_b: str) -> float:
    """
    Computes a simple ratio of similarity between two strings using SequenceMatcher.
    Normalized to lowercase and stripped.
    """
    str_a = title_a.strip().lower()
    str_b = title_b.strip().lower()
    return SequenceMatcher(None, str_a, str_b).ratio()


def is_similar_to_recent(
    title: str, 
    recent_titles: List[str], 
    threshold: float = 0.8
) -> bool:
    """
    Compares the current title against the list of recently scraped titles.
    Returns True if similarity exceeds the threshold percentage.
    """
    for recent in recent_titles:
        similarity = calculate_similarity(title, recent)
        if similarity >= threshold:
            logger.warning(
                f"Similarity match found! '{title[:35]}...' "
                f"is {similarity:.2%} similar to recent '{recent[:35]}...'."
            )
            return True
    return False


def translate_text(text: str, target_lang: str = "pt") -> str:
    """
    Translates a title into Portuguese using deep-translator (Google Translator API).
    Includes failure fallback that returns the original text to prevent execution stops.
    """
    if not text:
        return ""
    try:
        logger.info(f"Translating: '{text[:40]}...'")
        translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
        return translated
    except Exception as e:
        logger.error(f"Translation API failed for text '{text[:40]}...': {str(e)}")
        # Fallback: Return original text to keep the news moving
        return text


def generate_ai_summary(title: str, source_name: str) -> str:
    """
    Generates a 3-bullet-point executive summary focusing on business and tech using Gemini or OpenAI.
    If the AI API fails or is unconfigured, falls back to a clean mock summary.
    """
    system_prompt = (
        "Você é um engenheiro de dados e analista de inteligência de negócios. "
        "Sua tarefa é gerar um resumo executivo curto de no máximo 3 pontos-chave (bullet points), "
        "focado em tecnologia e oportunidades de negócios, baseado no título da notícia fornecido. "
        "O formato de saída deve conter estritamente 3 marcadores usando hífen ('-'). Seja claro e objetivo."
    )
    user_prompt = f"Título da notícia: {title}"

    # 1. Try Gemini first if key is present
    if settings.GEMINI_API_KEY:
        try:
            summary = call_gemini_api(
                prompt=user_prompt,
                system_instruction=system_prompt,
                max_tokens=150,
                temperature=0.3
            )
            if summary:
                return summary.strip()
        except Exception as e:
            logger.error(f"Gemini API direct call failed for summary of '{title[:40]}...': {str(e)}")

    # 2. Try OpenAI fallback if client is initialized
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=150,
                temperature=0.3
            )
            summary = response.choices[0].message.content
            if summary:
                return summary.strip()
        except Exception as e:
            logger.error(f"OpenAI API call failed for summary of '{title[:40]}...': {str(e)}")

    # 3. No AI config fallback
    if not settings.GEMINI_API_KEY and not openai_client:
        logger.warning("No AI providers configured. Using static fallback summary.")
        return (
            f"- Notícia originada do portal {source_name}.\n"
            f"- Requer análise manual devido à ausência de chaves de API de IA.\n"
            f"- Título do Artigo: {title}"
        )
        
    # Fallback in case of call errors (rate limit, credit expiration, connection issues)
    return (
        f"- Notícia de tecnologia relevante reportada por {source_name}.\n"
        f"- Coleta executada com sucesso. Resumo automático indisponível (limite de API/Timeout).\n"
        f"- Assunto principal: {title}"
    )


def is_relevant_article_ai(title: str) -> bool:
    """
    Uses the configured AI client (Gemini or OpenAI) to perform a context-aware relevance check.
    Returns True if the article is relevant to Tech, Entrepreneurship, or Investments/Business.
    Returns False otherwise.
    """
    system_prompt = (
        "Você é um classificador de notícias para um portal focado estritamente em "
        "Tecnologia, Empreendedorismo e Investimentos/Negócios.\n"
        "Sua tarefa é analisar o título da notícia fornecido e determinar se ele é RELEVANTE "
        "para essas áreas ou se é IRRELEVANTE (esportes, política partidária, fofocas, "
        "crimes comuns, receitas, variedades, etc.).\n"
        "Responda estritamente com 'SIM' se for relevante, ou 'NÃO' se for irrelevante. "
        "Não escreva nada além de 'SIM' ou 'NÃO'."
    )
    user_prompt = f"Título: {title}"

    # 1. Try Gemini first if key is present
    if settings.GEMINI_API_KEY:
        try:
            answer = call_gemini_api(
                prompt=user_prompt,
                system_instruction=system_prompt,
                max_tokens=5,
                temperature=0.0
            )
            if answer:
                clean_answer = answer.strip().upper()
                logger.info(f"Gemini classification for '{title[:40]}...': {clean_answer}")
                return "SIM" in clean_answer
        except Exception as e:
            logger.error(f"Gemini relevance check failed for '{title[:40]}...': {str(e)}")

    # 2. Try OpenAI fallback if client is initialized
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=5,
                temperature=0.0
            )
            answer = response.choices[0].message.content
            if answer:
                clean_answer = answer.strip().upper()
                logger.info(f"OpenAI classification for '{title[:40]}...': {clean_answer}")
                return "SIM" in clean_answer
        except Exception as e:
            logger.error(f"OpenAI relevance check failed for '{title[:40]}...': {str(e)}")

    # Fallback to True in case of API failure so we don't drop legitimate articles
    return True


# --- Intelligent Relevance Filter Configuration ---
BLACKLIST_PHRASES = [
    "champions league", "real madrid", "copa do mundo", "libertadores", "brasileirão",
    "previsão do tempo", "corpo encontrado", "receita de", "como fazer bolo",
    "ex-bbb", "dança dos famosos", "zona de rebaixamento", "fórmula 1", "fórmula-1",
    "grand slam", "roland garros", "wimbledon", "ucl", "premier league", "la liga",
    "série a", "série b", "série c", "copa do brasil", "sul-americana",
    "polícia militar", "polícia civil", "corpo de bombeiros", "acidente de trânsito",
    "tráfego de drogas", "tráfico de drogas", "prisão em flagrante", "mandado de prisão",
    "campeonato brasileiro", "campeonato paulista", "campeonato carioca", "futebol feminino",
    "futebol masculino", "copa américa", "copa america", "eurocopa", "mundial de clubes",
    "taça libertadores", "mercado da bola", "janela de transferências", "bola de ouro",
    "ballon d'or", "chuteira de ouro", "super bowl", "superbowl", "são paulo fc",
    "são paulo f.c.", "são paulo futebol clube", "campeonato espanhol", "campeonato inglês",
    "campeonato italiano", "campeonato alemão", "campeonato francês", "liga dos campeões",
    "liga europa", "europa league", "conference league", "formula 1", "formula-1",
    "contratação de jogador", "novo técnico do", "novo técnico de", "tabela do campeonato",
    "tabela do brasileirão", "jogo de futebol", "partida de futebol", "gol de placa",
    "gol de bicicleta", "gol de cabeça", "marcou um gol", "fazer gol", "fez gol", "faz gol",
    "reality show", "reality-show", "reality shows"
]

BLACKLIST_WORDS = {
    # Esportes & Futebol
    "futebol", "partida", "campeonato", "copa", "torcida", "escalação", "clássico",
    "palmeiras", "corinthians", "flamengo", "santos", "vasco", "botafogo", "fluminense",
    "grêmio", "cruzeiro", "neymar", "messi", "ronaldo", "mbappé", "treinador", "quadra",
    "estádio", "arena", "atleta", "atletas", "basquete", "vôlei", "voleibol", "natação",
    "tênis", "ufc", "boxe", "luta", "combate", "nocaute", "olimpíada", "olimpíadas",
    "olímpico", "olímpica", "esporte", "esportes", "esportiva", "esportivo", "seleção",
    "convocado", "convocação", "arbitragem", "árbitro", "pênalti", "impedimento",
    "haaland", "haland", "lewandowski", "bellingham", "guardiola", "ancelotti", "dorival",
    "tite", "zubeldia", "gabigol", "endrick", "estêvão", "estevao", "spfc", "coritiba",
    "coxa", "chapecoense", "chape", "bragantino", "ituano", "novorizontino", "mirassol",
    "brusque", "paysandu", "avai", "avaí", "criciúma", "criciuma", "juventude", "sporting",
    "benfica", "arsenal", "chelsea", "liverpool", "juventus", "milan", "barcelona",
    "psg", "bayer", "bayern", "dortmund", "tottenham", "sevilla", "atletico", "atlético",
    "boca juniors", "river plate", "al-nassr", "al-hilal", "chuteira", "chuteiras",
    "placar", "goleador", "goleadores", "goleada", "goleadas", "goleiro", "goleiros",
    "zagueiro", "zagueiros", "atacante", "atacantes", "centroavante", "centroavantes",
    "artilheiro", "artilheiros", "artilharia", "apitador", "apito", "futsal", "futevôlei",
    "futevolei", "altinha", "nba", "nfl", "superbowl", "fifa", "cbf", "conmebol", "uefa",
    "ciclista", "ciclismo", "maratona", "maratonista", "maratonistas", "ginasta", "ginastas",
    "ginástica", "judoca", "karateca", "esgrimista", "esgrima", "surfista", "surfistas",
    "skatista", "skatistas", "velejador", "velejadores", "gols", "djokovic", "alcaraz",
    "federer", "nadal", "swiatek", "sinner", "hamilton", "verstappen", "senna", "pique",
    "rubinho", "leclerc", "norris", "poatan", "popó", "bambam",
    # Celebridades, Entretenimento & TV
    "bbb", "novela", "novelas", "ator", "atriz", "atores", "atrizes",
    "celebridade", "celebridades", "fofoca", "fofocas", "influencer", "influenciador",
    "influenciadores", "tiktok", "youtuber", "divórcio", "flagrado", "flagrada", "biquíni",
    "look", "looks", "anitta", "virgínia", "ludmilla", "gusttavo",
    # Violência, Crimes & Acidentes
    "assassinato", "homicídio", "latrocínio", "estupro", "baleado", "baleada",
    "tiroteio", "facada", "furto", "assalto", "sequestro", "refém", "reféns",
    "cadeia", "penitenciária", "tragédia", "trágico", "trágica", "atropelamento",
    "capotamento", "enchente", "inundação", "ventania", "tornado", "furacão",
    # Política Partidária e Eleitoral
    "eleição", "eleições", "urna", "urnas", "candidato", "candidata", "candidatos",
    "campanha", "debate", "debates", "prefeito", "prefeita", "vereador", "vereadora",
    "governador", "governadora", "senador", "senadora", "bolsonarista", "petista",
    # Cotidiano & Variedades
    "horóscopo", "signos", "astrologia", "culinária"
}

WHITELIST_WORDS = {
    # Tecnologia & Inovação
    "tecnologia", "tech", "ia", "ai", "inteligência", "inteligencia", "artificial",
    "software", "app", "aplicativo", "aplicativos", "startup", "startups", "chip", "chips",
    "semicondutor", "semicondutores", "dados", "cloud", "nuvem", "segurança", "hacker",
    "hackers", "cyber", "cibersegurança", "ciber", "robô", "robôs", "robótica", "cripto",
    "bitcoin", "btc", "blockchain", "algoritmo", "algoritmos", "programação", "desenvolvedor",
    "desenvolvedores", "hardware", "celular", "celulares", "smartphone", "smartphones",
    "apple", "microsoft", "google", "meta", "nvidia", "amazon", "telefonia", "5g", "inovação",
    "inovações", "digital", "digitais", "plataforma", "plataformas", "sistema", "sistemas",
    # Negócios, Economia & Mercado Financeiro
    "mercado", "mercados", "bolsa", "ações", "ação", "dividendo", "dividendos", "juros",
    "selic", "inflação", "ipca", "pib", "economia", "financeiro", "financeira", "finanças",
    "banco", "bancos", "fintech", "fintechs", "aporte", "aportes", "fusão", "fusões",
    "aquisição", "aquisições", "m&a", "investe", "investimento", "investimentos",
    "investidor", "investidores", "captar", "captação", "receita", "faturamento", "lucro",
    "lucros", "prejuízo", "valuation", "saf", "bilhão", "bilhões", "milhão", "milhões",
    "tesouro", "cdb", "fii", "fiis", "fundo", "fundos", "tributo", "tributos", "imposto",
    "impostos", "taxação", "taxar", "taxa", "taxas", "reforma", "tributária", "tributário",
    "bc", "central", "fed", "monetário", "monetária", "crédito", "debentures", "ouro",
    "commodities", "dólar", "euro", "câmbio", "vendas", "venda", "comercial", "varejo",
    "indústria", "produção", "alta", "altas", "queda", "quedas", "recua", "recuo", "sobe",
    "subida", "despenca", "despencar", "dispara", "disparar", "fecha", "fecham", "fechamento",
    "fechar",
    # Empreendedorismo & Gestão
    "empreendedor", "empreendedora", "empreendedores", "empreendedorismo", "negócio",
    "negócios", "empresa", "empresas", "empresário", "empresária", "empresários",
    "franquia", "franquias", "pyme", "pmes", "microempresa", "fundador", "fundadora",
    "fundadores", "liderança", "gestão", "ceo", "co-founder", "carreira", "vaga", "vagas",
    "trabalho", "emprego", "empregos", "estratégia", "estratégias", "cliente", "clientes",
    "produtos", "produto", "marca", "marcas", "líder", "setor", "setores", "grupo",
    "fábrica", "unidade", "unidades", "exportação", "exportações", "importação", "importações",
    # Governo & Regulação Econômica/Tech
    "governo", "regra", "regras", "lei", "leis", "projeto", "projetos", "senado", "câmara",
    "ministério", "ministro", "presidente", "decisão", "decisões", "medida", "medidas",
    "orçamento", "público", "pública", "estado", "tcu", "stf"
}

GENERALIST_SOURCES = {"InfoMoney", "G1 Tecnologia"}

def tokenize_and_normalize(text: str) -> Set[str]:
    # Replace non-alphanumeric characters (including hyphens) with spaces and split
    normalized = re.sub(r'[^\w\s]', ' ', text.lower())
    return set(normalized.split())

def is_relevant_article(title: str, source_name: str) -> bool:
    title_lower = title.lower()
    
    # 1. Blacklist Phrases Check (Substring match)
    for phrase in BLACKLIST_PHRASES:
        if phrase in title_lower:
            return False
            
    # Tokenize the title for word-level checks
    words = tokenize_and_normalize(title)
    
    # 2. Blacklist Words Check (Exact match of tokenized words)
    if not words.isdisjoint(BLACKLIST_WORDS):
        return False
        
    # 3. Whitelist Check for Generalist Sources
    if source_name in GENERALIST_SOURCES:
        # Require at least one word from the title to be in the whitelist
        if words.isdisjoint(WHITELIST_WORDS):
            return False
            
    return True


def process_article(
    article_data: Dict[str, Any], 
    source: Source, 
    recent_titles: List[str]
) -> Dict[str, Any] | None:
    """
    Applies the full processing pipeline to a newly scraped news item:
    0. Heuristic relevance check.
    1. Check for similarity deduplication.
    2. Check source type; translate title if SourceType.INTERNACIONAL.
    3. Generate executive summary using LLM.
    
    Returns the processed dictionary ready for DB save, or None if skipped.
    """
    title = article_data["original_title"]
    
    # 0. Relevance Heuristic Filter (skip off-topic/gossip/sports)
    if not is_relevant_article(title, source.name):
        logger.info(f"Skipping article (heuristic irrelevant): '{title[:50]}'")
        return None
        
    # 0.1. AI-powered Relevance Filter (smarter check using Gemini/OpenAI)
    if not is_relevant_article_ai(title):
        logger.info(f"Skipping article (AI classified as irrelevant): '{title[:50]}'")
        return None
        
    # 1. Deduplication check (Similarity > 80%)
    if is_similar_to_recent(title, recent_titles, threshold=0.8):
        logger.info(f"Skipping article (similar news exists): '{title[:50]}'")
        return None

    processed_data = article_data.copy()
    
    # 2. Translation logic
    if source.type == SourceType.INTERNACIONAL:
        translated_title = translate_text(title, target_lang="pt")
        processed_data["translated_title"] = translated_title
    else:
        # For national news, translated title can be the original or empty
        processed_data["translated_title"] = title

    # 3. AI Summary Generation
    # Uses translated title for better prompt context if available
    summary_seed_title = processed_data.get("translated_title") or title
    processed_data["ai_summary"] = generate_ai_summary(
        title=summary_seed_title, 
        source_name=source.name
    )
    
    # Define placeholder reduced key for search terms
    processed_data["reduced_key"] = " ".join(
        [word.lower() for word in summary_seed_title.split() if len(word) > 3]
    )[:255]

    return processed_data
