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

function createPopupElement(initial = {}) {
  return {
    value: "",
    checked: false,
    disabled: false,
    textContent: "",
    type: "text",
    listeners: {},
    addEventListener(event, handler) {
      this.listeners[event] = handler;
    },
    ...initial,
  };
}

function createPopupTestContext(options = {}) {
  const store = options.store || {};
  if (options.apiBase !== undefined) {
    store.apiBase = options.apiBase;
  }
  if (options.apiToken !== undefined) {
    store.apiToken = options.apiToken;
  }
  if (options.jobTitle !== undefined) {
    store.jobTitle = options.jobTitle;
  }
  const fetchCalls = [];
  const tabCreates = [];
  const activeTab = options.activeTab || {
    id: 7,
    url: "https://www.zhipin.com/web/geek/recommend",
  };
  const frameResult = options.frameResult || {
    cards: [
      {
        source_candidate_id: "boss-1",
        platform_uid: "boss:1",
        detail_url: "https://www.zhipin.com/candidate/1",
        raw_card_text: "候选人 A",
        name: "候选人 A",
      },
    ],
    meta: { platform: "boss", rounds_completed: 2 },
    frameUrl: activeTab.url,
  };
  const ids = [
    "jobTitle",
    "apiBase",
    "apiToken",
    "scrollMode",
    "scrollStep",
    "scrollWaitMs",
    "maxScrollCount",
    "noNewStopRounds",
    "resumeMessage",
    "waitSeconds",
    "pollIntervalMs",
    "batchActionDelaySeconds",
    "maxBatchSessions",
    "chatAutomationEnabled",
    "status",
    "batchStatus",
    "batchLog",
    "webIntakeStatus",
    "automationAuto",
    "pairingCode",
    "applyPairingCode",
    "downloadCurrentBatch",
    "retryWebIntake",
    "openWebWorkbench",
    "scrollWaitDown",
    "scrollWaitUp",
    "collectCurrent",
    "collectAuto",
    "pauseScroll",
    "requestResume",
    "downloadResume",
    "requestAndDownload",
    "startBatchRequest",
    "startBatchDownload",
    "stopBatch",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, createPopupElement()]));
  elements.chatAutomationEnabled.type = "checkbox";
  elements.apiBase.value = String(options.apiBase || store.apiBase || "http://127.0.0.1:17863");
  elements.apiToken.value = String(options.apiToken || store.apiToken || "token");
  elements.jobTitle.value = String(options.jobTitle || store.jobTitle || "Boss 推荐牛人");
  elements.scrollMode.value = "hold_end";
  elements.scrollStep.value = "900";
  elements.scrollWaitMs.value = "30";
  elements.maxScrollCount.value = "80";
  elements.noNewStopRounds.value = "4";
  elements.resumeMessage.value = "方便发一份你的简历过来吗？";
  elements.waitSeconds.value = "45";
  elements.pollIntervalMs.value = "2000";
  elements.batchActionDelaySeconds.value = "5";
  elements.maxBatchSessions.value = "50";
  elements.webIntakeStatus.textContent = "网页入库：等待发送。";

  const chrome = {
    storage: {
      local: {
        async get(key) {
          if (typeof key === "string") {
            return { [key]: store[key] };
          }
          if (Array.isArray(key)) {
            return Object.fromEntries(key.map((item) => [item, store[item]]));
          }
          return { ...key, ...store };
        },
        async set(value) {
          Object.assign(store, value);
        },
        async remove(key) {
          if (Array.isArray(key)) {
            for (const item of key) {
              delete store[item];
            }
            return;
          }
          delete store[key];
        },
      },
    },
    tabs: {
      async query() {
        return [activeTab];
      },
      async sendMessage() {
        return { ok: true };
      },
      async create(payload) {
        tabCreates.push(payload);
        return { id: 88, ...payload };
      },
    },
    scripting: {
      async executeScript(details) {
        if (details.args?.length === 2) {
          return [{ result: frameResult }];
        }
        return [];
      },
    },
    runtime: {
      async sendMessage() {
        return {
          ok: true,
          status: {
            running: false,
            phase: "idle",
            mode: "",
            stats: {},
            runtimeLogs: [],
            recentEvents: [],
          },
        };
      },
    },
  };

  const fetch = async (url, requestOptions = {}) => {
    fetchCalls.push({
      url: String(url),
      options: {
        ...requestOptions,
        headers: { ...(requestOptions.headers || {}) },
      },
    });
    if (typeof options.fetchImpl === "function") {
      return options.fetchImpl(url, requestOptions);
    }
    throw new Error(`Unexpected fetch: ${String(url)}`);
  };

  const context = {
    URL,
    Blob,
    chrome,
    console,
    fetch,
    clearInterval,
    clearTimeout,
    setTimeout,
    addEventListener() {},
    setInterval() {
      return 1;
    },
    window: null,
    document: {
      getElementById(id) {
        return elements[id] || createPopupElement();
      },
    },
    BossLocalBatchExport: {
      batchBelongsToConnection(previous, next) {
        if (!previous || !next) {
          return false;
        }
        return (
          String(previous.apiBase || "").replace(/\/+$/, "") === String(next.apiBase || "").replace(/\/+$/, "")
          && String(previous.apiToken || "") === String(next.apiToken || "")
        );
      },
      async downloadBatchCsv() {
        return { batchId: 1, filename: "batch.csv" };
      },
    },
    BossLocalPairing: {
      parsePairingCode(value) {
        if (String(value || "").includes("pair-token")) {
          return { apiBase: "http://127.0.0.1:17863", apiToken: "pair-token_123" };
        }
        throw new Error("连接码格式无效，请从桌面端设置页重新复制。");
      },
    },
    globalThis: {},
    __bossLocalPopupTestMode: true,
  };
  context.window = context;
  context.globalThis = context;

  const intakeSource = fs.readFileSync(path.join(EXTENSION_DIR, "web_intake.js"), "utf8");
  vm.runInNewContext(intakeSource, context, { filename: "web_intake.js" });
  const popupSource = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  vm.runInNewContext(popupSource, context, { filename: "popup.js" });

  return {
    api: context.BossLocalPopup,
    chrome,
    context,
    elements,
    fetchCalls,
    store,
    tabCreates,
  };
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
  const contentScript = fs.readFileSync(path.join(EXTENSION_DIR, "content_script.js"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8"));
  assert(html.includes('id="automationAuto"'));
  assert(html.includes("滚动采集 + AI 初筛"));
  assert(popup.includes("async function runAutomation"));
  assert(popup.includes("/api/automation/start"));
  assert(popup.includes("apiToken"));
  assert(popup.includes("X-Boss-Local-Token"));
  assert(contentScript.includes("X-Boss-Local-Token"));
  assert(html.includes('id="apiToken"'));
  assert(popup.includes("automation_requested"));
  assert(popup.includes("AUTO 采集完成，已提交 AI 初筛"));
  assert.strictEqual(manifest.version, "0.5.1");
}

function testChatAutomationIsOptIn() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8"));
  const guardCalls = popup.match(/if \(!ensureChatAutomationEnabled\(settings\)\)/g) || [];
  assert(html.includes('id="chatAutomationEnabled"'));
  assert(html.includes('type="checkbox"'));
  assert(popup.includes("chatAutomationEnabled: false"));
  assert(popup.includes('element.type === "checkbox"'));
  assert(popup.includes("function ensureChatAutomationEnabled"));
  assert.strictEqual(guardCalls.length, 2);
  assert(popup.indexOf("if (!ensureChatAutomationEnabled(settings))") < popup.indexOf("await ensureChatRunnerInjected(tab.id)"));
  assert(manifest.description.includes("opt-in Boss chat"));
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

function testHoldEndScrollStrategyIsDefault() {
  const collector = fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(popup.includes('scrollMode: "hold_end"'));
  assert(popup.includes("scrollModeDefaultVersion"));
  assert(html.includes('value="hold_end"'));
  assert(html.includes("长按 End 键到底"));
  assert(html.includes('value="end"'));
  assert(collector.includes("async function holdEndScroll"));
  assert(collector.includes("dispatchEndKeyDown(target, false)"));
  assert(collector.includes("dispatchEndKeyDown(target, true)"));
  assert(collector.includes("dispatchEndKeyUp(target)"));
  assert(collector.includes("bottom-reached"));
  assert(collector.includes("paused-by-user"));
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

function loadRemoteControlForBehaviorTest() {
  const store = {};
  const chrome = {
    alarms: { create() {}, onAlarm: { addListener() {} } },
    tabs: {
      async query() {
        return [{ id: 71, url: "https://www.zhipin.com/web/geek/recommend" }];
      },
      async get(id) {
        return { id, url: "https://www.zhipin.com/web/geek/recommend" };
      },
    },
    storage: {
      local: {
        async get(key) {
          if (typeof key === "string") return { [key]: store[key] };
          return { ...key, ...store };
        },
        async set(value) {
          Object.assign(store, value);
        },
        async remove(key) {
          delete store[key];
        },
      },
    },
    scripting: {
      async executeScript(details) {
        if (details.args?.length === 2) {
          return [
            {
              result: {
                cards: [{ platform_uid: "boss-1", raw_card_text: "候选人 A" }],
                meta: { platform: "boss", rounds_completed: 2 },
                frameUrl: "https://www.zhipin.com/web/geek/recommend",
              },
            },
          ];
        }
        return [];
      },
    },
  };
  const fetch = async (url) => {
    const textUrl = String(url);
    if (textUrl.endsWith("/api/automation/start")) {
      return {
        ok: true,
        async json() {
          return {
            ok: true,
            result: {
              ready: true,
              profile_id: 3,
              task_id: 12,
              platform: "boss",
              source_url: "https://www.zhipin.com/web/geek/recommend",
              job_title: "招聘顾问",
            },
          };
        },
      };
    }
    if (textUrl.endsWith("/api/import/cards")) {
      return {
        ok: true,
        async json() {
          return { ok: true, result: { batch_id: 88 } };
        },
      };
    }
    throw new Error(`Unexpected fetch: ${textUrl}`);
  };
  const context = {
    URL,
    chrome,
    clearInterval,
    console,
    fetch,
    globalThis: {},
    setInterval,
    setTimeout,
    __bossLocalRemoteControlTestMode: true,
  };
  context.globalThis = context;
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "remote_control.js"), "utf8");
  vm.runInNewContext(source, context, { filename: "remote_control.js" });
  return context.BossLocalRemoteControl;
}

