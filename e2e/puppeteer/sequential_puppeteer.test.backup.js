const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3001';

function logStep(n, msg){
  console.log(`[step ${n}] ${msg}`);
}

async function ensureDir(p){
  await fs.promises.mkdir(p, { recursive: true });
}

(async () => {
  const outDir = path.resolve(__dirname, 'artifacts');
  await ensureDir(outDir);

  let step = 1;
  logStep(step++, `launch chromium`);
  const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox','--disable-setuid-sandbox'] });
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);

  try {
    logStep(step++, `go to ${BASE_URL}`);
    await page.goto(BASE_URL, { waitUntil: ['load','domcontentloaded','networkidle0'] }).catch(async (e) => {
      // try IPv6 loopback explicitly if IPv4 failed
      await page.goto(BASE_URL.replace('localhost','[::1]'), { waitUntil: ['load','domcontentloaded','networkidle0'] });
    });

    logStep(step++, 'capture landing screenshot');
    await page.screenshot({ path: path.join(outDir, '01-landing.png'), fullPage: true });

    const title = await page.title().catch(() => '');
    logStep(step++, `page title: ${title || '(empty)'}`);

    // Check basic app shell indicators
    const bodyHTML = await page.evaluate(() => document.body.innerText.slice(0, 500));
    logStep(step++, `body snippet: ${bodyHTML.replace(/\s+/g,' ').slice(0, 120)}`);

    // Try to detect common navigation links
    const links = await page.$$eval('a', as => as.map(a => ({href: a.getAttribute('href')||'', text: (a.textContent||'').trim()})));
    fs.writeFileSync(path.join(outDir,'links.json'), JSON.stringify(links, null, 2));
    logStep(step++, `found ${links.length} links`);

    // Attempt a projects-like route if present
    const projLink = links.find(l => /project/i.test(l.href || l.text));
    if (projLink && projLink.href && !projLink.href.startsWith('http')){
      logStep(step++, `navigate to projects link: ${projLink.href}`);
      await Promise.all([
        page.waitForNavigation({ waitUntil: ['load','domcontentloaded','networkidle0'] }),
        page.click(`a[href='${projLink.href}']`)
      ]);
      await page.screenshot({ path: path.join(outDir, '02-projects.png'), fullPage: true });
    } else {
      logStep(step++, 'no explicit projects link; try common paths');
      const candidates = ['/projects', '/dashboard', '/analytics'];
      for (const c of candidates){
        try {
          await page.goto(`${BASE_URL}${c}`, { waitUntil: ['load','domcontentloaded','networkidle0'] });
          await page.screenshot({ path: path.join(outDir, `02-${c.replace(/\//g,'_')}.png`), fullPage: true });
        } catch(e){ /* ignore */ }
      }
    }

    // Basic performance and console check
    const metrics = await page.metrics();
    fs.writeFileSync(path.join(outDir,'metrics.json'), JSON.stringify(metrics, null, 2));
    const perf = await page.evaluate(() => ({
      timing: performance.timing ? { domComplete: performance.timing.domComplete, loadEventEnd: performance.timing.loadEventEnd } : null
    }));
    fs.writeFileSync(path.join(outDir,'performance.json'), JSON.stringify(perf, null, 2));

    logStep(step++, 'done');
    await browser.close();
    process.exit(0);
  } catch (err){
    await page.screenshot({ path: path.join(outDir, 'error.png'), fullPage: true }).catch(()=>{});
    console.error('Test failed:', err && err.message ? err.message : err);
    await browser.close();
    process.exit(1);
  }
})();
