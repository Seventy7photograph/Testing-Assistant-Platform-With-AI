/**
 * 前端冒烟：真起一个后端 + 真点一遍关键按钮。
 *
 * 为什么需要它：后端已经能生成判定表/因果图/正交实验的用例，而界面还在显示
 * 「未实现」；用例集列表的「导出 Excel」按钮传的是 `xlsx`，后端注册表里叫 `excel`，
 * 点了就是 404 —— 这两个缺陷 pytest 全绿，因为它们都只存在于**前端与后端的契约之间**。
 * 契约类问题只能靠"真的点一次"来发现。
 *
 * 断言（不通过就退出码非 0）：
 *   1. 生成页的方法清单与后端能力清单一致：后端说 implemented 的，前端必须是可勾选按钮；
 *      后端说未实现的，前端才允许渲染成「未实现」。
 *   2. 点一下新方法能被选中（不只是"看起来可用"）。
 *   3. 用例集列表的导出按钮真的返回 200（而不是 404）。
 *   4. 全程没有浏览器 console error。
 *
 * 用法（在 frontend/ 下）：node tools/smoke-ui.mjs
 * 可选：--keep-open 保留下载的截图以便人工查看；默认截图写到 ../../output/ui-smoke/。
 */
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const OUT = process.env.SMOKE_OUT || path.join(REPO, "output", "ui-smoke");
const CHROME =
  process.env.SHOOT_CHROME || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PYTHON =
  process.env.SMOKE_PYTHON || path.join(REPO, ".venv", "Scripts", "python.exe");

const problems = [];
const passes = [];

function check(label, ok, detail = "") {
  (ok ? passes : problems).push(`${label}${detail ? ` — ${detail}` : ""}`);
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}${detail ? `  ${detail}` : ""}`);
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function waitForServer(base, timeoutMs = 40_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${base}/api/v1/health`);
      if (response.ok) return await response.json();
    } catch {
      /* 还没起来 */
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error("后端在超时时间内没有起来");
}

const REQUIREMENT = `# 会员注册需求

## 1、会员注册
手机号：11位数字，必填
年龄：18~120
会员等级：普通/白银/黄金

业务规则：
- 若手机号已注册则提示直接登录
- 不允许使用黑名单渠道注册
`;

/**
 * 专门制造「提示刷屏」的需求：5 个模块 × 三个组合类方法，会产出 20+ 条过程提示，
 * 且带长度区间字段（水平取值是几十个填充字符），正是把页面撑宽的那种长 token。
 */
const WARN_HEAVY = ["用户注册", "订单创建", "订单查询", "退款申请", "用户登录"]
  .map(
    (name, index) => `## ${index + 1}、${name}
手机号：11位数字，必填
昵称：2-20位
验证码：6位数字
邀请码：6-10位
年龄：18~120
订单金额：0.01~50000
状态：待支付/已支付/已取消

业务规则：
- 若手机号已注册，则不允许重复注册
- 不允许昵称包含敏感词
- 同一个手机号 60 秒内只允许发送一条验证码

主流程：
1. 进入页面
2. 填写信息
3. 提交

异常场景：
- 短信通道异常
`,
  )
  .join("\n");

