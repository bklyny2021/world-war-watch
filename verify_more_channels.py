"""Verify BBC News + CNN channel IDs for the geo-router."""
import re, urllib.request, time

CANDIDATES = [
    ("BBC News", "https://www.youtube.com/@BBCNews"),
    ("CNN", "https://www.youtube.com/@CNN"),
    ("ABC News", "https://www.youtube.com/@ABCNews"),
    ("NHK World", "https://www.youtube.com/@NHKWORLD-Japan"),
]

for label, url in CANDIDATES:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'"externalId":"(UC[\w-]{22})"', html)
        print(f"{label:<14} id={m.group(1) if m else 'NOT FOUND'}")
    except Exception as e:
        print(f"{label:<14} ERR {e}")
    time.sleep(1)
