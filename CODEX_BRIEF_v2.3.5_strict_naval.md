# World War Watch (WWW) — Codex brief: STRICT warship detection + battleship icon

## TASK
1. Fix false positives in warship detection — ONLY real warships/naval vessels may show as warships. Civilian ships must never be flagged.
2. Make the warship icon look like a proper battleship (prominent gun turret).

## FILES
- C:\Users\bklyn\worldview\server.py
- C:\Users\bklyn\worldview\static\index.html

## CURRENT STATE (verified 2026-08-14, commit a5a3af9)
`_is_military_ship(name, ship_type, flag)` in server.py currently returns True if:
- type == "Military", OR
- name starts with a naval prefix (USS, HMS, USCGC, HDMS, ARC, CCGS, etc.), OR
- name CONTAINS any of: "NAVY", "MILITARY", "WARSHIP", "MARINE", "COAST GUARD", OR
- name contains "PATROL" AND (prefix match OR flag in _NAVAL_PATROL_FLAGS)

### FALSE POSITIVES (confirmed in live feed — these are CIVILIAN, must NOT be warships):
- AMERICAN MARINER (Cargo, US) — caught by "MARINE" substring
- CASCADE MARINER (Wing In Ground, US) — caught by "MARINE"
- WESTERN MARINER (Special Craft, US) — caught by "MARINE"
- DELTA MARINER (Tanker, LR) — caught by "MARINE"
- PACIFIC MARINER (Cargo, HK) — caught by "MARINE"
- SKANDI MARINER (Special Craft, CA) — caught by "MARINE"
- MARINE HOPE (Tanker, MH) — caught by "MARINE"
- ULTRAMARINE (Passenger, MH) — caught by "MARINE"

Root cause: the substring check `"MARINE" in vessel_name` matches "MARINER" (a common civilian ship-name suffix) and "MARINE HOPE" (civilian tanker). "MARINE" as a bare word is NOT a reliable warship signal — US Marine Corps vessels use the USMC prefix (already in the prefix list).

### REAL WARSHIPS (must STAY detected):
- USCGC ELM (Special Craft, US) — US Coast Guard cutter
- HDMS KNUD RASMUSSEN (Special Craft, DK) — Danish Navy
- ARC DEFENDER (Cargo, US) — US Army vessel
- ARC INTEGRITY (Cargo, US) — US Army vessel
- CCGS ATLANTIC EAGLE (Special Craft, CA) — Canadian Coast Guard

## WHAT TO CHANGE

### 1. server.py — `_is_military_ship` strictness
- REMOVE "MARINE" from the substring terms list. Keep only: "NAVY", "MILITARY", "WARSHIP", "COAST GUARD".
- TIGHTEN the patrol rule: drop the `vessel_flag in _NAVAL_PATROL_FLAGS` escape hatch — a name containing "PATROL" is only military if it ALSO matches a naval name prefix (e.g. "USCGC ... PATROL"). Civilian patrol boats (harbor patrol, fisheries patrol) must not be flagged.
- Keep: type == "Military" and the naval-prefix match (those are solid).
- Do NOT touch the prefix list itself (USS, HMS, USCGC, HDMS, ARC, CCGS, etc. are all correct).

### 2. static/index.html — battleship icon with gun turret
`makeWarshipIconDataUrl()` currently draws a red hull with a small turret block. Redesign it so it reads as a BATTLESHIP at small scale:
- Dark gray/charcoal hull silhouette (pointed bow at top, North-up like the ship arrow)
- TWO prominent forward gun turrets (twin-barrel look) in RED (#ff4444) with red glow — the red is the warship signature color
- A bridge/superstructure block amidships
- Keep the red glow outline so it pops against the ocean
- 48x48 canvas, same style as the other icons (glow + bright core)
- The icon must still rotate with the ship's course (rotation: toRadians(-cog) is applied by the caller — keep the nose at top)

## HARD RULES (from Boo — violations get rolled back)
1. NEVER delete anything. Backups: copy file -> file.v_working BEFORE editing. Never overwrite old backups.
2. Versioned releases go in C:\Users\bklyn\backup\WorldWarWatch_vN\ — never touch.
3. Server runs windowless (pythonw server.py, port 8767). Never restart Ollama/11434.
4. 100% FREE tools only. No paid APIs, no credit cards.
5. Screenshot-verify every UI change (playwright, chromium-1228, swiftshader).
6. Chrome only. No Edge.

## WORLDVIEW PITFALLS (all hit in production — do not re-break)
- Cesium keeps ONE action per event type — a second setInputAction(LEFT_CLICK) silently REPLACES the first. One unified handler dispatches to all layers.
- disableDepthTestDistance: Infinity on billboards = x-ray. Ships use POSITIVE_INFINITY deliberately — keep it.
- Entity clustering hides entities — clustering.enabled = false.
- Billboard heading: rotation: toRadians(-heading), alignedAxis: Cartesian3.ZERO.
- Camera floor: minimumZoomDistance 1000, enableCollisionDetection FALSE (crash), watchdog setView at <300m. Do NOT change camera code.
- requestRenderMode must stay false. tileCacheSize stays default. maximumScreenSpaceError 16 on the photoreal tileset. Do NOT touch these.
- Ships are created in CHUNKS of 500 per frame — do not make ship creation synchronous.
- Do NOT restart the server yourself. Sarah (Hermes) restarts and verifies after you commit.
- Do NOT change the fallback ship set's positions/names.

## VERIFY BEFORE DONE
- python -m py_compile server.py
- node --check on any edited .js (run from the file's dir — MSYS /c/ paths false-positive otherwise)
- Test the detection function with these cases (all must pass):
  - USCGC ELM / Special Craft / US -> True
  - HDMS KNUD RASMUSSEN / Special Craft / DK -> True
  - ARC DEFENDER / Cargo / US -> True
  - CCGS ATLANTIC EAGLE / Special Craft / CA -> True
  - AMERICAN MARINER / Cargo / US -> False
  - MARINE HOPE / Tanker / MH -> False
  - ULTRAMARINE / Passenger / MH -> False
  - EVER GIVEN / Cargo / PA -> False
  - NYC FERRY / Passenger / US -> False
- git add + git commit with a clear message (e.g. "v2.3.5: strict warship detection (no MARINER false positives) + battleship turret icon")
- Report exactly what you changed and what you verified. Do NOT claim success without evidence.
