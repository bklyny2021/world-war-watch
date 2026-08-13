const { chromium } = require('C:/Users/bklyn/AppData/Local/hermes/hermes-agent/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/bklyn/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  page.on('console', m => { if (m.type() === 'error') console.log('CONSOLE_ERR:', m.text().slice(0, 200)); });
  page.on('pageerror', e => console.log('PAGE_ERR:', String(e).slice(0, 200)));

  await page.goto('http://127.0.0.1:8767/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(18000); // Cesium + tiles

  // 1) global view screenshot
  await page.screenshot({ path: 'C:/Users/bklyn/worldview/_fix_verify_global.png' });

  // 2) fly low over a plane (simulate the zoom-in that used to crash)
  const camInfo = await page.evaluate(() => {
    const viewer = window.viewer || (window.Cesium && document.querySelector('.cesium-viewer') && null);
    return { hasViewer: !!viewer };
  });
  console.log('hasViewer:', camInfo.hasViewer);

  // find first plane entity via the flights map if exposed, else pick a known spot
  const lowResult = await page.evaluate(() => {
    try {
      // try to grab a real plane position from the app's internal state
      const anyPlane = window.__flights || null;
      return { anyPlane: anyPlane ? 'found' : 'none' };
    } catch (e) { return { err: String(e) }; }
  });
  console.log('plane state:', JSON.stringify(lowResult));

  // fly to a low altitude over NYC-ish coords and check camera height after
  await page.evaluate(() => {
    const c = window.Cesium;
    const viewer = window.viewer;
    if (!viewer || !c) return;
    viewer.camera.flyTo({
      destination: c.Cartesian3.fromDegrees(-74.0, 40.7, 1500),
      duration: 2.0,
    });
  });
  await page.waitForTimeout(4000);
  const h = await page.evaluate(() => {
    const viewer = window.viewer;
    return viewer ? viewer.camera.positionCartographic.height : -1;
  });
  console.log('camera height after low flyTo:', h);
  await page.screenshot({ path: 'C:/Users/bklyn/worldview/_fix_verify_low.png' });

  // 3) force the underground scenario: set camera below 300m, check watchdog recovers
  await page.evaluate(() => {
    const c = window.Cesium;
    const viewer = window.viewer;
    if (!viewer || !c) return;
    viewer.camera.setView({
      destination: c.Cartesian3.fromDegrees(-74.0, 40.7, 50), // 50m = underground in photoreal
    });
  });
  await page.waitForTimeout(4000);
  const h2 = await page.evaluate(() => {
    const viewer = window.viewer;
    return viewer ? viewer.camera.positionCartographic.height : -1;
  });
  console.log('camera height after underground test (watchdog should have recovered):', h2);
  await page.screenshot({ path: 'C:/Users/bklyn/worldview/_fix_verify_recovered.png' });

  // 4) simulate the USER's actual scenario: wheel-zoom into the ground 20x
  await page.evaluate(() => {
    const c = window.Cesium;
    const viewer = window.viewer;
    if (!viewer || !c) return;
    viewer.camera.flyTo({
      destination: c.Cartesian3.fromDegrees(-74.0, 40.7, 5000),
      duration: 1.5,
    });
  });
  await page.waitForTimeout(2500);
  for (let i = 0; i < 20; i++) {
    await page.mouse.move(800, 450);
    await page.mouse.wheel(0, -400); // zoom in
    await page.waitForTimeout(150);
  }
  const h3 = await page.evaluate(() => {
    const viewer = window.viewer;
    return viewer ? viewer.camera.positionCartographic.height : -1;
  });
  console.log('camera height after 20 wheel-zoom-ins (min 1000 + collision):', h3);
  await page.screenshot({ path: 'C:/Users/bklyn/worldview/_fix_verify_wheel.png' });

  await browser.close();
  console.log('DONE');
})().catch(e => { console.log('FATAL:', e.message); process.exit(1); });
