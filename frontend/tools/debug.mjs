import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => console.log(`console.${m.type()}: ${m.text()}`));
page.on("pageerror", (e) => console.log(`pageerror: ${e.message}\n${e.stack}`));
page.on("requestfailed", (r) => console.log(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const html = await page.evaluate(() => document.getElementById("app")?.innerHTML ?? "(no #app)");
console.log("--- #app innerHTML (first 1500) ---");
console.log(html.slice(0, 1500));
await browser.close();
