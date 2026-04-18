import feedparser
import requests

def test_new_sources():
    sources = [
        ("https://www.solidot.org/index.rss", "Solidot"),
        ("https://36kr.com/feed", "36kr")
    ]
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url, name in sources:
        print(f"\n--- Testing: {name} ---")
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            d = feedparser.parse(resp.text)
            print(f"Status: {resp.status_code}, Entries: {len(d.entries)}")
            if len(d.entries) > 0:
                print(f"Latest: {d.entries[0].title}")
        except Exception as e:
            print(f"Error for {name}: {e}")

if __name__ == "__main__":
    test_new_sources()
