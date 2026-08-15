#!/usr/bin/env python3
"""
World War Watch — Offline Recorder (v2.3.1)
============================================
Records raw plane/ship/fire positions into worldview_archive.db while the
app is NOT running. The app's "Update" button imports this archive into
the main telemetry DB for playback.

- Windowless: run with pythonw (no console).
- Same schema as the app's telemetry table, so playback code works unchanged.
- Separate DB file -> no lock contention with the running app.
- Retention: 30 days (ARCHIVE_RETENTION_DAYS), purged hourly.
- REAL DATA ONLY: every row comes from a live feed (OpenSky / MarineTraffic /
  NASA FIRMS). No simulated data, ever.

Usage:
    pythonw recorder.py            # run forever (60s cycle)
    python recorder.py --once      # single snapshot cycle, then exit (testing)
    python recorder.py --interval 30   # custom cycle seconds
"""
import csv
import io
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- paths
BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR  # source mode; frozen mode would set this next to the EXE
DATA_DIR = BASE_DIR / "data"
ARCHIVE_DB = APP_DIR / "worldview_archive.db"
LOG_FILE = APP_DIR / "recorder.log"

ARCHIVE_RETENTION_DAYS = 30
DEFAULT_INTERVAL = 60  # seconds between snapshots (matches app telemetry cadence)

# ---------------------------------------------------------------- feeds
OPENSKY_STATES = "https://opensky-network.org/api/states/all"
OPENSKY_BOUNDS = "lamin=-90&lomin=-180&lamax=90&lomax=180"
OPENSKY_CREDS_FILE = DATA_DIR / "opensky_creds.json"

MARINETRAFFIC_GRID_Z = 3  # z:3 = 64 tiles, same as the app
MT_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

FIRMS_URL = ("https://firms.modaps.eosdis.nasa.gov/data/active_fire/"
             "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv")

# ---------------------------------------------------------------- logging
def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- db
_db_lock = threading.Lock()


