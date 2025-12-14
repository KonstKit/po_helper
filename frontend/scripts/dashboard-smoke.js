const puppeteer = require('puppeteer');
const fs = require('fs/promises');

let browser;
let page;

const FRONTEND_BASE_URL = (process.env.FRONTEND_BASE_URL || 'http://127.0.0.1:4173/').replace(/\s+$/, '');

async function ensureProjectSwitch(page) {
  const triggerSelector = 'div[role="button"][aria-haspopup="listbox"]';
  await page.waitForSelector(triggerSelector, { timeout: 15000 });
  await page.click(triggerSelector);
  await page.waitForSelector('li[role="option"]', { timeout: 5000 });
  const target = await page.$$eval('li[role="option"]', nodes => {
    const labels = nodes.map(node => node.textContent.trim()).filter(Boolean);
    if (!labels.length) return null;
    const preferred = ['WaBank', 'Wellbeing'];
    for (const name of preferred) {
      if (labels.includes(name)) return name;
    }
    return labels[Math.min(1, labels.length - 1)];
  });
  if (target) {
    await page.evaluate((label) => {
      const items = Array.from(document.querySelectorAll('li[role="option"]'));
      const match = items.find(item => item.textContent && item.textContent.trim() === label);
      if (match) {
        match.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        match.click();
      }
    }, target);
  }
  await page.waitForTimeout(500);
}

async function clickByTestId(page, testId, expectDialog = false) {
  const selector = `[data-testid="${testId}"]`;
  await page.waitForSelector(selector, { timeout: 10000 });
  await page.click(selector);
  if (expectDialog) {
    await page.waitForSelector('[role="dialog"]', { timeout: 5000 });
    const closeBtn = await page.$x("//button[contains(., 'Close')]");
    if (closeBtn[0]) {
      await closeBtn[0].click();
      await page.waitForTimeout(300);
    }
  }
}

(async () => {
  browser = await puppeteer.launch({ headless: 'new' });
  page = await browser.newPage();
  page.setDefaultTimeout(20000);

  await page.goto('about:blank');
  await page.evaluate(() => {
    try {
      localStorage.setItem('token', 'demo');
    } catch (err) {
      console.warn('failed to seed token', err);
    }
  });
  await page.goto(FRONTEND_BASE_URL, { waitUntil: 'networkidle0' });
  await page.waitForSelector('[data-testid="card-total"]', { timeout: 30000 });

  await ensureProjectSwitch(page);

  const interactions = [];
  try {
    await clickByTestId(page, 'card-total', true);
    interactions.push('card-total');
  } catch (err) {
    interactions.push(`card-total FAILED: ${err.message}`);
  }

  try {
    await clickByTestId(page, 'card-completed', true);
    interactions.push('card-completed');
  } catch (err) {
    interactions.push(`card-completed FAILED: ${err.message}`);
  }

  try {
    await clickByTestId(page, 'card-blockers', true);
    interactions.push('card-blockers');
  } catch (err) {
    interactions.push(`card-blockers FAILED: ${err.message}`);
  }

  try {
    const riskItemSelector = '[data-testid^="risk-item-"]';
    await page.waitForSelector(riskItemSelector, { timeout: 10000 });
    await page.click(riskItemSelector);
    await page.waitForSelector('[role="dialog"]', { timeout: 5000 });
    const closeBtn = await page.$x("//button[contains(., 'Close')]");
    if (closeBtn[0]) {
      await closeBtn[0].click();
      await page.waitForTimeout(300);
    }
    interactions.push('risk-drilldown');
  } catch (err) {
    interactions.push(`risk-drilldown FAILED: ${err.message}`);
  }

  try {
    const upcomingItems = await page.$$('[data-testid="upcoming-item"]');
    interactions.push(`upcoming-count:${upcomingItems.length}`);
  } catch (err) {
    interactions.push(`upcoming FAILED: ${err.message}`);
  }

  await page.setViewport({ width: 1440, height: 900 });
  await page.screenshot({ path: 'dashboard-smoke.png', fullPage: true });

  console.log(JSON.stringify({ interactions }, null, 2));
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('dashboard smoke failed', err);
  if (page) {
    try {
      await page.screenshot({ path: 'dashboard-smoke-error.png', fullPage: true });
    } catch (shotErr) {
      console.error('failed to capture error screenshot', shotErr);
    }
    try {
      const html = await page.content();
      await fs.writeFile('dashboard-smoke-error.html', html);
    } catch (writeErr) {
      console.error('failed to save error html', writeErr);
    }
  }
  if (browser) {
    try {
      await browser.close();
    } catch (_) {}
  }
  process.exit(1);
});
