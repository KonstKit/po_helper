const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const BASE_URL = process.env.BASE_URL || "http://localhost:3001";

function logStep(n, msg) { console.log(`[step ${n}] ${msg}`); }
async function ensureDir(p) { await fs.promises.mkdir(p, { recursive: true }); }

async function waitVisibleXPath(page, xp, timeout = 15000) {
  await page.waitForFunction((xpInner) => {
    try {
      const res = document.evaluate(xpInner, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      return !!res.singleNodeValue;
    } catch { return false; }
  }, { timeout }, xp);
  const handle = await page.evaluateHandle((xpInner) => {
    return document.evaluate(xpInner, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  }, xp);
  const el = handle.asElement();
  if (!el) throw new Error("XPath did not resolve to element: " + xp);
  return el;
}
async function clickXPath(page, xp, timeout = 15000) { const el = await waitVisibleXPath(page, xp, timeout); await el.click(); }
async function typeByLabel(page, labelText, value) {
  const xp = `//label[normalize-space(.)='${labelText}']/following::*[(self::input or self::textarea) and not(@disabled)][1]`;
  const el = await waitVisibleXPath(page, xp);
  await el.click({ clickCount: 3 });
  await page.keyboard.type(value);
}

(async () => {
  const outDir = path.resolve(__dirname, "artifacts");
  await ensureDir(outDir);
  let step = 1;
  logStep(step++, "launch chromium");
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  page.setDefaultTimeout(20000);

  try {
    logStep(step++, `go to ${BASE_URL}`);
    await page.goto(BASE_URL, { waitUntil: ["load", "domcontentloaded", "networkidle0"] }).catch(async () => {
      await page.goto(BASE_URL.replace("localhost", "[::1]"), { waitUntil: ["load", "domcontentloaded", "networkidle0"] });
    });

    logStep(step++, "capture landing screenshot");
    await page.screenshot({ path: path.join(outDir, "01-landing.png"), fullPage: true });

    // Projects flow via route
    logStep(step++, "navigate to Projects");
    await page.goto(`${BASE_URL}/projects`, { waitUntil: ["load", "domcontentloaded", "networkidle0"] });
    await waitVisibleXPath(page, "//h4[normalize-space(.)='Projects']");
    await page.screenshot({ path: path.join(outDir, "02-projects.png"), fullPage: true });

    const emptyFound = await page.waitForFunction(() => !!document.evaluate("//p[contains(.,'No projects found. Click \"New Project\" to create one.')]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue, { timeout: 1000 }).then(() => true).catch(() => false);
    if (emptyFound) {
      logStep(step++, "empty projects: creating");
      await clickXPath(page, "//button[.='New Project']");
      await waitVisibleXPath(page, "//h2[contains(.,'Create New Project')]");
      await typeByLabel(page, "Project Name", "E2E Project");
      await typeByLabel(page, "Jira Key (or pick below)", "E2E");
      await typeByLabel(page, "Description", "Created by Puppeteer E2E");
      await clickXPath(page, "//button[.='Create']");
      await waitVisibleXPath(page, "//div[contains(@class,'MuiCard-root')]//h2[normalize-space(.)='E2E Project']", 20000);
      await page.screenshot({ path: path.join(outDir, "03-project-created.png"), fullPage: true });
    } else {
      logStep(step++, "projects exist");
      await page.screenshot({ path: path.join(outDir, "03-projects-existing.png"), fullPage: true });
    }

    // Analytics flow via route
    logStep(step++, "navigate to Analytics");
    await page.goto(`${BASE_URL}/analytics`, { waitUntil: ["load", "domcontentloaded", "networkidle0"] });
    await waitVisibleXPath(page, "//h4[normalize-space(.)='Analytics']");

    const cardChecks = [
      "Average Velocity",
      "Total Value Delivered",
      "Sprint Success Rate",
      "Avg. Task Completion",
      "Budget Efficiency",
    ];
    for (const label of cardChecks) {
      await waitVisibleXPath(page, `//p[normalize-space(.)='${label}']/following::h4[1]`);
    }
    await page.screenshot({ path: path.join(outDir, "05-analytics-cards.png"), fullPage: true });

    const sections = [
      "Team Velocity Trend",
      "Risk Distribution",
      "Current Sprint Burndown",
      "Test Trend (Total vs Failed)",
      "Coverage Trend (% by day)",
      "Pull Request Metrics",
    ];
    for (const s of sections) {
      await waitVisibleXPath(page, `//h6[normalize-space(.)='${s}']`, 20000).catch(() => {});
    }
    await page.screenshot({ path: path.join(outDir, "06-analytics-sections.png"), fullPage: true });

    logStep(step++, "done");
    await browser.close();
    process.exit(0);
  } catch (err) {
    await page.screenshot({ path: path.join(outDir, "error.png"), fullPage: true }).catch(() => {});
    console.error("Test failed:", err && err.message ? err.message : err);
    await browser.close();
    process.exit(1);
  }
})();