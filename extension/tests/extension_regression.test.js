const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXTENSION_DIR = path.resolve(__dirname, "..");

function createChromeMock() {
  const store = {};
  const downloadCalls = [];
  return {
    __store: store,
    __downloadCalls: downloadCalls,
    runtime: {
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
      onMessage: { addListener() {} },
    },
    tabs: {
      onRemoved: { addListener() {} },
      async get(id) {
        return { id: Number(id), windowId: 1, url: "https://www.zhipin.com/web/chat/index" };
      },
      async query() {
        return [];
      },
      async sendMessage() {
        return { ok: true };
      },
      async remove() {},
      async update() {},
    },
    scripting: {
      async executeScript() {
        return [];
      },
    },
    storage: {
      local: {
        async get(key) {
          if (typeof key === "string") {
            return { [key]: store[key] };
          }
          return { ...store };
        },
        async set(value) {
          Object.assign(store, value);
        },
      },
    },
    downloads: {
      async download(payload) {
        downloadCalls.push(payload);
        return 527;
      },
      async search() {
        return [];
      },
    },
  };
}

function createFetchMock(contentTypeByUrl = {}) {
  return async function fetchMock(url) {
    const textUrl = String(url || "");
    const contentType = Object.entries(contentTypeByUrl).find(([key]) => textUrl.includes(key))?.[1] || "text/html";
    return {
      ok: true,
      url: textUrl,
      headers: {
        get(name) {
          return String(name || "").toLowerCase() === "content-type" ? contentType : "";
        },
      },
      body: {
        cancel() {},
      },
    };
  };
}

function loadServiceWorker(fetch = createFetchMock()) {
  const chrome = createChromeMock();
  const code = `${fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8")}
globalThis.__serviceTest = {
  downloadResume,
  getBatchStatus,
  handleBatchProgress,
  hasDirectPdfSignal,
  isValidResumeDownload,
  saveBatchStatus,
  shouldVerifyPdfBeforeDownload,
  stopBatch,
};`;
  const context = {
    URL,
    chrome,
    clearTimeout,
    console,
    fetch,
    globalThis: {},
    setTimeout,
  };
  context.globalThis = context;
  vm.runInNewContext(code, context, { filename: "service_worker.js" });
  return { chrome, api: context.__serviceTest };
}

async function testDownloadEndpointValidation() {
  const { api } = loadServiceWorker();
  const downloadUrl = "https://www.zhipin.com/wflow/zpgeek/download/preview4boss/abc123?d=1&id=xyz";
  assert.strictEqual(api.hasDirectPdfSignal(downloadUrl, ""), false);
  assert.strictEqual(api.isValidResumeDownload(downloadUrl, "candidate.pdf"), false);
  assert.strictEqual(api.shouldVerifyPdfBeforeDownload(downloadUrl, "candidate.pdf"), true);
  assert.strictEqual(api.isValidResumeDownload("https://img.bosszhipin.com/static/file/icon.png", "candidate.pdf"), false);
}

async function testStopGuardIgnoresStaleProgress() {
  const { api } = loadServiceWorker();
  await api.saveBatchStatus({
    running: true,
    stopRequested: false,
    phase: "running",
    mode: "download_only",
    tabId: 7,
    stats: { processed: 1 },
    runtimeLogs: [],
  });

  await api.stopBatch(7, "manual stop");
  let status = await api.getBatchStatus();
  assert.strictEqual(status.running, false);
  assert.strictEqual(status.phase, "stopped");

  await api.handleBatchProgress(
    {
      running: true,
      phase: "running",
      message: "stale runner progress",
      stats: { processed: 99 },
      runtimeLogs: ["stale"],
    },
    { tab: { id: 7, windowId: 1, url: "https://www.zhipin.com/web/chat/index" } },
  );

  status = await api.getBatchStatus();
  assert.strictEqual(status.running, false);
  assert.strictEqual(status.phase, "stopped");
  assert.notStrictEqual(status.message, "stale runner progress");
  assert.notStrictEqual(status.stats.processed, 99);
}

