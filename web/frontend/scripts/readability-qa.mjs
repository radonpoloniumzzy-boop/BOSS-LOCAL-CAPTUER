import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright";
import { createServer } from "vite";

const VIEWPORTS = [
  { label: "1920x1080", width: 1920, height: 1080 },
  { label: "1440x900", width: 1440, height: 900 },
  { label: "1280x720", width: 1280, height: 720 },
  { label: "760x720", width: 760, height: 720 },
];

const outputDir = process.env.READABILITY_QA_DIR || join(tmpdir(), "boss-local-readability-qa");
mkdirSync(outputDir, { recursive: true });

const appStatus = {
  status: "ready",
  version: "0.2.0",
  database_ready: true,
  data_dir: "D:/mock-workbench-data",
  candidate_count: 2,
  batch_count: 2,
  latest_batch_id: 42,
  latest_batch_status: "completed",
};

const candidateRows = [
  {
    id: 1,
    name: "林知夏",
    source_platform: "boss",
    latest_source_platform: "boss",
    latest_source_job_title: "高级证券交易员 / 量化交易支持与机构业务协同方向（超长岗位标题用于换行验证）",
    latest_batch_id: 42,
    latest_capture_time: "2026-08-18T10:30:00",
    latest_ingest_status: "updated",
    latest_batch_role_id: null,
    has_role_binding: false,
    batch_count: 3,
  },
  {
    id: 2,
    name: "周明",
    source_platform: "liepin",
    latest_source_platform: "liepin",
    latest_source_job_title: "渠道销售",
    latest_batch_id: 41,
    latest_capture_time: "2026-08-17T20:10:00",
    latest_ingest_status: "new",
    latest_batch_role_id: 9,
    has_role_binding: true,
    batch_count: 1,
  },
];

const candidateDetail = {
  ...candidateRows[0],
  job_title: "",
  source_url:
    "https://example.com/source/very/long/url/that/should/wrap/properly/without/breaking/the/layout?query=alpha-beta-gamma-delta-epsilon-zeta",
  capture_time: "2026-08-18T10:30:00",
  raw_card_text:
    "姓名：林知夏\n城市：上海\n经历：7年证券交易与机构协作经验\n\n这是一段比较长的原始卡片快照，用来验证默认预览、展开、收起和复制行为。\n\n链接：https://example.com/really/long/raw/snapshot/url/that/should-wrap-safely-without-forcing-horizontal-overflow\n\n技能：期权、做市、TCA、Python、执行算法、交易风控。\n\n补充说明：这里继续放一些较长的连续文字，确保超长内容也能自然换行而不是把抽屉撑坏。",
  active_status: "",
  expected_salary: "",
  work_experience_text: "7年",
  education_text: "",
  tags_text: "证券, 做市, 量化协作",
  summary_text: "负责交易执行、盘中风控与机构协同，熟悉高频节奏下的策略落地与复盘。",
  detail_url: "https://example.com/candidate/detail/lin-zhixia",
  latest_raw_card_text:
    "姓名：林知夏\n城市：上海\n近一年：负责机构交易支持与盘中协同\n\n这是最近一次保存的原始卡片快照，用来验证详情区的阅读体验。\n\n长链接：https://example.com/latest/detail/url/that/should-wrap-cleanly-and-remain-readable-even-on-narrow-viewports",
  latest_source_url: "https://example.com/latest/source/lin-zhixia",
  latest_detail_url: "https://example.com/latest/detail/lin-zhixia",
  city: "上海",
  years_experience: 7,
  job_family: "",
  job_track: "",
  batch_count: 3,
};

const batchRows = [
  {
    id: 42,
    start_time: "2026-08-18T10:31:00",
    source_platform: "boss",
    total_collected: 2,
    total_new: 1,
    total_updated: 1,
    total_skipped: 0,
    total_failed: 0,
    status: "completed",
    role_id: null,
  },
  {
    id: 41,
    start_time: "2026-08-17T20:11:00",
    source_platform: "liepin",
    total_collected: 1,
    total_new: 1,
    total_updated: 0,
    total_skipped: 0,
    total_failed: 0,
    status: "completed",
    role_id: 9,
  },
];