function testPairingCodeParsesAndRejectsInvalidInput() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "pairing.js"), "utf8");
  const context = { URL };
  context.globalThis = context;
  vm.runInNewContext(source, context, { filename: "pairing.js" });

  assert.deepStrictEqual(
    { ...context.BossLocalPairing.parsePairingCode(
      "boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A19001&apiToken=pair-token_123",
    ) },
    { apiBase: "http://127.0.0.1:19001", apiToken: "pair-token_123" },
  );
  assert.throws(
    () => context.BossLocalPairing.parsePairingCode("http://127.0.0.1:17863"),
    /连接码格式无效/,
  );
}

function testPopupSupportsPairingAndAuthenticatedConnectionCheck() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(html.includes('id="pairingCode"'));
  assert(html.includes('id="applyPairingCode"'));
  assert(html.includes('<script src="pairing.js"></script>'));
  assert(html.includes('<script src="web_intake.js"></script>'));
  assert(html.includes('id="retryWebIntake"'));
  assert(html.includes('id="openWebWorkbench"'));
  assert(popup.includes("applyPairingCodeAndTest"));
  assert(popup.includes("/api/connection/check"));
  assert(popup.includes("Token 不正确"));
}

function testCollectionCarriesCanonicalJobProfileId() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const content = fs.readFileSync(path.join(EXTENSION_DIR, "content_script.js"), "utf8");
  const chatRunner = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(popup.includes("jobProfileId: activeJobProfileId"));
  assert(popup.includes("job_profile_id: settings.jobProfileId"));
  assert(popup.includes("if (!options.automationRequested && !webMode)"));
  assert(popup.includes("baseSettings = await loadDesktopJobProfile(baseSettings)"));
  assert(popup.includes("/api/extension/config"));
  assert(content.includes("job_profile_id: settings.jobProfileId"));
  assert(chatRunner.includes("jobProfileId: payload.result?.job_profile_id"));
  assert(popup.includes("recruitment_task_id: settings.recruitmentTaskId"));
  assert(content.includes("recruitment_task_id: settings.recruitmentTaskId"));
  assert(!popup.includes("window.setTimeout(() => window.close(), 1200)"));
}

