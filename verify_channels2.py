"""Find real channel IDs for Sky News + France 24 English."""
import re, urllib.request, time

CANDIDATES = [
    ("Sky News", "https://www.youtube.com/@SkyNews"),
    ("Sky News alt", "https://www.youtube.com/channel/UCkFclpi8U9VJjfxLYoms7Aw"),
    ("France 24 English", "https://www.youtube.com/@FRANCE24English"),
    ("France 24 alt", "https://www.youtube.com/@france24english"),
]

for label, url in CANDIDATES:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'"externalId":"(UC[\w-]{22})"', html)
        title = re.search(r'"title":"([^"]{0,60})"', html)
        print(f"{label:<22} id={m.group(1) if m else 'NOT FOUND'}  title={title.group(1) if title else '?'}")
    except Exception as e:
        print(f"{label:<22} ERR {e}")
    time.sleep(1)
