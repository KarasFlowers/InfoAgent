import httpx
import feedparser
import asyncio
import sys

async def test_wechat_rss(url):
    print(f"--- Testing WeChat RSS: {url} ---")
    async with httpx.AsyncClient() as client:
        try:
            print(f"1. Fetching URL...")
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            print(f"✅ Fetch successful (Status: {response.status_code})")
            
            print(f"2. Parsing with feedparser...")
            feed = feedparser.parse(response.text)
            if not feed.entries:
                print("❌ No entries found in the feed.")
                return
            
            print(f"✅ Found {len(feed.entries)} entries.")
            print("\nTop 3 entries:")
            for i, entry in enumerate(feed.entries[:3]):
                print(f"  [{i+1}] {entry.get('title')}")
                print(f"      Link: {entry.get('link')}")
                
            # Test scraping one link
            test_link = feed.entries[0].get('link')
            print(f"\n3. Testing link scrapeability: {test_link}")
            try:
                import trafilatura
                downloaded = trafilatura.fetch_url(test_link)
                if downloaded:
                    result = trafilatura.extract(downloaded)
                    if result:
                        print(f"✅ Scraped successfully ({len(result)} chars)")
                        print(f"Preview: {result[:100]}...")
                    else:
                        print("❌ Trafilatura could not extract text.")
                else:
                    print("❌ Could not download content from the link.")
            except ImportError:
                print("⚠️ trafilatura not installed, skipping scrape test.")
                
        except Exception as e:
            print(f"❌ Error during test: {e}")

if __name__ == "__main__":
    target_url = "http://localhost:5000/api/rss/all"
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    asyncio.run(test_wechat_rss(target_url))
