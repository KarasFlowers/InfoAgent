import asyncio
import httpx
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.rag_service import fetch_article_text, ingest
from app.core.url_safety import ensure_public_url_target

async def test_url(url: str):
    print(f"Testing URL: {url}")
    try:
        public_url = await ensure_public_url_target(url)
        print(f"Public URL: {public_url}")
        
        text = await fetch_article_text(url)
        print(f"Extracted text length: {len(text)}")
        
        result = await ingest(url)
        print(f"Ingest result: {result}")
    except Exception as e:
        print(f"Error for {url}: {type(e).__name__}: {e}")

if __name__ == "__main__":
    urls = [
        "https://news.ycombinator.com/item?id=39912345", # Sample public URL
        "http://localhost:8000", # Should fail
        "https://www.google.com" # Should work
    ]
    for url in urls:
        asyncio.run(test_url(url))
