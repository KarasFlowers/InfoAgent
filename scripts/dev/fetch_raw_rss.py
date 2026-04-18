import httpx
import asyncio

async def fetch_raw_rss(url):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10.0)
            print(f"--- Raw Response (Top 2000 chars) ---")
            print(response.text[:2000])
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    import sys
    url = "http://localhost:5000/api/rss/all"
    if len(sys.argv) > 1:
        url = sys.argv[1]
    asyncio.run(fetch_raw_rss(url))
