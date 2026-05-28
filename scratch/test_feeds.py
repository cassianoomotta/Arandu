import httpx
import asyncio

USER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

urls = [
    # US Government
    "https://www.whitehouse.gov/feed/",
    "https://www.whitehouse.gov/briefing-room/statements-releases/feed/",
    "https://www.whitehouse.gov/briefing-room/feed/",
    
    # Brazilian Government
    "https://www.gov.br/pt-br/noticias/feed",
    "https://www.gov.br/pt-br/noticias/RSS",
    "https://www.gov.br/planalto/pt-br/acompanhe-o-planalto/noticias/RSS",
    
    # Russian Government
    "http://en.kremlin.ru/feed.xml",
    "http://en.kremlin.ru/events/all/feed",
    "http://en.kremlin.ru/events/all/feed.xml",
    "http://kremlin.ru/events/all/feed"
]

async def test_url(client, url):
    try:
        res = await client.get(url, headers=USER_HEADERS, timeout=10.0, follow_redirects=True)
        print(f"[{res.status_code}] {url} -> Content Length: {len(res.content)}")
        if res.status_code == 200:
            snippet = res.text[:200]
            print(f"    Snippet: {snippet.strip()[:100]}...")
    except Exception as e:
        print(f"[ERR] {url} -> {str(e)}")

async def main():
    async with httpx.AsyncClient() as client:
        for url in urls:
            await test_url(client, url)

if __name__ == "__main__":
    asyncio.run(main())