def _init_db():
    """Create the archive table + indexes (idempotent, same schema as app)."""
    conn = sqlite3.connect(str(ARCHIVE_DB), timeout=10)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                entity_id TEXT,
                entity_type TEXT,   -- 'plane', 'ship', 'fire'
                lat REAL,
                lon REAL,
                alt REAL,
                heading REAL,
                speed REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_type ON telemetry(timestamp, entity_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time ON telemetry(timestamp)")
        conn.commit()
    finally:
        conn.close()


def _purge_old():
    """Delete rows older than ARCHIVE_RETENTION_DAYS (runs hourly)."""
    try:
        conn = sqlite3.connect(str(ARCHIVE_DB), timeout=10)
        with _db_lock:
            conn.execute(
                "DELETE FROM telemetry WHERE timestamp < datetime('now', 'localtime', ?)",
                (f"-{ARCHIVE_RETENTION_DAYS} days",),
            )
            conn.commit()
        conn.close()
        log(f"archive purge done (>{ARCHIVE_RETENTION_DAYS}d removed)")
    except Exception as e:
        log(f"archive purge error: {e}")


def _write_rows(rows):
    if not rows:
        return 0
    conn = sqlite3.connect(str(ARCHIVE_DB), timeout=10)
    try:
        with _db_lock:
            conn.executemany(
                "INSERT INTO telemetry (entity_id, entity_type, lat, lon, alt, heading, speed, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()
        return len(rows)
    finally:
        conn.close()


# ---------------------------------------------------------------- feeds
def _load_opensky_creds():
    try:
        if OPENSKY_CREDS_FILE.exists():
            d = json.loads(OPENSKY_CREDS_FILE.read_text(encoding="utf-8"))
            return d.get("username") or d.get("user") or "", d.get("password") or d.get("pass") or ""
    except Exception:
        pass
    return "", ""


def _fetch_planes():
    """OpenSky state vectors -> rows. Real data only; skip invalid coords."""
    user, pw = _load_opensky_creds()
    req = urllib.request.Request(f"{OPENSKY_STATES}?{OPENSKY_BOUNDS}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    if user and pw:
        import base64
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    rows = []
    for s in data.get("states") or []:
        s = (list(s) + [None] * 18)[:18]
        (icao24, _cs, _oc, _tp, _lc, lon, lat, alt, _og, vel,
         track, _vr, _sn, _ga, _sq, _spi, _ps, _cat) = s
        if lat is None or lon is None:
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        rows.append((str(icao24), "plane", lat, lon,
                     float(alt) if alt is not None else 0.0,
                     float(track) if track is not None else 0.0,
                     float(vel) if vel is not None else 0.0))
    return rows


def _fetch_ships():
    """MarineTraffic z:3 tile grid crawl (same as the app). Partial OK."""
    ships = []
    n = 2 ** MARINETRAFFIC_GRID_Z
    tiles = [(x, y) for x in range(n) for y in range(n)]
    deadline = time.time() + 30.0
    for idx, (x, y) in enumerate(tiles):
        if time.time() > deadline:
            break
        ua = MT_UAS[idx % len(MT_UAS)]
        for attempt in range(2):
            try:
                url = (f"https://www.marinetraffic.com/getData/get_data_json_4/"
                       f"z:{MARINETRAFFIC_GRID_Z}/X:{x}/Y:{y}")
                req = urllib.request.Request(url, headers={
                    "User-Agent": ua,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": "https://www.marinetraffic.com/",
                    "X-Requested-With": "XMLHttpRequest",
                })
                with urllib.request.urlopen(req, timeout=8) as r:
                    raw = r.read()
                d = json.loads(raw)
                for row in d.get("data", {}).get("rows", []):
                    try:
                        lat = float(row.get("LAT"))
                        lon = float(row.get("LON"))
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            continue
                        ships.append((str(row.get("SHIP_ID", "")), "ship", lat, lon,
                                      0.0,
                                      float(row.get("COURSE") or 0),
                                      float(row.get("SPEED") or 0)))
                    except (TypeError, ValueError):
                        continue
                break  # tile succeeded
            except Exception:
                time.sleep(0.25)  # retry after a beat
    return ships


def _fetch_fires():
    """NASA FIRMS 24h CSV, high-confidence only (same filter as the app)."""
    try:
        req = urllib.request.Request(FIRMS_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    except Exception:
        return []
    fires = []
    try:
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            try:
                lat = float(row.get("latitude", ""))
                lon = float(row.get("longitude", ""))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                conf = (row.get("confidence") or "nominal").strip().lower()
                if conf not in ("h", "high"):
                    try:
                        if float(conf) < 75:
                            continue
                    except (TypeError, ValueError):
                        continue
                fires.append((f"{lat:.3f},{lon:.3f}", "fire", lat, lon,
                              float(row.get("bright_ti4") or 0), 0.0, 0.0))
            except (TypeError, ValueError):
                continue
    except Exception:
        return []
    return fires


# ---------------------------------------------------------------- cycle
def snapshot_once():
    """One full snapshot cycle: planes + ships + fires -> archive DB."""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    try:
        rows += _fetch_planes()
        log(f"planes: {len(rows)}")
    except Exception as e:
        log(f"planes fetch failed: {e}")
    ship_rows = []
    try:
        ship_rows = _fetch_ships()
        log(f"ships: {len(ship_rows)}")
    except Exception as e:
        log(f"ships fetch failed: {e}")
    fire_rows = []
    try:
        fire_rows = _fetch_fires()
        log(f"fires: {len(fire_rows)}")
    except Exception as e:
        log(f"fires fetch failed: {e}")
    all_rows = [(eid, etype, lat, lon, alt, hdg, spd, now)
                for (eid, etype, lat, lon, alt, hdg, spd) in rows + ship_rows + fire_rows]
    written = _write_rows(all_rows)
    log(f"snapshot {now}: {written} rows written "
        f"({len(rows)} planes / {len(ship_rows)} ships / {len(fire_rows)} fires)")
    return written


def main():
    interval = DEFAULT_INTERVAL
    once = False
    args = sys.argv[1:]
    if "--once" in args:
        once = True
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            try:
                interval = max(10, int(args[i + 1]))
            except ValueError:
                pass
    _init_db()
    log(f"recorder started (interval={interval}s, db={ARCHIVE_DB.name}, "
        f"retention={ARCHIVE_RETENTION_DAYS}d)")
    _purge_old()
    last_purge = time.time()
    while True:
        try:
            snapshot_once()
        except Exception as e:
            log(f"cycle error: {e}")
        if once:
            log("--once done")
            return
        # hourly purge
        if time.time() - last_purge >= 3600:
            _purge_old()
            last_purge = time.time()
        time.sleep(interval)


if __name__ == "__main__":
    main()
