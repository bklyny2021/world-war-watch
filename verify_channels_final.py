"""DECISIVE TEST: which channel IDs actually resolve on YouTube?

Fetch https://www.youtube.com/channel/<ID> for every candidate ID.
A real channel returns 200 + its own channelId in the page.
A wrong ID returns 404 "This channel does not exist".
"""
import re, urllib.request, time

CANDIDATES = [
    # (label, channel_id, source)
    ("DW News — Gemini", "UCvpy1d3jNq7P2GvMmsY9wyg", "gemini"),
    ("DW News — verified", "UCbbS1GE942k3UVqpLklyhIA", "hermes"),
    ("Al Jazeera — Gemini", "UCNye-wNBqNL5ZzHSJj3l8Bg", "gemini"),
    ("Al Jazeera — verified", "UCfiwzLy-8yKzIbsmZTzxDgw", "hermes"),
    ("Sky News — Gemini v1", "UCoMdktPbSTixAyNGwb-UYkQ", "gemini"),
    ("Sky News — Gemini v2", "UCg-_lKUhn8553pL_RkjO_7Q", "gemini"),
    ("Sky News — verified", "UCkFclpi8U9VJjfxLYoms7Aw", "hermes"),
    ("France 24 — Gemini", "UCQfwfsi5VrQ8yKZ-UWmAEFg", "both"),
]

for label, cid, src in CANDIDATES:
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/channel/{cid}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                     "Accept-Language": "en-US,en;q=0.9"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
            status = r.status
        m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'"externalId":"(UC[\w-]{22})"', html)
        page_id = m.group(1) if m else "NONE"
        title = re.search(r'"title":"([^"]{0,50})"', html)
        t = title.group(1) if title else "?"
        if status == 200 and page_id == cid:
            verdict = "✅ REAL CHANNEL"
        elif status == 200 and page_id != cid:
            verdict = f"⚠️ RESOLVES TO DIFFERENT CHANNEL ({page_id})"
        else:
            verdict = f"❌ HTTP {status} — DEAD ID"
        print(f"{label:<24} {cid}  →  {verdict}  title={t}")
    except Exception as e:
        print(f"{label:<24} {cid}  →  ❌ ERR {str(e)[:60]}")
    time.sleep(1)