async function testBackgroundDownloadIsCalledAndLogged() {
  const { api, chrome } = loadServiceWorker(createFetchMock({ "real-pdf": "application/pdf" }));
  await api.saveBatchStatus({ running: true, phase: "running", tabId: 7, runtimeLogs: [] });
  const url = "https://www.zhipin.com/wflow/zpgeek/download/real-pdf/abc123?d=1&id=xyz";

  const result = await api.downloadResume({
    url,
    fileName: "BossResumes/candidate.pdf",
    trustedPdf: false,
  });

  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.downloadId, 527);
  assert.strictEqual(chrome.__downloadCalls.length, 1);
  assert.strictEqual(chrome.__downloadCalls[0].url, url);
  const status = await api.getBatchStatus();
  assert(status.runtimeLogs.some((line) => line.includes("background download request")));
  assert(status.runtimeLogs.some((line) => line.includes("background download verified pdf")));
  assert(status.runtimeLogs.some((line) => line.includes("chrome.downloads.download ok")));
}

async function testHtmlPreviewPageIsNotDownloadedAsPdf() {
  const { api, chrome } = loadServiceWorker(createFetchMock({ preview4boss: "text/html" }));
  await api.saveBatchStatus({ running: true, phase: "running", tabId: 7, runtimeLogs: [] });
  const url = "https://www.zhipin.com/wflow/zpgeek/download/preview4boss/abc123?d=1&id=xyz";

  const result = await api.downloadResume({
    url,
    fileName: "BossResumes/candidate.pdf",
    trustedPdf: false,
  });

  assert.strictEqual(result.ok, false);
  assert.strictEqual(chrome.__downloadCalls.length, 0);
  assert(String(result.error || "").includes("不是 PDF"));
  const status = await api.getBatchStatus();
  assert(status.runtimeLogs.some((line) => line.includes("url is not pdf after probe")));
}

function testChatRunnerHasPendingAttachmentFlow() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("async function acceptPendingAttachmentRequests"));
  assert(source.includes("isPendingAttachmentRequestText"));
  assert(source.includes("accepted pending attachment requests"));
  assert(source.includes("includePending: true"));
  assert(source.includes("pendingAccept"));
}

function testChatRunnerHandlesTwoResumeRequestButtons() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("topRequestResume"));
  assert(source.includes("isLikelyHeaderResumeActionButton"));
  assert(source.includes("waitForRequestResumeButton"));
  assert(source.includes("messageContainer?.contains(node)"));
  assert(source.includes("isLikelyRequestResumeAction"));
  assert(source.includes("isRequestResumeButtonUsable"));
  assert(source.includes("messageOnly"));
  assert(source.includes("双方回复后可用"));
}

function testBatchModesAreSeparated() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("已完成 ${runnerState.currentSession} 的话术发送和求简历/附件简历操作。"));
  assert(source.includes("async function requestAndDownload"));
  assert(source.includes("async function processDownloadOnlySession"));
  assert(!source.includes("request flow download ok"));
  assert(!source.includes("开始等待附件简历"));
}

function testPreviewClickAvoidsAttachmentCardFalsePositive() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("async function openAttachmentPreview"));
  assert(source.includes("function findPreviewTargets"));
  assert(source.includes("isExplicitPreviewActionText"));
  assert(source.includes("open preview attempt"));
  assert(source.includes("messageContainer && messageContainer.contains(node)"));
  assert(source.includes("已找到预览入口，但未能打开附件预览。"));
}

function testBatchPausesOnVerification() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("function detectAccountVerificationBlock"));
  assert(source.includes("账号登录异常"));
  assert(source.includes("检测到账号验证/登录异常"));
  assert(source.includes("batchActionDelayMs"));
}

