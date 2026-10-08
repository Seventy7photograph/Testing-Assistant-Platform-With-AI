import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto("http://127.0.0.1:8000/suites/SUITE-7aa0f9a1", { waitUntil: "networkidle" });
await page.waitForSelector(".cases__table", { timeout: 15000 });
await page.waitForTimeout(800);

const report = await page.evaluate(() => {
  const pick = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return { selector, missing: true };
    const rect = el.getBoundingClientRect();
    return {
      selector,
      left: Math.round(rect.left),
      right: Math.round(rect.right),
      width: Math.round(rect.width),
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      overflowX: getComputedStyle(el).overflowX,
    };
  };
  return {
    viewport: window.innerWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    nodes: [
      pick(".shell__content"),
      pick(".cases"),
      pick(".cases__table"),
      pick(".el-table__inner-wrapper"),
      pick(".el-table__body-wrapper"),
      pick(".el-table__body"),
      pick(".el-table__header"),
    ],
  };
});

console.log(JSON.stringify(report, null, 2));
await browser.close();
