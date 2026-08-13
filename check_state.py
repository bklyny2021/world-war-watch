"""Check telemetry DB + API health with tight timeouts."""
import sqlite3, urllib.request, json, time

# 1. DB with short timeout
try:
    t0 = time.time()
    db = sqlite3.connect(r"C:\Users\bklyn\worldview\worldview.db", timeout=5)
    c = db.cursor()
    c.execute("SELECT COUNT(*) FROM telemetry")
    n = c.fetchone()[0]
    c.execute("SELECT entity_type, COUNT(*) FROM telemetry GROUP BY entity_type ORDER BY 2 DESC")
    types = c.fetchall()
    print(f"TELEMETRY: {n} rows ({time.time()-t0:.1f}s)")
    for t, cnt in types:
        print(f"  {t}: {cnt:,}")
    db.close()
except Exception as e:
    print("DB ERROR:", e)

# 2. Health
try:
    d = json.load(urllib.request.urlopen("http://localhost:8767/api/health", timeout=10))
    print("HEALTH:", d)
except Exception as e:
    print("HEALTH ERROR:", e)

# 3. Ships
try:
    d = json.load(urllib.request.urlopen("http://localhost:8767/api/ships", timeout=30))
    print("SHIPS:", len(d.get("ships", [])))
except Exception as e:
    print("SHIPS ERROR:", e)

# 4. Road path (traffic sim fix)
try:
    t0 = time.time()
    d = json.load(urllib.request.urlopen("http://localhost:8767/api/road_path?cam_id=flock-knightdale-hedingham", timeout=25))
    print(f"ROAD: {len(d.get('waypoints', []))} waypoints, {d.get('speed_kph')} km/h, {d.get('source')} ({time.time()-t0:.1f}s)")
except Exception as e:
    print("ROAD ERROR:", e)
