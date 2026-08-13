const { chromium } = require('C:/Users/bklyn/AppData/Local/hermes/hermes-agent/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/bklyn/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const jsErrors = [];
  page.on('pageerror', e => jsErrors.push(String(e).slice(0, 150)));
  page.on('console', m => { if (m.type() === 'error') jsErrors.push(m.text().slice(0, 150)); });

  await page.goto('http://127.0.0.1:8767/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(15000);

  // layer state after boot
  const boot = await page.evaluate(() => {
    const v = window.viewer;
    return {
      requestRenderMode: v.scene.requestRenderMode,
      shipCount: window.shipEntities ? window.shipEntities.size : -1,
      hasShipBillboards: !!(v.scene.primitives._primitives || []).find(p => p.constructor && p.constructor.name === 'BillboardCollection'),
      camBillboards: (v.scene.primitives._primitives || []).filter(p => p.constructor && p.constructor.name === 'BillboardCollection').length,
    };
  });
  console.log('BOOT:', JSON.stringify(boot));

  // camera floor watchdog still present?
  const hasWatchdog = await page.evaluate(() => {
    return document.documentElement.innerHTML.includes('CAMERA FLOOR WATCHDOG');
  });
  console.log('watchdog present:', hasWatchdog);

  // ZOOM STRESS: global -> NYC -> street, 25 rapid wheel zooms, back out
  await page.evaluate(() => {
    const c = window.Cesium, v = window.viewer;
    v.camera.flyTo({ destination: c.Cartesian3.fromDegrees(-95, 38, 28000000), duration: 1.0 });
  });
  await page.waitForTimeout(2000);
  await page.mouse.move(800, 450);
  for (let i = 0; i < 25; i++) { await page.mouse.wheel(0, -500); await page.waitForTimeout(100); }
  const hIn = await page.evaluate(() => window.viewer.camera.positionCartographic.height);
  console.log('height after 25 zoom-ins:', hIn.toFixed(0));
  for (let i = 0; i < 40; i++) { await page.mouse.wheel(0, 500); await page.waitForTimeout(100); }
  const hOut = await page.evaluate(() => window.viewer.camera.positionCartographic.height);
  console.log('height after 40 zoom-outs:', hOut.toFixed(0));
  await page.screenshot({ path: 'C:/Users/bklyn/worldview/_v23_verify_zoom.png' });

  // underground trap: force 50m, watchdog must recover
  await page.evaluate(() => {
    const c = window.Cesium, v = window.viewer;
    v.camera.setView({ destination: c.Cartesian3.fromDegrees(-74.0, 40.7, 50) });
  });
  await page.waitForTimeout(3000);
  const hRec = await page.evaluate(() => window.viewer.camera.positionCartographic.height);
  console.log('height after underground trap (watchdog):', hRec.toFixed(0));

  // click a ship if any exist
  const shipClickTest = await page.evaluate(() => {
    const first = window.shipEntities && window.shipEntities.size ? window.shipEntities.keys().next().value : null;
    return first ? 'ships-present' : 'no-ships';
  });
  console.log('ship click prep:', shipClickTest);

  console.log('JS ERRORS:', jsErrors.length ? JSON.stringify(jsErrors.slice(0, 5)) : 'NONE');
  await browser.close();
  console.log('DONE');
})().catch(e => { console.log('FATAL:', e.message); process.exit(1); });
