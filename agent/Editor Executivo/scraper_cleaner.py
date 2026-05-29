import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("news_agent.editor.scraper_cleaner")

USER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

async def fetch_and_clean_content(url: str, timeout: float = 15.0) -> str:
    """
    Fetches the web page content, parses it, and cleans up boilerplate/noise HTML tags,
    returning only paragraphs containing the core article text.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url, headers=USER_HEADERS)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url} (HTTP {response.status_code})")
                return ""
            html = response.text
    except Exception as e:
        logger.error(f"Error fetching article content from {url}: {e}")
        return ""

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        logger.error(f"Error parsing HTML for {url}: {e}")
        return ""

    # Remove non-content structural elements
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe", "noscript"]):
        element.decompose()

    # Try to find common article containers
    content_area = None
    for selector in ["article", "main", "[role='main']", ".post-content", ".article-content", ".entry-content", ".story-content"]:
        found = soup.select(selector)
        if found:
            content_area = found[0]
            break

    # If no wrapper content area is found, default to body
    if not content_area:
        content_area = soup.body or soup

    # Extract paragraph texts, filtering out short lines
    paragraphs = []
    for p in content_area.find_all("p"):
        text = p.get_text().strip()
        # Filter out typical boilerplate lines like share links, newsletter opt-ins, cookie messages
        if len(text) > 40 and not any(term in text.lower() for term in [
            "newsletter", "inscreva-se", "receba por e-mail", "todos os direitos reservados",
            "copyright", "compartilhe", "siga-nos", "cookie", "política de privacidade"
        ]):
            paragraphs.append(text)

    cleaned_text = "\n\n".join(paragraphs)
    logger.info(f"Cleaned content from {url}: {len(cleaned_text)} characters extracted ({len(paragraphs)} paragraphs).")
    return cleaned_text
