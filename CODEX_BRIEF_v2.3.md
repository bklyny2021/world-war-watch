# CODEX TASK — WorldView v2.3: Kill "Page Unresponsive" freezes + GPU perf (Boo-approved Gemini spec)

## TASK
Update static/index.html (and server.py if truly needed) to eliminate main-thread freezing and Chrome "Page Unresponsive" dialogs when zooming in. This is the Gemini spec Boo approved — implement it, but read the CORRECTIONS below first; several spec items are already done, and one is a behavior trap.

## FILES
- C:\Users\bklyn\worldview\static\index.html  (main target)
- C:\Users\bklyn\worldview\static\cameras.js  (CCTV layer lives here)
- C:\Users\bklyn\worldview\server.py          (only if a data-side change is genuinely needed — likely NOT)

## THE GEMINI SPEC (6 items)

### 1. Backup protocol — ALREADY DONE by Sarah. Do NOT re-backup. Just edit.

### 2. GPU WebGL context (index.html ~line 680 Viewer constructor)
- contextOptions.webgl: alpha:false, depth:true, stencil:false (currently true — change it), antialias:true, premultipliedAlpha:true, preserveDrawingBuffer:false, failIfMajorPerformanceCaveat:false, powerPreference:'high-performance'
- targetFrameRate: 60, requestRenderMode: true, maximumRenderTimeChange: Infinity
- viewer.scene.globe.maximumScreenSpaceError = 2.0 (ALREADY 2 at line ~738 — keep)
- viewer.scene.globe.tileCacheSize = 1000

**CORRECTION / TRAP (Sarah's production knowledge):**
- requestRenderMode:true is a BEHAVIOR CHANGE. The app has continuous per-frame animation (plane interpolation in viewer.clock.onTick, traffic particles, idle globe spin in postUpdate, WWW bot camera moves). Under requestRenderMode these only continue if something requests a render each frame. The onTick position writes and camera moves DO request renders (self-sustaining), but verify after the change that: planes still move, idle spin still spins, traffic particles still move. If idle spin dies, add a `viewer.scene.requestRender()` call inside the onTick animation block. Do NOT ship a frozen globe.
- debugShowFramesPerSecond: true currently — keep it (Boo likes the FPS readout).
- Do NOT remove the existing camera crash fix: enableCollisionDetection + the postUpdate watchdog (height<300 -> flyTo 2000m). It is at ~line 986-1010. Keep BOTH intact.

### 3. Convert heavy layers to BillboardCollection (Primitive API)
Convert CCTV cameras and ship markers to Cesium.BillboardCollection. Fires are ALREADY a PointPrimitiveCollection (firePrimitives) — leave them.

**CORRECTIONS / TRAPS:**
- **cameras.js**: entities are created in addCamera() with pick-tags ent._worldviewCamId / _worldviewCamSrc, heightReference CLAMP_TO_GROUND, disableDepthTestDistance:1000, distanceDisplayCondition 50km, scaleByDistance. index.html's handleWorldViewClick (line ~1615) picks via drillPick and checks entity._worldviewCamId. If you convert to BillboardCollection, set each billboard's `.id` to an object carrying the cam data + _worldviewCamId tag, and make sure drillPick still returns it (it does — primitive billboards return their .id). Update handleWorldViewClick if the pick shape changes. Clicking a camera MUST still open the live snapshot popup.
- **Ships** (index.html ~line 2370): currently entity billboards with SampledPositionProperty per-frame interpolation between polls. 15K+ ships interpolated per frame is a suspected freeze source. Convert to BillboardCollection: positions updated ONCE per poll batch (drop per-frame interpolation — ships jump every poll tick instead; acceptable for perf). Ship clicks must still work (openShipCard via _worldviewShip tag on billboard.id). Preserve rotation (-cog), scaleByDistance, disableDepthTestDistance POSITIVE_INFINITY, distanceDisplayCondition 2.5M, labels? — labels in a collection: use a LabelCollection paired with it, or drop ship labels beyond 300km (already culled). Keep it simple and performant.
- Planes stay ENTITIES (they need per-frame interpolation, trails, tracking, labels). Do NOT convert planes.

### 4. Time-slice spawn loops (200/frame chunks)
- Planes: ALREADY time-sliced via creationQueue (drained ~few hundred/frame in onTick). Keep.
- Ships: add the batchUpdateEntities(dataArray, updateFn, chunkSize=200) pattern for the ship add/update loop so a 15K array doesn't block the main thread in one synchronous burst.
- Cameras: already chunked ("chunked, sequential" in cameras.js) — verify, keep.

### 5. Distance culling — ALREADY DONE across all layers (planes 3.0M, ships 2.5M, cameras 50km, fires 4.0M). Verify each exists; add only if missing.

### 6. Verification
- node --check any edited .js (run from the file's dir; MSYS /c/ paths false-positive otherwise — the lint error "Cannot find module C:\c\..." is a TOOL BUG, not your bug).
- curl http://127.0.0.1:8767/static/index.html and confirm your change is served.
- Do NOT restart the server, do NOT kill/start any processes, do NOT touch Ollama/11434, do NOT touch anything outside C:\Users\bklyn\worldview. Sarah handles restart + browser verification after you finish.
- Commit your work: git add -A && git commit -m "v2.3: requestRenderMode + BillboardCollection (cams/ships) + ship time-slicing + tileCache" (git identity already configured).
- Report: exactly what you changed (file:line), what you verified, and any spec item you deviated from and WHY.

## HARD RULES (from Boo — violations get rolled back)
1. NEVER delete anything. Never touch the backup folders or .v_working files. Never touch *.v1_* / *.v2_* files.
2. 100% FREE tools only.
3. Do NOT break the camera crash fix (collision detection + watchdog) added in v2.2.
4. Do NOT break click-to-open for cameras/ships/fires/satellites/planes.
5. Keep the app booting instantly (lazy photoreal tiles below 500km stays as-is).

## CONTEXT (what's already in the file)
- Viewer at line ~680 with contextOptions ALREADY having powerPreference high-performance (extend it, don't duplicate the key).
- maximumScreenSpaceError=2 already set (~line 738).
- Photoreal tiles: lazy-loaded when camera < 500km (loadGoogleTilesLazy, ~line 842). DON'T change this flow.
- Idle spin gated on cameraHeight > IDLE_SPIN_MIN_ALT && !isUserInteracting && !trackedEntity (onTick, ~line 1524).
- creationQueue for planes (~line 1420) — keep.
- Ship layer: shipDataSource entities, 15K+ from AISstream, per-poll sync (~line 2360-2450).
- Camera layer: cameras.js addCamera() ~line 181.
- Fires: firePrimitives PointPrimitiveCollection (~line 3072).
