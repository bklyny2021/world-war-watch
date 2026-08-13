const { chromium } = require('C:/Users/bklyn/AppData/Local/hermes/hermes-agent/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/bklyn/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errs = [];
  page.on('pageerror', e => errs.push('PAGE: ' + String(e).slice(0, 120)));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('404')) errs.push('CON: ' + m.text().slice(0, 120)); });

  await page.goto('http://127.0.0.1:8767/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(15000);

  const boot = await page.evaluate(() => {
    const v = window.viewer;
    const prims = [];
    for (let i = 0; i < v.scene.primitives.length; i++) {
      const p = v.scene.primitives.get(i);
      if (p && typeof p.add === 'function' && p.constructor.name.length <= 3) {
        prims.push({ name: p.constructor.name, count: p.length });
      }
    }
    return { ships: window.shipEntities ? window.shipEntities.size : -1, prims };
  });
  console.log('BOOT:', JSON.stringify(boot));

  // zoom in 15x from space
  await page.evaluate(() => {
    window.viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(-95, 38, 28000000), duration: 0.8 });
  });
  await page.waitForTimeout(2000);
  await page.mouse.move(800, 450);
  for (let i = 0; i < 15; i++) { await page.mouse.wheel(0, -500); await page.waitForTimeout(80); }
  const hIn = await page.evaluate(() => window.viewer.camera.positionCartographic.height);
  console.log('zoom-in height:', hIn.toFixed(0));

  // zoom back out 15x — must respond
  for (let i = 0; i < 20; i++) { await page.mouse.wheel(0, 500); await page.waitForTimeout(80); }
  const hOut = await page.evaluate(() => window.viewer.camera.positionCartographic.height);
  console.log('zoom-out height:', hOut.toFixed(0));

  // underground trap
  await page.evaluate(() => {
    window.viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(-74.0, 40.7, 50) });
  });
  await page.waitForTimeout(3000);
  const hRec = await page.evaluate(() => window.viewer.camera.positionCartographic.height);
  console.log('watchdog recovery:', hRec.toFixed(0));
  await page.screenshot({ path: 'C:/Users/bklyn/worldview/_v23_verify2.png' });

  console.log('ERRORS:', errs.length ? JSON.stringify(errs.slice(0, 4)) : 'NONE');
  await browser.close();
  console.log('DONE');
})().catch(e => { console.log('FATAL:', e.message); process.exit(1); });
