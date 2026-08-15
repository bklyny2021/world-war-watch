"""
WorldView — live 3D flight tracker backend.
FastAPI proxy to OpenSky Network API (free, no key) + aircraft metadata DB.
"""
import csv
import json
import os
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import sys

# --- Paths: frozen (PyInstaller EXE) vs source ---
# When bundled, read-only assets (data/, static/) come from the onefile
# extraction dir (sys._MEIPASS); writable files (log, creds, last_flights)
# live NEXT TO the EXE so they persist across runs.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    APP_DIR = BASE_DIR
DATA_DIR = BASE_DIR / "data"
AC_DB = DATA_DIR / "aircraftDatabase.csv"
AIRPORTS_DB = DATA_DIR / "airports.dat"
STATIC_DIR = BASE_DIR / "static"
LOG_FILE = APP_DIR / "worldview.log"
_OPENSKY_CREDS_FILE = APP_DIR / "opensky_creds.json"
_LAST_FLIGHTS_FILE = APP_DIR / "last_flights.json"

OPENSKY_STATES = "https://opensky-network.org/api/states/all"
OPENSKY_FLIGHTS = "https://opensky-network.org/api/flights/aircraft"

UA = {"User-Agent": "WorldView/1.0 (local flight tracker)"}

# ---------------------------------------------------------------- OpenSky auth
# Authenticated tier = 4,000 calls/day (vs 400 anonymous). Credentials live in
# opensky_creds.json NEXT TO THE EXE (or data/ in source mode).
_OPENSKY_AUTH = None   # base64 "user:pass" or None (anonymous)


def _load_opensky_creds():
    global _OPENSKY_AUTH
    # source mode: data/opensky_creds.json; frozen mode: next to the EXE
    candidates = [APP_DIR / "opensky_creds.json"]
    if not getattr(sys, "frozen", False):
        candidates.insert(0, BASE_DIR / "data" / "opensky_creds.json")
    for creds_file in candidates:
        try:
            if creds_file.exists():
                with creds_file.open("r", encoding="utf-8") as f:
                    creds = json.load(f)
                u = (creds.get("username") or "").strip()
                p = (creds.get("password") or "").strip()
                if u and p and not u.startswith("<"):
                    import base64
                    _OPENSKY_AUTH = base64.b64encode(f"{u}:{p}".encode()).decode()
                    print(f"[worldview] OpenSky authenticated as {u} (4,000 calls/day)")
                    return
                else:
                    print("[worldview] OpenSky creds file present but empty/placeholder — anonymous mode")
        except Exception as e:
            print(f"[worldview] opensky creds load error: {e}")
    print("[worldview] no OpenSky creds found — anonymous mode (400 calls/day)")


_load_opensky_creds()

# OpenSky anonymous tier: 400 calls/day. A 12s poll burns ~7,200/day -> 429.
# After a 429 we back off and skip upstream calls for a while.
_OPENSKY_BACKOFF_UNTIL = 0.0
_OPENSKY_BACKOFF_SEC = 90
_LAST_FLIGHTS = {}             # icao -> last known flight (served during 429 cooldown)


def _load_last_flights():
    """Load persisted last-known flights at startup (survives restarts)."""
    global _LAST_FLIGHTS
    try:
        if _LAST_FLIGHTS_FILE.exists():
            with _LAST_FLIGHTS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _LAST_FLIGHTS = data
                print(f"[worldview] loaded {len(data)} cached flights from disk")
    except Exception as e:
        print(f"[worldview] last_flights load error: {e}")


def _save_last_flights():
    """Persist last-known flights so a restart during a 429 cooldown
    doesn't leave the globe empty."""
    try:
        with _LAST_FLIGHTS_FILE.open("w", encoding="utf-8") as f:
            json.dump(_LAST_FLIGHTS, f)
    except Exception as e:
        print(f"[worldview] last_flights save error: {e}")


def _opensky_backoff():
    """True while we're in a rate-limit cooldown (skip upstream calls)."""
    return time.time() < _OPENSKY_BACKOFF_UNTIL


def _mark_opensky_429():
    global _OPENSKY_BACKOFF_UNTIL
    _OPENSKY_BACKOFF_UNTIL = time.time() + _OPENSKY_BACKOFF_SEC
    print(f"[worldview] OpenSky 429 -> backing off {_OPENSKY_BACKOFF_SEC}s")

app = FastAPI(title="WorldView", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------- metadata
_aircraft_index = None      # icao24 (lower) -> dict
_airports_index = None      # IATA -> (lat, lon, name, city)
_airlines_index = None      # icao callsign prefix (lower) -> airline name
_aircraft_load_time = 0.0
_aircraft_refresh = 6 * 3600  # re-read every 6h


def _load_aircraft():
    """Lazy-load + cache the aircraftDatabase.csv. Returns icao24 -> row dict."""
    global _aircraft_index, _aircraft_load_time
    now = time.time()
    if _aircraft_index is not None and now - _aircraft_load_time < _aircraft_refresh:
        return _aircraft_index
    idx = {}
    if AC_DB.exists():
        try:
            with AC_DB.open("r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    icao = (row.get("icao24") or "").strip().lower()
                    if icao:
                        idx[icao] = row
        except Exception as e:
            print(f"[worldview] aircraft DB read error: {e}")
    _aircraft_index = idx
    _aircraft_load_time = now
    print(f"[worldview] aircraft DB: {len(idx)} entries")
    return idx


def _load_airports():
    """Load OpenFlights airports.dat: CSV of AirportID,Name,City,Country,IATA,ICAO,lat,lon,..."""
    global _airports_index
    if _airports_index is not None:
        return _airports_index
    idx = {}
    if AIRPORTS_DB.exists():
        try:
            with AIRPORTS_DB.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) < 8:
                        continue
                    # quoted fields may contain commas; handle basic case
                    name, city = parts[1], parts[2]
                    iata = parts[4].strip('"')
                    if iata and iata != "\\N" and len(iata) == 3:
                        try:
                            lat, lon = float(parts[6]), float(parts[7])
                        except ValueError:
                            continue
                        idx[iata] = {"name": name.strip('"'), "city": city.strip('"'),
                                     "lat": lat, "lon": lon}
        except Exception as e:
            print(f"[worldview] airports DB read error: {e}")
    _airports_index = idx
    print(f"[worldview] airports DB: {len(idx)} entries")
    return idx


def _load_airlines():
    """Build callsign-prefix -> airline map from the aircraft DB operators.
    Flight callsigns start with the airline's ICAO code (e.g. UAL1223),
    which lives in `operatoricao`; `operatorcallsign` is the spoken word."""
    global _airlines_index
    if _airlines_index is not None:
        return _airlines_index
    idx = {}
    for row in _load_aircraft().values():
        op_icao = (row.get("operatoricao") or "").strip()
        op_name = (row.get("operator") or "").strip()
        if op_icao and op_name:
            idx[op_icao.lower()] = op_name
    _airlines_index = idx
    print(f"[worldview] airlines map: {len(idx)} ICAO codes")
    return idx


# ---------------------------------------------------------------- helpers
def _fetch_json(url, timeout=25):
    headers = dict(UA)
    if _OPENSKY_AUTH:
        headers["Authorization"] = f"Basic {_OPENSKY_AUTH}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _mark_opensky_429()
        raise
    if not raw:
        return None
    return json.loads(raw)


def _get_airline_and_flight(callsign):
    """From a callsign like 'UAL1223' -> (airline_name, flight_number '1223')."""
    if not callsign:
        return None, None
    cs = callsign.strip().upper()
    airlines = _load_airlines()
    # longest prefix match
    for i in range(len(cs), 1, -1):
        prefix = cs[:i].lower()
        if prefix in airlines:
            return airlines[prefix], cs[i:]
    return None, cs


# ---------------------------------------------------------------- CCTV cameras
CAMERAS_API = "https://webcams.nyctmc.org/api/cameras"
NC_CAMERAS_API = "https://www.drivenc.gov/map/mapIcons/Cameras"
NC_SNAPSHOT = "https://www.drivenc.gov/map/Cctv/{cid}"
NC_TOOLTIP = "https://www.drivenc.gov/tooltip/Cameras/{cid}?lang=en"
CAMERA_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}
_CAMERAS_CACHE = None          # cleaned NYC camera list
_CAMERAS_CACHE_TIME = 0.0
_CAMERAS_TTL = 300             # refresh upstream list at most every 5 min
_NC_CAMERAS_CACHE = None       # cleaned NC camera list
_NC_CAMERAS_CACHE_TIME = 0.0
_NC_NAMES = {}                 # nc cam id -> name (lazy tooltip fetches)


def _fetch_camera_json(url, timeout=25, gzip_ok=False):
    """Fetch JSON with a desktop Chrome UA. NYC sends plain JSON;
    NC (drivenc.gov) requires Accept-Encoding: gzip + manual decompress."""
    headers = dict(CAMERA_UA)
    if gzip_ok:
        headers["Accept-Encoding"] = "gzip"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if not raw:
        return None
    if r.headers.get("Content-Encoding") == "gzip":
        import gzip as _gzip
        raw = _gzip.decompress(raw)
    return json.loads(raw)


def get_nc_cameras(region: str = ""):
    """NC DOT (drivenc.gov) traffic cameras -> [{id, name, lat, lon, area, imageUrl}].

    List endpoint: GET /map/mapIcons/Cameras (gzip JSON, no key). Shape:
    {"item1": {icon config}, "item2": [ {itemId, location:[lat,lng]}, ... ]}.
    Camera names come from per-camera tooltips (lazy, cached). `region`
    filters the name/roadway (e.g. 'I-485', 'I-77', 'I-40', 'Charlotte').
    """
    global _NC_CAMERAS_CACHE, _NC_CAMERAS_CACHE_TIME
    now = time.time()
    if _NC_CAMERAS_CACHE is None or now - _NC_CAMERAS_CACHE_TIME > _CAMERAS_TTL:
        data = _fetch_camera_json(NC_CAMERAS_API, gzip_ok=True)
        clean = []
        if data and isinstance(data, dict):
            items = data.get("item2") or []
            for it in items:
                try:
                    cid = str(it.get("itemId"))
                    lat, lon = it.get("location")
                    lat, lon = float(lat), float(lon)
                except (TypeError, ValueError, AttributeError):
                    continue
                clean.append({
                    "id": cid,
                    "name": _NC_NAMES.get(cid, f"NC Cam {cid}"),
                    "lat": lat,
                    "lon": lon,
                    "area": "NC",
                    "src": "nc",
                    "imageUrl": NC_SNAPSHOT.format(cid=cid),
                })
        _NC_CAMERAS_CACHE = clean
        _NC_CAMERAS_CACHE_TIME = now
        print(f"[worldview] nc cameras: {len(clean)} from upstream")
    if region:
        r = region.strip().lower()
        return [c for c in _NC_CAMERAS_CACHE if r in c["name"].lower()]
    return _NC_CAMERAS_CACHE


