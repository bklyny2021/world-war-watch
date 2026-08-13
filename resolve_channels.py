"""Resolve YouTube @handles to channel IDs for embeddable live streams."""
import re, json, urllib.request, time

HANDLES = [
    "KyivLive", "UkraineNOW", "DWNews", "aljazeeraenglish", "AlMayadeenEnglish",
    "PressTV", "trtworld", "AlArabiya", "SudanTribune", "MizzimaTV", "DVBNews",
    "VOAnews", "taiwanplus", "CGTN",
]

out = {}
for h in HANDLES:
    url = f"https://www.youtube.com/@{h}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'"externalId":"(UC[\w-]{22})"', html)
        if m:
            out[h] = m.group(1)
            print(f"{h}: UC{m.group(1)[2:]}")
        else:
            print(f"{h}: NOT FOUND")
    except Exception as e:
        print(f"{h}: ERR {e}")
    time.sleep(1)

with open("yt_channels.json", "w") as f:
    json.dump(out, f, indent=2)
print("saved yt_channels.json")
