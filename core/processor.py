import logging
import os
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional, Set

from deep_translator import GoogleTranslator

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
import time as _time_module

# Gemini Free Tier rate limits (per minute):
# - gemini-2.5-flash-lite: 15 RPM
# - gemini-2.5-flash: 10 RPM  
# - gemini-3.5-flash: ~10 RPM (paid tier only, but may work with some keys)
_RATE_LIMIT_COOLDOWN_SECONDS = 60  # Gemini resets per-minute limits every 60s


def _ensure_rate_limit_table(session):
    """Creates the rate limit tracking table if it doesn't exist."""
    try:
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS gemini_rate_limit ("
            "  id INTEGER PRIMARY KEY, "
            "  last_hit_at TIMESTAMP NOT NULL"
            ")"
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create gemini_rate_limit table: {e}")


def record_rate_limit_hit():
    """Persists the timestamp of the last 429 rate limit error to the database."""
    try:
        with get_db_session() as session:
            _ensure_rate_limit_table(session)
            # Upsert: try update first, insert if no row exists
            result = session.execute(
                text("UPDATE gemini_rate_limit SET last_hit_at = :now WHERE id = 1"),
                {"now": datetime.utcnow()}
            )
            if result.rowcount == 0:
                session.execute(
                    text("INSERT INTO gemini_rate_limit (id, last_hit_at) VALUES (1, :now)"),
                    {"now": datetime.utcnow()}
                )
            session.commit()
    except Exception as e:
        logger.error(f"Failed to record rate limit hit: {e}")


def get_rate_limit_info() -> dict:
    """Returns rate limit status info for the admin dashboard, persisted in DB."""
    try:
        with get_db_session() as session:
            _ensure_rate_limit_table(session)
            result = session.execute(
                text("SELECT last_hit_at FROM gemini_rate_limit WHERE id = 1")
            ).fetchone()
            
            if not result or not result[0]:
                return {"active": False, "last_hit_at": None, "cooldown_seconds": 0, "resets_at": None}
            
            last_hit = result[0]
            # Handle timezone-naive datetimes
            if hasattr(last_hit, 'replace'):
                last_hit = last_hit.replace(tzinfo=None)
            
            elapsed = (datetime.utcnow() - last_hit).total_seconds()
            remaining = max(0, _RATE_LIMIT_COOLDOWN_SECONDS - elapsed)
            resets_at = last_hit + timedelta(seconds=_RATE_LIMIT_COOLDOWN_SECONDS)
            
            return {
                "active": remaining > 0,
                "last_hit_at": last_hit.isoformat() + "Z",
                "cooldown_seconds": round(remaining),
                "resets_at": resets_at.isoformat() + "Z"
            }
    except Exception as e:
        logger.error(f"Failed to get rate limit info: {e}")
        return {"active": False, "last_hit_at": None, "cooldown_seconds": 0, "resets_at": None}



from sqlalchemy import text

def check_and_create_usage_table(session):
    try:
        session.execute(text("CREATE TABLE IF NOT EXISTS gemini_usage_log (called_at TIMESTAMP)"))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create gemini_usage_log table: {e}")

def get_gemini_usage_today() -> int:
    from datetime import datetime, timedelta
    from database.connection import get_db_session
    
    cutoff = datetime.utcnow() - timedelta(hours=24)
    try:
        with get_db_session() as session:
            check_and_create_usage_table(session)
            result = session.execute(
                text("SELECT COUNT(*) FROM gemini_usage_log WHERE called_at >= :cutoff"),
                {"cutoff": cutoff}
            ).scalar()
            return int(result or 0)
    except Exception as e:
        logger.error(f"Error counting Gemini usage: {e}")
        return 0

def increment_gemini_usage():
    from datetime import datetime
    from database.connection import get_db_session
    try:
        with get_db_session() as session:
            check_and_create_usage_table(session)
            session.execute(
                text("INSERT INTO gemini_usage_log (called_at) VALUES (:now)"),
                {"now": datetime.utcnow()}
            )
            session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error incrementing Gemini usage: {e}")


import threading

# Thread-safe rate limiter to space calls by at least 6 seconds (max 10 RPM)
_gemini_api_lock = threading.Lock()
_last_gemini_call_time = 0.0

def call_gemini_api(prompt: str, system_instruction: str = None, max_tokens: int = 150, temperature: float = 0.3) -> str:
    """
    Direct HTTP request to Google Gemini API (bypassing OpenAI compatibility layer to avoid version/v1main errors).
    Tries multiple active models (gemini-3.5-flash, gemini-2.5-flash-lite) to avoid deprecation/quota failures,
    with exponential backoff for rate limits (HTTP 429).
    Includes a strict 6-second delay between calls to guarantee compliance with the Gemini free tier limits.
    """
    import time
    global _last_gemini_call_time
    
    key = settings.GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY is not configured.")
        
    # Check daily limit
    try:
        usage = get_gemini_usage_today()
        if usage >= settings.GEMINI_DAILY_LIMIT:
            logger.warning(f"Gemini API daily usage limit ({settings.GEMINI_DAILY_LIMIT}) reached. Current count: {usage}. Falling back.")
            raise ValueError(f"Gemini API daily quota limit of {settings.GEMINI_DAILY_LIMIT} requests has been reached. (Count: {usage})")
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Failed to verify Gemini daily usage limits: {e}")

    # Enforce minimum 6-second delay using thread lock to serialize requests
    with _gemini_api_lock:
        now = time.time()
        elapsed = now - _last_gemini_call_time
        required_gap = 6.0  # 10 RPM max
        if elapsed < required_gap:
            sleep_needed = required_gap - elapsed
            logger.info(f"Rate limiting: sleeping for {sleep_needed:.2f}s to respect Gemini API RPM limits.")
            time.sleep(sleep_needed)
        _last_gemini_call_time = time.time()

    # Log/track call
    try:
        increment_gemini_usage()
    except Exception as e:
        logger.error(f"Failed to increment Gemini usage log: {e}")
        
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
                        record_rate_limit_hit()
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


def _clean_summary_preamble(text: str) -> str:
    """
    Strips any preamble/intro text that Gemini sometimes adds before the actual
    bullet points (e.g. 'Aqui está o resumo executivo:', 'Segue abaixo:', etc).
    Returns only the lines starting with '-' or '**'.
    """
    lines = text.split('\n')
    bullet_lines = []
    found_first_bullet = False
    
    for line in lines:
        stripped = line.strip()
        # A line is a bullet if it starts with '-' or '- **'
        if stripped.startswith('-') or stripped.startswith('•') or stripped.startswith('*'):
            found_first_bullet = True
            bullet_lines.append(stripped)
        elif found_first_bullet and stripped:
            # Continuation of a bullet or blank line after bullets started
            bullet_lines.append(stripped)
    
    if bullet_lines:
        return '\n'.join(bullet_lines)
    
    # If no bullets found at all, return original text as-is
    return text


def generate_ai_summary(title: str, source_name: str) -> str:
    """
    Generates a 3-bullet-point executive summary focusing on business and tech using Gemini.
    If the Gemini API fails or is unconfigured, falls back to a clean mock summary.
    """
    system_prompt = (
        "Você é um analista de inteligência de negócios. "
        "Gere EXATAMENTE 3 bullet points de resumo executivo sobre a notícia, "
        "focados em tecnologia e oportunidades de negócios. "
        "REGRAS OBRIGATÓRIAS:\n"
        "1. Comece DIRETAMENTE com o primeiro bullet point usando hífen '-'.\n"
        "2. NÃO escreva introdução, preâmbulo, saudação ou qualquer texto antes dos bullets.\n"
        "3. NÃO escreva 'Aqui está', 'Segue', 'Resumo executivo' ou qualquer frase introdutória.\n"
        "4. Cada bullet deve ter no máximo 2 frases.\n"
        "5. Use português brasileiro.\n"
        "EXEMPLO DE FORMATO CORRETO:\n"
        "- Primeiro ponto sobre o impacto tecnológico.\n"
        "- Segundo ponto sobre oportunidade de negócio.\n"
        "- Terceiro ponto sobre tendência ou desafio."
    )
    user_prompt = f"Título da notícia: {title}"

    # 1. Try Gemini first if key is present
    if settings.GEMINI_API_KEY:
        try:
            summary = call_gemini_api(
                prompt=user_prompt,
                system_instruction=system_prompt,
                max_tokens=350,
                temperature=0.3
            )
            if summary:
                # Post-process: strip any preamble lines before the first bullet
                cleaned = _clean_summary_preamble(summary.strip())
                if cleaned:
                    return cleaned
        except Exception as e:
            logger.error(f"Gemini API direct call failed for summary of '{title[:40]}...': {str(e)}")

    # 2. No AI config fallback
    if not settings.GEMINI_API_KEY:
        logger.warning("No Gemini API key configured. Using static fallback summary.")
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
    Uses Gemini to perform a context-aware relevance check.
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

    # 1. Try Gemini if key is present
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
    "reality show", "reality-show", "reality shows",
    
    # Promoções, Cupons e Afiliados
    "cupom de desconto", "código promocional", "código de cupom", "promo code", "promo codes",
    "coupon code", "coupon codes", "cupom de", "ofertas do dia", "menor preço", "desconto em",
    "compre com desconto", "comprar com desconto"
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
    "horóscopo", "signos", "astrologia", "culinária",
    
    # Promoções, Cupons, Afiliados e Varejo de Consumo
    "cupom", "cupons", "promoção", "promoções", "promocional", "desconto", "descontos", 
    "oferta", "ofertas", "coupon", "coupons", "promo", "promos", "discount", "discounts", 
    "deal", "deals", "affiliate", "afiliado", "afiliados", "compre", "comprar", "compras", 
    "shop", "store", "sale", "liquidação", "queima", "estoque", "outlet"
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

GENERALIST_SOURCES = {
    "InfoMoney", 
    "G1 Tecnologia", 
    "Governo Brasileiro", 
    "Governo Chinês", 
    "Governo Americano", 
    "Governo Russo"
}

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
    1. Check source type; translate title if SourceType.INTERNACIONAL.
    2. Heuristic relevance check on translated title.
    3. AI-powered Relevance Filter on translated title.
    4. Check for similarity deduplication.
    5. Generate executive summary using LLM.
    
    Returns the processed dictionary ready for DB save, or None if skipped.
    """
    title = article_data["original_title"]
    
    # 1. Translate first if the source is international
    if source.type == SourceType.INTERNACIONAL:
        translated_title = translate_text(title, target_lang="pt")
    else:
        translated_title = title

    # 2. Relevance Heuristic Filter on the Portuguese translated title
    if not is_relevant_article(translated_title, source.name):
        logger.info(f"Skipping article (heuristic irrelevant): '{translated_title[:50]}'")
        return None
        
    # 3. AI-powered Relevance Filter on the Portuguese translated title
    if not is_relevant_article_ai(translated_title):
        logger.info(f"Skipping article (AI classified as irrelevant): '{translated_title[:50]}'")
        return None
        
    # 4. Deduplication check on the Portuguese translated title
    if is_similar_to_recent(translated_title, recent_titles, threshold=0.8):
        logger.info(f"Skipping article (similar news exists): '{translated_title[:50]}'")
        return None

    processed_data = article_data.copy()
    processed_data["translated_title"] = translated_title

    # 5. AI Summary Generation
    processed_data["ai_summary"] = generate_ai_summary(
        title=translated_title, 
        source_name=source.name
    )
    
    # Define placeholder reduced key for search terms
    processed_data["reduced_key"] = " ".join(
        [word.lower() for word in translated_title.split() if len(word) > 3]
    )[:255]

    return processed_data


BAD_SUMMARY_PATTERNS = [
    "resumo automático indisponível",
    "coleta executada com sucesso",
    "notícia de tecnologia relevante reportada",
    "aqui está o resumo",
    "resumo executivo",
    "segue abaixo"
]

def is_bad_summary(summary: str) -> bool:
    """Checks if the summary is empty, too short, or contains fallback/preamble patterns."""
    if not summary:
        return True
    s_lower = summary.lower()
    if len(s_lower.strip()) < 50:
        return True
    for pattern in BAD_SUMMARY_PATTERNS:
        if pattern in s_lower:
            return True
    return False


def heal_incomplete_summaries(limit: int = 3):
    """
    Looks for up to `limit` news items in the database with missing or placeholder summaries,
    and regenerates them using the AI summary function.
    """
    logger.info("Starting maintenance check for incomplete AI summaries...")
    try:
        with get_db_session() as session:
            # Query active sources map to get names
            sources_map = {s.id: s.name for s in session.query(Source).all()}
            
            # Fetch news items (order by created_at desc to heal recent items first)
            news_items = session.query(News).order_by(News.created_at.desc()).all()
            
            bad_articles = []
            for item in news_items:
                if is_bad_summary(item.ai_summary):
                    bad_articles.append(item)
                    if len(bad_articles) >= limit:
                        break
            
            if not bad_articles:
                logger.info("All existing database articles have valid AI summaries. No healing needed.")
                return
                
            logger.info(f"Found {len(bad_articles)} articles needing summary healing. Regenerating...")
            for article in bad_articles:
                title = article.translated_title or article.original_title
                source_name = sources_map.get(article.source_id, "Desconhecido")
                
                logger.info(f"Healing summary for article: '{title[:45]}...'")
                
                try:
                    new_summary = generate_ai_summary(title=title, source_name=source_name)
                    # Only save if it's not a fallback / bad summary
                    if not is_bad_summary(new_summary):
                        article.ai_summary = new_summary
                        session.commit()
                        logger.info(f"✓ Summary healed successfully.")
                    else:
                        logger.warning(f"✗ Regenerated summary was still invalid/fallback. Skipping save.")
                except Exception as e:
                    logger.error(f"Error during summary healing: {e}")
    except Exception as e:
        logger.error(f"Failed during heal_incomplete_summaries run: {e}")

