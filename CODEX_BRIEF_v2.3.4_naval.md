# World War Watch (WWW) — Codex brief: NAVAL FORCES layer

## TASK
Make every warship / naval asset on the map render as a distinct warship icon (not the generic green arrow), add a "Naval Forces" layer toggle, and show a WARSHIP badge in the ship card. Boo wants to see every type of asset in a naval fleet: carriers, destroyers, frigates, patrol vessels, amphibious ships, auxiliaries, coast guard cutters.

## FILES
- C:\Users\bklyn\worldview\server.py
- C:\Users\bklyn\worldview\static\index.html

## CURRENT STATE (verified 2026-08-14)
- Ships come from 3 sources: AISstream WebSocket (live, `source: "aisstream"`), MarineTraffic crawl (`source: "background-crawl"`), or 15-vessel fallback. Each ship dict has: mmsi, name, type (AIS class string like "Cargo"/"Tanker"/"Special Craft"/"Military"), lat, lon, sog, cog, heading, destination, eta, flag, length, width, source.
- `_SHIP_TYPE_MAP` in server.py maps AIS type codes to class strings; code 35 = "Military" (rarely transmitted by real warships).
- index.html `makeShipIconDataUrl()` draws ONE neon-green arrow used for ALL ships (`getShipIcon(type)` ignores type). `shipColor(type)` has a "Military" case (#ffc828) but it's unused by the billboard.
- Ship billboard: `image: getShipIcon(s.type)`, `rotation: toRadians(-s.cog)`, scale 0.7, NearFarScalar(1.0e3, 0.8, 2.5e6, 0.08), disableDepthTestDistance POSITIVE_INFINITY, distanceDisplayCondition 0–20,000,000.
- Layer toggles live in the top-right panel (`.layer-toggle` labels with `lt-dot` colors, e.g. `toggleShips` "Live Maritime (AIS)" with #38bdf8 dot). `layerState` object gates entity visibility.
- Ship card (`showShipCard`) shows name, MMSI · type · flag, speed/course/heading/destination/ETA/dimensions.
- Real naval assets ARE in the feed right now: USCGC ELM (USCG), HDMS KNUD RASMUSSEN (Danish Navy), ARC DEFENDER / ARC INTEGRITY (US Army), CCGS ATLANTIC EAGLE (Canadian CG) — but they render as green arrows like cargo ships.

## WHAT TO BUILD

### 1. server.py — warship detection
Add a `military` boolean (or `warship: true`) to every ship dict, detected by:
- AIS type == "Military" (code 35), OR
- Name prefix match (case-insensitive, word-boundary at start of name): USS, USNS, USCGC, USCG, HMS, HMAS, HMNZS, HMCS, INS, JS, JDS, ROKS, HDMS, HSwMS, KRI, KDB, RFA, RSS, TCG, ARC, ARM, BNS, PNS, ORP, ESPS, FNS, LÉ, NNS, SPS, TNS, UBS, VNS, CCGS, FGS, ITS, HTMS, RBNS, RSN, SAS, SLAF, SLNS, TCD, TSV, PLAN, WARSHIP, NAVY, MILITARY, plus "USMC" (Marines), OR
- Name contains "NAVY", "MILITARY", "WARSHIP", "MARINE", "COAST GUARD", "PATROL" (careful: "patrol" alone can be civilian — require it with a navy/cg prefix or flag), OR
- flag is US/GB/FR/... AND type == "Military".

Apply the same enrichment in ALL THREE paths: AISstream ShipStaticData/PositionReport updates (server.py `_aisstream_listener`), the MarineTraffic crawl row builder, and the fallback set (mark none of the fallbacks as military — they're civilian). Store `military` in the ship_cache dicts so it survives position updates (like `type` does).

### 2. index.html — warship icon + color
- Add `makeWarshipIconDataUrl()`: a distinct warship silhouette — dark gray hull with a gun turret / superstructure, red or amber accent, glowing outline so it reads at small scale. Points NORTH like the ship arrow (nose at top). 48x48 canvas, same style as the existing icons (glow + bright core).
- `getShipIcon(type, military)`: return the warship icon when `military` is true, else the green arrow.
- `shipColor(type, military)`: warships get a distinct color (e.g. #ff4444 red or #ffc828 amber) — used for the label fillColor.
- Ship label: warships get a red/amber label color instead of the default #7dd3fc so they pop.
- Ship card: when `military`, show a "⚔ WARSHIP" badge next to the name and color the MMSI/type line red. Also show flag prominently.

### 3. index.html — Naval Forces layer toggle
- Add a new `.layer-toggle` in the top-right panel: "Naval Forces" with a red dot (#ff4444), id `toggleNaval`, default CHECKED.
- Wire it into `layerState` (e.g. `layerState.naval`), the toggle listener (like `toggleShips`), and the ship visibility gate (`ent.show = layerState.ships && layerState.naval && ...` — naval ships hidden when EITHER toggle is off; civilian ships only gated by `layerState.ships`).
- HUD: optionally add a "NAVAL" count in the HUD stats row (red) counting military ships.

## HARD RULES (from Boo — violations get rolled back)
1. NEVER delete anything. Backups: copy file -> file.v_working BEFORE editing. Never overwrite old backups.
2. Versioned releases go in C:\Users\bklyn\backup\WorldWarWatch_vN\ — never touch.
3. Server runs windowless (pythonw server.py, port 8767). Never restart Ollama/11434.
4. 100% FREE tools only. No paid APIs, no credit cards.
5. Screenshot-verify every UI change (playwright, chromium-1228, swiftshader).
6. Chrome only. No Edge.

## WORLDVIEW PITFALLS (all hit in production — do not re-break)
- Cesium keeps ONE action per event type — a second setInputAction(LEFT_CLICK) silently REPLACES the first. One unified handler dispatches to all layers.
- disableDepthTestDistance: Infinity on billboards = x-ray: far-side entities render through the globe. Ships currently use POSITIVE_INFINITY deliberately (spec: ships stay visible everywhere) — keep it for ships.
- Entity clustering hides entities — clustering.enabled = false, use scaleByDistance + drillPick.
- Billboard heading: rotation: toRadians(-heading), alignedAxis: Cartesian3.ZERO.
- Camera floor: minimumZoomDistance 1000, enableCollisionDetection FALSE (crash), watchdog setView at <300m. Do NOT change camera code.
- requestRenderMode must stay false. tileCacheSize stays default. maximumScreenSpaceError 16 on the photoreal tileset. Do NOT touch these.
- Ships are created in CHUNKS of 500 per frame (perf) — do not make ship creation synchronous.
- The ship occluder (updateShipOcclusion) sets ent.show every 250ms — your naval gate must be compatible: it already reads layerState.ships, extend it to also read layerState.naval.
- Do NOT restart the server yourself. Sarah (Hermes) restarts and verifies after you commit.
- Do NOT change the fallback ship set's positions/names — only add the military flag (false) if you touch it at all.

## VERIFY BEFORE DONE
- node --check on any edited .js (run from the file's dir — MSYS /c/ paths false-positive otherwise)
- python -m py_compile server.py
- git add + git commit with a clear message (e.g. "v2.3.4: Naval Forces layer — warship icons, detection, toggle")
- Report exactly what you changed and what you verified. Do NOT claim success without evidence.
