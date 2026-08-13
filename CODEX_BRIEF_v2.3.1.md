# CODEX TASK — WorldView v2.3.1: Boo's 3 new features

## TASK
Three user-requested features on top of the current v2.3 codebase (which is committed and WORKING — do not regress it):

### FEATURE 1 — Destination in info tabs (flights AND ships)
- Flight sidebar (renderSidebar, ~line 1360+): show Destination (and Origin if available) — the route data already comes from `/api/routes?icaos=` (see selectFlight ~line 1357). Add dest/origin rows to the flight info card.
- Ship info card (showShipCard, ~line 2700+): ships from AISstream have destination fields (s.destination / s.dest / s.eta) — check what server.py exposes in /api/ships (search ship_cache / AIS message decode in server.py) and display Destination in the card if present.

### FEATURE 2 — "EARTH VIEW" button (integrated into an existing button — NO new screen space)
- Boo is out of screen space: integrate the new view toggle INTO an existing button (his words: "a button thats intergrated into another button"). Pick a sensible existing control (e.g. the Reset/Home button #btnReset, or the mode toggle) and make it a two-part or toggle button.
- Behavior: switches the camera to a FLAT, 2D-looking horizon view — "how it looks to someone on earth" — nearly level, looking horizontally at the globe. Name it "EARTH VIEW" (that is the view's name).
- Cesium approach: flyTo with pitch ~ -85 to -89 degrees (looking almost horizontally at the horizon) at a low-ish altitude, with heading 0 and roll 0. Ensure the idle spin does NOT fight it (it only spins above 2000km — below that we're fine).
- Toggle back: clicking again returns to the previous 3D view (remember the pre-EARTH camera and restore it, like satPrevCamera pattern at ~line 1925).

### FEATURE 3 — Planes must always fly LEVEL (heading fix when screen angle changes)
- Boo: "when i change my screen angle some planes may go sideways or backwards... make sure all planes level out and fly correctly."
- Root cause: billboards use rotation: toRadians(-heading) with alignedAxis ZERO — screen-aligned, so at oblique camera angles a plane heading north can render "sideways" (screen-aligned rotation ignores the camera's roll/tilt).
- Fix approach: keep rotation: toRadians(-heading), alignedAxis: Cartesian3.ZERO (this is the FR24-style screen-up alignment and is CORRECT at normal angles), BUT ensure roll stays zeroed so the camera never tilts (the postUpdate roll-zeroer at ~line 1560 handles this — verify it still works under requestRenderMode and with the new Earth View).
- ALSO: check the plane's heading sign convention — if planes appear to fly backwards, the rotation sign is inverted for some headings; -heading is correct for icons pointing North (verified earlier). If a plane's icon points right (East) when it should point up, the PNG itself may point East — verify against plane.png orientation and adjust the PNG or the sign, and document which.
- Do NOT over-engineer: if it's the camera roll causing it, the roll-zeroer is the fix. If it's the icon, rotate the icon file. Test both hypotheses by reading the current code.

## HARD RULES
1. NEVER delete anything. Never touch backup/ or *.v_working or *.v1_*/*.v2_* files.
2. Do NOT break: the camera crash fix (enableCollisionDetection + postUpdate watchdog at ~line 986-1030 — watchdog now uses setView), requestRenderMode heartbeat (~line 1561), BillboardCollection layers (cams/ships), lazy photoreal tiles, click-to-open for cams/ships/fires/sats/planes.
3. 100% FREE tools. Chrome only. No server restarts, no process kills, no touching Ollama.
4. Node --check any edited .js from the file's dir (MSYS false-positive otherwise).
5. Commit when done: git add -A && git commit -m "v2.3.1: Earth View button + dest in info tabs + plane leveling"
6. Report exactly what you changed (file:line), what you verified, and any deviations.

## CONTEXT (verified state of the codebase right now)
- viewer at ~line 680 (requestRenderMode: true, targetFrameRate 60, tileCacheSize 1000)
- Camera watchdog: postUpdate, setView to 2000m when height < 300 (~line 986-1030)
- Idle spin: onTick, only above IDLE_SPIN_MIN_ALT (2000km)
- Ships: BillboardCollection (shipBillboards + shipLabels), shipEntities Map mmsi -> {billboard, label, data} (~line 2300+)
- Cameras: BillboardCollection in cameras.js addCamera() (~line 180)
- Click handler: handleWorldViewClick (~line 1615) — drillPick, tags _worldviewCamId / _worldviewShip / _worldviewSatId / _worldviewHotspot
- Server: /api/flights, /api/ships, /api/routes, /api/cameras, /api/fires — all in server.py
- Git: repo at C:\Users\bklyn\worldview, clean tree, identity configured
