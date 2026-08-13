"""Verify the channel IDs from the user's spec against YouTube's own pages."""
import re, urllib.request, time

# (label, handle_or_url, claimed_id)
CHECKS = [
    ("DW News", "https://www.youtube.com/@DWNews", "UCvpy1d3jNq7P2GvMmsY9wyg"),
    ("Al Jazeera English", "https://www.youtube.com/@aljazeeraenglish", "UCNye-wNBqNL5ZzHSJj3l8Bg"),
    ("Sky News", "https://www.youtube.com/@SkyNews", "UCoMdktPbSTixAyNGwb-UYkQ"),
    ("France 24 English", "https://www.youtube.com/@France24_english", "UCQfwfsi5VrQ8yKZ-UWmAEFg"),
]

for label, url, claimed in CHECKS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'"externalId":"(UC[\w-]{22})"', html)
        real = m.group(1) if m else "NOT FOUND"
        match = "✅ MATCH" if real == claimed else "❌ MISMATCH"
        print(f"{label:<22} real={real}  claimed={claimed}  {match}")
    except Exception as e:
        print(f"{label:<22} ERR {e}")
    time.sleep(1)