const batchCandidates = [
  {
    id: 1001,
    batch_id: 42,
    candidate_id: 1,
    name: "林知夏",
    source_platform: "boss",
    platform_uid: "boss:1",
    job_title: "高级证券交易员 / 量化交易支持与机构业务协同方向（超长岗位标题用于换行验证）",
    capture_time: "2026-08-18T10:30:00",
    raw_card_text:
      "原始快照 1\n\n一长段说明文字，确保批次快照阅读器能处理很长的内容。\n\nhttps://example.com/very/long/snapshot/link/that/needs/to/wrap/without/breaking/the/drawer/layout",
    ingest_status: "updated",
    has_role_binding: false,
  },
  {
    id: 1002,
    batch_id: 42,
    candidate_id: 2,
    name: "周明",
    source_platform: "boss",
    platform_uid: "boss:2",
    job_title: "机构业务交易支持",
    capture_time: "2026-08-18T10:29:00",
    raw_card_text: "原始快照 2\n\n用于验证上一位/下一位切换。",
    ingest_status: "new",
    has_role_binding: true,
  },
];

function json(body) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  };
}

async function installMockApi(page) {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;

    if (pathname === "/api/setup/status") {
      return route.fulfill(json({
        setup_required: false,
        suggested_data_dir: "",
        configured_data_dir: "D:/mock-workbench-data",
        existing_database_detected: true,
      }));
    }
    if (pathname === "/api/health") {
      return route.fulfill(json({
        status: "ok",
        service: "recruiting-talent-workbench",
        version: "0.2.0",
        capabilities: ["phase2c_pairing", "batch_markdown_export", "m2a_job_task_foundation"],
      }));
    }
    if (pathname === "/api/app/status") return route.fulfill(json(appStatus));
    if (pathname === "/api/plugin-connection/status") {
      return route.fulfill(json({
        service_ok: true,
        api_base: "http://127.0.0.1:17864",
        connected: false,
        last_verified_at: null,
        data_dir: "D:/mock-workbench-data",
      }));
    }
    if (pathname === "/api/candidates") {
      return route.fulfill(json({ rows: candidateRows, total: 2, page: 1, page_size: 100 }));
    }
    if (pathname === "/api/candidates/1") return route.fulfill(json(candidateDetail));
    if (pathname === "/api/candidates/1/appearances") {
      return route.fulfill(json({
        rows: [
          {
            batch_id: 42,
            source_platform: "boss",
            source_job_title: candidateRows[0].latest_source_job_title,
            capture_time: "2026-08-18T10:30:00",
            ingest_status: "updated",
          },
        ],
      }));
    }
    if (pathname === "/api/capture-batches") {
      return route.fulfill(json({
        rows: batchRows,
        total: 2,
        page: 1,
        page_size: 20,
        today_summary: { received: 2, added: 1 },
      }));
    }
    if (pathname === "/api/capture-batches/42") return route.fulfill(json(batchRows[0]));
    if (pathname === "/api/capture-batches/42/candidates") {
      return route.fulfill(json({ rows: batchCandidates, total: 2, page: 1, page_size: 50 }));
    }
    if (pathname === "/api/capture-batches/42/export.md") {
      return route.fulfill({
        status: 200,
        contentType: "text/markdown",
        headers: { "Content-Disposition": "attachment; filename*=UTF-8''batch-42.md" },
        body: "# Batch 42\n\nmock export",
      });
    }

    return route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "not_found", message: "mock route not found" } }),
    });
  });
}

async function openWorkbench(page, url) {
  await page.goto(url, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "进入工作台" }).click();
  await page.getByRole("button", { name: "候选人" }).waitFor();
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function intersects(first, second) {
  return !(
    first.x + first.width <= second.x ||
    second.x + second.width <= first.x ||
    first.y + first.height <= second.y ||
    second.y + second.height <= first.y
  );
}

async function assertNoVerticalText(page, label) {
  const offenders = await page.evaluate(() => {
    const visible = Array.from(document.querySelectorAll("th, td, h1, h2, h3, button, a, .line-clamp-2"))
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const text = element.textContent?.trim() || "";
        return text.length >= 3 && rect.width > 0 && rect.height > 0;
      })
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          text: element.textContent?.trim().slice(0, 32),
          width: rect.width,
          height: rect.height,
        };
      });
    return visible.filter((item) => item.width < 18 && item.height > item.width * 3);
  });
  assert(offenders.length === 0, `${label}: found vertically squeezed text ${JSON.stringify(offenders)}`);
}

