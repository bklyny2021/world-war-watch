# WORLDVIEW v2.0 — RESUME FILE (saved 2026-08-13 ~01:00)
# Read this FIRST next session. Everything needed to resume the rebuild.

## WHERE WE ARE
- v2.0 rebuild in progress. 3 agents dispatched (backend/frontend/test harness).
- Baseline backups LOCKED: server.py.v1_0 + static/index.html.v1_0 (never overwrite).
- 12 tasks in todo DB (ids 133-144) + Mission Control TASKS tab (same DB).

## WHAT LANDED (verified on disk)
- server.py (75,206 bytes, modified 20:57): Agent 1 backend DONE —
  /api/satellite_snapshot CORS proxy present (grep count 2),
  telemetry 24h retention purge confirmed running ("telemetry purge done (24h retention)"),
  WAL + incremental vacuum confirmed ("auto_vacuum now = 2").
- AGENT_BOARD.md: full coordination file with all contracts + pitfalls + rules.

## WHAT'S NOT DONE (next session's work)
- static/index.html (124,613 bytes, 20:18) — Agent 2 frontend NOT landed yet:
  WebGL high-performance, depthTestAgainstTerrain, FPS readout, glassmorphic HUD,
  canvas green ship icons, depth settings (ships INF / fires 0), camera BillboardCollection
  batching + DistanceDisplayCondition, trail cap 30, recon zoom, photoreal tiles verify.
- Test harness (Agent 3) — not finished.
- Verification (task 143): syntax, restart, headless test, screenshot, NO-TINT check.
- EXE v1 build (task 144): WorldView_v1.exe — NEW RULE: save each EXE version, delete none.

## HARD RULES (Boo, 2026-08-13 — MANDATORY)
1. NEVER delete anything we made without ASKING first. Tell Boo what I'm doing before doing it.
2. Backups: NEVER overwrite — numbered/timestamped copy per version (.v1_0, .v1_1, ...).
3. EXE builds: save each as WorldView_vN.exe, NEVER delete old .exe versions.
4. After 'stop': do nothing until Boo explicitly says proceed.
5. NO COLOR TINTS / NO FILTERS unless Boo toggles them himself (the "smurf world" lesson:
   Cesium 1.119 PostProcessStage ignores enabled:false in constructor — force-disable after creation).
6. Screenshot-verify every UI change; Boo's eyes are the final test.
7. Chrome only, never Edge. Windowless procs (pythonw). 100% free tools.

## PITFALLS (hard-won, do not repeat)
- Cesium 1.119 PostProcessStage shaders: ES3 syntax (in/out, texture()), Cesium prepends
  out_FragColor, uniform is colorTexture. Declaring varying/gl_FragColor = compile crash.
- globe.show=true as depth backdrop + depthTestAgainstTerrain = tileset invisible (all blue).
- 30K entities at boot = main-thread freeze ("quit or wait"). Batch/chunk/LOD.
- Stale server on 8767 serves old code — check PID before trusting tests.
- MSYS path mangling: node --check with absolute /c/ paths fails; run from dir with relative path.
- Timed-out bash heredocs orphan python children holding SQLite locks.

## SERVER STATE
- Port 8767. Server running (pythonw or python server.py background).
- worldview.db: WAL, auto_vacuum INCREMENTAL, 24h retention purge hourly.
- ion_token.json in data/ (Boo's Cesium Ion token — photoreal tiles).
- opensky_creds.json next to EXE.

## NEXT SESSION FIRST ACTIONS
1. Read this file + AGENT_BOARD.md.
2. Check if delegation batch (deleg_722be094 / deleg_dead7c43) finished — read their summaries
   from C:\Users\bklyn\AppData\Local\hermes\cache\delegation\ if so.
3. Resume: Agent 2 frontend work → verify → EXE v1 → show Boo.