async function testPopupPairingSuccessDoesNotReferenceCollectionVariables() {
  const popup = createPopupTestContext({
    fetchImpl: async (url) => {
      if (String(url).endsWith("/api/connection/check")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return { ok: true };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${String(url)}`);
    },
  });
  popup.elements.pairingCode.value =
    "boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A17863&apiToken=pair-token_123";

  await popup.api.applyPairingCodeAndTest();

  assert.strictEqual(popup.fetchCalls.length, 1);
  assert.strictEqual(popup.fetchCalls[0].url, "http://127.0.0.1:17863/api/connection/check");
  assert(popup.elements.status.textContent.includes("桌面端已连接"));
}

async function testPopupWebModeCollectCurrentPostsDirectlyToWebIntake() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    fetchImpl: async (url, requestOptions) => {
      if (String(url).endsWith("/api/intake/candidates")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              batch_id: 201,
              status: "completed",
              received_count: 1,
              inserted_candidates: 1,
              updated_candidates: 0,
              skipped_candidates: 0,
              failed_candidates: 0,
            };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${String(url)}`);
    },
  });

  await popup.api.init();
  await popup.api.runCollection(false);

  assert.strictEqual(popup.fetchCalls.length, 1);
  assert.strictEqual(popup.fetchCalls[0].url, "http://127.0.0.1:17864/api/intake/candidates");
  assert(!("Origin" in popup.fetchCalls[0].options.headers));
  const payload = JSON.parse(popup.fetchCalls[0].options.body);
  assert.strictEqual(payload.job_profile_id, null);
  assert.strictEqual(payload.recruitment_task_id, null);
  assert.strictEqual(payload.candidates[0].platform_uid, "boss:1");
  assert.strictEqual(payload.candidates[0].source_candidate_id, "boss-1");
  assert(popup.elements.status.textContent.includes("已发送到网页工作台"));
}

