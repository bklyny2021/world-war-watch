const { chromium } = require('C:/Users/bklyn/AppData/Local/hermes/hermes-agent/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/bklyn/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  page.on('pageerror', e => console.log('PAGEERROR FULL:\n' + (e.stack || String(e))));
  page.on('console', m => { if (m.type() === 'error') console.log('CONSOLE ERR:', m.text()); });

  await page.goto('http://127.0.0.1:8767/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(15000);

  // also check: which primitive throws — try scene render manually
  const info = await page.evaluate(() => {
    const v = window.viewer;
    try {
      v.scene.render();
      return 'manual render OK';
    } catch (e) {
      return 'MANUAL RENDER THREW: ' + (e.stack || e.message);
    }
  });
  console.log(info);
  await browser.close();
  console.log('DONE');
})().catch(e => { console.log('FATAL:', e.message); process.exit(1); });
