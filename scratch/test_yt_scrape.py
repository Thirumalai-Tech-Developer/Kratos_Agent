import urllib.request
import urllib.parse
import re

def get_first_youtube_video(query: str):
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            # Find watch?v= IDs
            matches = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html)
            if matches:
                # Deduplicate while preserving order
                seen = set()
                deduped = [m for m in matches if not (m in seen or seen.add(m))]
                return deduped[0]
    except Exception as e:
        print("Error fetching:", e)
    return None

if __name__ == "__main__":
    vid = get_first_youtube_video("god of war walkthrough")
    print("Found video ID:", vid)
