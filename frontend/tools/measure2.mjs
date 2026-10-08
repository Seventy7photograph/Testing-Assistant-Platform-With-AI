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
  const wrap = document.querySelector(".el-table__body-wrapper .el-scrollbar__wrap");
  const bar = document.querySelector(".el-table__body-wrapper .el-scrollbar__bar.is-horizontal");
  const info = wrap
    ? {
        found: true,
        clientWidth: wrap.clientWidth,
        scrollWidth: wrap.scrollWidth,
        overflowX: getComputedStyle(wrap).overflowX,
        overflow: getComputedStyle(wrap).overflow,
      }
    : { found: false };
  const barInfo = bar
    ? { found: true, display: getComputedStyle(bar).display, height: bar.getBoundingClientRect().height }
    : { found: false };
  const outer = document.querySelector(".el-table__body-wrapper");
  return {
    wrap: info,
    horizontalBar: barInfo,
    outerChildren: [...(outer?.children ?? [])].map((child) => child.className),
    bodyWrapperClass: outer?.className,
  };
});

console.log(JSON.stringify(report, null, 2));
await browser.close();