async function testPopupWebModeCollectAutoPostsDirectlyToWebIntake() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    fetchImpl: async (url) => {
      if (String(url).endsWith("/api/intake/candidates")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              batch_id: 301,
              status: "completed",
              received_count: 1,
              inserted_candidates: 1,
              updated_candidates: 0,
              skipped_candidates: 0,
              failed_candidates: 0,
            };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${String(url)}`);
    },
  });

  await popup.api.init();
  await popup.api.runCollection(true);

  assert.strictEqual(popup.fetchCalls.length, 1);
  assert.strictEqual(popup.fetchCalls[0].url, "http://127.0.0.1:17864/api/intake/candidates");
}

async function testPopupDesktopModeStillUsesDesktopImportOnly() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17863",
    apiToken: "desktop-token",
    fetchImpl: async (url) => {
      const textUrl = String(url);
      if (textUrl.endsWith("/api/extension/config")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              ok: true,
              result: {
                job_profile_id: 9,
                recruitment_task_id: 12,
                job_title: "招聘顾问",
              },
            };
          },
        };
      }
      if (textUrl.endsWith("/api/import/cards")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return { ok: true, result: { batch_id: 88, parsed_cards: 1, total_batch_items: 1 } };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${textUrl}`);
    },
  });

  await popup.api.init();
  await popup.api.runCollection(false);

  assert.strictEqual(popup.fetchCalls.length, 2);
  assert(popup.fetchCalls.some((call) => call.url.endsWith("/api/extension/config")));
  assert(popup.fetchCalls.some((call) => call.url.endsWith("/api/import/cards")));
  assert(!popup.fetchCalls.some((call) => call.url.endsWith("/api/intake/candidates")));
}

