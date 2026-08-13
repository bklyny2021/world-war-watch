const { chromium } = require('C:/Users/bklyn/AppData/Local/hermes/hermes-agent/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/bklyn/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errs = [];
  page.on('pageerror', e => errs.push('PAGEERR: ' + (e.stack || String(e)).slice(0, 600)));
  page.on('console', m => { if (m.type() === 'error') errs.push('CONSOLE: ' + m.text().slice(0, 300)); });

  await page.goto('http://127.0.0.1:8767/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(12000);

  const info = await page.evaluate(() => {
    const v = window.viewer;
    return {
      primCount: v.scene.primitives.length,
      prims: Array.from({ length: v.scene.primitives.length }, (_, i) => {
        const p = v.scene.primitives.get(i);
        return p ? p.constructor.name : 'null';
      }).join(','),
    };
  });
  console.log('PRIMS:', JSON.stringify(info));

  await page.waitForTimeout(3000);
  console.log('ERRORS SO FAR:', errs.length);
  errs.slice(0, 3).forEach(e => console.log('---', e.slice(0, 400)));
  await browser.close();
  console.log('DONE');
})().catch(e => { console.log('FATAL:', e.message); process.exit(1); });
