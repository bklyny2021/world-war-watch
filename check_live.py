"""Check real live status of each channel via channel page HTML (isLiveNow)."""
import re, json, urllib.request, time

CHANNELS = {
    "aljazeeraenglish": "UCfiwzLy-8yKzIbsmZTzxDgw",
    "DWNews": "UCbbS1GE942k3UVqpLklyhIA",
    "trtworld": "UCnyCrv8b7bu0oWFXGyHaPzg",
    "PressTV": "UC0OO19kc2jt8ZtOWZMVa3Vw",
    "AlArabiya": "UCrj5BGAhtWxDfqbza9T9hqA",
    "CGTN": "UCd94YCD7yp6d-YZSRYWyeFA",
    "VOAnews": "UCKyTokYo0nK2OA-az-sDijA",
    "KyivLive": "UCwTXL6Sax8q4aqJ1pNNTGgA",
    "UkraineNOW": "UCVkYsQMROZHp_5AJiKKWFXA",
    "AlMayadeenEnglish": "UCZCFHCU-2eGF7V5ciMkoPHw",
    "SudanTribune": "UCrnkurRbU8ftAXCPKoONFbg",
    "MizzimaTV": "UC9duwzgDlAnqCF7k1tlvrXw",
    "DVBNews": "UC60W37GZodr7kTcqKqTWf9A",
    "taiwanplus": "UCHWZrE1UY7eL82fAIzskBYA",
}

for name, cid in CHANNELS.items():
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/channel/{cid}/live",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                     "Accept-Language": "en-US,en;q=0.9"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        live = '"isLiveNow":true' in html or '"isLive":true' in html
        # also look for a videoId on the live page
        vid = re.search(r'"videoId":"([\w-]{11})"', html)
        print(f"{name:<20} isLiveNow={live}  videoId={vid.group(1) if vid else 'none'}")
    except Exception as e:
        print(f"{name:<20} ERR {e}")
    time.sleep(1)
