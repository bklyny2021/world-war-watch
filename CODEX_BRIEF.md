# WorldView / World War Watch (WWW) — Codex brief template
# Copy this file, fill in the task, then: codex exec --sandbox workspace-write "$(cat brief.md)"
# Sarah (Hermes) writes the brief, Codex codes, Sarah verifies. Boo never talks to Codex directly.

## TASK
<one sentence: what to build/fix>

## FILES
- C:\Users\bklyn\worldview\server.py
- C:\Users\bklyn\worldview\static\index.html
- C:\Users\bklyn\worldview\static\cameras.js

## HARD RULES (from Boo — violations get rolled back)
1. NEVER delete anything. Backups: copy file -> file.v_working BEFORE editing. Never overwrite old backups.
2. Versioned releases go in C:\Users\bklyn\backup\WorldWarWatch_vN\ — never touch.
3. Server runs windowless (pythonw server.py, port 8767). Never restart Ollama/11434.
4. 100% FREE tools only. No paid APIs, no credit cards.
5. Screenshot-verify every UI change (playwright, chromium-1228, swiftshader).
6. Chrome only. No Edge.

## WORLDVIEW PITFALLS (all hit in production — do not re-break)
- ArcGISTiledElevationTerrainProvider.fromUrl() returns a PROMISE — never pass it into the Viewer constructor.
- Cesium keeps ONE action per event type — a second setInputAction(LEFT_CLICK) silently REPLACES the first. One unified handler dispatches to all layers.
- disableDepthTestDistance: Infinity on billboards = x-ray: far-side entities render through the globe (swarm illusion). Use finite values or omit.
- showGroundAtmosphere + dynamicAtmosphereLighting = gray haze at street level. Keep both false.
- PostProcessStage defaults to enabled:true — all stages stack at boot. Disable explicitly.
- Entity clustering hides planes — clustering.enabled = false, use scaleByDistance + drillPick.
- Billboard heading: rotation: toRadians(-heading), alignedAxis: Cartesian3.ZERO.
- Camera floor: minimumZoomDistance 2000 + camera.changed watchdog (height < 300 -> flyTo 2000m). Do NOT lower below 2000.
- Idle auto-rotation: gate on camera height > 2000km + !isUserInteracting + !trackedEntity.

## VERIFY BEFORE DONE
- node --check on any edited .js (run from the file's dir — MSYS /c/ paths false-positive otherwise)
- curl http://127.0.0.1:8767/ and confirm the change is served
- Report exactly what you changed and what you verified. Do NOT claim success without evidence.
