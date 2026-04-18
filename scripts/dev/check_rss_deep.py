import feedparser
import requests

def debug_jiqizhixin():
    url = "https://www.jiqizhixin.com/rss"
    print(f"\n--- Debugging: 机器之心 ---")
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {resp.status_code}")
        print("Raw XML Start (500 chars):")
        print(resp.text[:500])
        
        d = feedparser.parse(resp.text)
        print(f"Bozo error count: {d.bozo}")
        print(f"Entries: {len(d.entries)}")
    except Exception as e:
        print(f"Error: {e}")

def check_other_chinese():
    sources = [
        ("https://www.v2ex.com/feed/tab/hot.xml", "V2EX"),
        ("https://sspai.com/feed", "少数派")
    ]
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url, name in sources:
        print(f"\n--- Checking: {name} ---")
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            d = feedparser.parse(resp.text)
            print(f"Status: {resp.status_code}, Entries: {len(d.entries)}")
        except Exception as e:
            print(f"Error for {name}: {e}")

if __name__ == "__main__":
    debug_jiqizhixin()
    check_other_chinese()