async function assertDrawerWithinViewport(page, label, dialogName) {
  const box = await page.getByRole("dialog", { name: dialogName }).boundingBox();
  const viewport = page.viewportSize();
  assert(box && viewport, `${label}: drawer ${dialogName} missing`);
  assert(box.x >= -1, `${label}: drawer ${dialogName} starts outside viewport`);
  assert(box.y >= -1, `${label}: drawer ${dialogName} starts above viewport`);
  assert(
    box.x + box.width <= viewport.width + 1,
    `${label}: drawer ${dialogName} exceeds viewport width (${JSON.stringify({ box, viewport })})`,
  );
  assert(
    box.y + box.height <= viewport.height + 1,
    `${label}: drawer ${dialogName} exceeds viewport height (${JSON.stringify({ box, viewport })})`,
  );
}

async function assertVisibleHeadingAndClose(page, label, headingName, closeName) {
  await page.getByRole("heading", { name: headingName }).waitFor();
  await page.getByRole("button", { name: closeName }).waitFor();
  const headingVisible = await page.getByRole("heading", { name: headingName }).isVisible();
  const closeVisible = await page.getByRole("button", { name: closeName }).isVisible();
  assert(headingVisible, `${label}: heading ${headingName} is not visible`);
  assert(closeVisible, `${label}: close button ${closeName} is not visible`);
}

