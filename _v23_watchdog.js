const { chromium } = require('C:/Users/bklyn/AppData/Local/hermes/hermes-agent/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/bklyn/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  await page.goto('http://127.0.0.1:8767/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(12000);
  await page.evaluate(() => {
    window.viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(-74.0, 40.7, 50) });
  });
  await page.waitForTimeout(3000);
  const hRec = await page.evaluate(() => window.viewer.camera.positionCartographic.height);
  console.log('watchdog recovery after trap:', hRec.toFixed(0));
  const errs = [];
  page.on('pageerror', e => errs.push(String(e).slice(0, 100)));
  console.log('errors:', errs.length ? JSON.stringify(errs) : 'NONE');
  await browser.close();
  console.log('DONE');
})().catch(e => { console.log('FATAL:', e.message); process.exit(1); });