function testBatchThrottlingAndLimit() {
  const runner = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(runner.includes("function hasReachedBatchLimit"));
  assert(runner.includes("本批次已达到"));
  assert(runner.includes("maxBatchSessions"));
  assert(runner.includes("5000"));
  assert(popup.includes("batchActionDelaySeconds: 5"));
  assert(popup.includes("maxBatchSessions: 50"));
  assert(html.includes("每人间隔秒数"));
  assert(html.includes("每批最多人数"));
}

function testRequestResumeConfirmIsRequired() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("waitForConfirmButton(3600"));
  assert(source.includes("function findRequestResumeConfirmButton"));
  assert(source.includes("request confirm button found"));
  assert(source.includes("request confirm still visible, retry same button"));
  assert(source.includes("findDialogLikeAncestorText"));
}

function testBatchRequestSkipsAlreadyRequestedConversation() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("function hasSentResumeRequestInConversation"));
  assert(source.includes("hasSentResumeRequestInConversation(runnerState.settings)"));
  assert(source.includes("session skipped: resume request already sent"));
  assert(source.includes("已发过求简历"));
  assert(source.includes("简历请求已发送"));
  assert(source.includes("buildResumeRequestHistoryPatterns"));
}

function testPreviewToolbarDownloadDoesNotSaveHtmlPreviewPage() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const service = fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8");
  const manifest = fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8");
  const topToolbarClickIndex = source.indexOf("const downloadButton = findVisibleDownloadButton()");
  const frameFallbackIndex = source.indexOf('type: "click_preview_download_button"');
  assert(source.includes("preview click download button"));
  assert(topToolbarClickIndex >= 0);
  assert(frameFallbackIndex > topToolbarClickIndex);
  assert(source.includes("top preview toolbar download"));
  assert(source.includes("frame semantic button"));
  assert(!source.includes("preview direct download url"));
  assert(!source.includes("downloadUrl: directUrl"));
  assert(!source.includes('type: "resolve_active_pdf_url"'));
  assert(!source.includes("fallback card download url"));
  assert(source.includes("function isHtmlDownloadResult"));
  assert(source.includes("html download rejected"));
  assert(source.includes("preview toolbar download failed"));
  assert(source.includes("function findPreviewToolbarDownloadByLayout"));
  assert(source.includes("preview toolbar download candidate"));
  assert(source.includes("preview toolbar layout candidates"));
  assert(source.includes("distanceToCloseLeft(left.rect, closeRect) - distanceToCloseLeft(right.rect, closeRect)"));
  assert(!source.includes("Math.abs(right.rect.right - closeRect.left) - Math.abs(left.rect.right - closeRect.left)"));
  assert(source.includes('type: "click_preview_download_button"'));
  assert(source.includes("preview frame download click"));
  assert(service.includes('case "click_preview_download_button"'));
  assert(service.includes("async function clickPreviewDownloadButtonInFrames"));
  assert(service.includes("target: { tabId: targetTab.id, allFrames: true }"));
  assert(service.includes("button[name='download-pdf']"));
  assert(service.includes("button[name='download-image']"));
  assert(service.includes("semantic download button missing"));
  assert(!service.includes('document.querySelectorAll("button, a, [role=\'button\'], [title], [aria-label], div, span, i, svg")'));
  assert(manifest.includes("https://*.weizhipin.com/*"));
  assert(source.includes('fileNameHint: ""'));
}

function testCollectionSupportsBossAndLiepinAdapters() {
  const collector = fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const manifest = fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8");
  assert(collector.includes("PLATFORM_ADAPTERS"));
  assert(collector.includes('id: "boss"'));
  assert(collector.includes('id: "liepin"'));
  assert(collector.includes("__bossLocalCollectorPlatforms"));
  assert(collector.includes("findCandidateCardsBySelectors"));
  assert(collector.includes("getScrollRoot(platform)"));
  assert(collector.includes("lpt.liepin.com"));
  assert(popup.includes("COLLECT_PLATFORMS"));
  assert(popup.includes("getActiveSupportedTab"));
  assert(popup.includes("getActiveBossTab"));
  assert(popup.includes("applyPlatformDefaults"));
  assert(popup.includes("猎聘推荐人才"));
  assert(html.includes("猎聘推荐页"));
  assert(manifest.includes("https://*.liepin.com/*"));
  assert(manifest.includes("Recruiting Local Capture"));
}

