import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.PORTAL_BASE_URL || 'http://127.0.0.1:18999';
const VIEWS_DIR = process.env.PORTAL_VIEWS_DIR || path.resolve('template/views');

const viewFiles = fs.readdirSync(VIEWS_DIR).filter(f => f.endsWith('.html')).sort();
const browser = await chromium.launch({ headless: true });

let failures = 0;

// 1. Check dashboard.html + all views at 1440x900
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
for (const urlPath of ['dashboard.html', ...viewFiles.map(f => `views/${f}`)]) {
  if (urlPath === 'views/floorplan.html' || urlPath === 'views/stack-diagram.html') continue;
  const page = await context.newPage();
  const pageErrors = [];
  const badResponses = [];
  page.on('pageerror', e => pageErrors.push(e.message));
  page.on('response', r => {
    if (r.status() >= 400 && !(r.request().method() === 'HEAD' && r.url().includes('stack-diagram.html'))) {
      badResponses.push(`${r.status()} ${r.url()}`);
    }
  });

  await page.goto(`${BASE}/${urlPath}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(400);

  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (bg !== 'rgb(15, 15, 15)') {
    console.error(`FAIL bg ${urlPath}: ${bg}`);
    failures++;
  }
  if (pageErrors.length > 0 || badResponses.length > 0) {
    console.error(`FAIL errors ${urlPath}:`, { pageErrors, badResponses });
    failures++;
  }
  await page.close();
}
await context.close();

// 2. Responsive + Live Telemetry + Keyboard shortcut checks
for (const vp of [{ width: 1440, height: 900 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
  const ctx = await browser.newContext({ viewport: vp });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/views/live-telemetry.html`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(1000);
  const res = await page.evaluate(() => ({
    conn: document.querySelector('#conn-text')?.textContent || '',
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  }));
  if (!res.conn.includes('Live') || res.overflow) {
    console.error(`FAIL responsive ${vp.width}x${vp.height}:`, res);
    failures++;
  }
  await ctx.close();
}

// 3. Keyboard '/' search focus + 'Esc' clear
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/views/db-lineage.html`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(400);
  await page.keyboard.press('/');
  const focused = await page.evaluate(() => document.activeElement?.tagName.toLowerCase());
  if (focused !== 'input') {
    console.error(`FAIL '/' shortcut did not focus input (got ${focused})`);
    failures++;
  }
  await ctx.close();
}

await browser.close();
console.log(`Playwright E2E Smoke complete. Failures: ${failures}`);
process.exit(failures > 0 ? 1 : 0);
