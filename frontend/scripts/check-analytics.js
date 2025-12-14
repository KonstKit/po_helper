const puppeteer = require('puppeteer');

async function main() {
  const url = 'http://127.0.0.1:4173/analytics';
  const browser = await puppeteer.launch({ headless: 'new' });
  const page = await browser.newPage();
  page.setDefaultTimeout(20000);
  await page.goto(url, { waitUntil: 'networkidle0' });

  // Wait for key sections from the updated layout
  await page.waitForSelector('text=Team Health Snapshot');
  await page.waitForSelector('text=Average Velocity');
  await page.waitForSelector('text=Avg Cycle Time');
  await page.waitForSelector('text=Budget Efficiency');

  // Grab card titles for confirmation
  const cardTitles = await page.$$eval('div.MuiGrid-item .MuiTypography-root', nodes => {
    return nodes
      .map((node) => node.textContent.trim())
      .filter((text) => [
        'Average Velocity',
        'Total Value Delivered',
        'Completion Rate',
        'Avg Cycle Time',
        'Avg. Task Completion',
        'Budget Efficiency',
      ].includes(text));
  });

  // Capture a screenshot for visual verification
  await page.setViewport({ width: 1440, height: 900 });
  await new Promise(resolve => setTimeout(resolve, 500));
  await page.screenshot({ path: 'analytics-preview.png', fullPage: true });

  await browser.close();

  const uniqueTitles = Array.from(new Set(cardTitles));
  console.log(JSON.stringify({ url, cardTitles: uniqueTitles }));
}

main().catch((err) => {
  console.error('analytics preview check failed', err);
  process.exit(1);
});
