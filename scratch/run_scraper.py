import sys
import asyncio
sys.path.append('.')

from core.scraper import main as run_scraper

async def main():
    print("Starting news scraper run...")
    await run_scraper()
    print("Scraper run completed.")

if __name__ == "__main__":
    asyncio.run(main())