def _nc_camera_name(cid):
    """Lazy per-camera name from drivenc.gov tooltip HTML (cached in _NC_NAMES)."""
    if cid in _NC_NAMES:
        return _NC_NAMES[cid]
    name = f"NC Cam {cid}"
    try:
        import re as _re
        req = urllib.request.Request(NC_TOOLTIP.format(cid=cid), headers=CAMERA_UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", "replace")
        m = _re.search(r"<strong>([^<]+)</strong>", html)
        if m:
            name = m.group(1).strip() or name
    except Exception:
        pass
    _NC_NAMES[cid] = name
    return name


def get_cameras(area: str = ""):
    """NYC DOT traffic webcams -> clean list [{id, name, lat, lon, area, imageUrl}].

    Cached for _CAMERAS_TTL seconds; `area` filters case-insensitively
    (e.g. 'Brooklyn', 'Manhattan', 'Bronx', 'Queens', 'Staten Island').
    """
    global _CAMERAS_CACHE, _CAMERAS_CACHE_TIME
    now = time.time()
    if _CAMERAS_CACHE is None or now - _CAMERAS_CACHE_TIME > _CAMERAS_TTL:
        data = _fetch_camera_json(CAMERAS_API)
        clean = []
        for c in data or []:
            try:
                cid = str(c.get("id"))
                lat = float(c.get("latitude"))
                lon = float(c.get("longitude"))
            except (TypeError, ValueError):
                continue
            clean.append({
                "id": cid,
                "name": str(c.get("name") or f"Camera {cid}"),
                "lat": lat,
                "lon": lon,
                "area": str(c.get("area") or ""),
                "src": "nyc",
                "imageUrl": f"https://webcams.nyctmc.org/api/cameras/{cid}/image",
            })
        _CAMERAS_CACHE = clean
        _CAMERAS_CACHE_TIME = now
        print(f"[worldview] cameras: {len(clean)} from upstream")
    if area:
        a = area.strip().lower()
        return [c for c in _CAMERAS_CACHE if c["area"].lower() == a]
    return _CAMERAS_CACHE


def _fetch_camera_image(cam_id, timeout=20):
    """Snapshot bytes + content-type; upstream sometimes returns an empty body
    on the first attempt, so retry up to 3 times with a 2s delay."""
    url = f"https://webcams.nyctmc.org/api/cameras/{cam_id}/image"
    last_err = "unknown error"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=CAMERA_UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type") or "image/jpeg"
            if body:
                return body, ctype
            last_err = "empty body"
        except Exception as e:
            last_err = str(e)
        if attempt < 2:
            time.sleep(2)
    raise RuntimeError(f"camera image {cam_id} fetch failed: {last_err}")


def _fetch_nc_image(cam_id, timeout=20):
    """NC DOT snapshot bytes + content-type (drivenc.gov /map/Cctv/{id})."""
    url = NC_SNAPSHOT.format(cid=cam_id)
    last_err = "unknown error"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=CAMERA_UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type") or "image/jpeg"
            if body:
                return body, ctype
            last_err = "empty body"
        except Exception as e:
            last_err = str(e)
        if attempt < 2:
            time.sleep(2)
    raise RuntimeError(f"nc camera image {cam_id} fetch failed: {last_err}")


# ---------------------------------------------------------------- military detection
import re as _re
MILITARY_OPERATOR_KEYWORDS = (
    "air force", "airforce", "navy", "army", "marine", "military", "defense",
    "luftwaffe", "royal air force", "aeronautica", "militare", "fuerza aerea",
    "forca aerea", "force aerienne", "hava kuvvetleri", "koku", "vojenske",
    "usaf", "usn ", "usmc", "us army", "national guard", "coast guard",
    "aerospace force", "air defence", "air defense", "armed forces",
)
MILITARY_CALLSIGN_PREFIXES = (
    "RCH", "CMB", "RRR", "GAF", "BAF", "IAF", "UAE", "KAF", "ROF", "HKY",
    "DUKE", "JEDI", "SPAR", "NIGHT", "DEATH", "COPTER", "GUARD", "PACK",
    "OMAHA", "DEMON", "AXEMAN", "VIPER", "SNAKE", "ROGUE", "MACH", "BULL",
    "COBRA", "HAWK", "TALON", "FURY", "RAPTOR", "WOLF", "TIGER", "PANTHER",
    "CONDOR", "EAGLE", "HOMER", "JOKER", "KING", "LANCER", "MACE", "MOOSE",
    "NICKEL", "OTIS", "PISTOL", "QUID", "RIDER", "SABER", "TEXAN", "UMBER",
    "VENOM", "WAGON", "XRAY", "YANKEE", "ZULU", "GORILLA", "RAZOR", "SHADOW",
    "GHOST", "PHANTOM", "THUNDER", "LIGHTNING", "STRIKE", "WARRIOR", "DAGGER",
    "BLADE", "IRON", "STEEL", "BRONCO", "CREEK", "DODGE", "EVERGREEN",
)


def _is_military(callsign, operator):
    cs = (callsign or "").strip().upper()
    op = (operator or "").strip().lower()
    if any(k in op for k in MILITARY_OPERATOR_KEYWORDS):
        return True
    for p in MILITARY_CALLSIGN_PREFIXES:
        if cs.startswith(p):
            return True
    return False


# ---------------------------------------------------------------- plane priority
# Priority score for /api/flights: military=0 (show first), commercial=1,
# general aviation=2. Frontend renders planes in priority order and may cap
# the total count, so military/defense traffic always survives the cap.
# Military callsign PREFIX whitelist (NOT a generic 2-3 letter + 3 digit
# pattern — that matches every commercial flight: UAL123, DAL456, AAL789).
# These are the real US/UK/Allied military callsign families:
_MIL_PREFIXES = (
    "RCH", "CMB", "GAF", "QID", "RRR", "RFR", "DUKE", "SPAR", "BAF", "IAF",
    "CFC", "CFC", "HKY", "HUSKY", "MCC", "MCC", "NAF", "NATO", "RCH", "REACH",
    "SNAKE", "VIPR", "WAR", "AXIS", "BOLT", "BULL", "COBRA", "DARK", "DEAD",
    "DEMON", "FANG", "HAWK", "HORNET", "IRON", "JEDI", "JOKER", "KILLER",
    "MAD", "MAKO", "MOJO", "MUSTANG", "NIGHT", "RAZOR", "REAPER", "ROGUE",
    "SABER", "SHADOW", "STING", "VIPER", "WOLF", "ZULU",
)
_MIL_CALLSIGN_RE = _re.compile(r"^(" + "|".join(_MIL_PREFIXES) + r")\d{1,4}$")


def _plane_priority(callsign, operator, airline):
    """0 = military/defense, 1 = commercial (has operator/airline), 2 = GA."""
    if _is_military(callsign, operator):
        return 0
    # known military callsign prefix + digits (RCH123, CMB456, QID789)
    if _MIL_CALLSIGN_RE.match((callsign or "").strip().upper()):
        return 0
    if operator or airline:
        return 1
    return 2


# ---------------------------------------------------------------- TLE proxy
# Celestrak 'active' group = ALL operational satellites (~16K, measured
# 2026-08-13: 16,087). The old 'visual' group (brightest only, 157) was
# what the user flagged as too low. Frontend renders a capped subset for
# perf but the HUD shows the true total.
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"
_TLE_CACHE = None
_TLE_CACHE_TIME = 0.0
_TLE_TTL = 6 * 3600   # refresh TLEs at most every 6h


def get_tle():
    """Celestrak 'active' group TLEs (all operational satellites), cached 6h."""
    global _TLE_CACHE, _TLE_CACHE_TIME
    now = time.time()
    if _TLE_CACHE is None or now - _TLE_CACHE_TIME > _TLE_TTL:
        try:
            req = urllib.request.Request(TLE_URL, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            sats = []
            for i in range(0, len(lines) - 2, 3):
                sats.append({"name": lines[i], "line1": lines[i + 1], "line2": lines[i + 2]})
            _TLE_CACHE = sats
            _TLE_CACHE_TIME = now
            print(f"[worldview] TLEs: {len(sats)} satellites from Celestrak (active group)")
        except Exception as e:
            print(f"[worldview] TLE fetch failed: {e}")
            if _TLE_CACHE is None:
                _TLE_CACHE = []
    return _TLE_CACHE or []


# ---------------------------------------------------------------- telemetry DB
# SQLite time-series store for historical playback. A background thread logs
# live plane/ship/fire snapshots every 15s; /api/playback queries it.
import sqlite3 as _sqlite3
import threading as _threading

_TELEMETRY_DB = APP_DIR / "worldview.db"
_TELEMETRY_INTERVAL = 60          # seconds between snapshots (15s = 64K rows/min = DB bloat; 60s is plenty — the frontend interpolates between samples)
_telemetry_lock = _threading.Lock()


def _init_telemetry_db():
    """Create the telemetry table + time index (idempotent)."""
    try:
        conn = _sqlite3.connect(str(_TELEMETRY_DB), timeout=10)
        cur = conn.cursor()
        # WAL mode: readers never block on the writer (the telemetry logger
        # writes every 15s — without WAL, playback queries can stall).
        cur.execute("PRAGMA journal_mode = WAL;")
        # INCREMENTAL auto-vacuum: lets the purge daemon reclaim disk space
        # without a full VACUUM (which would lock the DB for seconds).
        # NOTE: SQLite silently IGNORES the pragma on an already-populated
        # DB — it only takes effect on a fresh DB or after a VACUUM. So
        # verify it stuck and force a one-time VACUUM if not (idempotent:
        # once auto_vacuum=2 is persisted, later startups skip the rebuild).
        cur.execute("PRAGMA auto_vacuum = INCREMENTAL;")
        cur.execute("PRAGMA auto_vacuum")
        if cur.fetchone()[0] != 2:
            print("[worldview] auto_vacuum was OFF — running one-time VACUUM to enable INCREMENTAL mode")
            cur.execute("VACUUM")
            cur.execute("PRAGMA auto_vacuum")
            print(f"[worldview] auto_vacuum now = {cur.fetchone()[0]}")
        cur.execute("""
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_time_type ON telemetry(timestamp, entity_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_time ON telemetry(timestamp)")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[worldview] telemetry db init failed: {e}")


def _auto_purge_db():
    """Background daemon: hourly retention + incremental vacuum.

    Deletes telemetry older than 24 hours (playback depth is capped at a
    day — enough to scrub back through, but the DB stays small) and
    reclaims the freed pages. Runs every hour, never blocks the server.
    """
    while True:
        conn = None
        try:
            conn = _sqlite3.connect(str(_TELEMETRY_DB), timeout=10)
            with _telemetry_lock:
                cur = conn.cursor()
                cur.execute("DELETE FROM telemetry WHERE timestamp < datetime('now', 'localtime', '-24 hours')")
                cur.execute("PRAGMA incremental_vacuum;")
                cur.fetchall()   # pragma returns rows — MUST drain before commit
                conn.commit()
            conn.close()
            conn = None
            print("[worldview] telemetry purge done (24h retention)")
        except Exception as e:
            print(f"[worldview] DB purge error: {e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        time.sleep(3600)   # once per hour (first run is immediate)


def _log_telemetry_snapshot():
    """One background snapshot of live planes + ships + fires."""
    try:
        rows = []
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        # planes (from the last OpenSky poll)
        for f in _LAST_FLIGHTS.values():
            if f.get("lat") is None or f.get("lon") is None:
                continue
            rows.append((f["icao"], "plane", f["lat"], f["lon"],
                         f.get("alt_m") or 0, f.get("heading") or 0,
                         f.get("speed_ms") or 0, now))
        # ships (from the ships cache)
        for s in _SHIPS_CACHE:
            rows.append((s["mmsi"], "ship", s["lat"], s["lon"], 0,
                         s.get("cog") or 0, s.get("sog") or 0, now))
        # fires (from the fires cache)
        for f in _FIRES_CACHE:
            rows.append((f"{f['lat']:.3f},{f['lon']:.3f}", "fire",
                         f["lat"], f["lon"], 0, 0, f.get("brightness") or 0, now))
        if not rows:
            return
        conn = _sqlite3.connect(str(_TELEMETRY_DB), timeout=10)
        with _telemetry_lock:
            conn.executemany(
                "INSERT INTO telemetry (entity_id, entity_type, lat, lon, alt, heading, speed, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?)", rows)
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[worldview] telemetry snapshot failed: {e}")


def _telemetry_loop():
    """Background thread: snapshot every _TELEMETRY_INTERVAL seconds."""
    while True:
        time.sleep(_TELEMETRY_INTERVAL)
        _log_telemetry_snapshot()


@app.get("/api/playback")
def api_playback(timestamp: str = "", entity_type: str = ""):
    """State vectors closest to the requested ISO timestamp.

    ?timestamp=2026-08-12 07:00:00 (or ISO with T/Z) — returns the snapshot
    nearest to that moment (within ±60s), optionally filtered by entity_type.
    """
    if not timestamp:
        return {"error": "missing timestamp", "states": []}
    ts = timestamp.strip().replace("T", " ").replace("Z", "")
    if len(ts) > 19:
        ts = ts[:19]
    try:
        conn = _sqlite3.connect(str(_TELEMETRY_DB), timeout=10)
        cur = conn.cursor()
        q = ("SELECT entity_id, entity_type, lat, lon, alt, heading, speed, timestamp "
             "FROM telemetry WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1")
        args = [ts]
        if entity_type:
            q = ("SELECT entity_id, entity_type, lat, lon, alt, heading, speed, timestamp "
                 "FROM telemetry WHERE timestamp <= ? AND entity_type = ? "
                 "ORDER BY timestamp DESC LIMIT 1")
            args = [ts, entity_type]
        cur.execute(q, args)
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"error": "no data before that timestamp", "states": []}
        snap_ts = row[7]
        # fetch the full snapshot at that timestamp
        cur.execute(
            "SELECT entity_id, entity_type, lat, lon, alt, heading, speed, timestamp "
            "FROM telemetry WHERE timestamp = ?", (snap_ts,))
        states = [
            {"id": r[0], "type": r[1], "lat": r[2], "lon": r[3], "alt": r[4],
             "heading": r[5], "speed": r[6]}
            for r in cur.fetchall()
        ]
        conn.close()
        return {"timestamp": snap_ts, "states": states, "count": len(states)}
    except Exception as e:
        return {"error": str(e), "states": []}


@app.get("/api/playback/range")
def api_playback_range():
    """Earliest + latest timestamps in the telemetry DB (for the scrubber)."""
    try:
        conn = _sqlite3.connect(str(_TELEMETRY_DB), timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM telemetry")
        mn, mx, cnt = cur.fetchone()
        conn.close()
        return {"min": mn, "max": mx, "count": cnt}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/satellite_snapshot")
def api_satellite_snapshot(lat: float = 0.0, lon: float = 0.0, zoom: int = 16):
    """Proxy an Esri World Imagery tile for the satellite recon modal.

    Server-side fetch bypasses browser referrer/CORS blocking (the direct
    <img src=...arcgisonline...> URL was returning a broken/blank tile).
    Converts lat/lon to Web Mercator tile X/Y at the requested zoom and
    returns the raw image bytes (image/jpeg) with a browser-like UA.
    """
    import math
    zoom = max(1, min(int(zoom), 19))
    # clamp latitude to the Web Mercator range (±85.0511°) — the tan/cos
    # formula blows up at the poles and would produce garbage tile Y
    lat = max(-85.0511, min(85.0511, float(lat)))
    lon = float(lon)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(math.radians(lat)) + (1.0 / math.cos(math.radians(lat)))) / math.pi) / 2.0 * n)
    xtile = max(0, min(int(n) - 1, xtile))
    ytile = max(0, min(int(n) - 1, ytile))
    url = (f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
           f"MapServer/tile/{zoom}/{ytile}/{xtile}")
    try:
        req = urllib.request.Request(url, headers=CAMERA_UA)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read()
        ctype = r.headers.get("Content-Type", "image/jpeg")
        return Response(content=data, media_type=ctype,
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- config
# Google Map Tiles API key (Photorealistic 3D Tiles). NOT hardcoded — read
# from the environment so the key never ships in the EXE. Without a key the
# frontend falls back to the flat globe (no 3D buildings).
GOOGLE_3D_TILES_KEY = os.environ.get("GOOGLE_3D_TILES_KEY", "")

# Cesium Ion token (free tier — Boo's account, 2026-08-12). Lives in
# ion_token.json NEXT TO THE EXE (or data/ in source mode) — never hardcoded.
_ION_TOKEN = ""


def _load_ion_token():
    global _ION_TOKEN
    candidates = [APP_DIR / "ion_token.json"]
    if not getattr(sys, "frozen", False):
        candidates.insert(0, BASE_DIR / "data" / "ion_token.json")
    for tok_file in candidates:
        try:
            if tok_file.exists():
                with tok_file.open("r", encoding="utf-8") as f:
                    tok = json.load(f).get("ion_token", "")
                if tok and not tok.startswith("<"):
                    _ION_TOKEN = tok.strip()
                    print("[worldview] Cesium Ion token loaded (3D tiles enabled)")
                    return
        except Exception:
            pass
    print("[worldview] No Cesium Ion token — 3D tiles disabled")


_load_ion_token()


@app.get("/api/config")
def api_config():
    """Frontend config: google_3d_key + ion_token (empty = not configured)."""
    return {
        "google_3d_key": GOOGLE_3D_TILES_KEY,
        "ion_token": _ION_TOKEN,
    }


# ---------------------------------------------------------------- endpoints
@app.get("/api/flights")
def get_flights(limit: int = 0):
    """Live aircraft states from OpenSky, enriched with model + origin/dest.

    Each flight carries a 'priority' score (0=military/defense, 1=commercial,
    2=general aviation). The list is sorted by priority (military first) and
    optionally capped by the 'limit' query param (0 = no limit).
    """
    if _opensky_backoff():
        # rate-limit cooldown: serve the last known positions instead of failing
        cached = list(_LAST_FLIGHTS.values())
        for f in cached:
            f["priority"] = _plane_priority(f.get("callsign", ""), f.get("airline", ""), f.get("airline", ""))
        cached.sort(key=lambda f: f.get("priority", 2))
        if limit and limit > 0:
            cached = cached[:limit]
        return {"error": "opensky rate-limited (429), serving cached positions",
                "flights": cached,
                "count": len(cached),
                "time": int(time.time()),
                "cached": True,
                "auth": bool(_OPENSKY_AUTH)}
    bounds = "lamin=-90&lomin=-180&lamax=90&lomax=180"
    try:
        data = _fetch_json(f"{OPENSKY_STATES}?{bounds}")
    except Exception as e:
        # 429 (rate limit) or network error -> serve last known positions
        print(f"[worldview] flights fetch failed: {e}")
        cached = list(_LAST_FLIGHTS.values())
        for f in cached:
            f["priority"] = _plane_priority(f.get("callsign", ""), f.get("airline", ""), f.get("airline", ""))
        cached.sort(key=lambda f: f.get("priority", 2))
        if limit and limit > 0:
            cached = cached[:limit]
        return {"error": f"opensky unavailable ({e})",
                "flights": cached,
                "count": len(cached),
                "time": int(time.time()),
                "cached": True,
                "auth": bool(_OPENSKY_AUTH)}
    if not data:
        return {"error": "opensky unavailable", "flights": [], "time": int(time.time())}

    ac_db = _load_aircraft()
    airports = _load_airports()
    flights = []
    for s in data.get("states") or []:
        # OpenSky state vector layout
        (icao24, callsign, origin_country, time_position, last_contact,
         longitude, latitude, baro_altitude, on_ground, velocity,
         true_track, vertical_rate, sensors, geo_altitude, squawk,
         spi, position_source, category) = (list(s) + [None] * 18)[:18]

        if longitude is None or latitude is None:
            continue
        if on_ground:
            continue  # only show flying aircraft

        icao = (icao24 or "").lower()
        cs = (callsign or "").strip()
        if not cs:
            continue  # no callsign -> no flight identity

        airline, flight_no = _get_airline_and_flight(cs)
        alt_m = baro_altitude if baro_altitude is not None else geo_altitude
        alt_ft = round((alt_m or 0) * 3.28084)
        speed_kt = round((velocity or 0) * 1.94384)  # m/s -> knots

        row = ac_db.get(icao, {})
        model = (row.get("model") or "").strip() or None
        typecode = (row.get("typecode") or "").strip() or None
        operator = (row.get("operator") or "").strip() or airline

        # OpenSky category (index 17): 0=No info, 1=No ADS-B, 2=Small,
        # 3=Large, 4=High-vortex, 5=Heavy, 6=High-performance, 7=Rotorcraft,
        # 8=Glider, 9=Lighter-than-air, 10=Parachutist, 11=Ultralight,
        # 12=Reserved, 13=UAV, 14=Space, 15=EMERGENCY, 16=Service Level 1.
        # Fall back to typecode/model hints when category is missing.
        cat = int(category) if category is not None else 0
        if cat == 0:
            tc = (typecode or "").upper()
            mdl = (model or "").upper()
            # Model names are the most reliable signal; typecode H* is
            # ambiguous (H60=Black Hawk heli vs H900=Hawker JET) so exclude
            # Hawker jets when using the H-prefix hint.
            if ("HELICOPTER" in mdl or "ROTORCRAFT" in mdl
                    or "EUROCOPTER" in mdl or "AGUSTA" in mdl
                    or "ROBINSON" in mdl or "SIKORSKY" in mdl
                    or "HUGHES" in mdl or "ENSTROM" in mdl
                    or "BELL" in mdl):
                cat = 7
            elif (tc.startswith("H") or "HELI" in tc or "ROTOR" in tc) and "HAWKER" not in mdl:
                cat = 7
            elif tc.startswith("G") or "GLID" in tc or "GLIDER" in mdl:
                cat = 8
            elif tc.startswith("U") or "UAV" in tc or "DRONE" in tc or "UAV" in mdl:
                cat = 13
        ac_type = "helicopter" if cat == 7 else ("glider" if cat == 8 else ("uav" if cat == 13 else "plane"))

        flights.append({
            "icao": icao,
            "callsign": cs,
            "flight": flight_no,
            "airline": airline or operator,
            "model": model,
            "typecode": typecode,
            "registration": (row.get("registration") or "").strip() or None,
            "origin_country": origin_country,
            "lat": latitude,
            "lon": longitude,
            "alt_m": round(alt_m or 0),
            "alt_ft": alt_ft,
            "speed_kt": speed_kt,
            "heading": round(true_track or 0) % 360,
            "vrate_fpm": round((vertical_rate or 0) * 196.85),
            "origin": None,   # filled by /api/routes enrichment
            "destination": None,
            "military": _is_military(cs, operator),
            "priority": _plane_priority(cs, operator, airline),
            "ac_type": ac_type,
        })

    _LAST_FLIGHTS.clear()
    for f in flights:
        _LAST_FLIGHTS[f["icao"]] = f
    _save_last_flights()

    # sort by priority (military first), stable so same-priority flights keep
    # upstream order; cap the RETURNED list only (cache/telemetry stay full)
    flights.sort(key=lambda f: f["priority"])
    if limit and limit > 0:
        flights = flights[:limit]

    return {"time": int(time.time()), "flights": flights, "count": len(flights),
            "auth": bool(_OPENSKY_AUTH)}


@app.get("/api/routes")
def get_routes(icaos: str = ""):
    """Enrich flights with origin/destination airport IATA codes."""
    icao_list = [i.strip().lower() for i in icaos.split(",") if i.strip()]
    if not icao_list:
        return {"routes": {}}
    now = int(time.time())
    routes = {}
    for icao in icao_list:
        routes[icao] = {"origin": None, "destination": None}
        try:
            url = f"{OPENSKY_FLIGHTS}?icao24={icao}&begin={now-7200}&end={now}"
            flights = _fetch_json(url, timeout=15)
            if flights:
                f = flights[-1]
                routes[icao] = {"origin": f.get("estDepartureAirport"),
                                "destination": f.get("estArrivalAirport")}
        except Exception:
            pass
    return {"routes": routes}


@app.get("/api/airports")
def get_airports():
    return {"airports": _load_airports()}


@app.get("/api/airlines")
def get_airlines():
    return {"airlines": sorted({v for v in _load_airlines().values()})}


@app.get("/api/tle")
def api_tle():
    """Celestrak TLEs for the satellite orbit layer (active group, ~16K sats).
    The frontend renders a capped subset for perf; `total` is the true
    operational-satellite count shown in the HUD."""
    sats = get_tle()
    return {"satellites": sats, "total": len(sats), "time": int(time.time())}


@app.get("/api/health")
def health():
    return {"status": "ok", "time": int(time.time()),
            "aircraft_db": len(_load_aircraft()),
            "airports_db": len(_load_airports())}


@app.get("/api/cameras")
def api_cameras(area: str = "", src: str = "nyc"):
    """Traffic webcams (same-origin proxy). ?area= filters; ?src=nyc|nc|all.
    Appends custom localized feeds (Flock ALPR + neighborhood DOT cams)."""
    src = (src or "nyc").lower()
    custom = _custom_cameras(area)
    if src == "nc":
        return {"cameras": get_nc_cameras(area) + [c for c in custom if c["src"] == "nc"]}
    if src == "all":
        return {"cameras": get_cameras("") + get_nc_cameras(area) + custom}
    return {"cameras": get_cameras(area) + [c for c in custom if c["src"] == "nyc"]}


# ---------------------------------------------------------------- custom feeds
# Explicit localized cameras: Flock ALPR targets + neighborhood DOT cams.
# Flock cams have no public snapshot URL — they get the specialized ALPR card.
_CUSTOM_CAMERAS = [
    # --- Knightdale & Raleigh, NC (Flock ALPR + NCDOT) ---
    {"id": "flock-knightdale-hedingham", "name": "Food Lion Hedingham (Flock ALPR)",
     "lat": 35.7914, "lon": -78.5486, "area": "Knightdale", "src": "nc", "type": "Flock ALPR"},
    {"id": "flock-knightdale-blvd", "name": "Food Lion Knightdale Blvd (Flock ALPR)",
     "lat": 35.8000, "lon": -78.4900, "area": "Knightdale", "src": "nc", "type": "Flock ALPR"},
    {"id": "ncdot-parkside", "name": "US-64 Bus @ Parkside Dr / First Ave (Knightdale)",
     "lat": 35.7921, "lon": -78.4711, "area": "Knightdale", "src": "nc", "type": "NCDOT", "upstream_id": "6011"},
    {"id": "ncdot-faison", "name": "I-540 @ Old Faison Rd (Knightdale)",
     "lat": 35.8012, "lon": -78.4680, "area": "Knightdale", "src": "nc", "type": "NCDOT", "upstream_id": "6011"},
    {"id": "ncdot-milburnie", "name": "US-64 @ Old Milburnie Rd (Knightdale)",
     "lat": 35.7950, "lon": -78.4981, "area": "Knightdale", "src": "nc", "type": "NCDOT", "upstream_id": "6012"},
    {"id": "ncdot-sunnybrook", "name": "New Bern Ave @ Sunnybrook Rd (Raleigh East)",
     "lat": 35.7871, "lon": -78.5822, "area": "Raleigh", "src": "nc", "type": "NCDOT", "upstream_id": "5614"},
    # --- Brownsville, Brooklyn, NY (NYC DOT CCTVs — real camera IDs so snapshots work) ---
    {"id": "nycdot-utica-stjohns", "name": "St. Johns Ave & Utica Ave (Brownsville/Crown Heights)",
     "lat": 40.6687, "lon": -73.9311, "area": "Brooklyn", "src": "nyc", "type": "NYCDOT", "upstream_id": "c89b62d1-35be-4bb8-b22b-a77c2583733c"},
    {"id": "nycdot-utica-eastern", "name": "Eastern Pkwy & Utica Ave (Brownsville)",
     "lat": 40.6694, "lon": -73.9310, "area": "Brooklyn", "src": "nyc", "type": "NYCDOT", "upstream_id": "c89b62d1-35be-4bb8-b22b-a77c2583733c"},
    {"id": "nycdot-atlantic-rockaway", "name": "Atlantic Ave & Eastern Pkwy / Rockaway Ave",
     "lat": 40.6765, "lon": -73.9082, "area": "Brooklyn", "src": "nyc", "type": "NYCDOT", "upstream_id": "fde1748c-7c0f-4df8-8acd-120df29a9305"},
    {"id": "nycdot-linden-rockaway", "name": "Linden Blvd & Rockaway Pkwy (Brownsville)",
     "lat": 40.6548, "lon": -73.9215, "area": "Brooklyn", "src": "nyc", "type": "NYCDOT", "upstream_id": "a8389158-7e9c-4e57-8127-841f710582f8"},
    {"id": "nycdot-pitkin-saratoga", "name": "Pitkin Ave & Saratoga Ave (Brownsville Core)",
     "lat": 40.6698, "lon": -73.9142, "area": "Brooklyn", "src": "nyc", "type": "NYCDOT", "upstream_id": "fde1748c-7c0f-4df8-8acd-120df29a9305"},
]


def _custom_cameras(area: str = ""):
    """Custom feeds, optionally filtered by area (case-insensitive substring)."""
    if area:
        a = area.lower()
        return [c for c in _CUSTOM_CAMERAS if a in c["area"].lower() or a in c["name"].lower()]
    return list(_CUSTOM_CAMERAS)


# ---------------------------------------------------------------- road paths
# Camera Traffic Simulator: /api/road_path?cam_id=... returns the nearest road
# waypoints + speed limit so the frontend can drive simulated cars along it.
_ROAD_CACHE = {}          # cam_id -> road path dict
_ROAD_CACHE_TIME = {}     # cam_id -> fetch time
_ROAD_TTL = 1800          # refresh at most every 30 min

# default speed limits (m/s) by highway class when OSM has no maxspeed tag
_HW_SPEED_DEFAULT = {
    "motorway": 29.0,        # ~65 mph
    "trunk": 24.6,           # ~55 mph
    "primary": 20.1,         # ~45 mph
    "secondary": 17.9,       # ~40 mph
    "tertiary": 15.6,        # ~35 mph
    "residential": 11.2,     # ~25 mph
    "unclassified": 11.2,
    "service": 8.9,          # ~20 mph
    "living_street": 8.9,
}


def _mph_to_ms(mph):
    return mph * 0.44704


def _find_camera_by_id(cam_id):
    """Locate a camera record (custom, NYC, or NC) by its id."""
    for c in _CUSTOM_CAMERAS:
        if c["id"] == cam_id:
            return c
    for c in get_cameras(""):
        if c["id"] == cam_id:
            return c
    for c in get_nc_cameras(""):
        if c["id"] == cam_id:
            return c
    return None


def _haversine_m(lat1, lon1, lat2, lon2):
    import math
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_BUILDINGS_CACHE = []
_BUILDINGS_CACHE_KEY = ""
_BUILDINGS_CACHE_TIME = 0.0
_STREETS_CACHE = []
_STREETS_CACHE_KEY = ""
_STREETS_CACHE_TIME = 0.0
_LABELS_CACHE = []
def _overpass_query(q, timeout=25):
    """Run an Overpass query with mirror fallback (504s hit in practice)."""
    import urllib.parse
    last_err = None
    for mirror in _OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(
                mirror,
                data=("data=" + urllib.parse.quote(q)).encode(),
                headers={"User-Agent": "WorldView/1.0 (local traffic sim)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last_err = e
    raise RuntimeError(f"overpass failed: {last_err}")


def _fetch_road_path(cam):
    """Overpass: nearest named road to the camera, its waypoints + maxspeed.
    Prefers named main roads (primary/secondary/tertiary) over service/parking
    roads so simulated cars drive on real streets, not parking lots.
    Retries with a wider bbox and any-highway acceptance on failure."""
    import math
    lat, lon = cam["lat"], cam["lon"]

    # try 2km bbox with main-road classes, then 4km with ANY highway
    attempts = [
        (0.018, 0.024, "^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|service)$"),
        (0.036, 0.048, ""),
    ]
    for dlat, dlon, hw_re in attempts:
        bbox = f"{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon}"
        if hw_re:
            q = (
                f'[out:json][timeout:25];'
                f'(way["highway"~"{hw_re}"]'
                f'({bbox}););out body;'
            )
        else:
            q = f'[out:json][timeout:25];(way["highway"]({bbox}););out body;'
        try:
            data = _overpass_query(q)
        except Exception:
            continue
        ways = data.get("elements", [])
        if not ways:
            continue

        # collect node coords
        node_ids = set()
        for w in ways:
            node_ids.update(w.get("nodes", []))
        if not node_ids:
            continue
        nq = f'[out:json][timeout:25];node(id:{",".join(str(n) for n in list(node_ids)[:1500])});out;'
        try:
            ndata = _overpass_query(nq)
        except Exception:
            continue
        node_coords = {el["id"]: (el["lat"], el["lon"]) for el in ndata.get("elements", [])}

        # score each way: distance to camera + class bonus (named main roads win)
        _CLASS_RANK = {"motorway": 4, "trunk": 4, "primary": 3, "secondary": 2, "tertiary": 1}
        best = None
        best_score = 1e18
        for w in ways:
            pts = [node_coords[n] for n in w.get("nodes", []) if n in node_coords]
            if len(pts) < 2:
                continue
            mid = pts[len(pts) // 2]
            d = _haversine_m(lat, lon, mid[0], mid[1])
            tags = w.get("tags", {})
            hw = tags.get("highway", "residential")
            rank = _CLASS_RANK.get(hw, 0)
            if tags.get("name"):
                rank += 0.5
            score = d - rank * 300
            if score < best_score:
                best_score = score
                best = (w, pts)
        if not best:
            continue
        way, pts = best
        tags = way.get("tags", {})
        hw = tags.get("highway", "residential")

        # speed limit: OSM maxspeed (mph or km/h) -> m/s, else class default
        speed_ms = _HW_SPEED_DEFAULT.get(hw, 11.2)
        maxspeed = tags.get("maxspeed")
        if maxspeed:
            try:
                if "mph" in maxspeed:
                    speed_ms = _mph_to_ms(float(maxspeed.replace("mph", "").strip()))
                elif "km/h" in maxspeed or "kmh" in maxspeed:
                    speed_ms = float(maxspeed.replace("km/h", "").replace("kmh", "").strip()) / 3.6
                else:
                    speed_ms = float(maxspeed) / 3.6   # assume km/h
            except (ValueError, TypeError):
                pass

        # build waypoints with cumulative distances
        waypoints = []
        total = 0.0
        for i, (plat, plon) in enumerate(pts):
            if i == 0:
                seg = 0.0
            else:
                seg = _haversine_m(pts[i - 1][0], pts[i - 1][1], plat, plon)
                total += seg
            waypoints.append({"lat": plat, "lon": plon, "distanceMeters": round(seg, 1)})
        if total < 50:
            continue   # too short to drive on

        return {
            "cam_id": cam["id"],
            "road": tags.get("name") or f"Unnamed {hw}",
            "highway": hw,
            "speedMetersPerSec": round(speed_ms, 2),
            "speedLabel": tags.get("maxspeed") or f"{round(speed_ms / 0.44704)} mph (est.)",
            "totalMeters": round(total, 1),
            "waypoints": waypoints,
        }
    return None


@app.get("/api/buildings")
def api_buildings(lat: float = 40.7484, lon: float = -73.9857, radius: int = 600):
    """3D building footprints near a point (OSM Overpass — free, no key).

    Returns polygons with heights (from `height` or `building:levels` tags)
    so the frontend can extrude real 3D buildings at street level.
    """
    global _BUILDINGS_CACHE, _BUILDINGS_CACHE_KEY, _BUILDINGS_CACHE_TIME
    key = f"{lat:.4f},{lon:.4f},{radius}"
    now = time.time()
    if _BUILDINGS_CACHE and key == _BUILDINGS_CACHE_KEY and now - _BUILDINGS_CACHE_TIME < 600:
        return {"buildings": _BUILDINGS_CACHE, "cached": True}
    query = f"""
[out:json][timeout:25];
(
  way["building"](around:{radius},{lat},{lon});
);
out tags geom;
"""
    buildings = []
    for mirror in _OVERPASS_MIRRORS:
        try:
            body = urllib.parse.urlencode({"data": query}).encode()
            req = urllib.request.Request(mirror, data=body, method="POST")
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
            req.add_header("Accept", "*/*")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
            for el in d.get("elements", []):
                tags = el.get("tags", {})
                geom = el.get("geometry", [])
                if len(geom) < 3:
                    continue
                h = tags.get("height")
                if h:
                    try:
                        h = float(h.replace("m", "").strip())
                    except Exception:
                        h = None
                if not h:
                    lv = tags.get("building:levels")
                    if lv:
                        try:
                            h = float(lv) * 3.2
                        except Exception:
                            h = None
                if not h:
                    h = 8.0
                buildings.append({
                    "id": el.get("id"),
                    "name": tags.get("name", ""),
                    "type": tags.get("building", ""),
                    "height": round(min(h, 200.0), 1),
                    "ring": [[round(p["lat"], 6), round(p["lon"], 6)] for p in geom],
                })
            break
        except Exception:
            continue
    _BUILDINGS_CACHE = buildings
    _BUILDINGS_CACHE_KEY = key
    _BUILDINGS_CACHE_TIME = now
    return {"buildings": buildings, "cached": False}


@app.get("/api/street_names")
def api_street_names(lat: float = 40.7484, lon: float = -73.9857, radius: int = 800):
    """Street names near a point (OSM Overpass — free, no key).

    Returns named roads as polylines so the frontend can draw floating
    street-name labels over the photoreal 3D tiles (which have no labels).
    """
    global _STREETS_CACHE, _STREETS_CACHE_KEY, _STREETS_CACHE_TIME
    key = f"{lat:.4f},{lon:.4f},{radius}"
    now = time.time()
    if _STREETS_CACHE and key == _STREETS_CACHE_KEY and now - _STREETS_CACHE_TIME < 600:
        return {"streets": _STREETS_CACHE, "cached": True}
    query = f"""
[out:json][timeout:25];
(
  way["highway"]["name"](around:{radius},{lat},{lon});
);
out tags geom;
"""
    streets = []
    for mirror in _OVERPASS_MIRRORS:
        try:
            body = urllib.parse.urlencode({"data": query}).encode()
            req = urllib.request.Request(mirror, data=body, method="POST")
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
            req.add_header("Accept", "*/*")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
            for el in d.get("elements", []):
                tags = el.get("tags", {})
                geom = el.get("geometry", [])
                name = tags.get("name", "")
                if not name or len(geom) < 2:
                    continue
                hw = tags.get("highway", "")
                rank = {"motorway": 6, "trunk": 6, "primary": 5, "secondary": 4,
                        "tertiary": 3, "residential": 2, "unclassified": 1}.get(hw, 1)
                streets.append({
                    "name": name,
                    "highway": hw,
                    "rank": rank,
                    "line": [[round(p["lat"], 6), round(p["lon"], 6)] for p in geom],
                })
            break
        except Exception:
            continue
    streets.sort(key=lambda s: -s["rank"])
    _STREETS_CACHE = streets
    _STREETS_CACHE_KEY = key
    _STREETS_CACHE_TIME = now
    return {"streets": streets, "cached": False}


@app.get("/api/labels")
def api_labels():
    """Global place labels (Natural Earth — free, bundled offline).

    Countries + states + major cities with centroids and label ranks, so the
    frontend can draw floating names over the photoreal 3D tiles (which have
    no labels). Loaded once, cached in memory.
    """
    global _LABELS_CACHE
    if _LABELS_CACHE:
        return {"labels": _LABELS_CACHE}
    labels = []
    base = BASE_DIR / "data" if not getattr(sys, "frozen", False) else Path(sys._MEIPASS) / "data"

    def centroid(geom):
        if geom["type"] == "Point":
            return geom["coordinates"][1], geom["coordinates"][0]
        coords = geom["coordinates"]
        if geom["type"] == "Polygon":
            rings = coords
        else:  # MultiPolygon
            rings = [r for poly in coords for r in poly]
        best = None
        for ring in rings:
            if len(ring) < 3:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            c = (sum(ys) / len(ys), sum(xs) / len(xs))
            if best is None or abs(c[0]) < abs(best[0]):
                best = c
        return best or (0, 0)

    try:
        # compact pre-processed labels (10m Natural Earth — 5,247 labels)
        compact = base / "labels_10m.json"
        if compact.exists():
            labels = json.loads(compact.read_text(encoding="utf-8"))
        else:
            # fallback: build from the raw 110m GeoJSON files
            def centroid(geom):
                if geom["type"] == "Point":
                    return geom["coordinates"][1], geom["coordinates"][0]
                coords = geom["coordinates"]
                rings = coords if geom["type"] == "Polygon" else [r for poly in coords for r in poly]
                best = None
                for ring in rings:
                    if len(ring) < 3:
                        continue
                    xs = [p[0] for p in ring]
                    ys = [p[1] for p in ring]
                    c = (sum(ys) / len(ys), sum(xs) / len(xs))
                    if best is None or abs(c[0]) < abs(best[0]):
                        best = c
                return best or (0, 0)

            d = json.loads((base / "ne_countries.geojson").read_text(encoding="utf-8"))
            for f in d["features"]:
                p = f["properties"]
                name = p.get("NAME") or p.get("ADMIN") or ""
                if not name:
                    continue
                lat, lon = centroid(f["geometry"])
                labels.append({"name": name, "lat": round(lat, 2), "lon": round(lon, 2),
                               "kind": "country", "rank": int(p.get("LABELRANK", 9) or 9)})
            d = json.loads((base / "ne_states.geojson").read_text(encoding="utf-8"))
            for f in d["features"]:
                p = f["properties"]
                name = p.get("name", "")
                if not name:
                    continue
                lat, lon = centroid(f["geometry"])
                labels.append({"name": name, "lat": round(lat, 2), "lon": round(lon, 2),
                               "kind": "state", "rank": int(p.get("scalerank", 6) or 6)})
            d = json.loads((base / "ne_cities.geojson").read_text(encoding="utf-8"))
            cities = []
            for f in d["features"]:
                p = f["properties"]
                name = p.get("NAME", "")
                if not name:
                    continue
                lat, lon = centroid(f["geometry"])
                cities.append({"name": name, "lat": round(lat, 2), "lon": round(lon, 2),
                               "kind": "city", "rank": int(p.get("SCALERANK", 8) or 8),
                               "pop": int(p.get("POP_MAX", 0) or 0)})
            cities.sort(key=lambda c: -c["pop"])
            labels.extend(cities[:120])
    except Exception as e:
        print("[worldview] labels load failed:", e)
    _LABELS_CACHE = labels
    return {"labels": labels}


@app.get("/api/road_path")
def api_road_path(cam_id: str = ""):
    """Road waypoints + speed limit for the camera traffic simulator."""
    if not cam_id:
        return {"error": "cam_id required"}
    now = time.time()
    if cam_id in _ROAD_CACHE and now - _ROAD_CACHE_TIME.get(cam_id, 0) < _ROAD_TTL:
        return _ROAD_CACHE[cam_id]
    cam = _find_camera_by_id(cam_id)
    if not cam:
        return {"error": f"camera {cam_id} not found"}
    # HARD DEADLINE: Overpass can take 4x25s; the browser fetch gives up at
    # ~30s. Run the fetch in a thread and cap it at 10s — if it doesn't
    # finish, return the straight-line fallback instead of timing out.
    import threading
    result = {"path": None}
    def _fetch():
        try:
            result["path"] = _fetch_road_path(cam)
        except Exception:
            result["path"] = None
    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=10)
    path = result["path"]
    if not path:
        # straight-line fallback: camera position, 1.2km of road at 15.6 m/s
        # (35 mph) pointing east — cars ALWAYS drive even if Overpass is down
        lat, lon = cam["lat"], cam["lon"]
        pts = []
        for i in range(13):
            pts.append((lat, lon + i * 0.0011))   # ~0.1km per step east
        waypoints = []
        for i, (plat, plon) in enumerate(pts):
            waypoints.append({"lat": plat, "lon": plon,
                              "distanceMeters": 0.0 if i == 0 else round(100.0, 1)})
        path = {
            "cam_id": cam["id"],
            "road": "Fallback road (Overpass slow)",
            "highway": "residential",
            "speedMetersPerSec": 15.6,
            "speedLabel": "35 mph (fallback)",
            "totalMeters": 1200.0,
            "waypoints": waypoints,
            "fallback": True,
        }
    _ROAD_CACHE[cam_id] = path
    _ROAD_CACHE_TIME[cam_id] = now
    return path


# ---------------------------------------------------------------- maritime / AIS
# Live ship positions via the MarineTraffic tile scraper (free, no key —
# same pattern as the FR24 scraper / camera feeds). z:3 grid = 8x8 tiles
# covering the whole globe; fetched once per _SHIPS_TTL and cached.
SHIPS_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.marinetraffic.com/en/ais/home/centerx:-30/centery:30/zoom:3",
            "X-Requested-With": "XMLHttpRequest"}
_SHIPS_CACHE = []
_SHIPS_CACHE_TIME = 0.0
_SHIPS_CACHE_LOCK = _threading.Lock()   # guards background crawl writes
_SHIPS_TTL = 60          # refresh every 60s
_SHIPS_GRID_Z = 3        # zoom level (0 = 1 tile, 3 = 64 tiles)

# MarineTraffic SHIPTYPE codes -> friendly class
_SHIP_TYPE_MAP = {
    "1": "Reserved", "2": "Wing In Ground", "3": "Special Craft", "4": "High Speed Craft",
    "5": "Special Craft", "6": "Passenger", "7": "Cargo", "8": "Tanker", "9": "Tanker",
    "10": "Tanker", "11": "Tanker", "12": "Tanker", "13": "Tanker", "14": "Tanker",
    "15": "Tanker", "16": "Tanker", "17": "Tanker", "18": "Tanker", "19": "Tanker",
    "20": "Wing In Ground", "21": "High Speed Craft", "22": "High Speed Craft",
    "23": "High Speed Craft", "24": "High Speed Craft", "25": "High Speed Craft",
    "26": "High Speed Craft", "27": "High Speed Craft", "28": "High Speed Craft",
    "29": "High Speed Craft", "30": "Fishing", "31": "Towing", "32": "Towing",
    "33": "Dredging", "34": "Diving", "35": "Military", "36": "Sailing",
    "37": "Pleasure", "38": "Pleasure", "39": "Pleasure", "40": "High Speed Craft",
    "41": "High Speed Craft", "42": "High Speed Craft", "43": "High Speed Craft",
    "44": "High Speed Craft", "45": "High Speed Craft", "46": "High Speed Craft",
    "47": "High Speed Craft", "48": "High Speed Craft", "49": "High Speed Craft",
    "50": "Pilot Vessel", "51": "Search & Rescue", "52": "Tug", "53": "Port Tender",
    "54": "Anti-Pollution", "55": "Law Enforcement", "56": "Spare", "57:": "Spare",
    "58": "Medical", "59": "Non-Combatant", "60": "Passenger", "61": "Passenger",
    "62": "Passenger", "63": "Passenger", "64": "Passenger", "65": "Passenger",
    "66": "Passenger", "67": "Passenger", "68": "Passenger", "69": "Passenger",
    "70": "Cargo", "71": "Cargo", "72": "Cargo", "73": "Cargo", "74": "Cargo",
    "75": "Cargo", "76": "Cargo", "77": "Cargo", "78": "Cargo", "79": "Cargo",
    "80": "Tanker", "81": "Tanker", "82": "Tanker", "83": "Tanker", "84": "Tanker",
    "85": "Tanker", "86": "Tanker", "87": "Tanker", "88": "Tanker", "89": "Tanker",
    "90": "Other", "91": "Other", "92": "Other", "93": "Other", "94": "Other",
    "95": "Other", "96": "Other", "97": "Other", "98": "Other", "99": "Other",
}


_FALLBACK_SHIPS = [
    {"mmsi": "FALLBACK-1", "name": "NYC Ferry", "type": "Passenger", "lat": 40.70, "lon": -74.01, "sog": 12.0, "cog": 90, "heading": 90, "destination": "Wall St", "flag": "US", "length": 40, "width": 10},
    {"mmsi": "FALLBACK-2", "name": "Harbor Tug", "type": "Tug", "lat": 40.64, "lon": -74.07, "sog": 6.0, "cog": 180, "heading": 180, "destination": "Staten Is", "flag": "US", "length": 25, "width": 9},
    {"mmsi": "FALLBACK-3", "name": "Hormuz Tanker", "type": "Tanker", "lat": 26.55, "lon": 56.30, "sog": 14.0, "cog": 120, "heading": 120, "destination": "Fujairah", "flag": "PA", "length": 330, "width": 60},
    {"mmsi": "FALLBACK-4", "name": "Hormuz Cargo", "type": "Cargo", "lat": 26.20, "lon": 56.60, "sog": 11.0, "cog": 300, "heading": 300, "destination": "Bandar Abbas", "flag": "IR", "length": 200, "width": 32},
    {"mmsi": "FALLBACK-5", "name": "NC Coastal", "type": "Cargo", "lat": 34.20, "lon": -76.60, "sog": 9.0, "cog": 45, "heading": 45, "destination": "Wilmington", "flag": "US", "length": 180, "width": 28},
    {"mmsi": "FALLBACK-6", "name": "Gulf Tanker", "type": "Tanker", "lat": 28.90, "lon": -89.50, "sog": 10.0, "cog": 200, "heading": 200, "destination": "New Orleans", "flag": "US", "length": 250, "width": 44},
    {"mmsi": "FALLBACK-7", "name": "Channel Ferry", "type": "Passenger", "lat": 50.10, "lon": -1.20, "sog": 18.0, "cog": 90, "heading": 90, "destination": "Calais", "flag": "GB", "length": 180, "width": 25},
    {"mmsi": "FALLBACK-8", "name": "Med Cargo", "type": "Cargo", "lat": 36.80, "lon": 12.50, "sog": 12.0, "cog": 270, "heading": 270, "destination": "Gibraltar", "flag": "GR", "length": 150, "width": 24},
    {"mmsi": "FALLBACK-9", "name": "LA Harbor", "type": "Cargo", "lat": 33.72, "lon": -118.27, "sog": 8.0, "cog": 0, "heading": 0, "destination": "Long Beach", "flag": "US", "length": 300, "width": 45},
    {"mmsi": "FALLBACK-10", "name": "Tokyo Bay", "type": "Tanker", "lat": 35.40, "lon": 139.80, "sog": 7.0, "cog": 90, "heading": 90, "destination": "Yokohama", "flag": "JP", "length": 220, "width": 36},
    {"mmsi": "FALLBACK-11", "name": "Singapore Straits", "type": "Cargo", "lat": 1.20, "lon": 103.80, "sog": 13.0, "cog": 60, "heading": 60, "destination": "Singapore", "flag": "SG", "length": 260, "width": 40},
    {"mmsi": "FALLBACK-12", "name": "Suez Transit", "type": "Cargo", "lat": 30.20, "lon": 32.50, "sog": 9.0, "cog": 0, "heading": 0, "destination": "Port Said", "flag": "EG", "length": 280, "width": 42},
    {"mmsi": "FALLBACK-13", "name": "Panama Approach", "type": "Tanker", "lat": 8.90, "lon": -79.50, "sog": 10.0, "cog": 180, "heading": 180, "destination": "Balboa", "flag": "PA", "length": 240, "width": 38},
    {"mmsi": "FALLBACK-14", "name": "Cape Cod Trawler", "type": "Fishing", "lat": 41.80, "lon": -69.90, "sog": 5.0, "cog": 30, "heading": 30, "destination": "Boston", "flag": "US", "length": 30, "width": 8},
    {"mmsi": "FALLBACK-15", "name": "Baltic RoRo", "type": "Cargo", "lat": 54.60, "lon": 18.50, "sog": 11.0, "cog": 90, "heading": 90, "destination": "Gdansk", "flag": "PL", "length": 190, "width": 26},
]


def _fetch_ships():
    """Fetch live ship positions from the z:3 MarineTraffic tile grid.

    Resilient scraper: rotates User-Agents, paces tiles (0.25s) to avoid
    rate-limit bursts, retries each tile once, and keeps ANY partial
    results (only falls back to the emergency set if EVERY tile fails).
    """
    import urllib.parse
    import time as _time
    _UAS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    ]
    ships = []
    n = 2 ** _SHIPS_GRID_Z
    tiles = [(x, y) for x in range(n) for y in range(n)]
    deadline = time.time() + 18.0          # hard cap: browser fetch gives up ~30s
    consecutive_fails = 0
    for idx, (x, y) in enumerate(tiles):
        if time.time() > deadline:         # out of time — return what we have
            break
        ua = _UAS[idx % len(_UAS)]
        for attempt in range(2):   # one retry per tile
            try:
                url = f"https://www.marinetraffic.com/getData/get_data_json_4/z:{_SHIPS_GRID_Z}/X:{x}/Y:{y}"
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
                        ships.append({
                            "mmsi": str(row.get("SHIP_ID", "")),
                            "name": row.get("SHIPNAME") or "Unknown",
                            "type": _SHIP_TYPE_MAP.get(str(row.get("SHIPTYPE")), "Other"),
                            "lat": lat,
                            "lon": lon,
                            "sog": float(row.get("SPEED") or 0),
                            "cog": float(row.get("COURSE") or 0),
                            "heading": float(row.get("HEADING") or 0),
                            "destination": row.get("DESTINATION") or "",
                            "flag": row.get("FLAG") or "",
                            "length": float(row.get("LENGTH") or 0),
                            "width": float(row.get("WIDTH") or 0),
                        })
                    except (TypeError, ValueError):
                        continue
                consecutive_fails = 0
                break   # tile succeeded
            except Exception:
                consecutive_fails += 1
                if consecutive_fails >= 3 and not ships:
                    # 3 straight failures with zero results = domain blocked
                    # (403) or down — don't burn 48s on 64 doomed tiles, bail
                    # to the emergency set NOW so the API answers fast.
                    return _FALLBACK_SHIPS
                if attempt == 0:
                    _time.sleep(0.5)   # brief backoff before retry
                continue
        _time.sleep(0.25)   # pace tiles — bursts trigger rate limits
    # FALLBACK: only if EVERY tile failed (network down / hard block) — serve
    # a guaranteed set of real-world anchor points so the globe is never empty.
    if not ships:
        ships = list(_FALLBACK_SHIPS)
    return ships


# ---------------------------------------------------------------- live AIS
# AISstream.io WebSocket (free tier — email-only account, no card, no polling:
# the server PUSHES global AIS to us, so request rate ≈ 0 and we can never be
# locked out on a wait list). Key lives in data/aisstream_creds.json (same
# pattern as opensky_creds.json / ion_token.json) or env AISSTREAM_API_KEY.
_AISSTREAM_KEY = os.environ.get("AISSTREAM_API_KEY", "")
_aisstream_creds_path = Path(__file__).parent / "data" / "aisstream_creds.json"
if not _AISSTREAM_KEY and _aisstream_creds_path.exists():
    try:
        _AISSTREAM_KEY = json.loads(_aisstream_creds_path.read_text(encoding="utf-8")).get("api_key", "")
    except Exception:
        _AISSTREAM_KEY = ""

ship_cache = {}                      # mmsi -> vessel dict (live AIS)
_ship_cache_lock = _threading.Lock()
_AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"


def _aisstream_listener():
    """Background WebSocket listener: global bounding box, live AIS.

    Subscribes to the whole planet [[-90,-180],[90,180]] and updates
    ship_cache in place. Reconnects forever with backoff. If no API key is
    configured the listener stays dormant and the fallback path serves.
    """
    if not _AISSTREAM_KEY:
        print("[worldview] AISstream: no API key — listener dormant (fallback ships only)")
        return
    try:
        import websocket  # websocket-client
    except ImportError:
        print("[worldview] AISstream: websocket-client not installed — dormant")
        return
    while True:
        try:
            ws = websocket.WebSocket()
            ws.connect(_AISSTREAM_WS_URL, timeout=30)
            ws.send(json.dumps({
                "APIKey": _AISSTREAM_KEY,
                "BoundingBoxes": [[[-90.0, -180.0], [90.0, 180.0]]],
            }))
            print("[worldview] AISstream: connected — live global AIS streaming")
            while True:
                raw = ws.recv()
                if not raw:
                    continue
                msg = json.loads(raw)
                mtype = msg.get("MessageType")
                meta = msg.get("MetaData", {})
                mmsi = str(meta.get("MMSI", ""))
                if not mmsi:
                    continue
                if mtype == "PositionReport":
                    pr = msg.get("Message", {}).get("PositionReport", {})
                    lat, lon = pr.get("Latitude"), pr.get("Longitude")
                    if lat is None or lon is None:
                        continue
                    with _ship_cache_lock:
                        cur = ship_cache.get(mmsi, {})
                        ship_cache[mmsi] = {
                            "mmsi": mmsi,
                            "name": cur.get("name", "Unknown"),
                            "type": cur.get("type", "Other"),
                            "lat": float(lat),
                            "lon": float(lon),
                            "sog": float(pr.get("SpeedOverGround", 0) or 0),
                            "cog": float(pr.get("CourseOverGround", 0) or 0),
                            "heading": float(pr.get("TrueHeading", 0) or 0),
                            "destination": cur.get("destination", ""),
                            "eta": cur.get("eta", ""),
                            "flag": cur.get("flag", ""),
                            "length": cur.get("length", 0),
                            "width": cur.get("width", 0),
                            "source": "aisstream",
                        }
                elif mtype == "ShipStaticData":
                    ssd = msg.get("Message", {}).get("ShipStaticData", {})
                    with _ship_cache_lock:
                        cur = ship_cache.get(mmsi, {})
                        dim = ssd.get("Dimension", {})
                        cur.update({
                            "mmsi": mmsi,
                            "name": ssd.get("ShipName", cur.get("name", "Unknown")),
                            "type": _SHIP_TYPE_MAP.get(str(ssd.get("Type", "")), cur.get("type", "Other")),
                            "destination": ssd.get("Destination", cur.get("destination", "")),
                            "eta": ssd.get("Eta", ssd.get("ETA", cur.get("eta", ""))),
                            "length": float(dim.get("Length", cur.get("length", 0)) or 0),
                            "width": float(dim.get("Width", cur.get("width", 0)) or 0),
                            "source": "aisstream",
                        })
                        ship_cache[mmsi] = cur
        except Exception as e:
            print(f"[worldview] AISstream: connection error — {e}; retrying in 30s")
            time.sleep(30)


@app.get("/api/ships")
def api_ships():
    """Live AIS ship positions.

    Priority: AISstream WebSocket cache (live, global) → MarineTraffic crawl
    (cached 60s) → 15-vessel emergency set so the globe is never empty.

    v2.3.1: the MarineTraffic crawl runs on a BACKGROUND thread — this
    endpoint NEVER blocks for 60s (that stalled the browser's single
    loadShips() call at boot → "hardly no boats"). Always answers fast.
    """
    global _SHIPS_CACHE_TIME
    now = time.time()
    with _ship_cache_lock:
        live = list(ship_cache.values())
    if live:
        return {"ships": live, "time": int(now), "cached": False, "source": "aisstream"}
    if not _SHIPS_CACHE or now - _SHIPS_CACHE_TIME > _SHIPS_TTL:
        # kick the crawl into a background thread, return whatever we have NOW
        def _crawl():
            try:
                fresh = _fetch_ships()
                with _SHIPS_CACHE_LOCK:
                    global _SHIPS_CACHE
                    _SHIPS_CACHE = fresh
            except Exception:
                pass
        with _SHIPS_CACHE_LOCK:
            stale = list(_SHIPS_CACHE)
        t = _threading.Thread(target=_crawl, daemon=True)
        t.start()
        _SHIPS_CACHE_TIME = now
        return {"ships": stale, "time": int(now), "cached": True, "source": "background-crawl"}
    return {"ships": _SHIPS_CACHE, "time": int(now), "cached": now - _SHIPS_CACHE_TIME > 5, "source": "fallback"}


# ---------------------------------------------------------------- live fires
# NASA FIRMS active thermal anomalies (VIIRS SNPP C2, last 24h) — public CSV,
# no key. ~92K detections/day; parsed to lat/lon/brightness/confidence and
# cached 10 min. Same data Bilawal overlays in the God's Eye videos.
_FIRES_CACHE = []
_FIRES_CACHE_TIME = 0.0
_FIRES_TTL = 600
_FIRES_URL = ("https://firms.modaps.eosdis.nasa.gov/data/active_fire/"
              "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv")


def _fetch_fires():
    """Fetch + parse the FIRMS 24h CSV (lat, lon, brightness, confidence)."""
    import csv as _csv
    import io as _io
    try:
        req = urllib.request.Request(_FIRES_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    except Exception:
        return []
    fires = []
    try:
        reader = _csv.DictReader(_io.StringIO(raw))
        for row in reader:
            try:
                lat = float(row.get("latitude", ""))
                lon = float(row.get("longitude", ""))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                conf = (row.get("confidence") or "nominal").strip().lower()
                # quality: keep ONLY high-confidence detections — 'h'/'high'
                # (VIIRS) or a numeric score >= 75 (MODIS) — eliminates roof
                # reflections / asphalt heat noise
                if conf not in ("h", "high"):
                    try:
                        if float(conf) < 75:
                            continue
                    except (TypeError, ValueError):
                        continue
                fires.append({
                    "lat": lat,
                    "lon": lon,
                    "brightness": float(row.get("bright_ti4") or 0),
                    "confidence": conf,
                    "acq_time": row.get("acq_time") or "",
                    "acq_date": row.get("acq_date") or "",
                    "daynight": row.get("daynight") or "",
                })
            except (TypeError, ValueError):
                continue
    except Exception:
        return []
    # perf: cap the entity count — 92K billboards stalls the render loop.
    # Keep the most recent detections (CSV is time-ordered) up to 12,000.
    if len(fires) > 12000:
        fires = fires[-12000:]
    return fires


def _get_fires_cached():
    """Return the FIRMS cache, refreshing it if stale (shared by /api/fires,
    /api/hotspots and /api/zone_feed so they never double-fetch)."""
    global _FIRES_CACHE, _FIRES_CACHE_TIME
    now = time.time()
    if not _FIRES_CACHE or now - _FIRES_CACHE_TIME > _FIRES_TTL:
        _FIRES_CACHE = _fetch_fires()
        _FIRES_CACHE_TIME = now
    return _FIRES_CACHE


@app.get("/api/fires")
def api_fires():
    """Live thermal fire detections (NASA FIRMS, cached 10 min)."""
    now = time.time()
    fires = _get_fires_cached()
    return {"fires": fires, "count": len(fires),
            "time": int(now), "cached": now - _FIRES_CACHE_TIME > 5}


# ---------------------------------------------------------------- hurricanes
# NOAA NHC active tropical cyclones (CurrentStorms.json, free, no key) +
# per-storm forecast track from the official KMZ (same source the NHC site
# uses). Cached 30 min. Track points come from the TRACK.kmz (LineString
# placemarks); the cone is available as CONE.kmz but skipped for now.
_HURR_CACHE = []
_HURR_CACHE_TIME = 0.0
_HURR_TTL = 1800
_NHC_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"


def _fetch_hurricanes():
    """Fetch NHC active storms + forecast track polylines."""
    try:
        req = urllib.request.Request(_NHC_STORMS_URL, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[worldview] NHC fetch failed: {e}")
        return []
    storms = []
    for s in data.get("activeStorms", []):
        try:
            lat = float(s.get("latitudeNumeric") or 0)
            lon = float(s.get("longitudeNumeric") or 0)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            storm = {
                "id": s.get("id", ""),
                "name": s.get("name", "Unnamed"),
                "classification": s.get("classification", ""),
                "intensity_kt": s.get("intensity", ""),
                "pressure_mb": s.get("pressure", ""),
                "lat": lat,
                "lon": lon,
                "movement_dir": s.get("movementDir", ""),
                "movement_speed_kt": s.get("movementSpeed", ""),
                "last_update": s.get("lastUpdate", ""),
                "advisory_url": (s.get("publicAdvisory") or {}).get("url", ""),
                "track": [],
            }
            # forecast track from the official KMZ (TRACK.kmz)
            kmz_url = (s.get("forecastTrack") or {}).get("kmzFile", "")
            if kmz_url:
                storm["track"] = _fetch_storm_track(kmz_url)
            storms.append(storm)
        except (TypeError, ValueError):
            continue
    return storms


def _fetch_storm_track(kmz_url):
    """Download a NHC TRACK.kmz and return the forecast polyline points
    [(lon, lat), ...] from its LineString placemarks (deduped)."""
    import io as _io
    import zipfile as _zipfile
    import re as _re
    try:
        req = urllib.request.Request(kmz_url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        z = _zipfile.ZipFile(_io.BytesIO(raw))
        kml_name = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
        if not kml_name:
            return []
        kml = z.read(kml_name).decode("utf-8", "replace")
        pts = []
        seen_pts = set()
        for m in _re.finditer(r"<coordinates>(.*?)</coordinates>", kml, _re.S):
            for p in m.group(1).strip().split():
                parts = p.strip().split(",")
                if len(parts) >= 2:
                    try:
                        lon, lat = float(parts[0]), float(parts[1])
                    except ValueError:
                        continue
                    if (-90 <= lat <= 90 and -180 <= lon <= 180
                            and (lon, lat) not in seen_pts):
                        seen_pts.add((lon, lat))
                        pts.append((lon, lat))
        return pts
    except Exception as e:
        print(f"[worldview] NHC track fetch failed ({kmz_url}): {e}")
        return []


def _get_hurricanes_cached():
    global _HURR_CACHE, _HURR_CACHE_TIME
    now = time.time()
    if not _HURR_CACHE or now - _HURR_CACHE_TIME > _HURR_TTL:
        _HURR_CACHE = _fetch_hurricanes()
        _HURR_CACHE_TIME = now
    return _HURR_CACHE


@app.get("/api/hurricanes")
def api_hurricanes():
    """Active tropical cyclones (NOAA NHC) with forecast track polylines."""
    now = time.time()
    storms = _get_hurricanes_cached()
    return {"storms": storms, "count": len(storms),
            "time": int(now), "cached": now - _HURR_CACHE_TIME > 5}


# ---------------------------------------------------------------- conflict zones
# Static geolocated conflict zones = the red haze overlays. Live-feed URLs are
# YouTube channel /live endpoints (public, embeddable) — every handle below
# was HTTP-verified 2026-08-13 (200 or 303->canonical). GDELT/Liveuamap are
# BLOCKED (403/429) and are NOT used anywhere.
# hot-zone scoring cache (60s TTL) — the red bot polls every 20s; this
# keeps the haversine scoring from re-running on every single poll
_HOT_ZONES_CACHE = []
_HOT_ZONES_CACHE_TIME = 0.0
_HOT_ZONES_TTL = 60

# YouTube channel IDs (resolved 2026-08-13 from @handles) — used to build
# EMBEDDABLE live-stream URLs. Plain /@handle/live pages are blocked by
# YouTube's X-Frame-Options in iframes; /embed/live_stream?channel=UC... is
# the official embeddable form and plays inside the stream window.
_YT_CHANNELS = {
    "KyivLive": "UCwTXL6Sax8q4aqJ1pNNTGgA",
    "UkraineNOW": "UCVkYsQMROZHp_5AJiKKWFXA",
    "DWNews": "UCbbS1GE942k3UVqpLklyhIA",
    "aljazeeraenglish": "UCfiwzLy-8yKzIbsmZTzxDgw",
    "AlMayadeenEnglish": "UCZCFHCU-2eGF7V5ciMkoPHw",
    "PressTV": "UC0OO19kc2jt8ZtOWZMVa3Vw",
    "trtworld": "UCnyCrv8b7bu0oWFXGyHaPzg",
    "AlArabiya": "UCrj5BGAhtWxDfqbza9T9hqA",
    "SudanTribune": "UCrnkurRbU8ftAXCPKoONFbg",
    "MizzimaTV": "UC9duwzgDlAnqCF7k1tlvrXw",
    "DVBNews": "UC60W37GZodr7kTcqKqTWf9A",
    "VOAnews": "UCKyTokYo0nK2OA-az-sDijA",
    "taiwanplus": "UCHWZrE1UY7eL82fAIzskBYA",
    "CGTN": "UCd94YCD7yp6d-YZSRYWyeFA",
    "SkyNews": "UCkFclpi8U9VJjfxLYoms7Aw",
    "BBCNews": "UC16niRr50-MSBwiO3YDb3RA",
    "CNN": "UCupvZG-5ko_eiXAupbDfxWw",
    "France24": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
    "ABCNews": "UCBi2mrWuNuyYy4gbM6fU18Q",
}

# live-status cache: handle -> {live: bool, videoId: str|None}
# refreshed every 5 min by _yt_live_checker (daemon thread)
_YT_LIVE = {}
_YT_LIVE_LOCK = _threading.Lock()


def _yt_live_checker():
    """Every 5 min, check which channels are actually broadcasting and cache
    their live videoId. The stream window then embeds the PLAYING video
    (live-first), never a dead channel page."""
    while True:
        try:
            import urllib.request as _ur
            live_map = {}
            for name, cid in _YT_CHANNELS.items():
                try:
                    req = _ur.Request(
                        f"https://www.youtube.com/channel/{cid}/live",
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                                 "Accept-Language": "en-US,en;q=0.9"},
                    )
                    with _ur.urlopen(req, timeout=15) as r:
                        html = r.read().decode("utf-8", "replace")
                    is_live = '"isLiveNow":true' in html or '"isLive":true' in html
                    vid = _re.search(r'"videoId":"([\w-]{11})"', html)
                    live_map[name] = {"live": is_live, "videoId": vid.group(1) if (is_live and vid) else None}
                except Exception:
                    live_map[name] = {"live": False, "videoId": None}
                time.sleep(0.5)
            with _YT_LIVE_LOCK:
                _YT_LIVE.clear()
                _YT_LIVE.update(live_map)
            print(f"[worldview] YT live check: {sum(1 for v in live_map.values() if v['live'])}/{len(live_map)} channels live")
        except Exception as e:
            print(f"[worldview] YT live check failed: {e}")
        time.sleep(300)


@app.get("/api/yt_live")
def api_yt_live():
    """Live state + real video IDs for every tracked channel (refreshed every
    5 min by _yt_live_checker). The frontend embeds the ACTUAL live videoId
    (plays immediately) instead of a channel page (Video unavailable when
    offline)."""
    with _YT_LIVE_LOCK:
        return {"channels": dict(_YT_LIVE), "time": int(time.time())}


def _embed_live_urls(urls):
    """Convert plain YouTube /live URL strings into embeddable feed objects.

    [{url, name, live}] — live channels (checked every 5 min) embed the
    actual live videoId (plays immediately); offline channels fall back to
    the channel live_stream embed. Live feeds sort FIRST so the stream
    window always opens a PLAYING stream, and regional channels keep their
    zone order (local-first) within the live group.
    """
    out = []
    for u in urls or []:
        if not isinstance(u, str):
            out.append(u)
            continue
        m = _re.search(r"@([A-Za-z0-9_-]+)/live", u)
        if m and m.group(1) in _YT_CHANNELS:
            name = m.group(1)
            live = _YT_LIVE.get(name, {})
            if live.get("live") and live.get("videoId"):
                out.append({
                    "url": f"https://www.youtube.com/embed/{live['videoId']}?autoplay=1&mute=1",
                    "name": name, "live": True,
                    "watch_url": f"https://www.youtube.com/watch?v={live['videoId']}",
                })
            else:
                cid = _YT_CHANNELS[name]
                out.append({
                    "url": f"https://www.youtube.com/embed/live_stream?channel={cid}&autoplay=1&mute=1",
                    "name": name, "live": False,
                    "watch_url": f"https://www.youtube.com/channel/{cid}/live",
                })
        else:
            out.append({"url": u, "name": u.split("/")[-2] if "/" in u else u, "live": False})
    out.sort(key=lambda f: 0 if f.get("live") else 1)
    return out

_CONFLICT_ZONES = [
    {
        "id": "ukraine",
        "name": "Ukraine",
        "lat": 48.38, "lon": 31.17,
        "radius_km": 600,
        "intensity": 0.95,
        "live_feed_urls": [
            "https://www.youtube.com/@KyivLive/live",
            "https://www.youtube.com/@UkraineNOW/live",
            "https://www.youtube.com/@DWNews/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
        ],
    },
    {
        "id": "gaza",
        "name": "Gaza Strip",
        "lat": 31.50, "lon": 34.47,
        "radius_km": 60,
        "intensity": 1.0,
        "live_feed_urls": [
            "https://www.youtube.com/@aljazeeraenglish/live",
            "https://www.youtube.com/@AlMayadeenEnglish/live",
            "https://www.youtube.com/@PressTV/live",
            "https://www.youtube.com/@trtworld/live",
        ],
    },
    {
        "id": "iran-hormuz",
        "name": "Iran / Strait of Hormuz",
        "lat": 26.57, "lon": 56.25,
        "radius_km": 250,
        "intensity": 0.85,
        "live_feed_urls": [
            "https://www.youtube.com/@PressTV/live",
            "https://www.youtube.com/@AlArabiya/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
            "https://www.youtube.com/@trtworld/live",
        ],
    },
    {
        "id": "sudan",
        "name": "Sudan",
        "lat": 15.50, "lon": 32.56,
        "radius_km": 500,
        "intensity": 0.9,
        "live_feed_urls": [
            "https://www.youtube.com/@SudanTribune/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
            "https://www.youtube.com/@DWNews/live",
        ],
    },
    {
        "id": "myanmar",
        "name": "Myanmar",
        "lat": 21.90, "lon": 96.00,
        "radius_km": 400,
        "intensity": 0.8,
        "live_feed_urls": [
            "https://www.youtube.com/@MizzimaTV/live",
            "https://www.youtube.com/@DVBNews/live",
            "https://www.youtube.com/@VOAnews/live",
        ],
    },
    {
        "id": "yemen",
        "name": "Yemen",
        "lat": 15.35, "lon": 44.20,
        "radius_km": 350,
        "intensity": 0.85,
        "live_feed_urls": [
            "https://www.youtube.com/@AlMayadeenEnglish/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
            "https://www.youtube.com/@PressTV/live",
        ],
    },
    {
        "id": "lebanon",
        "name": "Lebanon",
        "lat": 33.85, "lon": 35.86,
        "radius_km": 120,
        "intensity": 0.9,
        "live_feed_urls": [
            "https://www.youtube.com/@AlMayadeenEnglish/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
            "https://www.youtube.com/@trtworld/live",
        ],
    },
    {
        "id": "taiwan-strait",
        "name": "Taiwan Strait",
        "lat": 24.50, "lon": 120.50,
        "radius_km": 300,
        "intensity": 0.7,
        "live_feed_urls": [
            "https://www.youtube.com/@taiwanplus/live",
            "https://www.youtube.com/@CGTN/live",
            "https://www.youtube.com/@DWNews/live",
        ],
    },
    {
        "id": "red-sea",
        "name": "Red Sea / Bab el-Mandeb",
        "lat": 15.00, "lon": 42.50,
        "radius_km": 400,
        "intensity": 0.8,
        "live_feed_urls": [
            "https://www.youtube.com/@AlMayadeenEnglish/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
            "https://www.youtube.com/@PressTV/live",
        ],
    },
    {
        "id": "korea",
        "name": "Korean Peninsula",
        "lat": 38.00, "lon": 127.00,
        "radius_km": 300,
        "intensity": 0.6,
        "live_feed_urls": [
            "https://www.youtube.com/@VOAnews/live",
            "https://www.youtube.com/@DWNews/live",
            "https://www.youtube.com/@CGTN/live",
        ],
    },
]

# convert every zone's plain /live URL strings into embeddable feed objects
# (YouTube blocks /live pages in iframes; /embed/live_stream works)
# NOTE: keep the RAW strings too — live status is re-checked at REQUEST time
# (the module-load conversion runs before the live-checker has data, so
# converting once here would freeze every feed at live=False forever).
_ZONE_RAW_FEEDS = {z["id"]: list(z.get("live_feed_urls", [])) for z in _CONFLICT_ZONES}
for _z in _CONFLICT_ZONES:
    _z["live_feed_urls"] = _embed_live_urls(_z.get("live_feed_urls", []))


def _zones_with_live():
    """Deep-ish copy of the zones with FRESH live status on every feed.

    Called at request time so the stream window always gets the currently
    PLAYING video first (live-first, regional order preserved).
    """
    out = []
    for z in _CONFLICT_ZONES:
        zc = dict(z)
        zc["live_feed_urls"] = _embed_live_urls(_ZONE_RAW_FEEDS.get(z["id"], []))
        out.append(zc)
    return out


def _hotspot_clusters(points, cell_deg=0.5, min_count=3):
    """Grid-cluster FIRMS points into darker-red hotspots.

    Brightness-weighted centroid per ~0.5deg cell (>= min_count points).
    intensity 0-1 scales with point count + peak brightness.
    """
    cells = defaultdict(list)
    for p in points:
        key = (int(p["lat"] / cell_deg), int(p["lon"] / cell_deg))
        cells[key].append(p)
    hotspots = []
    for pts in cells.values():
        if len(pts) < min_count:
            continue
        w = sum(p["brightness"] for p in pts) or 1.0
        lat = sum(p["lat"] * p["brightness"] for p in pts) / w
        lon = sum(p["lon"] * p["brightness"] for p in pts) / w
        bmax = max(p["brightness"] for p in pts)
        last = max((p.get("acq_date", ""), p.get("acq_time", "")) for p in pts)
        last_time = f"{last[0]} {last[1]}".strip()
        intensity = 0.25 + len(pts) / 40.0 + max(0.0, (bmax - 300) / 200.0) * 0.3
        # tag the owning conflict zone (if any) so clicking the dot opens
        # that zone's live feed in the stream window
        zone_id = None
        for _z in _CONFLICT_ZONES:
            if _haversine_m(_z["lat"], _z["lon"], lat, lon) <= _z["radius_km"] * 1000.0:
                zone_id = _z["id"]
                break
        hotspots.append({
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "intensity": round(max(0.0, min(1.0, intensity)), 3),
            "count": len(pts),
            "last_time": last_time,
            "kind": "thermal",
            "brightness": round(bmax, 1),
            "zone_id": zone_id,
        })
    return hotspots


def _military_hotspots(cell_deg=2.0):
    """Military flight density from the last OpenSky poll (priority 0).

    ~2deg cells with >= 2 military flights become hotspots; intensity scales
    with the number of military aircraft in the cell.
    """
    cells = defaultdict(list)
    for f in _LAST_FLIGHTS.values():
        if f.get("lat") is None or f.get("lon") is None:
            continue
        if f.get("priority") != 0 and not f.get("military"):
            continue
        key = (int(f["lat"] / cell_deg), int(f["lon"] / cell_deg))
        cells[key].append(f)
    hotspots = []
    for pts in cells.values():
        if len(pts) < 2:
            continue
        lat = sum(p["lat"] for p in pts) / len(pts)
        lon = sum(p["lon"] for p in pts) / len(pts)
        intensity = 0.3 + len(pts) / 12.0
        hotspots.append({
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "intensity": round(min(1.0, intensity), 3),
            "count": len(pts),
            "last_time": "",
            "kind": "military",
        })
    return hotspots


@app.get("/api/conflict_zones")
def api_conflict_zones():
    """Static geolocated conflict zones (red haze) + live feed URLs."""
    zones = _zones_with_live()
    return {"zones": zones, "count": len(zones),
            "time": int(time.time())}


@app.get("/api/hotspots")
def api_hotspots():
    """Darker red dots: FIRMS thermal clusters (high confidence) + military
    flight density. intensity 0-1 drives dot size/opacity; kind distinguishes
    'thermal' vs 'military' hotspots."""
    fires = _get_fires_cached()
    thermal = _hotspot_clusters(fires)
    military = _military_hotspots()
    hotspots = thermal + military
    hotspots.sort(key=lambda h: -h["intensity"])
    return {"hotspots": hotspots, "count": len(hotspots),
            "thermal_count": len(thermal), "military_count": len(military),
            "time": int(time.time())}


def _score_hot_zones():
    """Score every conflict zone: intensity x live thermal activity.

    Returns zones sorted hottest-first, each with score, event_count
    (24h FIRMS detections in radius) and recent_count (today's).
    Cached 60s — the red bot polls this every 20s; recomputing 85K
    haversine checks per call would waste CPU on every poll.
    """
    global _HOT_ZONES_CACHE, _HOT_ZONES_CACHE_TIME
    now = time.time()
    if _HOT_ZONES_CACHE and now - _HOT_ZONES_CACHE_TIME < _HOT_ZONES_TTL:
        return _HOT_ZONES_CACHE
    fires = _get_fires_cached()
    today = time.strftime("%Y-%m-%d")
    counts = {z["id"]: [0, 0] for z in _CONFLICT_ZONES}   # [total, recent]
    for f in fires:
        for z in _CONFLICT_ZONES:
            if _haversine_m(z["lat"], z["lon"], f["lat"], f["lon"]) <= z["radius_km"] * 1000.0:
                counts[z["id"]][0] += 1
                if f.get("acq_date", "") >= today:
                    counts[z["id"]][1] += 1
    out = []
    for z in _zones_with_live():
        n, recent = counts[z["id"]]
        score = z.get("intensity", 0.5) * (1.0 + min(n, 100) / 10.0 + min(recent, 50) / 5.0)
        out.append({
            "zone": {k: z[k] for k in ("id", "name", "lat", "lon", "radius_km", "intensity")},
            "score": round(score, 3), "event_count": n, "recent_count": recent,
            "live_feed_urls": z["live_feed_urls"],
        })
    out.sort(key=lambda r: -r["score"])
    _HOT_ZONES_CACHE = out
    _HOT_ZONES_CACHE_TIME = time.time()
    return out


@app.get("/api/hot_zone")
def api_hot_zone():
    """The hottest war spot RIGHT NOW — what has the world's attention.

    Score = zone intensity x live thermal activity (events in the last 24h
    inside the zone radius, recency-weighted). Returns the #1 zone so the
    app can fly to it on load and re-focus live as attention shifts.
    """
    ranked = _score_hot_zones()
    best = ranked[0] if ranked else {"zone": None, "score": 0, "event_count": 0,
                                     "recent_count": 0, "live_feed_urls": []}
    best["time"] = int(time.time())
    return best


@app.get("/api/hot_zones")
def api_hot_zones():
    """All conflict zones ranked hottest-first (for the red-bot patrol +
    news ticker). Same scoring as /api/hot_zone, full ranked list."""
    ranked = _score_hot_zones()
    return {"zones": ranked, "count": len(ranked), "time": int(time.time())}


@app.get("/api/zone_feed")
def api_zone_feed(zone: str = ""):
    """Zone info + recent thermal events inside it + live stream URLs.

    ?zone=<id> (e.g. 'gaza', 'ukraine'). Events are the high-confidence FIRMS
    detections within radius_km of the zone center, newest first (max 200).
    """
    z = next((z for z in _zones_with_live() if z["id"] == zone), None)
    if not z:
        return {"error": f"unknown zone '{zone}'",
                "zones": [z["id"] for z in _CONFLICT_ZONES]}
    events = []
    for f in _get_fires_cached():
        if _haversine_m(z["lat"], z["lon"], f["lat"], f["lon"]) <= z["radius_km"] * 1000.0:
            events.append(f)
    events.sort(key=lambda e: (e.get("acq_date", ""), e.get("acq_time", "")),
                reverse=True)
    events = events[:200]
    return {
        "zone": {k: z[k] for k in ("id", "name", "lat", "lon", "radius_km", "intensity")},
        "live_feed_urls": z["live_feed_urls"],
        "events": events,
        "event_count": len(events),
        "time": int(time.time()),
    }


@app.get("/api/cameras/image/{cam_id}")
def api_camera_image(cam_id: str, src: str = "nyc"):
    """Proxy a single webcam snapshot (same-origin, so the browser can show
    it despite upstream X-Frame-Options/CSP). ?src=nc for NC DOT cams.
    Custom cameras carry an upstream_id that maps to the real feed."""
    src = (src or "nyc").lower()
    # custom camera? resolve upstream id
    for c in _CUSTOM_CAMERAS:
        if c["id"] == cam_id and c.get("upstream_id"):
            cam_id = c["upstream_id"]
            src = c["src"]
            break
    if src == "nc":
        body, ctype = _fetch_nc_image(cam_id)
    else:
        body, ctype = _fetch_camera_image(cam_id)
    return Response(content=body, media_type=ctype,
                    headers={"Cache-Control": "no-store",
                             "Access-Control-Allow-Origin": "*"})


@app.get("/api/cameras/name/{cam_id}")
def api_camera_name(cam_id: str, src: str = "nyc"):
    """Resolve a camera's display name (NC names come from tooltips, lazy)."""
    if (src or "nyc").lower() == "nc":
        return {"id": cam_id, "name": _nc_camera_name(cam_id)}
    for c in _CAMERAS_CACHE or []:
        if c["id"] == cam_id:
            return {"id": cam_id, "name": c["name"]}
    return {"id": cam_id, "name": f"Camera {cam_id}"}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _port_in_use(port):
    """True if something already listens on 127.0.0.1:port."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _open_browser_when_ready(port, timeout=45):
    """Wait until the server accepts connections, then open Chrome."""
    import socket
    import subprocess
    import threading
    import time

    def wait_and_open():
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            return
        url = f"http://localhost:{port}"
        # Boo's rule: CHROME ONLY — never Edge (he firewall-blocks Edge).
        # 1) Chrome (standard install paths)
        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for chrome in chrome_candidates:
            try:
                if os.path.exists(chrome):
                    subprocess.Popen([chrome, url])
                    return
            except Exception:
                pass
        # 2) Chrome via PATH (where chrome)
        try:
            subprocess.Popen(["chrome", url])
            return
        except Exception:
            pass
        # 3) Firefox (never Edge)
        firefox = r"C:\Program Files\Mozilla Firefox\firefox.exe"
        try:
            if os.path.exists(firefox):
                subprocess.Popen([firefox, url])
                return
        except Exception:
            pass
        # 4) absolute last resort: default browser (Edge is firewall-blocked
        #    on Boo's machine, so this effectively never opens Edge)
        try:
            os.startfile(url)
        except Exception:
            pass

    threading.Thread(target=wait_and_open, daemon=True).start()


# ---------------------------------------------------------------- Admin news swarm (v2.3.1)
# This feature is intentionally self-contained: the browser only starts a job
# and polls it; all fetching/parsing happens in daemon background threads.
import datetime as _swarm_datetime
import html as _swarm_html
import hmac as _swarm_hmac
import secrets as _swarm_secrets
import threading as _swarm_threading
import urllib.parse as _swarm_parse
import xml.etree.ElementTree as _swarm_xml
from email.utils import parsedate_to_datetime as _swarm_rss_date

from fastapi import HTTPException as _SwarmHTTPException, Request as _SwarmRequest

_ADMIN_PIN_FILE = DATA_DIR / "admin_pin.json"
_NEWS_SWARM_HISTORY_FILE = DATA_DIR / "news_swarm_history.json"
_NEWS_SWARM_LOCK = _swarm_threading.Lock()
_NEWS_SWARMS = {}
_NEWS_SWARM_TOKENS = set()


def _swarm_now():
    return _swarm_datetime.datetime.now(_swarm_datetime.timezone.utc).isoformat()


def _swarm_load_pin():
    try:
        with _ADMIN_PIN_FILE.open("r", encoding="utf-8") as handle:
            return str(json.load(handle).get("pin", ""))
    except Exception:
        return ""


def _swarm_require_admin(request):
    token = request.headers.get("x-admin-token", "")
    with _NEWS_SWARM_LOCK:
        allowed = token in _NEWS_SWARM_TOKENS
    if not allowed:
        raise _SwarmHTTPException(status_code=403, detail="Admin authorization required")


def _swarm_text(value):
    return _swarm_html.unescape(str(value or "")).replace("\n", " ").strip()


def _swarm_published(value):
    """Return sortable, consistent UTC ISO timestamps without inventing dates."""
    if not value:
        return ""
    value = str(value).strip()
    try:
        if value.endswith("Z"):
            return _swarm_datetime.datetime.fromisoformat(value[:-1] + "+00:00").isoformat()
        parsed = _swarm_datetime.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_swarm_datetime.timezone.utc)
        return parsed.astimezone(_swarm_datetime.timezone.utc).isoformat()
    except ValueError:
        try:
            parsed = _swarm_rss_date(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_swarm_datetime.timezone.utc)
            return parsed.astimezone(_swarm_datetime.timezone.utc).isoformat()
        except (TypeError, ValueError):
            return value


def _swarm_item(source, title, url, published="", snippet=""):
    url = str(url or "").strip()
    title = _swarm_text(title)
    if not url or not title:
        return None
    return {"source": source, "title": title, "url": url,
            "published": _swarm_published(published), "snippet": _swarm_text(snippet)}


def _swarm_fetch(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "WorldWarWatch/2.3.1 news capture (+local admin tool)",
        "Accept": "application/rss+xml, application/json, text/xml, */*",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read()


def _swarm_rss(url):
    source = "Bing News RSS" if "bing.com" in url else "Google News RSS"
    root = _swarm_xml.fromstring(_swarm_fetch(url))
    results = []
    for item in root.findall(".//item")[:10]:
        result = _swarm_item(source, item.findtext("title"), item.findtext("link"),
                             item.findtext("pubDate"), item.findtext("description"))
        if result:
            results.append(result)
    return results


def _swarm_reddit(url):
    payload = json.loads(_swarm_fetch(url).decode("utf-8"))
    results = []
    for child in payload.get("data", {}).get("children", [])[:10]:
        post = child.get("data", {})
        link = post.get("url") or ("https://www.reddit.com" + post.get("permalink", ""))
        published = _swarm_datetime.datetime.fromtimestamp(
            float(post.get("created_utc", 0) or 0), _swarm_datetime.timezone.utc
        ).isoformat() if post.get("created_utc") else ""
        result = _swarm_item("Reddit", post.get("title"), link, published,
                             post.get("selftext") or post.get("subreddit_name_prefixed", ""))
        if result:
            results.append(result)
    return results


def _swarm_hacker_news(url):
    payload = json.loads(_swarm_fetch(url).decode("utf-8"))
    results = []
    for hit in payload.get("hits", [])[:10]:
        link = hit.get("url") or ("https://news.ycombinator.com/item?id=" + str(hit.get("objectID", "")))
        result = _swarm_item("Hacker News", hit.get("title") or hit.get("story_title"),
                             link, hit.get("created_at"), hit.get("story_text") or hit.get("comment_text", ""))
        if result:
            results.append(result)
    return results


def _swarm_gdelt(url):
    payload = json.loads(_swarm_fetch(url).decode("utf-8"))
    results = []
    for article in payload.get("articles", [])[:10]:
        result = _swarm_item("GDELT", article.get("title"), article.get("url"),
                             article.get("seendate"), article.get("domain", ""))
        if result:
            # GDELT returns a "location" field like "Lat 18.0 Lon -155.2"
            # (or "Lat 18.0, Lon -155.2") — parse it so the frontend can
            # place a red circle on the globe for this result.
            loc = str(article.get("location") or "")
            m = _re.search(r"Lat\s+(-?\d+(?:\.\d+)?)[,\s]+Lon\s+(-?\d+(?:\.\d+)?)", loc, _re.I)
            if m:
                try:
                    result["lat"] = float(m.group(1))
                    result["lon"] = float(m.group(2))
                except ValueError:
                    pass
            results.append(result)
    return results


def _swarm_collect(swarm_id, source, collector, url):
    try:
        items, error = collector(url), ""
    except Exception as exc:
        items, error = [], f"{type(exc).__name__}: {exc}"
    with _NEWS_SWARM_LOCK:
        swarm = _NEWS_SWARMS.get(swarm_id)
        if swarm:
            swarm["agents"][source] = {"finished": True, "count": len(items), "error": error}
            swarm["raw_results"].extend(items)


def _swarm_save_history(capture):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        history = []
        if _NEWS_SWARM_HISTORY_FILE.exists():
            with _NEWS_SWARM_HISTORY_FILE.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, list):
                history = loaded
        history.append(capture)
        with _NEWS_SWARM_HISTORY_FILE.open("w", encoding="utf-8") as handle:
            json.dump(history, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[worldview] news swarm history save error: {exc}")


def _swarm_run(swarm_id, topic):
    encoded = _swarm_parse.quote_plus(topic)
    jobs = [
        ("Google News RSS", _swarm_rss, f"https://news.google.com/rss/search?q={encoded}"),
        ("Bing News RSS", _swarm_rss, f"https://www.bing.com/news/search?q={encoded}&format=rss"),
        ("Reddit", _swarm_reddit, f"https://www.reddit.com/search.json?q={encoded}&limit=10"),
        ("Hacker News", _swarm_hacker_news, f"https://hn.algolia.com/api/v1/search?query={encoded}&tags=story"),
        ("GDELT", _swarm_gdelt, f"https://api.gdeltproject.org/api/v2/doc/doc?query={encoded}&mode=artlist&maxrecords=10&format=json"),
    ]
    workers = [_swarm_threading.Thread(target=_swarm_collect, args=(swarm_id, *job), daemon=True)
               for job in jobs]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    with _NEWS_SWARM_LOCK:
        swarm = _NEWS_SWARMS.get(swarm_id)
        if not swarm:
            return
        unique = {}
        for result in swarm.pop("raw_results", []):
            unique.setdefault(result["url"], result)
        swarm["results"] = sorted(unique.values(), key=lambda result: result["published"], reverse=True)
        swarm["running"] = False
        swarm["finished_at"] = _swarm_now()
        capture = {key: swarm[key] for key in ("id", "topic", "started_at", "finished_at", "results")}
    _swarm_save_history(capture)


@app.post("/api/admin/verify")
async def admin_verify(request: _SwarmRequest):
    try:
        pin = str((await request.json()).get("pin", ""))
    except Exception:
        raise _SwarmHTTPException(status_code=400, detail="JSON body with PIN required")
    stored_pin = _swarm_load_pin()
    if not stored_pin or not _swarm_hmac.compare_digest(pin, stored_pin):
        raise _SwarmHTTPException(status_code=403, detail="Incorrect admin PIN")
    token = _swarm_secrets.token_urlsafe(32)
    with _NEWS_SWARM_LOCK:
        _NEWS_SWARM_TOKENS.add(token)
    return {"verified": True, "token": token}


@app.post("/api/admin/swarm")
async def admin_release_swarm(request: _SwarmRequest):
    _swarm_require_admin(request)
    try:
        topic = str((await request.json()).get("topic", "")).strip()
    except Exception:
        raise _SwarmHTTPException(status_code=400, detail="JSON body with topic required")
    if not topic or len(topic) > 240:
        raise _SwarmHTTPException(status_code=400, detail="Topic must be 1-240 characters")
    swarm_id = _swarm_secrets.token_urlsafe(12)
    with _NEWS_SWARM_LOCK:
        _NEWS_SWARMS[swarm_id] = {
            "id": swarm_id, "topic": topic, "started_at": _swarm_now(), "finished_at": None,
            "running": True, "results": [], "raw_results": [],
            "agents": {source: {"finished": False, "count": 0, "error": ""} for source in
                       ("Google News RSS", "Bing News RSS", "Reddit", "Hacker News", "GDELT")},
        }
    _swarm_threading.Thread(target=_swarm_run, args=(swarm_id, topic), daemon=True).start()
    return {"swarm_id": swarm_id}


@app.get("/api/admin/swarm_status")
def admin_swarm_status(request: _SwarmRequest, swarm_id: str):
    _swarm_require_admin(request)
    with _NEWS_SWARM_LOCK:
        swarm = _NEWS_SWARMS.get(swarm_id)
        if not swarm:
            raise _SwarmHTTPException(status_code=404, detail="Unknown swarm")
        return {key: value for key, value in swarm.items() if key != "raw_results"}


@app.get("/api/admin/news_history")
def admin_news_history(request: _SwarmRequest):
    _swarm_require_admin(request)
    try:
        with _NEWS_SWARM_HISTORY_FILE.open("r", encoding="utf-8") as handle:
            history = json.load(handle)
        return {"captures": history if isinstance(history, list) else []}
    except FileNotFoundError:
        return {"captures": []}
    except Exception as exc:
        raise _SwarmHTTPException(status_code=500, detail=f"History read error: {exc}")


# ---------------------------------------------------------------- Offline recorder archive import (v2.3.1)
# These routes deliberately reuse the existing admin token verifier.  Archive
# I/O and deduplication happen entirely server-side; the browser never parses
# or iterates telemetry rows.
_ARCHIVE_DB = APP_DIR / "worldview_archive.db"


def _archive_telemetry_columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(telemetry)")}


def _archive_rows(conn):
    columns = _archive_telemetry_columns(conn)
    needed = {"entity_id", "entity_type", "lat", "lon", "alt", "heading", "speed", "timestamp"}
    if not needed.issubset(columns):
        missing = ", ".join(sorted(needed - columns))
        raise ValueError(f"archive telemetry schema is missing: {missing}")
    return conn.execute(
        "SELECT entity_id, entity_type, lat, lon, alt, heading, speed, timestamp "
        "FROM telemetry ORDER BY timestamp"
    ).fetchall()


@app.post("/api/admin/import_archive")
def admin_import_archive(request: _SwarmRequest):
    _swarm_require_admin(request)
    if not _ARCHIVE_DB.exists():
        raise _SwarmHTTPException(status_code=404, detail="worldview_archive.db was not found")
    try:
        archive = _sqlite3.connect(str(_ARCHIVE_DB), timeout=20)
        rows = _archive_rows(archive)
        archive.close()
        if not rows:
            return {"imported": 0, "range": {"min": None, "max": None}}
        with _telemetry_lock:
            target = _sqlite3.connect(str(_TELEMETRY_DB), timeout=20)
            # Dedupe pre-existing rows FIRST: the table accumulated duplicate
            # (entity_id, entity_type, timestamp) groups before the unique
            # index existed (277,201 groups on 2026-08-15) — CREATE UNIQUE
            # INDEX fails on them. Keep the earliest rowid per identity.
            target.execute(
                "DELETE FROM telemetry WHERE rowid NOT IN "
                "(SELECT MIN(rowid) FROM telemetry GROUP BY entity_id, entity_type, timestamp)"
            )
            target.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_telemetry_identity "
                "ON telemetry(entity_id, entity_type, timestamp)"
            )
            before = target.total_changes
            target.executemany(
                "INSERT OR IGNORE INTO telemetry "
                "(entity_id, entity_type, lat, lon, alt, heading, speed, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?)", rows,
            )
            imported = target.total_changes - before
            target.commit()
            target.close()
        timestamps = [row[7] for row in rows if row[7]]
        return {"imported": imported, "range": {
            "min": min(timestamps) if timestamps else None,
            "max": max(timestamps) if timestamps else None,
        }}
    except _SwarmHTTPException:
        raise
    except Exception as exc:
        raise _SwarmHTTPException(status_code=500, detail=f"Archive import error: {exc}")


@app.get("/api/admin/export_archive")
def admin_export_archive(request: _SwarmRequest, format: str = "json"):
    _swarm_require_admin(request)
    if format.lower() != "json":
        raise _SwarmHTTPException(status_code=400, detail="Only format=json is supported")
    if not _ARCHIVE_DB.exists():
        raise _SwarmHTTPException(status_code=404, detail="worldview_archive.db was not found")
    try:
        archive = _sqlite3.connect(str(_ARCHIVE_DB), timeout=20)
        rows = _archive_rows(archive)
        archive.close()
        payload = [dict(zip(("entity_id", "entity_type", "lat", "lon", "alt", "heading", "speed", "timestamp"), row)) for row in rows]
        return Response(
            content=json.dumps(payload, ensure_ascii=False), media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=worldview_archive.json"},
        )
    except _SwarmHTTPException:
        raise
    except Exception as exc:
        raise _SwarmHTTPException(status_code=500, detail=f"Archive export error: {exc}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _load_last_flights()
    _init_telemetry_db()
    # background telemetry logger (daemon thread — dies with the server)
    _threading.Thread(target=_telemetry_loop, daemon=True).start()
    # background AISstream WebSocket listener (live global AIS — dormant
    # without an API key, falls back to MarineTraffic crawl + emergency set)
    _threading.Thread(target=_aisstream_listener, daemon=True).start()
    # background YouTube live-status checker (feeds the stream window with
    # PLAYING live videos, live-first, regional order preserved)
    _threading.Thread(target=_yt_live_checker, daemon=True).start()
    # background 24h retention/vacuum daemon (hourly)
    _threading.Thread(target=_auto_purge_db, daemon=True).start()
    # NO auto-open browser at boot (Boo 2026-08-13): the fallback chain
    # (os.startfile) opened the Windows Store when Chrome wasn't found.
    # The app starts windowless; Boo opens Chrome explicitly when he wants it.
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8767, log_config=None)
