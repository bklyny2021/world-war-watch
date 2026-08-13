#!/usr/bin/env python3
"""Audit every YouTube channel used by the WWW geo-router.
For each channel: resolve name, check /live redirect, check embed page state.
Output: one line per channel with status."""
import urllib.request, re, json, sys, time

CHANNELS = [
    "UC0OO19kc2jt8ZtOWZMVa3Vw","UC16niRr50-MSBwiO3YDb3RA","UC60W37GZodr7kTcqKqTWf9A",
    "UC9duwzgDlAnqCF7k1tlvrXw","UCbbS1GE942k3UVqpLklyhIA","UCBi2mrWuNuyYy4gbM6fU18Q",
    "UCd94YCD7yp6d-YZSRYWyeFA","UCfiwzLy-8yKzIbsmZTzxDgw","UCHWZrE1UY7eL82fAIzskBYA",
    "UCkFclpi8U9VJjfxLYoms7Aw","UCKyTokYo0nK2OA-az-sDijA","UCnyCrv8b7bu0oWFXGyHaPzg",
    "UCQfwfsi5VrQ8yKZ-UWmAEFg","UCrj5BGAhtWxDfqbza9T9hqA","UCrnkurRbU8ftAXCPKoONFbg",
    "UCupvZG-5ko_eiXAupbDfxWw","UCVkYsQMROZHp_5AJiKKWFXA","UCwTXL6Sax8q4aqJ1pNNTGgA",
    "UCZCFHCU-2eGF7V5ciMkoPHw",
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.geturl(), r.status, r.read(400000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.geturl() if hasattr(e, "geturl") else url, e.code, ""
    except Exception as e:
        return url, 0, str(e)

results = []
for cid in CHANNELS:
    row = {"id": cid}
    # 1) channel page /live — does it redirect to a live stream?
    try:
        final, status, body = fetch(f"https://www.youtube.com/channel/{cid}/live")
    except Exception as e:
        final, status, body = cid, 0, str(e)
    row["final"] = final
    row["status"] = status
    # name from <title>
    m = re.search(r"<title>(.*?)</title>", body, re.S)
    row["name"] = (m.group(1).strip()[:60] if m else "?")
    # live markers
    row["is_live"] = bool(re.search(r'"isLive":true|"isLiveNow":true|"isLive": true', body))
    row["redirected_live"] = ("/live/" in final) or bool(re.search(r"/watch\?v=", final))
    # 2) embed page state
    try:
        eurl, estatus, ebody = fetch(f"https://www.youtube.com/embed/live_stream?channel={cid}")
    except Exception as e:
        eurl, estatus, ebody = "", 0, str(e)
    row["embed_status"] = estatus
    row["embed_unavailable"] = ("Video unavailable" in ebody) or ("This video is unavailable" in ebody)
    row["embed_ended"] = ("This live stream has ended" in ebody) or ("stream has ended" in ebody)
    results.append(row)
    print(f"{cid} | {row['name'][:40]:40s} | http {status} | live={row['is_live']} redir={row['redirected_live']} | embed {estatus} unavail={row['embed_unavailable']} ended={row['embed_ended']}")
    sys.stdout.flush()
    time.sleep(1.5)

print("\n=== SUMMARY ===")
live = [r for r in results if r["is_live"] or r["redirected_live"]]
notlive = [r for r in results if not (r["is_live"] or r["redirected_live"])]
print(f"LIVE NOW ({len(live)}):")
for r in live: print("  OK ", r["id"], r["name"][:40])
print(f"NOT LIVE ({len(notlive)}):")
for r in notlive: print("  -- ", r["id"], r["name"][:40])
json.dump(results, open("_feed_audit.json", "w"), indent=1)
print("saved _feed_audit.json")