function testAutoScrollCanBePausedFromPopup() {
  const collector = fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(html.includes('id="pauseScroll"'));
  assert(html.includes("暂停滚动"));
  assert(popup.includes("requestScrollPause"));
  assert(popup.includes("resetScrollPause"));
  assert(popup.includes("__bossLocalRequestScrollPause"));
  assert(collector.includes("__bossLocalRequestScrollPause"));
  assert(collector.includes("__bossLocalResetScrollPause"));
  assert(collector.includes("paused-by-user"));
  assert(collector.includes("pause_requested"));
}

function testAutomationAutoButtonStartsDesktopWorkflow() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8"));
  assert(html.includes('id="automationAuto"'));
  assert(html.includes("滚动采集 + AI 初筛"));
  assert(popup.includes("async function runAutomation"));
  assert(popup.includes("/api/automation/start"));
  assert(popup.includes("automation_requested"));
  assert(popup.includes("AUTO 采集完成，已提交 AI 初筛"));
  assert.strictEqual(manifest.version, "0.3.27");
}

function testScrollWaitDefaultsToThirtyMillisecondsAndHasAdjusters() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(popup.includes("scrollWaitMs: 30"));
  assert(popup.includes("OLD_DEFAULT_SCROLL_WAIT_MS = 1500"));
  assert(popup.includes("scrollWaitDefaultVersion"));
  assert(popup.includes("adjustScrollWait(-30)"));
  assert(popup.includes("adjustScrollWait(30)"));
  assert(popup.includes("Math.max(Number(fields.scrollWaitMs.value || DEFAULTS.scrollWaitMs), 0)"));
  assert(html.includes('id="scrollWaitDown"'));
  assert(html.includes('id="scrollWaitUp"'));
  assert(html.includes('value="30"'));
  assert(html.includes('step="30"'));
}

function testRuntimeFingerprintAndVersionAwareRunnerInjection() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const service = fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  assert(service.includes("SERVICE_WORKER_DOWNLOAD_CLICK_REVISION"));
  assert(service.includes("runtimeFingerprint"));
  assert(service.includes("manifestVersion"));
  assert(service.includes("chatRunnerVersion"));
  assert(service.includes("runnerReplaced"));
  assert(service.includes("delete globalThis.__bossLocalChatBatchRunner"));
  assert(service.includes("expectedVersion"));
  assert(service.includes("staleRuntime"));
  assert(source.includes("runnerVersion"));
  assert(source.includes("runToken: runnerState.runToken"));
  assert(popup.includes("formatRuntimeFingerprint"));
}

async function main() {
  await testDownloadEndpointValidation();
  await testStopGuardIgnoresStaleProgress();
  await testBackgroundDownloadIsCalledAndLogged();
  await testHtmlPreviewPageIsNotDownloadedAsPdf();
  testChatRunnerHasPendingAttachmentFlow();
  testChatRunnerHandlesTwoResumeRequestButtons();
  testBatchModesAreSeparated();
  testPreviewClickAvoidsAttachmentCardFalsePositive();
  testBatchPausesOnVerification();
  testBatchThrottlingAndLimit();
  testRequestResumeConfirmIsRequired();
  testBatchRequestSkipsAlreadyRequestedConversation();
  testPreviewToolbarDownloadDoesNotSaveHtmlPreviewPage();
  testCollectionSupportsBossAndLiepinAdapters();
  testAutoScrollCanBePausedFromPopup();
  testAutomationAutoButtonStartsDesktopWorkflow();
  testScrollWaitDefaultsToThirtyMillisecondsAndHasAdjusters();
  testRuntimeFingerprintAndVersionAwareRunnerInjection();
  console.log("extension regression tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