async function seed(base) {
  const upload = await fetch(`${base}/api/v1/documents/upload`, {
    method: "POST",
    body: (() => {
      const form = new FormData();
      form.append("file", new Blob([REQUIREMENT], { type: "text/markdown" }), "冒烟需求.md");
      return form;
    })(),
  });
  const docId = (await upload.json()).data.doc_id;
  for (let round = 0; round < 2; round += 1) {
    await fetch(`${base}/api/v1/testcases/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, methods: ["equivalence", "boundary"], use_llm: false }),
    });
  }
  return docId;
}

async function main() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const storage = fs.mkdtempSync(path.join(os.tmpdir(), "smoke-ui-"));
  console.log(`后端端口 ${port}，临时存储 ${storage}`);

  const server = spawn(PYTHON, ["-m", "uvicorn", "app.main:app", "--port", String(port)], {
    cwd: REPO,
    env: {
      ...process.env,
      STORAGE_DIR: storage,
      // 用离线假 Provider：既能验证「生成阶段大模型复核/补充」这条链路，
      // 又完全不打网络。密钥显式清空，避免读到本机 .env 里的真实 Key。
      LLM_PROVIDER: "fake",
      LLM_API_KEY: "",
      VISION_API_KEY: "",
      VISION_PROVIDER: "fake",
      LOG_LEVEL: "ERROR",
    },
    stdio: "ignore",
    windowsHide: true,
  });

  let browser;
  try {
    const health = (await waitForServer(base)).data;
    const declared = new Map(health.methods.map((item) => [item.name, item.implemented]));
    const docId = await seed(base);

    fs.mkdirSync(OUT, { recursive: true });
    browser = await chromium.launch({ executablePath: CHROME, headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 980 } });
    const page = await context.newPage();
    const consoleErrors = [];
    const exportResponses = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(String(error)));
    page.on("response", (response) => {
      if (response.url().includes("/api/v1/export/")) {
        exportResponses.push({ url: response.url(), status: response.status() });
      }
    });

    console.log("\n=== 生成页：方法清单与后端一致性 ===");
    await page.goto(`${base}/generate`, { waitUntil: "networkidle" });
    await page.waitForSelector(".methods");
    check("生成页首屏显示吸底送检栏", (await page.locator(".sticky-actions").count()) === 1);
    const initialGenerateBar = await page.locator(".sticky-actions .el-button--primary").textContent();
    check("生成页底部栏主操作是生成用例集", initialGenerateBar?.includes("生成用例集") === true, initialGenerateBar ?? "");

    // SPA 内切换菜单：Pinia 会话必须保留输入，KeepAlive 也必须保住组件状态。
    await page.fill("textarea", "状态缓存验证：手机号：11位数字，必填");
    await page.locator('a[href="/"]').first().click();
    check("总览不残留生成页或报告页吸底栏", (await page.locator(".sticky-actions").count()) === 0);
    await page.locator('a[href="/generate"]').first().click();
    await page.waitForTimeout(200);
    const cachedInput = await page.locator("textarea").inputValue();
    check("菜单切换后生成输入仍在", cachedInput.includes("状态缓存验证"), cachedInput.slice(0, 24));
    const returnedBarCount = await page.locator(".sticky-actions").count();
    check("返回生成页只显示生成页吸底栏", returnedBarCount === 1, `count=${returnedBarCount}`);
    await page.fill("textarea", "");
    const uiMethods = await page.$$eval(".methods .method", (nodes) =>
      nodes.map((node) => ({
        label: node.querySelector(".method__label")?.textContent?.trim() ?? node.textContent.trim(),
        disabled: node.classList.contains("method--off"),
      })),
    );
    const labelByName = { equivalence: "等价类划分", boundary: "边界值分析", scenario: "场景法", decision_table: "判定表", cause_effect: "因果图", orthogonal: "正交实验" };
    for (const [name, implemented] of declared) {
      const label = labelByName[name] ?? name;
      const item = uiMethods.find((entry) => entry.label.startsWith(label));
      check(
        `生成页展示「${label}」且可用性与后端一致`,
        Boolean(item) && item.disabled === !implemented,
        item ? `disabled=${item.disabled}` : "界面未展示该方法",
      );
    }
    check("生成页不再出现「未实现」字样", !(await page.content()).includes("未实现"));
    for (const [name, implemented] of declared) {
      if (!implemented) continue;
      const label = labelByName[name] ?? name;
      const selector = `.methods .method:has(.method__label:text-is("${label}"))`;
      const before = await page.$eval(selector, (node) => node.classList.contains("method--on"));
      await page.click(selector);
      const after = await page.$eval(selector, (node) => node.classList.contains("method--on"));
      // 默认勾选的方法点一下是「取消」，因此断言的是状态翻转而不是"变成选中"。
      check(`点击「${label}」可切换选中状态`, after !== before, `${before} -> ${after}`);
      await page.click(selector);
    }
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.waitForTimeout(150);
    const compactViewport = await page.evaluate(() => ({
      sticky: Boolean(document.querySelector(".sticky-actions")),
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    check(
      "1366×768 首屏吸底操作可见且无横向溢出",
      compactViewport.sticky && compactViewport.scroll <= compactViewport.client + 1,
      `scrollWidth=${compactViewport.scroll} clientWidth=${compactViewport.client}`,
    );
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.screenshot({ path: path.join(OUT, "generate.png"), fullPage: true });

    console.log("\n=== 需求页：方法清单与后端一致性 ===");
    await page.goto(`${base}/documents/${docId}/requirement`, { waitUntil: "networkidle" });
    await page.waitForSelector(".methods");
    const requirementOff = await page.$$eval(".methods .method--off", (nodes) => nodes.length);
    const expectedOff = [...declared.values()].filter((value) => !value).length;
    check("需求页「未实现」数量与后端一致", requirementOff === expectedOff, `界面 ${requirementOff} / 后端 ${expectedOff}`);
    await page.screenshot({ path: path.join(OUT, "requirement.png"), fullPage: true });

    console.log("\n=== 用例集列表：版本号与导出按钮 ===");
    await page.goto(`${base}/suites`, { waitUntil: "networkidle" });
    await page.waitForSelector("table");
    const revisions = await page.$$eval(".rev", (nodes) => nodes.map((node) => node.textContent.trim()));
    check("列表显示版本号", revisions.length >= 2, revisions.join(" / "));
    const excelButton = page.locator("table tbody tr").first().getByText("导出 Excel", { exact: true });
    await excelButton.click();
    await page.waitForTimeout(1500);
    check(
      "「导出 Excel」返回 200",
      exportResponses.some((item) => item.status === 200),
      JSON.stringify(exportResponses),
    );
    check(
      "导出请求用的是后端格式名",
      exportResponses.every((item) => item.url.endsWith("/excel")),
      JSON.stringify(exportResponses.map((item) => item.url.split("/").pop())),
    );
    await page.screenshot({ path: path.join(OUT, "suites.png"), fullPage: true });

    console.log("\n=== 详情页：面包屑与返回上一级 ===");
    await page.locator("table tbody tr").first().getByText("查看", { exact: true }).click();
    await page.waitForSelector(".bar__parent");
    const crumbText = await page.locator(".bar__parent").textContent();
    check("用例集详情显示父级面包屑", crumbText?.trim() === "用例集", crumbText ?? "");
    await page.locator(".bar__parent").click();
    await page.waitForURL("**/suites");
    check("点击面包屑返回用例集列表", page.url().endsWith("/suites"), page.url());

    console.log("\n=== 文档库：图片状态 ===");
    await page.goto(`${base}/documents`, { waitUntil: "networkidle" });
    await page.waitForSelector("table");
    await page.screenshot({ path: path.join(OUT, "documents.png"), fullPage: true });
    check("文档库没有 console error", consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" | "));

    console.log("\n=== 报告工作台：会话状态与吸底操作 ===");
    await page.goto(`${base}/report`, { waitUntil: "networkidle" });
    await page.locator("textarea").first().fill('{"total_cases": 10, "passed": 9, "failed": 1}');
    await page.locator('a[href="/"]').first().click();
    await page.locator('a[href="/report"]').first().click();
    await page.waitForTimeout(200);
    const reportCached = await page.locator("textarea").first().inputValue();
    check("报告输入在菜单切换后保留", reportCached.includes("total_cases"), reportCached);
    check("报告工作台首屏显示吸底送检栏", (await page.locator(".sticky-actions").count()) === 1);
    const reportBar = await page.locator(".sticky-actions .el-button--primary").textContent();
    check("报告工作台底部栏主操作是生成报告", reportBar?.includes("生成报告") === true, reportBar ?? "");

    // 回归：报告页用 Teleport 挂到 body，KeepAlive 停用后必须移除底部栏。
    await page.locator('a[href="/"]').first().click();
    check("离开报告页后总览无吸底栏", (await page.locator(".sticky-actions").count()) === 0);
    await page.locator('a[href="/report"]').first().click();
    await page.waitForTimeout(200);
    check("返回报告页只显示报告页吸底栏", (await page.locator(".sticky-actions").count()) === 1);

    console.log("\n=== 生成页：提示是否刷屏 / 长文本是否撑宽页面 ===");
    await page.locator('a[href="/generate"]').first().click();
    await page.waitForTimeout(200);
    check("从报告页切到生成页不会残留报告底部栏", (await page.locator(".sticky-actions").count()) === 1);
    const switchedGenerateBar = await page.locator(".sticky-actions .el-button--primary").textContent();
    check("切到生成页后底部栏恢复生成用例集", switchedGenerateBar?.includes("生成用例集") === true, switchedGenerateBar ?? "");
    // 关掉「解析用大模型」：让规则解析的结果确定，冒烟结论不受 Provider 影响。
    // 注意 el-switch 真正可点的是外层 .el-switch（里层的 input 是隐藏的原生控件）。
    const parseLlmSwitch = page.locator('.switch:has-text("解析用大模型") .el-switch');
    await parseLlmSwitch.click();
    await page.fill("textarea", WARN_HEAVY);
    // 六种方法全选：提示最多的组合。
    for (const [, label] of Object.entries(labelByName)) {
      const selector = `.methods .method:has(.method__label:text-is("${label}"))`;
      const on = await page.$eval(selector, (node) => node.classList.contains("method--on"));
      if (!on) await page.click(selector);
    }
    await page.locator(".sticky-actions .el-button--primary").click();
    // 大模型可用时会先弹一次确认；不可用时直接开始。两种情况下都要能继续。
    const confirmButton = page.getByRole("button", { name: "开始生成" });
    if (await confirmButton.isVisible({ timeout: 1500 }).catch(() => false)) {
      await confirmButton.click();
    }
    try {
      await page.waitForSelector(".wl", { timeout: 90_000 });
    } catch (error) {
      // 失败时把页面现场留下来，否则只能看到一句"等不到元素"。
      fs.mkdirSync(OUT, { recursive: true });
      await page.screenshot({ path: path.join(OUT, "generate-warnings-FAILED.png"), fullPage: true });
      const text = await page.evaluate(() => document.body.innerText.slice(0, 1200));
      console.log("---- 失败现场（页面可见文本）----");
      console.log(text);
      throw error;
    }
    await page.waitForTimeout(400);

    const pastedDocument = await page.evaluate(async () => {
      const response = await fetch("/api/v1/documents?limit=10");
      const body = await response.json();
      return (body.data ?? []).find((item) => item.parser === "pasted_text");
    });
    check(
      "粘贴文本已记录到文档库",
      Boolean(pastedDocument) &&
        pastedDocument.has_requirement === true &&
        pastedDocument.char_count > 0 &&
        pastedDocument.filename.endsWith(".txt"),
      pastedDocument
        ? `${pastedDocument.filename} · ${pastedDocument.char_count} 字`
        : "未找到 pasted_text 文档记录",
    );

    const overflow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
      worst: Math.max(...[...document.querySelectorAll("body *")].map((node) => node.scrollWidth - node.clientWidth)),
    }));
    check(
      "长文本没有把页面撑出横向滚动",
      overflow.scroll <= overflow.client + 1,
      `scrollWidth=${overflow.scroll} clientWidth=${overflow.client} 最宽元素溢出=${overflow.worst}`,
    );

    const collapsedWidth = await page.$$eval(".wl__list li", (nodes) => nodes.length);
    const counts = await page.$eval(".wl", (node) => ({
      total: Number(node.dataset.total),
      actionable: Number(node.dataset.actionable),
      shown: Number(node.dataset.shown),
      routine: Number(node.dataset.routine),
    }));
    const hasSummary = await page.$(".wl__summary");
    check(
      "折叠态只露「需要复核」的条目",
      Boolean(hasSummary) &&
        counts.routine > 0 &&
        collapsedWidth === counts.shown &&
        collapsedWidth <= 5,
      `共 ${counts.total} 条（需复核 ${counts.actionable} / 过程 ${counts.routine}），可见 ${collapsedWidth} 条`,
    );
    const summaryText = hasSummary ? await page.$eval(".wl__summary", (node) => node.textContent.trim()) : "";
    check("折叠态给出分组计数摘要", /过程提示/.test(summaryText), summaryText);
    await page.screenshot({ path: path.join(OUT, "generate-warnings-collapsed.png"), fullPage: true });
    // 再存一张「首屏」图：整页截图会被几百行用例压扁，看不出提示区长什么样。
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(OUT, "generate-warnings-top.png") });

    await page.click(".wl__toggle");
    await page.waitForTimeout(300);
    const expandedCount = await page.$$eval(".wl__list li", (nodes) => nodes.length);
    check("展开后能看到全部提示", expandedCount > collapsedWidth, `${collapsedWidth} -> ${expandedCount}`);

    // 第一版：生成状态、历史结果在菜单切换后不丢；返回顶部按钮真实可用。
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(250);
    const backTopVisible = await page.getByRole("button", { name: "返回顶部" }).isVisible();
    check("长页面显示返回顶部按钮", backTopVisible);
    if (backTopVisible) {
      await page.getByRole("button", { name: "返回顶部" }).click();
      await page.waitForFunction(() => window.scrollY < 20, undefined, { timeout: 5000 }).catch(() => {});
      const top = await page.evaluate(() => window.scrollY);
      check("返回顶部按钮滚动到页面顶部", top < 20, `scrollY=${top}`);
    }

    const methodSelect = page.locator(".cases__bar .el-select").first();
    await methodSelect.click();
    const methodOptionText = await page.locator(".el-select-dropdown__item").allTextContents();
    check(
      "方法筛选展示中文标签与数量",
      methodOptionText.some((item) => /等价类/.test(item) && /\d+/.test(item)),
      methodOptionText.join(" / "),
    );
    check(
      "方法筛选不直接展示英文枚举",
      methodOptionText.every((item) => !/^(equivalence|boundary|scenario|decision_table|cause_effect|orthogonal)/.test(item.trim())),
      methodOptionText.join(" / "),
    );
    await page.keyboard.press("Escape");

    await page.locator(".el-table__expand-icon").first().click();
    await page.waitForTimeout(150);
    const detailText = await page.locator(".detail").first().textContent();
    check(
      "展开区覆盖标签 / 备注 / 来源与证据",
      /标签/.test(detailText ?? "") &&
        /备注/.test(detailText ?? "") &&
        /来源/.test(detailText ?? "") &&
        /原文证据/.test(detailText ?? ""),
      (detailText ?? "").slice(0, 120),
    );
    await page.locator(".el-table__expand-icon").first().click();
    const clampOk = await page.$$eval(".wl__text", (nodes) =>
      nodes.every((node) => node.scrollHeight <= node.clientHeight + 4),
    );
    check("单条提示限高，不会无限拉长", clampOk);

    // 几百条用例全部铺在一页里，页面会长到无法使用；分页是刚需。
    const pagerVisible = await page.$(".cases__pager");
    const renderedRows = await page.$$eval(".el-table__body-wrapper tbody tr", (nodes) => nodes.length);
    check(
      "用例表分页，不再一次渲染几百行",
      Boolean(pagerVisible) && renderedRows <= 50,
      `单页渲染 ${renderedRows} 行`,
    );
    await page.screenshot({ path: path.join(OUT, "generate-warnings-expanded.png"), fullPage: true });

    // 把上限压到很小，验证两件事：告警数字自洽（截断前 / 保留 / 去重后），
    // 以及"截断不再饿死后执行的方法"——这两种情况只在小上限下才会暴露。
    await page.locator('.field:has-text("单条需求用例上限") input').fill("12");
    await page.locator('.field:has-text("单条需求用例上限") input').press("Enter");
    await page.locator(".sticky-actions .el-button--primary").click();
    const confirmAgain = page.getByRole("button", { name: "开始生成" });
    if (await confirmAgain.isVisible({ timeout: 1500 }).catch(() => false)) {
      await confirmAgain.click();
    }
    await page.waitForSelector(".wl__text", { timeout: 90_000 });
    await page.waitForTimeout(300);
    const truncationText = await page.$$eval(".wl__text", (nodes) => nodes.map((n) => n.textContent).join(" | "));
    check(
      "小上限下告警给出三个口径",
      /生成 \d+ 条/.test(truncationText) &&
        /按方法轮转保留 \d+ 条/.test(truncationText) &&
        /去重合并后本需求 \d+ 条/.test(truncationText),
      truncationText.slice(0, 120),
    );
    const methodCount = await page.evaluate(async () => {
      const suites = await (await fetch("/api/v1/testcases/suites?limit=1")).json();
      const suite = await (await fetch(`/api/v1/testcases/${suites.data[0].suite_id}`)).json();
      return new Set(suite.data.cases.map((item) => item.design_method)).size;
    });
    check("小上限下六种方法都还在结果里", methodCount === 6, `结果中出现 ${methodCount} 种方法`);
    await page.screenshot({ path: path.join(OUT, "generate-truncated.png"), fullPage: true });

    // 窄屏最容易暴露溢出：390px 下再量一次。
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const narrow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    if (narrow.scroll > narrow.client + 1) {
      // 溢出时必须点出「谁把页面撑宽了」，否则只能靠肉眼在长页面里找。
      const offenders = await page.evaluate(() => {
        const limit = document.documentElement.clientWidth;
        return [...document.querySelectorAll("body *")]
          .filter((node) => node.getBoundingClientRect().right > limit + 1)
          .slice(0, 8)
          .map((node) => ({
            tag: node.tagName.toLowerCase(),
            cls: typeof node.className === "string" ? node.className.slice(0, 48) : "",
            right: Math.round(node.getBoundingClientRect().right),
            width: Math.round(node.getBoundingClientRect().width),
          }));
      });
      console.log("---- 溢出元素 ----");
      offenders.forEach((item) => console.log(`  ${item.tag}.${item.cls} right=${item.right} width=${item.width}`));
    }
    check(
      "窄屏（390px）也不横向溢出",
      narrow.scroll <= narrow.client + 1,
      `scrollWidth=${narrow.scroll} clientWidth=${narrow.client}`,
    );
    await page.screenshot({ path: path.join(OUT, "generate-warnings-mobile.png"), fullPage: true });

    // 深色模式下也过一眼：新组件必须跟着主题令牌走，而不是只在浅色下好看。
    // 用顶栏按钮切换（不 reload），否则页面状态会被重置、结果区就看不到提示了。
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.getByTitle("切换到深色护眼模式").click();
    await page.waitForTimeout(400);
    const darkOverflow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
      theme: document.documentElement.dataset.theme,
    }));
    check(
      "深色模式下无横向溢出",
      darkOverflow.theme === "dark" && darkOverflow.scroll <= darkOverflow.client + 1,
      `theme=${darkOverflow.theme} scrollWidth=${darkOverflow.scroll}`,
    );
    await page.screenshot({ path: path.join(OUT, "generate-warnings-dark.png") });
    await page.getByTitle("切换到冰川蓝白（浅色）").click();

    console.log("\n=== 生成阶段的大模型复核与补充（review / enhance） ===");
    // 打开「生成用大模型」，参与方式选「复核规则产出」。
    await page.locator('.switch:has-text("生成用大模型") .el-switch').click();
    await page.getByRole("tab", { name: "复核规则产出" }).click();
    await page.locator(".sticky-actions .el-button--primary").click();
    const confirmThird = page.getByRole("button", { name: "开始生成" });
    if (await confirmThird.isVisible({ timeout: 1500 }).catch(() => false)) {
      await confirmThird.click();
    }
    await page.waitForSelector(".rf", { timeout: 90_000 });
    const findingCount = await page.$$eval(".rf__list li", (nodes) => nodes.length);
    check("复核模式给出核对意见", findingCount >= 1, `${findingCount} 条`);
    const zeroRewrite = await page.evaluate(() => {
      // 规则用例不得被改写：复核只产出意见，不产生 [LLM补充] 用例。
      return !document.body.innerText.includes("[LLM补充]");
    });
    check("复核不改写规则用例（无 LLM补充 用例）", zeroRewrite);
    const callsChip = await page.locator(".chip", { hasText: "模型调用" }).count();
    check("界面显示本次模型调用次数", callsChip === 1, `chip 数量 ${callsChip}`);
    await page.screenshot({ path: path.join(OUT, "generate-review-findings.png"), fullPage: false });

    await page.getByRole("tab", { name: "复核 + 补充用例" }).click();
    await page.locator(".sticky-actions .el-button--primary").click();
    const confirmFourth = page.getByRole("button", { name: "开始生成" });
    if (await confirmFourth.isVisible({ timeout: 1500 }).catch(() => false)) {
      await confirmFourth.click();
    }
    await page.waitForSelector(".rf", { timeout: 90_000 });
    await page.fill(".cases__search input", "LLM补充");
    await page.waitForTimeout(400);
    const supplementRows = await page.$$eval(".el-table__body-wrapper tbody tr", (nodes) => nodes.length);
    const supplementText = await page.$eval(".cases__count", (node) => node.textContent.trim());
    check("enhance 模式补充了用例", supplementRows >= 1, `${supplementText}`);
    await page.screenshot({ path: path.join(OUT, "generate-enhance-supplement.png"), fullPage: false });
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  console.log("\n" + "=".repeat(64));
  console.log(`通过 ${passes.length} 项，失败 ${problems.length} 项`);
  problems.forEach((item) => console.log(`  ! ${item}`));
  console.log(`截图目录：${OUT}`);
  return problems.length ? 1 : 0;
}

process.exitCode = await main();
