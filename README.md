# World War Watch (WWW)

> **⚠️ BETA** — this app is in active development. Data feeds, features, and the installer are being tested and improved continuously. Expect changes between versions.

**Real-time global tracking — flights, ships, fires, hotspots, live streams.**
A CesiumJS 3D globe + Python server. Everything on screen is REAL data from live feeds — nothing simulated, ever.

Current version: **v2.3.1 (BETA)** · Previous: v2.3 (snapshot in `backup\WorldWarWatch_v2_3\`)

---

## 1. What it shows

| Layer | Data source | What you see |
|---|---|---|
| Aircraft | OpenSky Network (ADS-B) | ~10,000+ live planes, military first, 3,000 km render cull |
| Ships | MarineTraffic (AIS tile crawl) | ~17,000 live vessels, 20,000 km render cull (effectively always visible) |
| Fires | NASA FIRMS (VIIRS) | High-confidence thermal detections, 4,000 km render cull |
| Hotspots | FIRMS clusters + conflict zones | Red haze zones, darker red dots, click → attack card → live streams |
| Cameras | NYC + NC DOT public cams | 50 km cull |
| Satellites | Celestrak TLE | Orbital paths, 1 Hz updates |
| Clouds / weather | Cloud texture + weather HUD | Visual layer |

**Golden-goose rule:** if you can't see it, don't spawn it. Entities are culled by distance + view frustum so the app stays at 55 FPS on the RTX 4060 Ti.

**HUD counters:** the aircraft counter counts ALL aircraft entities (layer toggle only). What renders on screen is a separate concern — the counter and the screen are decoupled.

---

## 2. Playback — recording & replay (SQL database)

The app records the real world into a **SQLite database** and can replay any recorded moment.

### Two recorders, one schema

| | App telemetry (built-in) | Offline recorder (`recorder.py`) |
|---|---|---|
| Database | `worldview.db` | `worldview_archive.db` |
| Runs | Only while the app is running | **Always — even when the app is closed** |
| Snapshot | Every 60 s | Every 60 s |
| Retention | 24 hours (auto-purged) | 30 days (auto-purged) |
| Contents | planes + ships + fires | planes + ships + fires |
| Schema | `telemetry(entity_id, entity_type, lat, lon, alt, heading, speed, timestamp)` | identical |

Both write the **same table schema**, so playback code works on either database unchanged.

### How the offline recorder works

```bash
pythonw recorder.py              # run forever, windowless (60 s cycle)
python recorder.py --once        # one snapshot cycle, then exit (testing)
python recorder.py --interval 30 # custom cycle (min 10 s)
```

- Fetches **live** OpenSky planes, MarineTraffic ships, and NASA FIRMS fires every cycle.
- Writes raw positions to `worldview_archive.db` (WAL mode — readers never block).
- Purges rows older than 30 days, hourly.
- Logs to `recorder.log`.
- **REAL DATA ONLY** — every row comes from a live feed. No simulated data, ever.

### The Update button (app start) — v2.3.1 (in build)

> Status: being implemented in v2.3.1 (Codex build in progress, 2026-08-15). This section is the spec.

When the app starts, an **Update** button appears. Clicking it:

1. Imports all rows from `worldview_archive.db` (the offline recording) into the app's `worldview.db` telemetry table.
2. Gives you a **download** of the past data (JSON export of the imported range).
3. The playback scrubber then has the full history — including the time the app was closed.

### Playback in the app

- **Playback timeline** (bottom): scrub through recorded time — 30M / 2H / 6H windows.
- `GET /api/playback?timestamp=...` — state vectors nearest to a moment (±60 s), optionally filtered by `entity_type`.
- `GET /api/playback/range` — earliest + latest timestamps + row count (drives the scrubber).
- The frontend interpolates between 60 s samples, so motion looks smooth.

---

## 3. The AI Agent Swarm (admin-only, v2.3.1)

An **admin-only** feature: release a swarm of 5 AI agents to capture live news about anything you describe.

### Unlock (owner only)

1. Click the hidden **key icon** in the HUD.
2. Enter the owner's admin PIN (stored in `data/admin_pin.json` on the owner's machine — **never shipped to users**).
3. Wrong PIN = denied. Only the owner can release the swarm.

**Users do not get a PIN.** If a user wants swarm access, they must **email the owner** to request one — the owner decides and issues it manually. (Owner's contact: add your email here before distributing.)

### Release

1. In the admin panel, type what you want captured — e.g. `Strait of Hormuz tanker incidents`.
2. Click **Release Swarm**.
3. The server spawns **5 parallel agent threads**, each querying a DIFFERENT free source:

| Agent | Source | Endpoint |
|---|---|---|
| 1 | Google News | `news.google.com/rss/search?q=...` |
| 2 | Bing News | `bing.com/news/search?q=...&format=rss` |
| 3 | Reddit | `reddit.com/search.json?q=...` |
| 4 | Hacker News | `hn.algolia.com/api/v1/search?query=...` |
| 5 | GDELT | `api.gdeltproject.org/api/v2/doc/doc?query=...` |

No API keys, no accounts, no cards — all free public sources.

### Results

- Each agent returns `{source, title, url, published, snippet}`.
- Results are **deduped by URL**, sorted newest first.
- Saved to `data/news_swarm_history.json` (appended with a timestamp — your capture history).
- The panel shows a spinning indicator while the swarm runs, then the results list (source, title, link, time) and a history view of past captures.
- **Lag audit:** all swarm work runs server-side in background threads. The frontend only polls status — nothing touches the render loop.

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/admin/verify` | POST | PIN check `{pin}` → ok/denied |
| `/api/admin/swarm` | POST | `{topic}` → starts swarm, returns `swarm_id` |
| `/api/admin/swarm_status` | GET | running / finished + results |
| `/api/admin/news_history` | GET | past captures |

---

## 4. Setup from scratch (complete guide)

Everything a new user needs to install and run World War Watch on their own PC.

### Step 1 — Install Python 3.11

1. Go to https://www.python.org/downloads/ and download **Python 3.11** (Windows installer).
2. Run the installer. **IMPORTANT:** tick **"Add python.exe to PATH"** at the bottom of the first screen, then click Install Now.
3. Verify: open a terminal (Win+R → `cmd`) and run:
   ```
   python --version
   ```
   You should see `Python 3.11.x`.

### Step 2 — Install the backend dependencies

Open a terminal in the app folder (`cd C:\Users\bklyn\worldview`) and run:

```
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn websockets httpx python-multipart
```

That installs everything the server needs (FastAPI 0.133, uvicorn 0.41, websockets 15, httpx 0.28, python-multipart). The offline recorder (`recorder.py`) needs nothing extra — it's pure Python standard library.

### Step 3 — Install Chrome (required)

The app runs in **Chrome only** (Edge is blocked by the firewall rule). If you don't have Chrome:
1. Go to https://www.google.com/chrome/ and download the installer.
2. Run it and install Chrome.
3. **Turn on hardware acceleration** (needed for smooth 3D): Chrome menu → Settings → System → **"Use graphics acceleration when available"** → ON → relaunch Chrome.

### Step 4 — Create a free Cesium Ion account (for 3D tiles)

The 3D globe needs a Cesium Ion token (free tier, email only — no credit card):
1. Go to https://ion.cesium.com/ and sign up (email + password).
2. After signing in, go to **Access Tokens** (left menu) → your default token.
3. Copy the token and save it to `data\ion_token.json` in the app folder:
   ```json
   {
     "ion_token": "PASTE_YOUR_TOKEN_HERE"
   }
   ```
4. The app uses the token for the 3D tileset. Without it, the app still runs (flat globe + OSM Buildings fallback).

### Step 5 — (Optional) OpenSky credentials for faster flight updates

OpenSky's free anonymous tier polls every 240s. With a free account it's every 22s:
1. Go to https://opensky-network.org/ and register (free).
2. Save your username/password to `data\opensky_creds.json`:
   ```json
   {
     "username": "YOUR_EMAIL",
     "password": "YOUR_PASSWORD"
   }
   ```

### Step 6 — Owner-only admin PIN (news swarm)

The admin news swarm is **owner-only** — users never get a PIN. The PIN lives in `data\admin_pin.json` on the owner's machine:
```json
{
  "pin": "YOUR_SECRET_PIN",
  "note": "Owner-only admin PIN for the news swarm."
}
```
The installer does **NOT** ship this file — without it, the swarm stays locked for everyone else. Users who want access must **email the owner** to request a PIN.

### Step 7 — Run the app

```
pythonw server.py
```

Then open **http://localhost:8767** in Chrome. (If port 8767 is taken on your machine, edit the `port=8767` line at the bottom of `server.py` to another port, e.g. 8768.)

- The server runs windowless (no console window).
- It does **NOT** auto-open a browser — open Chrome yourself.
- Data files live in `data/` (source mode) or next to the EXE (frozen mode).

### Step 8 — (Optional) Run the offline recorder

The recorder keeps logging planes/ships/fires even when the app is closed:

```
pythonw recorder.py              # runs forever, windowless, 60s snapshots
python recorder.py --once        # one snapshot cycle, then exit (testing)
python recorder.py --interval 30 # custom cycle (min 10s)
```

It writes to `worldview_archive.db` (30-day retention). When you start the app, click **⬇ UPDATE** in the HUD to import the recorded history into playback (asks for the admin PIN).

### Step 9 — (Optional) Build the EXE

Use the spec file (it bundles ALL uvicorn + anyio submodules — the plain
`--hidden-import` flags crash the frozen EXE with `ModuleNotFoundError:
uvicorn.loops.auto` / `anyio._backends`):

```
python -m PyInstaller --noconfirm --clean www_v2_3_1.spec
```

The EXE lands in `dist\WorldWarWatch_v2_3_1.exe`. Put `data\` (ion token, creds, admin pin) next to the EXE.

### Step 10 — (Optional) Build the installer

Requires Inno Setup 6 (free): https://jrsoftware.org/isdl.php

```
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\www_v2_3_1.iss
```

The installer (`WorldWarWatch_v2_3_1_Setup.exe`) installs to **Program Files\WorldWarWatch** with a desktop shortcut and uninstaller.

Every EXE version is saved as `WorldWarWatch_vN.exe` — **old EXEs are never deleted**.

---

## 5. File layout

```
C:\Users\bklyn\worldview\
├── server.py                 # FastAPI server (append-only for new features)
├── recorder.py               # OFFLINE recorder — runs even when app is closed
├── static\
│   ├── index.html            # the whole frontend (CesiumJS globe)
│   └── cameras.js            # camera layer
├── data\
│   ├── opensky_creds.json    # OpenSky credentials (optional)
│   ├── ion_token.json        # Cesium Ion token (photoreal 3D tiles)
│   ├── admin_pin.json        # admin PIN for the swarm (CHANGE IT)
│   ├── news_swarm_history.json  # swarm capture history
│   └── ... (aircraft DB, airports, labels, geojson)
├── worldview.db              # app telemetry (24 h retention)
├── worldview_archive.db      # offline recorder archive (30 d retention)
├── recorder.log              # recorder log
└── backup\                   # versioned snapshots (v2_0, v2_1, v2_2, v2_3...)
```

---

## 6. Backup rules (standing)

- **Before any edit:** `index.html → index.html.v_working`, `server.py → server.py.v_working`.
- **Versioned releases** go to `C:\Users\bklyn\backup\WorldWarWatch_vN\` — NEVER overwritten, timestamped.
- **NEVER delete anything we made without asking first.**
- Backups are byte-verified after every save.

---

## 7. Version history

| Version | What changed |
|---|---|
| v2.0 | Photoreal 3D tiles, ships layer, playback timeline |
| v2.1 | Live streams, hotspots, attack cards |
| v2.2 | Golden-goose culling, cloud texture, weather HUD, lazy-load |
| v2.3 | GPU integration (Chrome HW accel ON), FPS 2→55, freeze fix (ships off SampledPositionProperty), plane cull 3,000 km, real-speed Earth spin, search-bar spin gate, HUD counter decoupled from rendering |
| v2.3.1 | **AI agent swarm (admin-only news capture)** + **offline recorder + Update button** (playback of data recorded while the app was closed) |

---

## 8. Rules the agents work by

- **REAL DATA ONLY** — only display what the data states is currently real. Blocked feed → layer shows nothing. (Only exception: the clearly-marked 15-ship emergency fallback when every AIS tile fails.)
- **No accounts / no cards** — except Cesium Ion free tier (email only).
- **Lag audit** — every new feature gets checked: nothing added that can lag the app.
- **Codex** does the coding; Hermes verifies (self-reports aren't facts — every change is independently verified).
- **Chrome only**, never Edge.
- Dark theme, easy on the eyes.