async function assertTableHasScrollContract(page, label) {
  const result = await page.evaluate(() => {
    const scroller = Array.from(document.querySelectorAll(".table-scroll")).find((element) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    const table = scroller?.querySelector("table");
    const headers = Array.from(table?.querySelectorAll("th") || []).map((header) => ({
      text: header.textContent?.trim() || "",
      width: header.getBoundingClientRect().width,
    }));
    const textColumns = headers.filter((header) => ["候选人", "来源岗位"].includes(header.text));
    return {
      hasScroller: Boolean(scroller),
      scrollerClient: scroller?.clientWidth || 0,
      scrollerScroll: scroller?.scrollWidth || 0,
      minTextColumnWidth: textColumns.length ? Math.min(...textColumns.map((header) => header.width)) : 0,
    };
  });
  assert(result.hasScroller, `${label}: table scroller missing`);
  assert(result.minTextColumnWidth >= 80, `${label}: key table text columns are too compressed`);
  if ((page.viewportSize()?.width || 0) <= 760) {
    assert(result.scrollerScroll > result.scrollerClient, `${label}: narrow table should use horizontal scroll`);
  }
}

async function assertMobileBreakpointContract(page, label) {
  if ((page.viewportSize()?.width || 0) > 760) return;
  const result = await page.evaluate(() => {
    const panel = Array.from(document.querySelectorAll(".drawer-panel")).find((element) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    const header = document.querySelector(".detail-header");
    return {
      drawerPadding: panel ? window.getComputedStyle(panel).paddingTop : "",
      detailHeaderColumns: header ? window.getComputedStyle(header).gridTemplateColumns : "",
    };
  });
  assert(result.drawerPadding === "18px", `${label}: mobile drawer padding did not apply`);
  assert(!result.detailHeaderColumns.includes("auto"), `${label}: mobile detail header layout did not apply`);
}

async function assertNoDrawerHorizontalOverflow(page, label) {
  const result = await page.evaluate(() => {
    const panel = Array.from(document.querySelectorAll(".drawer-panel")).find((element) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    return panel
      ? {
          clientWidth: panel.clientWidth,
          scrollWidth: panel.scrollWidth,
        }
      : null;
  });
  assert(result, `${label}: drawer panel missing`);
  assert(result.scrollWidth <= result.clientWidth + 2, `${label}: drawer content overflows horizontally`);
}

async function assertButtonsDoNotOverlap(page, label) {
  const boxes = await page.locator("button:visible").evaluateAll((buttons) =>
    buttons.filter((button) => {
      const topDrawer = Array.from(document.querySelectorAll(".drawer-panel")).find((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      });
      return topDrawer ? topDrawer.contains(button) : !button.closest("[hidden], [aria-hidden='true']");
    }).map((button) => {
      const rect = button.getBoundingClientRect();
      return { text: button.textContent?.trim() || button.getAttribute("aria-label") || "", x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    }).filter((box) => box.width > 0 && box.height > 0),
  );
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      if (intersects(boxes[i], boxes[j])) {
        throw new Error(`${label}: buttons overlap ${JSON.stringify([boxes[i], boxes[j]])}`);
      }
    }
  }
}

async function capture(page, label, stateName) {
  const path = join(outputDir, `${label}-${stateName}.png`);
  await page.screenshot({ path, fullPage: true });
  return path;
}

async function runViewport(browser, baseUrl, viewport) {
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, locale: "zh-CN" });
  const page = await context.newPage();
  await installMockApi(page);
  await openWorkbench(page, baseUrl);

  const evidence = [];
  await page.getByRole("button", { name: "候选人" }).click();
  await page.getByRole("button", { name: "查看详情" }).first().waitFor();
  await assertNoVerticalText(page, `${viewport.label} candidate list`);
  await assertTableHasScrollContract(page, `${viewport.label} candidate list`);
  await assertButtonsDoNotOverlap(page, `${viewport.label} candidate list`);
  evidence.push(await capture(page, viewport.label, "candidates-list"));

  await page.getByRole("button", { name: "查看详情" }).first().click();
  await page.getByRole("dialog", { name: "候选人详情" }).waitFor();
  await assertVisibleHeadingAndClose(page, `${viewport.label} candidate detail`, "林知夏", "关闭候选人详情");
  await assertDrawerWithinViewport(page, `${viewport.label} candidate detail`, "候选人详情");
  await assertMobileBreakpointContract(page, `${viewport.label} candidate detail`);
  await assertNoDrawerHorizontalOverflow(page, `${viewport.label} candidate detail`);
  await assertNoVerticalText(page, `${viewport.label} candidate detail`);
  await assertButtonsDoNotOverlap(page, `${viewport.label} candidate detail`);
  evidence.push(await capture(page, viewport.label, "candidate-detail"));

  await page.getByRole("button", { name: /打开最近批次 #42/ }).click();
  await page.getByRole("heading", { name: "批次 #42" }).waitFor();
  await page.getByRole("button", { name: "查看原始快照" }).first().waitFor();
  await assertNoVerticalText(page, `${viewport.label} batch detail`);
  await assertTableHasScrollContract(page, `${viewport.label} batch detail`);
  await assertButtonsDoNotOverlap(page, `${viewport.label} batch detail`);
  evidence.push(await capture(page, viewport.label, "batch-detail"));

  await page.getByRole("button", { name: "查看原始快照" }).first().click();
  await page.getByRole("dialog", { name: "原始快照" }).waitFor();
  await assertVisibleHeadingAndClose(page, `${viewport.label} snapshot drawer`, "林知夏", "关闭原始快照");
  await assertDrawerWithinViewport(page, `${viewport.label} snapshot drawer`, "原始快照");
  await assertMobileBreakpointContract(page, `${viewport.label} snapshot drawer`);
  await assertNoDrawerHorizontalOverflow(page, `${viewport.label} snapshot drawer`);
  await assertNoVerticalText(page, `${viewport.label} snapshot drawer`);
  await assertButtonsDoNotOverlap(page, `${viewport.label} snapshot drawer`);
  evidence.push(await capture(page, viewport.label, "snapshot-drawer"));

  await context.close();
  return evidence;
}

async function tabUntil(page, predicate, label, maxTabs = 32) {
  for (let index = 0; index < maxTabs; index += 1) {
    await page.keyboard.press("Tab");
    const current = await page.evaluate(() => {
      const active = document.activeElement;
      return {
        text: active?.textContent || "",
        aria: active?.getAttribute?.("aria-label") || "",
        tag: active?.tagName || "",
      };
    });
    if (predicate(current)) return current;
  }
  throw new Error(`Unable to reach focus target: ${label}`);
}

async function focusStyle(page) {
  return page.evaluate(() => {
    const active = document.activeElement;
    const style = active ? window.getComputedStyle(active) : null;
    return {
      text: active?.textContent?.trim() || "",
      aria: active?.getAttribute?.("aria-label") || "",
      boxShadow: style?.boxShadow || "",
      outlineStyle: style?.outlineStyle || "",
      outlineWidth: style?.outlineWidth || "",
    };
  });
}

function assertFocusRing(style, label) {
  const hasRing = style.boxShadow !== "none" || (style.outlineStyle !== "none" && style.outlineWidth !== "0px");
  assert(hasRing, `${label}: focus ring is not visible (${JSON.stringify(style)})`);
}

async function runAccessibilityChecks(browser, baseUrl) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-CN" });
  const page = await context.newPage();
  await installMockApi(page);
  await openWorkbench(page, baseUrl);
  await page.getByRole("button", { name: "候选人" }).click();
  await page.getByRole("button", { name: "查看详情" }).first().waitFor();

  await tabUntil(page, (current) => current.text.includes("最近批次"), "navigation button");
  const button = await focusStyle(page);
  assertFocusRing(button, "button");

  await tabUntil(page, (current) => current.aria === "候选人搜索", "candidate search input");
  const input = await focusStyle(page);
  assertFocusRing(input, "input");

  await tabUntil(page, (current) => current.aria === "来源平台", "source platform select");
  const select = await focusStyle(page);
  assertFocusRing(select, "select");

  await page.getByRole("button", { name: "查看详情" }).first().click();
  await page.getByRole("dialog", { name: "候选人详情" }).waitFor();
  await tabUntil(page, (current) => current.text.includes("打开来源页面"), "external link");
  const link = await focusStyle(page);
  assertFocusRing(link, "external link");

  await tabUntil(page, (current) => current.text.includes("展开完整快照"), "drawer button");
  const drawerButton = await focusStyle(page);
  assertFocusRing(drawerButton, "drawer button");

  const screenshot = await capture(page, "1440x900", "focus-visible");
  await context.close();

  const motion = {};
  for (const reducedMotion of ["no-preference", "reduce"]) {
    const motionContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion, locale: "zh-CN" });
    const motionPage = await motionContext.newPage();
    await installMockApi(motionPage);
    await openWorkbench(motionPage, baseUrl);
    await motionPage.getByRole("button", { name: "候选人" }).click();
    await motionPage.getByRole("button", { name: "查看详情" }).first().click();
    await motionPage.getByRole("dialog", { name: "候选人详情" }).waitFor();
    motion[reducedMotion] = await motionPage.evaluate(() => {
      const panel = document.querySelector(".drawer-panel");
      const style = panel ? window.getComputedStyle(panel) : null;
      return {
        animationName: style?.animationName || "",
        transform: style?.transform || "",
      };
    });
    await capture(motionPage, "1440x900", reducedMotion === "reduce" ? "motion-reduced" : "motion-normal");
    await motionContext.close();
  }

  assert(motion["no-preference"].animationName.includes("drawer-in"), "normal motion should keep drawer animation");
  assert(motion.reduce.animationName === "none", "reduced motion should disable drawer animation");
  assert(motion.reduce.transform === "none", "reduced motion should remove drawer transform");

  return { focus: { button, input, select, link, drawerButton, screenshot }, motion };
}

async function main() {
  let server = null;
  let browser = null;
  const report = { baseUrl: "", outputDir, viewports: {}, accessibility: null };
  try {
    server = await createServer({
      configFile: resolve("vite.config.ts"),
      server: { host: "127.0.0.1", port: 0 },
    });
    await server.listen();
    const address = server.httpServer.address();
    const port = typeof address === "object" && address ? address.port : 5173;
    const baseUrl = `http://127.0.0.1:${port}/`;
    report.baseUrl = baseUrl;

    browser = await chromium.launch({ headless: true });
    for (const viewport of VIEWPORTS) {
      report.viewports[viewport.label] = await runViewport(browser, baseUrl, viewport);
    }
    report.accessibility = await runAccessibilityChecks(browser, baseUrl);

    const reportPath = join(outputDir, "readability-qa-report.json");
    writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
    console.log(`Readability QA passed. Report: ${reportPath}`);
  } finally {
    const cleanup = [];
    if (browser) cleanup.push(browser.close());
    if (server) cleanup.push(server.close());
    const results = await Promise.allSettled(cleanup);
    for (const result of results) {
      if (result.status === "rejected") {
        console.warn("Readability QA cleanup warning:", result.reason);
      }
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
