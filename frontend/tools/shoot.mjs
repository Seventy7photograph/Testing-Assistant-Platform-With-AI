import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "playwright-core";

const BASE = process.env.SHOOT_BASE || "http://127.0.0.1:8000";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOOT_OUT || path.resolve(HERE, "..", "..", ".impeccable", "review");
const EXEC =
  process.env.SHOOT_CHROME ||
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

const targets = [
  { name: "workbench", url: "/" },
  { name: "suites", url: "/suites" },
  { name: "suite-detail", url: "/suites/SUITE-7aa0f9a1" },
  { name: "suite-trace", url: "/suites/SUITE-7aa0f9a1", expand: true },
  { name: "documents", url: "/documents" },
  { name: "requirement", url: "/documents/DOC-09339fca/requirement" },
];

const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ executablePath: EXEC, headless: true });
const problems = [];

for (const viewport of viewports) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") {
      problems.push(`[${viewport.name}] console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    problems.push(`[${viewport.name}] pageerror: ${error.message}`);
  });

  for (const target of targets) {
    await page.goto(`${BASE}${target.url}`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card, .strip, .index", { timeout: 15000 });
    await page.waitForTimeout(500);

    if (target.expand) {
      const clicked = await page.evaluate(() => {
        const button = document.querySelector(".el-table__expand-icon");
        if (!button) return false;
        button.click();
        return true;
      });
      if (!clicked) {
        problems.push(`[${viewport.name}] ${target.name}: no expandable row found`);
      } else {
        await page.waitForSelector(".trace-card", { timeout: 8000 }).catch(() => {
          problems.push(`[${viewport.name}] ${target.name}: trace card did not appear`);
        });
        await page.waitForTimeout(500);
      }
    }

    const file = path.join(OUT, `${target.name}-${viewport.name}.png`);
    await page.screenshot({ path: file, fullPage: true });
    process.stdout.write(`shot ${path.basename(file)}\n`);
  }

  await context.close();
}

await browser.close();

if (problems.length) {
  process.stdout.write(`\nPROBLEMS (${problems.length}):\n` + problems.join("\n") + "\n");
} else {
  process.stdout.write("\nno console errors\n");
}