async function testPopupRetryRestoresPendingStateAcrossInit() {
  const sharedStore = { apiBase: "http://127.0.0.1:17864", apiToken: "web-token" };
  const failing = createPopupTestContext({
    store: sharedStore,
    fetchImpl: async () => {
      throw new Error("connect ECONNREFUSED 127.0.0.1:17864");
    },
  });

  await failing.api.init();
  await failing.api.runCollection(false);
  const pendingState = sharedStore[failing.context.BossLocalWebIntake.STATE_KEY];
  assert.strictEqual(Object.keys(pendingState.pendingBatches).length, 1);

  const recovered = createPopupTestContext({
    store: sharedStore,
    fetchImpl: async (url) => {
      if (String(url).endsWith("/api/intake/candidates")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              batch_id: 302,
              status: "completed",
              received_count: 1,
              inserted_candidates: 1,
              updated_candidates: 0,
              skipped_candidates: 0,
              failed_candidates: 0,
            };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${String(url)}`);
    },
  });

  await recovered.api.init();
  assert(recovered.elements.webIntakeStatus.textContent.includes("Web 工作台未启动"));
  await recovered.api.retryWebIntake();
  const state = sharedStore[recovered.context.BossLocalWebIntake.STATE_KEY];
  assert.strictEqual(Object.keys(state.pendingBatches).length, 0);
  assert.strictEqual(Object.keys(state.completedBatches).length, 1);
  assert(recovered.elements.webIntakeStatus.textContent.includes("入库成功"));
}

async function testWebIntakeConnectionChangeDoesNotResendOldPendingBatch() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "token-a" });
  const settingsA = { apiBase: "http://127.0.0.1:17864", apiToken: "token-a", jobTitle: "Boss 推荐牛人" };
  const merged = {
    platform: "boss",
    cards: [{ source_candidate_id: "boss-1", raw_card_text: "候选人 A" }],
  };
  const queued = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings: settingsA,
    merged,
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "webcap-test-1",
    storageArea: popup.chrome.storage.local,
  });
  let fetchCalled = false;
  const result = await popup.context.BossLocalWebIntake.sendQueuedBatch({
    settings: { ...settingsA, apiToken: "token-b" },
    batchKey: queued.batchKey,
    storageArea: popup.chrome.storage.local,
    fetchImpl: async () => {
      fetchCalled = true;
      throw new Error("should not fetch");
    },
  });

  assert.strictEqual(fetchCalled, false);
  assert.strictEqual(result.statusLabel, "等待原连接");
}

async function testWebIntakeSameRunIdDoesNotDuplicatePendingBatch() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "token-a" });
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "token-a", jobTitle: "Boss 推荐牛人" };
  const merged = {
    platform: "boss",
    cards: [{ source_candidate_id: "boss-1", raw_card_text: "候选人 A" }],
  };
  const first = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged,
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "webcap-run-1",
    storageArea: popup.chrome.storage.local,
  });
  const second = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged,
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "webcap-run-1",
    storageArea: popup.chrome.storage.local,
  });
  const state = await popup.context.BossLocalWebIntake.loadState(popup.chrome.storage.local);

  assert.strictEqual(first.batchKey, second.batchKey);
  assert.strictEqual(state.pendingOrder.length, 1);
}

async function testCompletedCollectionCanDownloadItsExactBatch() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "batch_export.js"), "utf8");
  const calls = [];
  const context = {
    URL: {
      createObjectURL(blob) {
        calls.push(["object-url", blob.type]);
        return "blob:batch-csv";
      },
      revokeObjectURL(url) {
        calls.push(["revoke", url]);
      },
    },
    Blob,
    globalThis: {},
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, { filename: "batch_export.js" });

  assert(context.BossLocalBatchExport.batchBelongsToConnection(
    { apiBase: "http://127.0.0.1:17863/", apiToken: "secret-token" },
    { apiBase: "http://127.0.0.1:17863", apiToken: "secret-token" },
  ));
  assert(!context.BossLocalBatchExport.batchBelongsToConnection(
    { apiBase: "http://127.0.0.1:17863", apiToken: "old-token" },
    { apiBase: "http://127.0.0.1:17863", apiToken: "new-token" },
  ));
  assert(!context.BossLocalBatchExport.batchBelongsToConnection(
    { apiBase: "http://127.0.0.1:17863", apiToken: "secret-token" },
    { apiBase: "http://127.0.0.1:19000", apiToken: "secret-token" },
  ));

  const result = await context.BossLocalBatchExport.downloadBatchCsv({
    apiBase: "http://127.0.0.1:17863/",
    apiToken: "secret-token",
    batchId: 41,
    fetchImpl: async (url, options) => {
      calls.push(["fetch", url, options.headers["X-Boss-Local-Token"]]);
      return {
        ok: true,
        headers: { get: () => 'attachment; filename="job_batch_41.csv"' },
        async blob() {
          return new Blob(["name\nAlice\n"], { type: "text/csv" });
        },
      };
    },
    downloadsApi: {
      async download(options) {
        calls.push(["download", options.url, options.filename, options.saveAs]);
        return 73;
      },
    },
    urlApi: context.URL,
  });

  assert.strictEqual(result.downloadId, 73);
  assert.deepStrictEqual(calls[0], [
    "fetch",
    "http://127.0.0.1:17863/api/export/batches/41.csv",
    "secret-token",
  ]);
  assert.deepStrictEqual(calls[2], ["download", "blob:batch-csv", "job_batch_41.csv", false]);
  assert.deepStrictEqual(calls[3], ["revoke", "blob:batch-csv"]);

  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(html.includes('id="downloadCurrentBatch"'));
  assert(html.includes('<script src="batch_export.js"></script>'));
  assert(popup.includes("lastCompletedBatchId"));
  assert(popup.includes("lastCompletedBatchConnection"));
  assert(popup.includes("batchBelongsToConnection"));
  assert(popup.includes("imported.batch_id"));
  assert(popup.includes("BossLocalBatchExport.downloadBatchCsv"));
}

function testFilenameTemplatesMatchDesktopFixtures() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const start = source.indexOf("function renderFilenameTemplate(");
  assert(start >= 0, "renderFilenameTemplate must exist");
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  let end = bodyStart;
  for (; end < source.length; end += 1) {
    if (source[end] === "{") depth += 1;
    if (source[end] === "}") depth -= 1;
    if (depth === 0) break;
  }
  const functionSource = source.slice(start, end + 1);
  const render = vm.runInNewContext(`(${functionSource})`);
  const fixtures = JSON.parse(
    fs.readFileSync(path.resolve(EXTENSION_DIR, "..", "tests", "fixtures", "filename_templates.json"), "utf8"),
  );
  for (const fixture of fixtures) {
    assert.strictEqual(render(fixture.template, fixture.values), fixture.expected);
  }
}

function testDesktopRemoteControlKeepsPopupControlsAndUsesTaskScopedCommands() {
  const worker = fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8");
  const remote = fs.readFileSync(path.join(EXTENSION_DIR, "remote_control.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");

  assert(worker.includes('importScripts("remote_control.js")'));
  for (const action of [
    "automation_auto",
    "collect_current",
    "collect_auto",
    "pause_scroll",
    "stop_capture",
  ]) {
    assert(remote.includes(`"${action}"`));
  }
  assert(remote.includes("recruitment_task_id"));
  assert(remote.includes("command.platform"));
  assert(remote.includes("command.source_url"));
  assert(remote.includes("/api/extension/commands/next"));
  assert(remote.includes("/heartbeat"));
  assert(remote.includes("chrome.alarms.create"));
  assert(remote.includes("findRemoteCaptureTab"));
  assert(remote.includes("stopRequested"));
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8"));
  assert(manifest.permissions.includes("alarms"));
  assert(popup.includes('id="automationAuto"'));
  assert(popup.includes('id="collectCurrent"'));
  assert(popup.includes('id="collectAuto"'));
  assert(popup.includes('id="pauseScroll"'));
}

async function testDesktopRemoteAutoExecutesAgainstMatchedTaskTab() {
  const remote = loadRemoteControlForBehaviorTest();
  const message = await remote.executeRemoteCommand(
    {
      id: "command-1",
      action: "automation_auto",
      recruitment_task_id: 12,
      platform: "boss",
      source_url: "https://www.zhipin.com/web/geek/recommend",
    },
    {
      apiBase: "http://127.0.0.1:17863",
      apiToken: "token",
      scrollMode: "hold_end",
      scrollStep: 900,
      scrollWaitMs: 30,
      maxScrollCount: 5,
      noNewStopRounds: 2,
    },
  );
  assert.strictEqual(message, "采集完成：识别 1 人，导入批次 #88");
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
  testChatAutomationIsOptIn();
  testScrollWaitDefaultsToThirtyMillisecondsAndHasAdjusters();
  testHoldEndScrollStrategyIsDefault();
  testRuntimeFingerprintAndVersionAwareRunnerInjection();
  testPairingCodeParsesAndRejectsInvalidInput();
  testPopupSupportsPairingAndAuthenticatedConnectionCheck();
  testCollectionCarriesCanonicalJobProfileId();
  await testPopupPairingSuccessDoesNotReferenceCollectionVariables();
  await testPopupWebModeCollectCurrentPostsDirectlyToWebIntake();
  await testPopupWebModeCollectAutoPostsDirectlyToWebIntake();
  await testPopupDesktopModeStillUsesDesktopImportOnly();
  await testPopupRetryRestoresPendingStateAcrossInit();
  await testWebIntakeConnectionChangeDoesNotResendOldPendingBatch();
  await testWebIntakeSameRunIdDoesNotDuplicatePendingBatch();
  await testCompletedCollectionCanDownloadItsExactBatch();
  testFilenameTemplatesMatchDesktopFixtures();
  testDesktopRemoteControlKeepsPopupControlsAndUsesTaskScopedCommands();
  await testDesktopRemoteAutoExecutesAgainstMatchedTaskTab();
  console.log("extension regression tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
