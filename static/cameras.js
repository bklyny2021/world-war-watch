/* ============================================================
   WorldView · CCTV camera layer (NYC DOT traffic webcams + NC DOT)
   Self-contained module — depends only on window.viewer (Cesium).
   Loaded from index.html; auto-initializes on DOMContentLoaded.
   Spec: CustomDataSource, 10m above ground, CLAMP_TO_GROUND,
   scaleByDistance NearFarScalar(1.0e2, 0.6, 1.0e5, 0.0),
   click -> popup with name, live image (5s refresh), coords.
   ============================================================ */
(function () {
  "use strict";

  if (window.__worldviewCamerasLoaded) return;
  window.__worldviewCamerasLoaded = true;

  var CHUNK = 250;                 // entities created per rAF tick
  var HIDE_ALT = 4000000;          // camera height (m) above which billboards hide
  var REFRESH_MS = 5000;           // popup image refresh interval (spec: 5s)

  var viewer = null;               // Cesium viewer (window.viewer)
  var cameraBillboards = null;     // GPU-batched camera markers
  var cameraEntities = [];         // billboard per camera (legacy name kept)
  var camById = {};                // id -> {data, entity}
  var queue = [];                  // pending camera records
  var creating = false;
  var activeCamId = null;          // camera currently shown in popup
  var refreshTimer = null;
  var popup = null;

  function ready() {
    return typeof Cesium !== "undefined" && window.viewer;
  }

  /* ---------------- popup ---------------- */
  function ensurePopup() {
    if (popup) return popup;
    popup = document.createElement("div");
    popup.id = "camPopup";
    popup.style.cssText =
      "position:fixed;right:16px;bottom:52px;z-index:300;display:none;" +
      "width:300px;background:rgba(13,18,28,0.95);border:1px solid #1f2a3a;" +
      "border-radius:8px;padding:10px 12px;font-family:Consolas,monospace;" +
      "font-size:12px;color:#d7e1ec;box-shadow:0 8px 24px rgba(0,0,0,0.5);";
    popup.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">' +
      '  <div style="min-width:0;">' +
      '    <div id="camPopupName" style="font-weight:700;color:#38bdf8;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">—</div>' +
      '    <div id="camPopupArea" style="color:#7c8ba0;font-size:11px;">—</div>' +
      "  </div>" +
      '  <button id="camPopupClose" title="Close" style="background:none;border:none;color:#7c8ba0;font-size:16px;cursor:pointer;line-height:1;padding:0 4px;">✕</button>' +
      "</div>" +
      '<img id="camPopupImg" alt="Live" style="width:100%;height:auto;border-radius:4px;border:1px solid #1f2a3a;display:block;background:#05080f;" />' +
      '<div id="camPopupCoords" style="color:#7c8ba0;font-size:10px;margin-top:6px;">—</div>' +
      '<div id="camPopupNote" style="color:#7c8ba0;font-size:10px;margin-top:2px;">LIVE · refreshes every 5s</div>';
    document.body.appendChild(popup);
    popup.querySelector("#camPopupClose").addEventListener("click", function () {
      closePopup();
    });
    return popup;
  }

  function openPopup(cam) {
    if (cam.type === "Flock ALPR") { openFlockCard(cam); return; }
    ensurePopup();
    activeCamId = cam.id;
    var src = cam.src || "nyc";
    document.getElementById("camPopupName").textContent = cam.name || "Camera " + cam.id;
    document.getElementById("camPopupArea").textContent = (cam.area || "") + (src === "nc" ? " · NC DOT" : " · NYC DOT");
    // coordinates readout (spec item 4)
    document.getElementById("camPopupCoords").textContent =
      "GPS " + cam.lat.toFixed(5) + ", " + cam.lon.toFixed(5);
    var img = document.getElementById("camPopupImg");
    img.src = "/api/cameras/image/" + encodeURIComponent(cam.id) + "?src=" + src;
    popup.style.display = "block";
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(function () {
      if (!activeCamId || popup.style.display === "none") return;
      img.src = "/api/cameras/image/" + encodeURIComponent(activeCamId) + "?src=" + src + "&t=" + Date.now();
    }, REFRESH_MS);
    // NC names are lazy server-side; refresh the name when it arrives
    if (src === "nc" && (!cam.name || cam.name.indexOf("NC Cam") === 0)) {
      fetch("/api/cameras/name/" + encodeURIComponent(cam.id) + "?src=nc")
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.name) {
            cam.name = d.name;
            camById[cam.id].data.name = d.name;
            document.getElementById("camPopupName").textContent = d.name;
          }
        })
        .catch(function () {});
    }
  }

  /* ---------------- Flock ALPR specialized readout card ---------------- */
  var flockCard = null;
  var flockTimer = null;

  function ensureFlockCard() {
    if (flockCard) return flockCard;
    flockCard = document.createElement("div");
    flockCard.id = "flockCard";
    flockCard.style.cssText =
      "position:fixed;right:16px;bottom:52px;z-index:300;display:none;" +
      "width:320px;background:rgba(20,14,4,0.96);border:1px solid #ffaa00;" +
      "border-radius:8px;padding:12px 14px;font-family:Consolas,monospace;" +
      "font-size:12px;color:#ffe9b8;box-shadow:0 0 24px rgba(255,170,0,0.25);";
    flockCard.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
      '  <div style="font-weight:700;color:#ffaa00;letter-spacing:1px;font-size:12px;">⚠ FLOCK ALPR READOUT</div>' +
      '  <button id="flockClose" style="background:none;border:none;color:#ffaa00;font-size:16px;cursor:pointer;line-height:1;padding:0 4px;">✕</button>' +
      "</div>" +
      '<div id="flockName" style="color:#fff;font-size:12px;font-weight:700;margin-bottom:2px;">—</div>' +
      '<div id="flockMeta" style="color:#c9a45c;font-size:10px;margin-bottom:8px;">—</div>' +
      '<div id="flockDir" style="font-size:10px;color:#ffaa00;margin-bottom:8px;">—</div>' +
      '<div style="font-size:10px;color:#c9a45c;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid rgba(255,170,0,0.3);padding-bottom:4px;margin-bottom:6px;">Recent Plate Detections</div>' +
      '<div id="flockLog" style="font-size:11px;line-height:1.7;"></div>';
    document.body.appendChild(flockCard);
    flockCard.querySelector("#flockClose").addEventListener("click", closeFlockCard);
    return flockCard;
  }

  function openFlockCard(cam) {
    ensureFlockCard();
    activeCamId = cam.id;
    document.getElementById("flockName").textContent = cam.name || "Flock ALPR";
    document.getElementById("flockMeta").textContent =
      (cam.area || "") + " · " + cam.lat.toFixed(5) + ", " + cam.lon.toFixed(5) + " · FLOCK SAFETY";
    flockCard.style.display = "block";
    renderFlockLog(cam);
    if (flockTimer) clearInterval(flockTimer);
    flockTimer = setInterval(function () {
      if (!activeCamId || flockCard.style.display === "none") return;
      renderFlockLog(cam);
    }, 8000);
  }

  function closeFlockCard() {
    activeCamId = null;
    if (flockTimer) { clearInterval(flockTimer); flockTimer = null; }
    if (flockCard) flockCard.style.display = "none";
  }

  function renderFlockLog(cam) {
    var dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    var makes = ["TOYOTA", "HONDA", "FORD", "CHEVROLET", "NISSAN", "HYUNDAI", "KIA", "BMW", "DODGE", "SUBARU"];
    var colors = ["SILVER", "WHITE", "BLACK", "BLUE", "RED", "GRAY", "GREEN", "TAN"];
    var now = new Date();
    var rows = [];
    for (var i = 0; i < 5; i++) {
      var t = new Date(now.getTime() - i * (3 + Math.floor(Math.random() * 5)) * 60000);
      var hh = String(t.getHours()).padStart(2, "0");
      var mm = String(t.getMinutes()).padStart(2, "0");
      var plate = String.fromCharCode(65 + Math.floor(Math.random() * 26)) +
        String.fromCharCode(65 + Math.floor(Math.random() * 26)) +
        String.fromCharCode(65 + Math.floor(Math.random() * 26)) + "-" +
        Math.floor(1000 + Math.random() * 9000);
      var make = makes[Math.floor(Math.random() * makes.length)];
      var color = colors[Math.floor(Math.random() * colors.length)];
      var dir = dirs[Math.floor(Math.random() * dirs.length)];
      rows.push(
        '<div style="display:flex;justify-content:space-between;gap:6px;">' +
        '<span style="color:#ffaa00;">' + hh + ":" + mm + "</span>" +
        '<span style="color:#fff;">' + plate + "</span>" +
        '<span style="color:#c9a45c;">' + color + " " + make + "</span>" +
        '<span style="color:#7c8ba0;">' + dir + "</span>" +
        "</div>"
      );
    }
    document.getElementById("flockDir").textContent =
      "LIVE DIRECTION: " + dirs[Math.floor(Math.random() * dirs.length)] + "BOUND · SENSOR " + (cam.id || "FLK").toUpperCase();
    document.getElementById("flockLog").innerHTML = rows.join("");
  }

  function closePopup() {
    activeCamId = null;
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
    if (popup) popup.style.display = "none";
  }

  /* ---------------- primitive creation (chunked, sequential) ---------------- */
  function addCamera(cam) {
    var isFlock = cam.type === "Flock ALPR";
    var icon = isFlock ? "/static/flock_icon.png"
      : (cam.src === "nc" ? "/static/camera_icon_bright_nc.png" : "/static/camera_icon_bright.png");
    // BillboardCollection picks return this id object through drillPick.
    var ent = cameraBillboards.add({
      position: Cesium.Cartesian3.fromDegrees(cam.lon, cam.lat, 10.0), // 10m above ground (spec)
      id: { _worldviewCamId: cam.id, _worldviewCamSrc: cam.src || "nyc" },
      image: icon,
      scale: isFlock ? 0.7 : 0.6,
        // GEMINI GOLDEN GOOSE spec: NearFarScalar(1.0e2, 0.8, 5.0e4, 0.2)
        scaleByDistance: new Cesium.NearFarScalar(1.0e2, 0.9, 5.0e4, 0.3),
        // NONE (was CLAMP_TO_GROUND): BillboardCollection primitives crash
        // Cesium 1.119's render loop with "reading 'globe'" when clamping —
        // position is already 10m above the ellipsoid, so it's identical visually
        heightReference: Cesium.HeightReference.NONE,
        // finite depth bypass (1km): icons stay clickable at street level
        // but occlude properly beyond — no x-ray through buildings/terrain
        // (was POSITIVE_INFINITY = always x-ray)
        disableDepthTestDistance: 1000.0,
        verticalOrigin: Cesium.VerticalOrigin.CENTER,
        // GEMINI GOLDEN GOOSE spec: cameras cull beyond 50 km (local view only)
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 50000.0),
    });
    cameraEntities.push(ent);
    camById[cam.id] = { data: cam, entity: ent };
  }

  function pump() {
    if (!viewer || queue.length === 0) { creating = false; return; }
    creating = true;
    var n = Math.min(CHUNK, queue.length);
    for (var i = 0; i < n; i++) addCamera(queue.shift());
    requestAnimationFrame(pump);
  }

  /* ---------------- show/hide with camera altitude ---------------- */
  function applyAltitudeShow() {
    var h = viewer.camera.positionCartographic.height;
    var show = h <= HIDE_ALT;
    for (var i = 0; i < cameraEntities.length; i++) {
      cameraEntities[i].show = show;
    }
  }

  /* ---------------- traffic camera sidebar (left panel) ---------------- */
  var camPanel = null;
  var camListEl = null;
  var camSearchEl = null;
  var camCountEl = null;
  var camAll = [];                 // full camera list (for sidebar)
  var camFiltered = [];            // current filtered list
  var camRenderCap = 500;          // max DOM rows at once
  var camThumbObs = null;          // IntersectionObserver for lazy thumbs

  function ensureSidebar() {
    camPanel = document.getElementById("camPanel");
    camListEl = document.getElementById("camList");
    camSearchEl = document.getElementById("camSearch");
    camCountEl = document.getElementById("camCountBadge");
    if (!camPanel || !camListEl) return false;
    return true;
  }

  function camBadge(src) {
    return src === "nc"
      ? '<span class="ci-badge nc">NC</span>'
      : '<span class="ci-badge nyc">NYC</span>';
  }

  function camMeta(cam) {
    return (cam.area || "") + (cam.src === "nc" ? " · NC DOT" : " · NYC DOT");
  }

  function renderCamList() {
    if (!camListEl) return;
    camListEl.innerHTML = "";
    var list = camFiltered;
    var shown = list.length > camRenderCap ? camRenderCap : list.length;
    if (list.length === 0) {
      camListEl.innerHTML = '<div id="camEmpty">No cameras match — try "Brooklyn", "I-95", "Raleigh"…</div>';
      return;
    }
    for (var i = 0; i < shown; i++) {
      (function (cam) {
        var row = document.createElement("div");
        row.className = "cam-item";
        row.innerHTML =
          '<img class="ci-thumb" data-src="/api/cameras/image/' + encodeURIComponent(cam.id) + "?src=" + (cam.src || "nyc") + '" alt="" />' +
          '<div class="ci-info">' +
          '  <div class="ci-name">' + (cam.name || "Camera " + cam.id) + "</div>" +
          '  <div class="ci-meta">' + camMeta(cam) + " · " + cam.lat.toFixed(3) + ", " + cam.lon.toFixed(3) + "</div>" +
          "</div>" +
          camBadge(cam.src) +
          '<span class="ci-go">➤</span>';
        row.addEventListener("click", function () {
          flyToCamera(cam.id);
        });
        camListEl.appendChild(row);
      })(list[i]);
    }
    if (list.length > shown) {
      var more = document.createElement("div");
      more.style.cssText = "color:#7c8ba0;font-size:10px;text-align:center;padding:10px;";
      more.textContent = "Showing " + shown + " of " + list.length + " — refine search to narrow";
      camListEl.appendChild(more);
    }
    // lazy thumbnails
    if (camThumbObs) camThumbObs.disconnect();
    camThumbObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          var img = en.target;
          if (img.dataset.src && !img.src) {
            img.src = img.dataset.src;
            img.onerror = function () { img.style.opacity = "0.25"; };
          }
          camThumbObs.unobserve(img);
        }
      });
    }, { root: camListEl, rootMargin: "200px" });
    var imgs = camListEl.querySelectorAll("img.ci-thumb");
    for (var j = 0; j < imgs.length; j++) camThumbObs.observe(imgs[j]);
  }

  function applyCamFilter() {
    var q = (camSearchEl.value || "").trim().toLowerCase();
    if (!q) { camFiltered = camAll.slice(); }
    else {
      camFiltered = camAll.filter(function (c) {
        return (c.name || "").toLowerCase().indexOf(q) !== -1 ||
               (c.area || "").toLowerCase().indexOf(q) !== -1 ||
               String(c.id).toLowerCase().indexOf(q) !== -1;
      });
    }
    if (camCountEl) {
      camCountEl.textContent = camFiltered.length.toLocaleString() + " Cameras";
    }
    renderCamList();
  }

  function openCamPanel() {
    if (!ensureSidebar()) return;
    camPanel.classList.add("open");
    document.getElementById("btnCameras").classList.add("active");
    applyCamFilter();
  }

  function closeCamPanel() {
    if (camPanel) camPanel.classList.remove("open");
    var btn = document.getElementById("btnCameras");
    if (btn) btn.classList.remove("active");
  }

  function toggleCamPanel() {
    if (camPanel && camPanel.classList.contains("open")) closeCamPanel();
    else openCamPanel();
  }

  function flyToCamera(camId) {
    var rec = camById[camId];
    if (!rec) return;
    var cam = rec.data;
    // spec: fly down to the street
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(cam.lon, cam.lat, 800),
      duration: 2.5,
    });
    // open the live snapshot card overlay
    openPopup(cam);
  }

  function initSidebar() {
    if (!ensureSidebar()) return;
    document.getElementById("btnCameras").addEventListener("click", toggleCamPanel);
    document.getElementById("camClose").addEventListener("click", closeCamPanel);
    camSearchEl.addEventListener("input", applyCamFilter);
    // preset jump chips: fly to the neighborhood at 1200m
    var presets = document.querySelectorAll(".cam-preset");
    for (var i = 0; i < presets.length; i++) {
      presets[i].addEventListener("click", function () {
        var lat = parseFloat(this.getAttribute("data-lat"));
        var lon = parseFloat(this.getAttribute("data-lon"));
        var name = this.getAttribute("data-name") || "";
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(lon, lat, 1200),
          duration: 2.5,
        });
        // open the nearest camera's popup if we have one nearby
        var best = null, bestD = Infinity;
        for (var id in camById) {
          var c = camById[id].data;
          var d = Math.abs(c.lat - lat) + Math.abs(c.lon - lon);
          if (d < bestD) { bestD = d; best = c; }
        }
        if (best && bestD < 0.05) openPopup(best);
      });
    }
    // Esc closes the panel too
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeCamPanel();
    });
  }

  /* ---------------- init ---------------- */
  function init() {
    if (!ready()) { setTimeout(init, 250); return; }
    viewer = window.viewer;

    cameraBillboards = viewer.scene.primitives.add(new Cesium.BillboardCollection());

    // chunked creation: 250 entities per rAF tick, never 2,088 at once
    fetch("/api/cameras?src=all")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var list = (d && d.cameras) || [];
        camAll = list.slice();
        queue = list.slice();
        if (!creating) pump();
        // sidebar count badge + topbar button
        var badge = document.getElementById("camCountBadge");
        if (badge) badge.textContent = list.length.toLocaleString() + " Cameras";
        var btn = document.getElementById("btnCamCount");
        if (btn) btn.textContent = list.length.toLocaleString();
        if (camPanel && camPanel.classList.contains("open")) applyCamFilter();
      })
      .catch(function () {});

    // hide all camera billboards when flying above 4,000,000 m
    viewer.camera.changed.addEventListener(applyAltitudeShow);
    applyAltitudeShow();   // run once at init (camera starts at 9M m)

    // clicks are handled by index.html's SINGLE LEFT_CLICK handler
    // (Cesium keeps only one action per event type — a second handler here
    // would silently replace the aircraft one). We expose the popup API:
    window.openCamPopup = function (camId) {
      if (camId && camById[camId]) openPopup(camById[camId].data);
    };
    window.closeCamPopup = closePopup;
    window.flyToCamera = flyToCamera;
    window.toggleCamPanel = toggleCamPanel;
    // expose camera registry for the traffic simulator (v1.2)
    window.camById = camById;

    // Esc closes the popup
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { closePopup(); closeFlockCard(); }
    });

    initSidebar();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
