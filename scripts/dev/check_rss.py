import feedparser
import requests
import json

def check_feed(url, name):
    print(f"\n--- Checking: {name} ---")
    print(f"URL: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # Check raw reachability
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {resp.status_code}")
        
        # Parse with feedparser
        d = feedparser.parse(resp.text)
        print(f"Feed Title: {d.feed.get('title', 'N/A')}")
        print(f"Entries Found: {len(d.entries)}")
        
        if len(d.entries) > 0:
            entry = d.entries[0]
            print(f"Latest Headline: {entry.get('title', 'N/A')}")
            print(f"Summary Length: {len(entry.get('summary', ''))}")
            print(f"Link: {entry.get('link', 'N/A')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    sources = [
        ("https://www.jiqizhixin.com/rss", "机器之心"),
        ("https://linux.do/top.rss", "Linux.do"),
        ("https://www.v2ex.com/feed/tab/hot.xml", "V2EX"),
        ("https://sspai.com/feed", "少数派")
    ]
    
    for url, name in sources:
        check_feed(url, name)
