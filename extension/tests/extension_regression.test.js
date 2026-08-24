const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { webcrypto } = require("crypto");
const { TextEncoder } = require("util");
const vm = require("vm");
const { JSDOM } = require("../../web/frontend/node_modules/jsdom");

const EXTENSION_DIR = path.resolve(__dirname, "..");

function chromeStorageGetSemantics(store, key) {
  if (typeof key === "string") {
    return Object.prototype.hasOwnProperty.call(store, key) ? { [key]: store[key] } : {};
  }
  if (key === null || key === undefined) {
    return { ...store };
  }
  if (Array.isArray(key)) {
    const result = {};
    for (const item of key) {
      if (Object.prototype.hasOwnProperty.call(store, item)) {
        result[item] = store[item];
      }
    }
    return result;
  }
  const result = {};
  for (const [item, fallback] of Object.entries(key)) {
    result[item] = Object.prototype.hasOwnProperty.call(store, item) ? store[item] : fallback;
  }
  return result;
}

function createChromeMock() {
  const store = {};
  const downloadCalls = [];
  const alarmListeners = [];
  const messageListeners = [];
  const startupListeners = [];
  const installedListeners = [];
  return {
    __store: store,
    __downloadCalls: downloadCalls,
    __alarms: [],
    __alarmListeners: alarmListeners,
    __messageListeners: messageListeners,
    __startupListeners: startupListeners,
    __installedListeners: installedListeners,
    runtime: {
      onInstalled: { addListener(listener) { installedListeners.push(listener); } },
      onStartup: { addListener(listener) { startupListeners.push(listener); } },
      onMessage: { addListener(listener) { messageListeners.push(listener); } },
      async sendMessage(message) {
        if (!messageListeners.length) {
          return { ok: false, error: "No runtime.onMessage listener registered." };
        }
        const listener = messageListeners[messageListeners.length - 1];
        return new Promise((resolve) => {
          const maybePromise = listener(message, {}, (result) => resolve(result));
          if (maybePromise && typeof maybePromise.then === "function") {
            maybePromise.then(resolve);
          }
        });
      },
    },
    alarms: {
      onAlarm: { addListener(listener) { alarmListeners.push(listener); } },
      async create(name, options) {
        const existing = this.__owner.__alarms.filter((item) => item.name !== name);
        existing.push({ name, options });
        this.__owner.__alarms = existing;
      },
      async clear(name) {
        const before = this.__owner.__alarms.length;
        this.__owner.__alarms = this.__owner.__alarms.filter((item) => item.name !== name);
        return before !== this.__owner.__alarms.length;
      },
      __owner: null,
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
          return chromeStorageGetSemantics(store, key);
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

function createDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
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
  chrome.alarms.__owner = chrome;
  const context = {
    Blob,
    TextEncoder,
    URL,
    chrome,
    clearInterval() {},
    clearTimeout,
    console,
    crypto: webcrypto,
    fetch,
    globalThis: {},
    setInterval() {
      return 1;
    },
    setTimeout,
  };
  context.globalThis = context;
  context.importScripts = (...scripts) => {
    for (const script of scripts) {
      const source = fs.readFileSync(path.join(EXTENSION_DIR, script), "utf8");
      vm.runInNewContext(source, context, { filename: script });
    }
  };
  const code = `${fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8")}
globalThis.__serviceTest = {
  downloadResume,
  enqueueAndSendWebIntake,
  getBatchStatus,
  getWebIntakeStatus,
  handleBatchProgress,
  hasDirectPdfSignal,
  isValidResumeDownload,
  restorePendingWebIntake,
  retryWebIntake,
  scheduleWebIntakeRetryAlarm,
  saveBatchStatus,
  shouldVerifyPdfBeforeDownload,
  stopBatch,
  waitForLastWebIntakeAlarm,
};`;
  vm.runInNewContext(code, context, { filename: "service_worker.js" });
  return { chrome, api: context.__serviceTest, context };
}

async function triggerRetryAlarm(worker) {
  const listener = worker.chrome.__alarmListeners[0];
  listener({ name: worker.context.BossLocalWebIntake.RETRY_ALARM_NAME });
  await worker.api.waitForLastWebIntakeAlarm();
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
  if (options.connectionMode !== undefined) {
    store.connectionMode = options.connectionMode;
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
        raw_card_text: "鍊欓€変汉 A",
        name: "鍊欓€変汉 A",
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
    "pluginContextStatus",
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
    "captureCurrentDetail",
    "requestResume",
    "downloadResume",
    "requestAndDownload",
    "startBatchRequest",
    "startBatchDownload",
    "stopBatch",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, createPopupElement()]));
  elements.chatAutomationEnabled.type = "checkbox";
  elements.apiBase.value = String(options.initialApiBase || options.apiBase || "http://127.0.0.1:17863");
  elements.apiToken.value = String(options.initialApiToken || options.apiToken || "token");
  elements.jobTitle.value = String(options.jobTitle || store.jobTitle || "Boss 鎺ㄨ崘鐗涗汉");
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
  elements.webIntakeStatus.textContent = "网页入库：等待发送";
  elements.pluginContextStatus.textContent = "当前未选择招聘任务；仍可进行无岗位采集。";

  const chrome = {
    storage: {
      local: {
        async get(key) {
          return chromeStorageGetSemantics(store, key);
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
      async sendMessage(message) {
        if (message?.type === "get_batch_status") {
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
        }
        if (typeof options.runtimeHandler === "function") {
          return options.runtimeHandler(message, context);
        }
        return { ok: false, error: `Unexpected runtime message: ${String(message?.type || "")}` };
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
    TextEncoder,
    chrome,
    console,
    crypto: webcrypto,
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
        const previousMode = String(previous.connectionMode || "").trim().toLowerCase();
        const nextMode = String(next.connectionMode || "").trim().toLowerCase();
        if (!previousMode || !nextMode) {
          return false;
        }
        return (
          previousMode === nextMode
          && (
          String(previous.apiBase || "").replace(/\/+$/, "") === String(next.apiBase || "").replace(/\/+$/, "")
          && String(previous.apiToken || "") === String(next.apiToken || "")
          )
        );
      },
      async downloadBatchCsv() {
        return { batchId: 1, filename: "batch.csv" };
      },
      async downloadBatchMarkdown(options) {
        store.lastMarkdownExport = { apiBase: options.apiBase, batchId: options.batchId };
        store.lastMarkdownExportUrl = `${options.apiBase}/api/capture-batches/${options.batchId}/export.md`;
        return { batchId: options.batchId, filename: `boss-batch-${options.batchId}.md` };
      },
    },
    globalThis: {},
    __bossLocalPopupTestMode: true,
  };
  context.window = context;
  context.globalThis = context;

  for (const script of [
    "pairing.js",
    "web_intake_identity.js",
    "web_intake_storage.js",
    "web_intake_ui.js",
    "web_intake_sender.js",
    "web_intake.js",
  ]) {
    const source = fs.readFileSync(path.join(EXTENSION_DIR, script), "utf8");
    vm.runInNewContext(source, context, { filename: script });
  }
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

function createPopupWebRuntimeHandler() {
  return async function runtimeHandler(message, context) {
    switch (message?.type) {
      case "web_intake_get_status": {
        const result = await context.BossLocalWebIntake.getStatusView({
          settings: message.settings || {},
          storageArea: context.chrome.storage.local,
        });
        return { ok: true, record: result.record, legacyBlocked: result.legacyBlocked, view: result.view };
      }
      case "web_intake_enqueue_and_send": {
        const queued = await context.BossLocalWebIntake.queueCapturedBatch({
          settings: message.settings || {},
          merged: message.merged || {},
          sourceUrl: message.sourceUrl || "",
          idempotencyKey: message.idempotencyKey || "",
          storageArea: context.chrome.storage.local,
        });
        if (!queued) {
          return { ok: true, record: null };
        }
        return {
          ok: true,
          record: await context.BossLocalWebIntake.sendQueuedBatch({
            settings: message.settings || {},
            batchKey: queued.batchKey,
            storageArea: context.chrome.storage.local,
            fetchImpl: context.fetch,
          }),
        };
      }
      case "web_intake_retry":
        return {
          ok: true,
          record: await context.BossLocalWebIntake.retryPendingForCurrentConnection({
            settings: message.settings || {},
            storageArea: context.chrome.storage.local,
            fetchImpl: context.fetch,
          }),
        };
      default:
        return { ok: false, error: `Unexpected runtime message: ${String(message?.type || "")}` };
    }
  };
}

function loadCollectorForTest() {
  class HtmlAnchorElementMock {}
  const context = {
    HTMLAnchorElement: HtmlAnchorElementMock,
    URL,
    globalThis: {},
    location: { href: "https://www.zhipin.com/web/geek/recommend" },
    __bossLocalCollectorTestMode: true,
  };
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8"), context, {
    filename: "collector.js",
  });
  return context.BossLocalCollectorTest;
}

function loadCollectorForDom(dom, href = "https://www.zhipin.com/web/geek/recommend") {
  const context = {
    HTMLElement: dom.window.HTMLElement,
    HTMLAnchorElement: dom.window.HTMLAnchorElement,
    KeyboardEvent: dom.window.KeyboardEvent,
    NodeFilter: dom.window.NodeFilter,
    URL,
    document: dom.window.document,
    window: dom.window,
    globalThis: {},
    location: new URL(href),
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    setTimeout,
    clearTimeout,
    Date,
    __bossLocalCollectorTestMode: true,
  };
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8"), context, {
    filename: "collector.js",
  });
  return context.BossLocalCollectorTest;
}

function giveCardsLayout(dom) {
  for (const node of dom.window.document.querySelectorAll(".candidate-card, .resume-card, .ad-card, .filter-card")) {
    node.getBoundingClientRect = () => ({ width: 720, height: 180, top: 0, left: 0, right: 720, bottom: 180 });
  }
}

function giveDetailLayout(dom) {
  for (const node of dom.window.document.querySelectorAll(".candidate-detail, .resume-detail, .hidden-detail, .loading-detail")) {
    node.getBoundingClientRect = () => ({ width: 760, height: 520, top: 0, left: 0, right: 760, bottom: 520 });
  }
}

function giveBossNestedCardsLayout(dom) {
  for (const node of dom.window.document.querySelectorAll(".candidate-card-wrap, .card-inner, .candidate-card")) {
    node.getBoundingClientRect = () => ({ width: 720, height: 180, top: 0, left: 0, right: 720, bottom: 180 });
  }
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
  assert(String(result.error || "").includes("不是 PDF 文件"));
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

function testPopupClientFirstScreenKeepsCoreWebActionsVisibleAndLegacyFolded() {
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const dom = new JSDOM(html);
  const document = dom.window.document;
  const coreIds = ["applyPairingCode", "collectCurrent", "collectAuto", "pauseScroll", "downloadCurrentBatch", "retryWebIntake", "openWebWorkbench"];
  for (const id of coreIds) {
    const element = document.getElementById(id);
    assert(element, `missing ${id}`);
    assert.strictEqual(element.closest("details"), null, `${id} should be on the client first screen`);
  }
  for (const id of ["desktopAdvanced", "scrollAdvanced", "detailEnrichmentAdvanced", "legacyChatAdvanced", "legacyBatchAdvanced"]) {
    const details = document.getElementById(id);
    assert(details, `missing ${id}`);
    assert.strictEqual(details.open, false, `${id} should be folded by default`);
  }
  assert.strictEqual(document.getElementById("automationAuto").closest("details")?.id, "desktopAdvanced");
  assert.strictEqual(document.getElementById("captureCurrentDetail").closest("details")?.id, "detailEnrichmentAdvanced");
  assert.strictEqual(document.getElementById("chatAutomationEnabled").closest("details")?.id, "legacyChatAdvanced");
  assert.strictEqual(document.getElementById("startBatchRequest").closest("details")?.id, "legacyBatchAdvanced");
  assert(document.body.textContent.includes("网页工作台采集助手"));
  assert(document.body.textContent.includes("后续聊天与附件能力（默认关闭）"));
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
          return chromeStorageGetSemantics(store, key);
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
                cards: [{ platform_uid: "boss-1", raw_card_text: "鍊欓€変汉 A" }],
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
              job_title: "鎷涜仒椤鹃棶",
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
  const legacyTokenParam = "api" + "Token";

  assert.deepStrictEqual(
    { ...context.BossLocalPairing.parsePairingCode(
      `boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A19001&${legacyTokenParam}=pair-token_123`,
    ) },
    { apiBase: "http://127.0.0.1:19001", apiToken: "pair-token_123", connectionMode: "desktop" },
  );
  assert.deepStrictEqual(
    { ...context.BossLocalPairing.parsePairingCode("A1B2C3-D4E5F6") },
    { pairingCode: "A1B2C3-D4E5F6", apiBase: "http://127.0.0.1:17864", connectionMode: "web" },
  );
  assert.deepStrictEqual(
    { ...context.BossLocalPairing.parsePairingCode(
      "boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A19064&pairingCode=ABC123-DEF456",
    ) },
    { pairingCode: "ABC123-DEF456", apiBase: "http://127.0.0.1:19064", connectionMode: "web" },
  );
  for (const invalid of [
    "boss-local://web-pair?apiBase=https%3A%2F%2F127.0.0.1%3A19064&pairingCode=ABC123-DEF456",
    "boss-local://web-pair?apiBase=http%3A%2F%2Flocalhost%3A19064&pairingCode=ABC123-DEF456",
    "boss-local://web-pair?apiBase=http%3A%2F%2Fexample.com%3A19064&pairingCode=ABC123-DEF456",
    "boss-local://web-pair?apiBase=http%3A%2F%2Fuser%3Apass%40127.0.0.1%3A19064&pairingCode=ABC123-DEF456",
    "boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A99999&pairingCode=ABC123-DEF456",
    `boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A19064&pairingCode=ABC123-DEF456&${legacyTokenParam}=stolen`,
  ]) {
    assert.throws(() => context.BossLocalPairing.parsePairingCode(invalid));
  }
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
  assert(html.includes('<script src="web_intake_identity.js"></script>'));
  assert(html.includes('<script src="web_intake_storage.js"></script>'));
  assert(html.includes('<script src="web_intake_sender.js"></script>'));
  assert(html.includes('<script src="web_intake.js"></script>'));
  assert(html.includes('id="retryWebIntake"'));
  assert(html.includes('id="openWebWorkbench"'));
  assert(popup.includes("applyPairingCodeAndTest"));
  assert(popup.includes("/api/connection/check"));
  assert(popup.includes("连接凭证已失效"));
}

async function testPopupPairsWithSingleWebCodeAndRemembersConnection() {
  const popup = createPopupTestContext({
    fetchImpl: async (url, options) => {
      if (String(url).endsWith("/api/plugin/pair")) {
        assert.strictEqual(JSON.parse(options.body).pairing_code, "A1B2C3-D4E5F6");
        return {
          ok: true,
          status: 200,
          async json() {
            return { api_base: "http://127.0.0.1:17864", api_token: "remembered-web-token" };
          },
        };
      }
      if (String(url).endsWith("/api/plugin/connection/check")) {
        assert.strictEqual(options.headers["X-Boss-Local-Token"], "remembered-web-token");
        return { ok: true, status: 200, async json() { return { ok: true }; } };
      }
      if (String(url).endsWith("/api/plugin/context")) {
        return {
          ok: false,
          status: 409,
          async json() {
            return { error: { code: "context_unavailable", message: "当前未选择可用招聘任务。" } };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${String(url)}`);
    },
  });
  popup.elements.pairingCode.value = "A1B2C3-D4E5F6";
  await popup.api.applyPairingCodeAndTest();
  assert.strictEqual(popup.fetchCalls[0].url, "http://127.0.0.1:17864/api/plugin/pair");
  assert.strictEqual(popup.store.apiBase, "http://127.0.0.1:17864");
  assert.strictEqual(popup.store.apiToken, "remembered-web-token");
  assert.strictEqual(popup.store.connectionMode, "web");
  assert(popup.elements.status.textContent.includes("已连接网页工作台"));
  assert(!popup.elements.status.textContent.includes("remembered-web-token"));
}

async function testPopupPairsAndUsesConfiguredWebPortEndToEnd() {
  let webIntakePayload = null;
  const popup = createPopupTestContext({
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async (url, options = {}) => {
      const endpoint = String(url);
      if (endpoint === "http://127.0.0.1:19064/api/plugin/pair") {
        assert.strictEqual(JSON.parse(options.body).pairing_code, "ABC123-DEF456");
        return {
          ok: true,
          status: 200,
          async json() {
            return { api_base: "http://127.0.0.1:19064", api_token: "configured-port-token" };
          },
        };
      }
      if (endpoint === "http://127.0.0.1:19064/api/plugin/connection/check") {
        assert.strictEqual(options.headers["X-Boss-Local-Token"], "configured-port-token");
        return { ok: true, status: 200, async json() { return { ok: true }; } };
      }
      if (endpoint === "http://127.0.0.1:19064/api/plugin/context") {
        assert.strictEqual(options.headers["X-Boss-Local-Token"], "configured-port-token");
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              recruitment_task_id: 42,
              job_profile_id: 17,
              job_profile_version: 3,
              job_title: "量化研究员",
              platform: "boss",
              source_url: "https://www.zhipin.com/web/geek/recommend",
              task_status: "running",
              context_updated_at: "2026-08-19T10:00:00",
            };
          },
        };
      }
      if (endpoint === "http://127.0.0.1:19064/api/intake/candidates") {
        assert.strictEqual(options.headers["X-Boss-Local-Token"], "configured-port-token");
        webIntakePayload = JSON.parse(options.body);
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              batch_id: 19064,
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
      if (endpoint === "http://127.0.0.1:19064/api/health") {
        return { ok: true, status: 200, async json() { return { status: "ok" }; } };
      }
      throw new Error(`Unexpected fetch: ${endpoint}`);
    },
  });
  assert.strictEqual(popup.elements.apiBase.value, "http://127.0.0.1:17863");
  popup.elements.pairingCode.value =
    "boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A19064&pairingCode=ABC123-DEF456";

  await popup.api.applyPairingCodeAndTest();
  assert.strictEqual(popup.store.apiBase, "http://127.0.0.1:19064", popup.elements.status.textContent);
  assert.strictEqual(popup.store.apiToken, "configured-port-token");
  assert.strictEqual(popup.store.connectionMode, "web");
  assert.strictEqual(popup.store.jobProfileId, 17);
  assert.strictEqual(popup.store.recruitmentTaskId, 42);
  assert(popup.elements.pluginContextStatus.textContent.includes("当前招聘任务已连接"));
  assert(popup.elements.pluginContextStatus.textContent.includes("v3"));
  await popup.api.runCollection(false);
  assert.notStrictEqual(webIntakePayload, null, popup.elements.status.textContent);
  assert.strictEqual(webIntakePayload.job_profile_id, 17);
  assert.strictEqual(webIntakePayload.recruitment_task_id, 42);
  assert.strictEqual(webIntakePayload.source_job_title, "量化研究员");
  await popup.api.downloadCurrentBatch();
  await popup.api.openWebWorkbench();

  assert.deepStrictEqual(popup.store.lastMarkdownExport, {
    apiBase: "http://127.0.0.1:19064",
    batchId: 19064,
  });
  assert.strictEqual(
    popup.store.lastMarkdownExportUrl,
    "http://127.0.0.1:19064/api/capture-batches/19064/export.md",
  );
  assert(popup.fetchCalls.some((call) => call.url === "http://127.0.0.1:19064/api/plugin/connection/check"));
  assert(popup.fetchCalls.some((call) => call.url === "http://127.0.0.1:19064/api/intake/candidates"));
  assert(popup.fetchCalls.some((call) => call.url === "http://127.0.0.1:19064/api/health"));
  assert.strictEqual(popup.tabCreates[0]?.url, "http://127.0.0.1:19064/");

  const reopened = createPopupTestContext({
    store: popup.store,
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: popup.context.fetch,
  });
  await reopened.api.init();
  assert.strictEqual(reopened.store.connectionMode, "web");
  assert.strictEqual(reopened.store.connectionModeConfirmed, true);
  assert.strictEqual(reopened.elements.apiBase.value, "http://127.0.0.1:19064");
  await reopened.api.runCollection(false);
  assert(reopened.fetchCalls.some((call) => call.url === "http://127.0.0.1:19064/api/intake/candidates"));
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
    `boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A17863&${"api" + "Token"}=pair-token_123`;

  await popup.api.applyPairingCodeAndTest();

  assert.strictEqual(popup.fetchCalls.length, 1);
  assert.strictEqual(popup.fetchCalls[0].url, "http://127.0.0.1:17863/api/connection/check");
  assert.strictEqual(popup.store.connectionMode, "desktop");
  assert(popup.elements.status.textContent.includes("已连接桌面兼容模式"));
}

async function testPopupDesktopCustomPortRemainsDesktopMode() {
  const popup = createPopupTestContext({
    fetchImpl: async (url) => {
      const textUrl = String(url);
      if (textUrl.endsWith("/api/connection/check")) {
        return { ok: true, status: 200, async json() { return { ok: true }; } };
      }
      if (textUrl.endsWith("/api/extension/config")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              ok: true,
              result: {
                job_profile_id: 19,
                recruitment_task_id: 31,
                job_title: "Desktop 19001",
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
            return { ok: true, result: { batch_id: 901, parsed_cards: 1, total_batch_items: 1 } };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${textUrl}`);
    },
  });
  popup.elements.pairingCode.value =
    `boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A19001&${"api" + "Token"}=desktop-custom-token`;

  await popup.api.applyPairingCodeAndTest();
  assert.strictEqual(popup.store.apiBase, "http://127.0.0.1:19001");
  assert.strictEqual(popup.store.connectionMode, "desktop");
  assert.strictEqual(popup.fetchCalls[0].url, "http://127.0.0.1:19001/api/connection/check");

  await popup.api.runCollection(false);
  assert(popup.fetchCalls.some((call) => call.url === "http://127.0.0.1:19001/api/import/cards"));
  assert(!popup.fetchCalls.some((call) => call.url === "http://127.0.0.1:19001/api/intake/candidates"));
  assert.strictEqual(
    popup.api.isWebWorkbenchMode({ apiBase: "http://127.0.0.1:19001", apiToken: "desktop-custom-token", connectionMode: "desktop" }),
    false,
  );
}

async function testPopupManualDesktopAdvancedSettingsOverrideWebMode() {
  const popup = createPopupTestContext({
    store: {
      apiBase: "http://127.0.0.1:19064",
      apiToken: "web-token",
      connectionMode: "web",
      connectionModeConfirmed: true,
      jobTitle: "Manual Desktop Override",
    },
    fetchImpl: async (url) => {
      const textUrl = String(url);
      if (textUrl.endsWith("/api/connection/check")) {
        return { ok: true, status: 200, async json() { return { ok: true }; } };
      }
      if (textUrl.endsWith("/api/extension/config")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              ok: true,
              result: {
                job_profile_id: 22,
                recruitment_task_id: 41,
                job_title: "Desktop Override",
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
            return { ok: true, result: { batch_id: 905, parsed_cards: 1, total_batch_items: 1 } };
          },
        };
      }
      throw new Error(`Unexpected fetch: ${textUrl}`);
    },
  });
  await popup.api.init();
  popup.elements.apiBase.value = "http://127.0.0.1:19001";
  await popup.elements.apiBase.listeners.input();
  popup.elements.apiToken.value = "desktop-token";
  await popup.elements.apiToken.listeners.input();
  popup.elements.pairingCode.value =
    `boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A19001&${"api" + "Token"}=desktop-token`;

  assert.strictEqual(popup.store.connectionMode, "desktop");
  assert.strictEqual(popup.store.connectionModeConfirmed, true);
  assert.strictEqual(popup.elements.applyPairingCode.textContent, "连接并记住");

  await popup.api.applyPairingCodeAndTest();
  await popup.api.runCollection(false);
  assert(popup.fetchCalls.some((call) => call.url === "http://127.0.0.1:19001/api/connection/check"));
  assert(popup.fetchCalls.some((call) => call.url === "http://127.0.0.1:19001/api/import/cards"));
  assert(!popup.fetchCalls.some((call) => call.url.endsWith("/api/intake/candidates")));
}

async function testPopupClearsOldTaskContextWhenNewConnectionContextFails() {
  let intakePayload = null;
  const popup = createPopupTestContext({
    store: {
      apiBase: "http://127.0.0.1:17864",
      apiToken: "old-token",
      connectionMode: "web",
      connectionModeConfirmed: true,
      jobProfileId: 99,
      recruitmentTaskId: 88,
    },
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async (url, options = {}) => {
      const endpoint = String(url);
      if (endpoint === "http://127.0.0.1:19064/api/plugin/pair") {
        return {
          ok: true,
          status: 200,
          async json() {
            return { api_base: "http://127.0.0.1:19064", api_token: "new-token" };
          },
        };
      }
      if (endpoint === "http://127.0.0.1:19064/api/plugin/connection/check") {
        assert.strictEqual(options.headers["X-Boss-Local-Token"], "new-token");
        return { ok: true, status: 200, async json() { return { ok: true }; } };
      }
      if (endpoint === "http://127.0.0.1:19064/api/plugin/context") {
        return {
          ok: false,
          status: 401,
          async json() {
            return { error: { code: "unauthorized", message: "本地写入鉴权失败。" } };
          },
        };
      }
      if (endpoint === "http://127.0.0.1:19064/api/intake/candidates") {
        intakePayload = JSON.parse(options.body);
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              batch_id: 19065,
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
      throw new Error(`Unexpected fetch: ${endpoint}`);
    },
  });

  popup.elements.pairingCode.value =
    "boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A19064&pairingCode=ABC123-DEF456";
  await popup.api.applyPairingCodeAndTest();
  assert.strictEqual(popup.store.apiBase, "http://127.0.0.1:19064");
  assert.strictEqual(popup.store.jobProfileId, null);
  assert.strictEqual(popup.store.recruitmentTaskId, null);
  assert(popup.elements.pluginContextStatus.textContent.includes("上下文未确认"));

  await popup.api.runCollection(false);
  assert.notStrictEqual(intakePayload, null);
  assert.strictEqual(intakePayload.job_profile_id, null);
  assert.strictEqual(intakePayload.recruitment_task_id, null);
}

async function testPopupWebModeCollectCurrentPostsDirectlyToWebIntake() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async (url, requestOptions) => {
      if (String(url).endsWith("/api/plugin/context")) {
        return {
          ok: false,
          status: 409,
          async json() {
            return { error: { code: "context_unavailable", message: "当前未选择可用招聘任务。" } };
          },
        };
      }
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

  const intakeCalls = popup.fetchCalls.filter((call) => call.url === "http://127.0.0.1:17864/api/intake/candidates");
  assert.strictEqual(intakeCalls.length, 1);
  assert(!("Origin" in intakeCalls[0].options.headers));
  const payload = JSON.parse(intakeCalls[0].options.body);
  assert.strictEqual(payload.job_profile_id, null);
  assert.strictEqual(payload.recruitment_task_id, null);
  assert.strictEqual(payload.candidates[0].platform_uid, "boss:1");
  assert.strictEqual(payload.candidates[0].source_candidate_id, "boss-1");
  assert(popup.elements.pluginContextStatus.textContent.includes("上下文未确认"));
  assert(popup.elements.automationAuto.title.includes("Web"));

  await popup.api.downloadCurrentBatch();
  assert.deepStrictEqual(popup.store.lastMarkdownExport, {
    apiBase: "http://127.0.0.1:17864",
    batchId: 201,
  });
  popup.elements.apiToken.value = "different-token";
  delete popup.store.lastMarkdownExport;
  await popup.api.downloadCurrentBatch();
  assert.strictEqual(popup.store.lastMarkdownExport, undefined);
  assert(popup.elements.status.textContent.includes("当前连接没有可导出的 Web 批次"));
}

async function testPopupWebModeCollectAutoPostsDirectlyToWebIntake() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async (url) => {
      if (String(url).endsWith("/api/plugin/context")) {
        return {
          ok: false,
          status: 409,
          async json() {
            return { error: { code: "context_unavailable", message: "当前未选择可用招聘任务。" } };
          },
        };
      }
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

  const intakeCalls = popup.fetchCalls.filter((call) => call.url === "http://127.0.0.1:17864/api/intake/candidates");
  assert.strictEqual(intakeCalls.length, 1);
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
                job_title: "测试岗位",
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
  assert(!popup.elements.automationAuto.title.includes("Web mojibake AUTO text"));
}

async function testPopupRetryRestoresPendingStateAcrossInit() {
  const sharedStore = { apiBase: "http://127.0.0.1:17864", apiToken: "web-token" };
  const failing = createPopupTestContext({
    store: sharedStore,
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async () => {
      throw new Error("connect ECONNREFUSED 127.0.0.1:17864");
    },
  });

  await failing.api.init();
  await failing.api.runCollection(false);
  let state = await failing.context.BossLocalWebIntake.loadState(failing.chrome.storage.local);
  assert.strictEqual(state.pendingOrder.length, 1);

  const recovered = createPopupTestContext({
    store: sharedStore,
    runtimeHandler: createPopupWebRuntimeHandler(),
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
  assert.strictEqual(recovered.elements.retryWebIntake.disabled, false);
  await recovered.api.retryWebIntake();
  state = await recovered.context.BossLocalWebIntake.loadState(recovered.chrome.storage.local);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
}

async function testWebIntakeConnectionChangeDoesNotResendOldPendingBatch() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "token-a" });
  const settingsA = { apiBase: "http://127.0.0.1:17864", apiToken: "token-a", jobTitle: "Boss 测试岗位" };
  const merged = {
    platform: "boss",
    cards: [{ source_candidate_id: "boss-1", raw_card_text: "测试原文 A" }],
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
  assert(result.statusLabel && String(result.statusLabel).length > 0);
}

async function testWebIntakeSameRunIdDoesNotDuplicatePendingBatch() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "token-a" });
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "token-a", jobTitle: "Boss 测试岗位" };
  const merged = {
    platform: "boss",
    cards: [{ source_candidate_id: "boss-1", raw_card_text: "测试原文 A" }],
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

async function testWebIntakeConcurrentCompletionDoesNotOverwriteQueuedBatch() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "web-token" });
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "web-token", jobTitle: "Boss 测试岗位" };
  const fetchStarted = createDeferred();
  const releaseFetch = createDeferred();
  const queuedA = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged: { platform: "boss", cards: [{ source_candidate_id: "boss-1", raw_card_text: "测试原文A" }] },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "concurrent-a",
    storageArea: popup.chrome.storage.local,
  });
  let resolveFetch;
  const sendPromise = popup.context.BossLocalWebIntake.sendQueuedBatch({
    settings,
    batchKey: queuedA.batchKey,
    storageArea: popup.chrome.storage.local,
    fetchImpl: () => {
      fetchStarted.resolve();
      return releaseFetch.promise;
    },
  });
  await fetchStarted.promise;
  const queuedB = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged: { platform: "boss", cards: [{ source_candidate_id: "boss-2", raw_card_text: "测试原文B" }] },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "concurrent-b",
    storageArea: popup.chrome.storage.local,
  });
  releaseFetch.resolve({
    ok: true,
    status: 200,
    async json() {
      return {
        batch_id: 401,
        status: "completed",
        received_count: 1,
        inserted_candidates: 1,
        updated_candidates: 0,
        skipped_candidates: 0,
        failed_candidates: 0,
      };
    },
  });
  await sendPromise;
  const state = await popup.context.BossLocalWebIntake.loadState(popup.chrome.storage.local);
  assert(state.pendingBatches[queuedB.batchKey]);
  assert.strictEqual(state.completedOrder.length, 1);
}

async function testSendingLeaseExpiryRecoversOnAlarm() {
  let fakeNow = Date.now();
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "lease-token", jobTitle: "Lease Test" };
  const worker = loadServiceWorker(async () => ({
    ok: true,
    status: 200,
    async json() {
      return {
        batch_id: 601,
        status: "completed",
        received_count: 1,
        inserted_candidates: 1,
        updated_candidates: 0,
        skipped_candidates: 0,
        failed_candidates: 0,
      };
    },
  }));
  worker.context.__bossLocalWebIntakeNow = () => fakeNow;
  Object.assign(worker.chrome.__store, settings);
  const queued = await worker.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged: { platform: "boss", cards: [{ source_candidate_id: "lease-1", raw_card_text: "candidate-lease" }] },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "lease-batch",
    storageArea: worker.chrome.storage.local,
  });
  await worker.context.BossLocalWebIntake.upsertPendingRecord(
    {
      ...(await worker.context.BossLocalWebIntake.readPendingRecord(queued.batchKey, worker.chrome.storage.local)),
      status: "sending",
      attemptCount: 1,
      sendingStartedAt: new Date(fakeNow - 30000).toISOString(),
      leaseOwner: "dead-worker",
      leaseExpiresAt: new Date(fakeNow + 30000).toISOString(),
    },
    worker.chrome.storage.local,
  );

  await triggerRetryAlarm(worker);
  let state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(state.pendingBatches[queued.batchKey].status, "sending");
  assert(worker.chrome.__alarms.some((alarm) => alarm.name === worker.context.BossLocalWebIntake.RETRY_ALARM_NAME));

  fakeNow += 31000;
  await triggerRetryAlarm(worker);
  state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
  assert(!worker.chrome.__alarms.some((alarm) => alarm.name === worker.context.BossLocalWebIntake.RETRY_ALARM_NAME));
}

async function testSameBatchConcurrentSendLockTwentyTimes() {
  for (let index = 0; index < 20; index += 1) {
    let fetchCalls = 0;
    const fetchStarted = createDeferred();
    const releaseFetch = createDeferred();
    const worker = loadServiceWorker(async () => {
      fetchCalls += 1;
      fetchStarted.resolve();
      await releaseFetch.promise;
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            batch_id: 700 + index,
            status: "completed",
            received_count: 1,
            inserted_candidates: 1,
            updated_candidates: 0,
            skipped_candidates: 0,
            failed_candidates: 0,
          };
        },
      };
    });
    const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "lock-token", jobTitle: "Lock Test" };
    const payload = {
      settings,
      sourceUrl: "https://www.zhipin.com/web/geek/recommend",
      merged: {
        platform: "boss",
        cards: [
          {
            source_candidate_id: `lock-${index}`,
            detail_url: `https://www.zhipin.com/candidate/${index}`,
            raw_card_text: `candidate-lock-${index}`,
            name: `candidate-${index}`,
          },
        ],
      },
      idempotencyKey: `lock-batch-${index}`,
    };

    const firstSend = worker.api.enqueueAndSendWebIntake(payload);
    await fetchStarted.promise;
    const secondSend = worker.api.retryWebIntake(settings);
    releaseFetch.resolve();
    await Promise.all([firstSend, secondSend]);

    const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
    assert.strictEqual(fetchCalls, 1);
    assert.strictEqual(state.pendingOrder.length, 0);
    assert.strictEqual(state.completedOrder.length, 1);
    const serialized = JSON.stringify(worker.chrome.__store);
    assert(!serialized.includes(`candidate-lock-${index}`));
    assert(!serialized.includes(`https://www.zhipin.com/candidate/${index}`));
  }
}

async function testAutomaticRetryStopsAtMaxAndManualRetryStillWorks() {
  let fetchCalls = 0;
  const failingWorker = loadServiceWorker(async () => {
    fetchCalls += 1;
    throw new Error("network down");
  });
  const settings = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "retry-token",
    connectionMode: "web",
    connectionModeConfirmed: true,
    jobTitle: "Retry Test",
  };
  Object.assign(failingWorker.chrome.__store, settings);
  await failingWorker.api.enqueueAndSendWebIntake({
    settings,
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    merged: { platform: "boss", cards: [{ source_candidate_id: "retry-1", raw_card_text: "retry-candidate" }] },
    idempotencyKey: "retry-batch",
  });
  await failingWorker.api.restorePendingWebIntake();
  await failingWorker.api.restorePendingWebIntake();
  await failingWorker.api.restorePendingWebIntake();
  await failingWorker.api.restorePendingWebIntake();
  assert.strictEqual(fetchCalls, 3);
  assert(
    !failingWorker.chrome.__alarms.some(
      (alarm) => alarm.name === failingWorker.context.BossLocalWebIntake.RETRY_ALARM_NAME,
    ),
  );

  const pendingBeforeManual = await failingWorker.context.BossLocalWebIntake.currentRecordForConnection(
    settings,
    failingWorker.chrome.storage.local,
  );
  assert.strictEqual(pendingBeforeManual.status, "failed");

  const recoveredWorker = loadServiceWorker(async () => ({
    ok: true,
    status: 200,
    async json() {
      return {
        batch_id: 801,
        status: "completed",
        received_count: 1,
        inserted_candidates: 1,
        updated_candidates: 0,
        skipped_candidates: 0,
        failed_candidates: 0,
      };
    },
  }));
  Object.assign(recoveredWorker.chrome.__store, failingWorker.chrome.__store, settings);
  await recoveredWorker.api.retryWebIntake(settings);
  const state = await recoveredWorker.context.BossLocalWebIntake.loadState(recoveredWorker.chrome.storage.local);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
}

async function testLegacyV2MigrationSanitizesSensitiveData() {
  const worker = loadServiceWorker();
  worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {
      "legacy-pending": {
        batchKey: "legacy-pending",
        idempotencyKey: "legacy-idem-1",
        connection: { mode: "web", apiBase: "http://127.0.0.1:17864", webApiBase: "http://127.0.0.1:17864" },
        payload: {
          candidates: [
            {
              name: "Legacy Name",
              raw_card_text: "Legacy Raw Card",
              detail_url: "https://www.zhipin.com/candidate/legacy",
            },
          ],
        },
      },
    },
    completedBatches: {
      "legacy-completed": {
        batchKey: "legacy-completed",
        idempotencyKey: "legacy-idem-2",
        payload: {
          candidates: [
            {
              name: "Completed Name",
              raw_card_text: "Completed Raw Card",
              detail_url: "https://www.zhipin.com/candidate/completed",
            },
          ],
        },
        webResult: { batch_id: 901, status: "completed", received_count: 1 },
      },
    },
  };
  const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  const pending = state.pendingBatches["legacy-pending"];
  assert.strictEqual(Boolean(pending), true);
  assert.strictEqual(pending.statusLabel, "等待原连接");
  assert.strictEqual(worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY], undefined);
  const serialized = JSON.stringify(worker.chrome.__store);
  assert(!serialized.includes("Legacy Name"));
  assert(!serialized.includes("Legacy Raw Card"));
  assert(!serialized.includes("Completed Name"));
  assert(!serialized.includes("Completed Raw Card"));
  assert(!serialized.includes("candidate/completed"));
}

async function testPendingLimitConcurrentEnqueueStaysWithinTen() {
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "limit-token", jobTitle: "Limit Test" };
  const fetchStarted = createDeferred();
  const releaseFetch = createDeferred();
  const worker = loadServiceWorker(async () => {
    fetchStarted.resolve();
    await releaseFetch.promise;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 951,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  for (let index = 0; index < 9; index += 1) {
    await worker.context.BossLocalWebIntake.queueCapturedBatch({
      settings,
      merged: { platform: "boss", cards: [{ source_candidate_id: `base-${index}`, raw_card_text: `base-${index}` }] },
      sourceUrl: "https://www.zhipin.com/web/geek/recommend",
      idempotencyKey: `base-batch-${index}`,
      storageArea: worker.chrome.storage.local,
    });
  }

  const firstPromise = worker.api.enqueueAndSendWebIntake({
    settings,
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    merged: { platform: "boss", cards: [{ source_candidate_id: "limit-a", raw_card_text: "limit-a" }] },
    idempotencyKey: "limit-a",
  });
  await fetchStarted.promise;
  const secondResult = await worker.api.enqueueAndSendWebIntake({
    settings,
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    merged: { platform: "boss", cards: [{ source_candidate_id: "limit-b", raw_card_text: "limit-b" }] },
    idempotencyKey: "limit-b",
  });
  const midState = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert(midState.pendingOrder.length <= 10);
  assert.strictEqual(secondResult.ok, false);
  assert.strictEqual(secondResult.code, "pending_limit_exceeded");
  releaseFetch.resolve();
  await firstPromise;
}

async function testWebIntakeSuccessSanitizesCompletedPayload() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "web-token" });
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "web-token", jobTitle: "Boss 测试岗位" };
  const queued = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged: {
      platform: "boss",
      cards: [
        {
          source_candidate_id: "boss-1",
          detail_url: "https://www.zhipin.com/candidate/1",
          raw_card_text: "测试 原文",
          name: "??",
        },
      ],
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "sanitize-1",
    storageArea: popup.chrome.storage.local,
  });
  await popup.context.BossLocalWebIntake.sendQueuedBatch({
    settings,
    batchKey: queued.batchKey,
    storageArea: popup.chrome.storage.local,
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 402,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    }),
  });
  const serialized = JSON.stringify(popup.store);
  assert(!serialized.includes("??"));
  assert(!serialized.includes("raw_card_text"));
  assert(!serialized.includes("https://www.zhipin.com/candidate/1"));
}

async function testWebIntakeQuotaFailureIsReportedSeparately() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "web-token" });
  popup.chrome.storage.local.set = async () => {
    throw new Error("QUOTA_BYTES quota exceeded");
  };
  await assert.rejects(
    () =>
      popup.context.BossLocalWebIntake.queueCapturedBatch({
        settings: { apiBase: "http://127.0.0.1:17864", apiToken: "web-token", jobTitle: "Boss 测试岗位" },
        merged: { platform: "boss", cards: [{ source_candidate_id: "boss-1", raw_card_text: "测试原文A" }] },
        sourceUrl: "https://www.zhipin.com/web/geek/recommend",
        idempotencyKey: "quota-1",
        storageArea: popup.chrome.storage.local,
      }),
    (error) => String(error?.name || "") === "WebIntakeStorageError",
  );
}

async function testServiceWorkerRestoresPendingBatchViaAlarm() {
  const first = loadServiceWorker(async () => {
    throw new Error("connect ECONNREFUSED 127.0.0.1:17864");
  });
  await first.api.enqueueAndSendWebIntake({
    settings: { apiBase: "http://127.0.0.1:17864", apiToken: "web-token", jobTitle: "Boss 测试岗位" },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    merged: { platform: "boss", cards: [{ source_candidate_id: "boss-1", raw_card_text: "测试原文A" }] },
    idempotencyKey: "restore-1",
  });
  const second = loadServiceWorker(async () => ({
    ok: true,
    status: 200,
    async json() {
      return {
        batch_id: 403,
        status: "completed",
        received_count: 1,
        inserted_candidates: 1,
        updated_candidates: 0,
        skipped_candidates: 0,
        failed_candidates: 0,
      };
    },
  }));
  Object.assign(second.chrome.__store, first.chrome.__store, { apiBase: "http://127.0.0.1:17864", apiToken: "web-token", jobTitle: "Boss 测试岗位" });
  await triggerRetryAlarm(second);
  const state = await second.context.BossLocalWebIntake.loadState(second.chrome.storage.local);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
}

function testWebIntakeIdentityUsesFullFieldsInsteadOfShortHash() {
  const context = createPopupTestContext().context;
  const left = {
    mode: "web",
    apiBase: "http://127.0.0.1:17864",
    webApiBase: "http://127.0.0.1:17864",
    tokenDigest: "abc",
    key: "deadbeef",
  };
  const right = {
    mode: "desktop",
    apiBase: "http://127.0.0.1:17863",
    webApiBase: "http://127.0.0.1:17864",
    tokenDigest: "xyz",
    key: "deadbeef",
  };
  assert.strictEqual(context.BossLocalWebIntake.sameConnectionIdentity(left, right), false);
  assert.strictEqual(
    context.BossLocalWebIntake.sameConnectionIdentity(
      {
        mode: "web",
        apiBase: "http://127.0.0.1:17864",
        webApiBase: "http://127.0.0.1:17864",
        tokenDigest: "same",
      },
      {
        mode: "desktop",
        apiBase: "http://127.0.0.1:17864",
        webApiBase: "http://127.0.0.1:17864",
        tokenDigest: "same",
      },
    ),
    false,
  );
}

async function testLegacyStorageConnectionModeMigrationRules() {
  const popup = createPopupTestContext({
    store: { apiBase: "http://127.0.0.1:19001", apiToken: "legacy-custom-token" },
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  const identity = popup.context.BossLocalWebIntakeIdentity;
  assert.strictEqual(identity.resolveConnectionMode({ apiBase: "http://127.0.0.1:17863" }), "");
  assert.strictEqual(identity.resolveConnectionMode({ apiBase: "http://127.0.0.1:17864" }), "");
  assert.strictEqual(identity.resolveConnectionMode({ apiBase: "http://127.0.0.1:19001" }), "");
  assert.strictEqual(identity.needsConnectionModeConfirmation({ connectionModeConfirmed: false }), true);
  assert.strictEqual(identity.needsConnectionModeConfirmation({ connectionModeConfirmed: true }), false);

  await popup.api.init();

  assert.strictEqual(popup.store.connectionMode, "desktop");
  assert.strictEqual(popup.store.connectionModeConfirmed, false);
  assert.strictEqual(popup.elements.apiBase.value, "http://127.0.0.1:19001");
  assert(popup.elements.webIntakeStatus.textContent.includes("请重新配对以确认连接模式。"));
}

async function testLegacyStorageDefaultPortsMigrateOnce() {
  const webPopup = createPopupTestContext({
    store: { apiBase: "http://127.0.0.1:17864", apiToken: "legacy-web-token" },
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  await webPopup.api.init();
  assert.strictEqual(webPopup.store.connectionMode, "web");
  assert.strictEqual(webPopup.store.connectionModeConfirmed, true);
  await webPopup.api.refreshWebIntakeStatus(webPopup.api.collectSettings());
  assert.notStrictEqual(webPopup.elements.apiBase.value, "http://127.0.0.1:17863");

  const desktopPopup = createPopupTestContext({
    store: { apiBase: "http://127.0.0.1:17863", apiToken: "legacy-desktop-token" },
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  await desktopPopup.api.init();
  assert.strictEqual(desktopPopup.store.connectionMode, "desktop");
  assert.strictEqual(desktopPopup.store.connectionModeConfirmed, true);
}

async function testExplicitModeBackfillsConfirmedAndPreservesJobTitle() {
  const worker = loadServiceWorker();
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "preserve-job-token",
    jobTitle: "Preserved Job Title",
    connectionMode: "web",
  });

  const migrated = await worker.context.BossLocalWebIntake.ensureStoredConnectionMode(worker.chrome.storage.local);
  const settings = await worker.context.BossLocalWebIntake.readCurrentSettings(worker.chrome.storage.local);

  assert.strictEqual(migrated.connectionMode, "web");
  assert.strictEqual(migrated.connectionModeConfirmed, true);
  assert.strictEqual(worker.chrome.__store.connectionModeConfirmed, true);
  assert.strictEqual(settings.jobTitle, "Preserved Job Title");
}

async function testWorkerMigratesLegacyWebConnectionBeforePopupAndRecoversPending() {
  let fetchCalls = 0;
  const worker = loadServiceWorker(async () => {
    fetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 2001,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "legacy-worker-token",
    jobTitle: "Worker Legacy Web",
  });
  const record = await worker.context.BossLocalWebIntake.buildPendingRecord({
    settings: {
      apiBase: "http://127.0.0.1:17864",
      apiToken: "legacy-worker-token",
      connectionMode: "web",
      jobTitle: "Worker Legacy Web",
    },
    merged: {
      platform: "boss",
      cards: [{ source_candidate_id: "legacy-worker-1", raw_card_text: "legacy-worker-card" }],
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "legacy-worker-1",
  });
  worker.chrome.__store[worker.context.BossLocalWebIntake.pendingStorageKey(record.batchKey)] = record;

  await triggerRetryAlarm(worker);

  const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(worker.chrome.__store.connectionMode, "web");
  assert.strictEqual(worker.chrome.__store.connectionModeConfirmed, true);
  assert.strictEqual(fetchCalls, 1);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
  const completed = state.completedBatches[state.completedOrder[0]];
  assert.notStrictEqual(completed.statusLabel, "等待原连接");
}

async function testWorkerMigratesLegacyDesktopConnectionWithoutWebIntake() {
  let fetchCalls = 0;
  const worker = loadServiceWorker(async () => {
    fetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {};
      },
    };
  });
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:17863",
    apiToken: "legacy-desktop-token",
    jobTitle: "Worker Legacy Desktop",
  });

  await worker.api.restorePendingWebIntake();

  assert.strictEqual(worker.chrome.__store.connectionMode, "desktop");
  assert.strictEqual(worker.chrome.__store.connectionModeConfirmed, true);
  assert.strictEqual(fetchCalls, 0);
}

async function testSendQueuedBatchUsesMigratedSettingsWhenMessageModeMissing() {
  let fetchCalls = 0;
  const worker = loadServiceWorker(async () => {
    fetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 2004,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "missing-mode-token",
    jobTitle: "Migrated Sender Job",
  });

  const result = await worker.api.enqueueAndSendWebIntake({
    settings: {
      apiBase: "http://127.0.0.1:17864",
      apiToken: "missing-mode-token",
      jobTitle: "Migrated Sender Job",
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    merged: {
      platform: "boss",
      cards: [{ source_candidate_id: "sender-migrate-1", raw_card_text: "sender-migrate-card" }],
    },
    idempotencyKey: "sender-migrate-1",
  });

  const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(worker.chrome.__store.connectionMode, "web");
  assert.strictEqual(worker.chrome.__store.connectionModeConfirmed, true);
  assert.strictEqual(fetchCalls, 1);
  assert.strictEqual(result.ok, true);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
  const completed = state.completedBatches[state.completedOrder[0]];
  assert.strictEqual(completed.idempotencyKey, "sender-migrate-1");
  assert.notStrictEqual(String(completed.statusLabel || ""), "等待原连接");
}

async function testWorkerKeepsCustomPortPendingWhenMigrationNeedsRePair() {
  let fetchCalls = 0;
  const worker = loadServiceWorker(async () => {
    fetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {};
      },
    };
  });
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:19001",
    apiToken: "custom-port-token",
    jobTitle: "Worker Custom Port",
  });
  const record = await worker.context.BossLocalWebIntake.buildPendingRecord({
    settings: {
      apiBase: "http://127.0.0.1:19001",
      apiToken: "custom-port-token",
      connectionMode: "desktop",
      jobTitle: "Worker Custom Port",
    },
    merged: {
      platform: "boss",
      cards: [{ source_candidate_id: "custom-port-1", raw_card_text: "custom-port-card" }],
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "custom-port-1",
  });
  const pendingKey = worker.context.BossLocalWebIntake.pendingStorageKey(record.batchKey);
  worker.chrome.__store[pendingKey] = record;
  const beforePayload = JSON.stringify(record.payload);

  await triggerRetryAlarm(worker);

  assert.strictEqual(worker.chrome.__store.connectionMode, "desktop");
  assert.strictEqual(worker.chrome.__store.connectionModeConfirmed, false);
  assert.strictEqual(fetchCalls, 0);
  assert.strictEqual(JSON.stringify(worker.chrome.__store[pendingKey].payload), beforePayload);
  assert(worker.chrome.__alarms.some((alarm) => alarm.name === worker.context.BossLocalWebIntake.RETRY_ALARM_NAME));
}

async function testPopupAndWorkerConcurrentMigrationIsIdempotent() {
  let fetchCalls = 0;
  const worker = loadServiceWorker(async (url) => {
    if (String(url).endsWith("/api/plugin/context")) {
      return {
        ok: false,
        status: 409,
        async json() {
          return { error: { code: "context_unavailable", message: "当前未选择可用招聘任务。" } };
        },
      };
    }
    fetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 2002,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "shared-web-token",
    jobTitle: "Concurrent Migration",
  });
  const record = await worker.context.BossLocalWebIntake.buildPendingRecord({
    settings: {
      apiBase: "http://127.0.0.1:17864",
      apiToken: "shared-web-token",
      connectionMode: "web",
      jobTitle: "Concurrent Migration",
    },
    merged: {
      platform: "boss",
      cards: [{ source_candidate_id: "concurrent-migration-1", raw_card_text: "concurrent-migration-card" }],
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "concurrent-migration-1",
  });
  worker.chrome.__store[worker.context.BossLocalWebIntake.pendingStorageKey(record.batchKey)] = record;

  const popup = createPopupTestContext({
    store: worker.chrome.__store,
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: worker.context.fetch,
  });

  await Promise.all([
    popup.api.init(),
    triggerRetryAlarm(worker),
  ]);

  const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(worker.chrome.__store.connectionMode, "web");
  assert.strictEqual(worker.chrome.__store.connectionModeConfirmed, true);
  assert.strictEqual(fetchCalls, 1);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
}

async function testPopupAndWorkerConcurrentSendSameBatchOnlyFetchesOnce() {
  let fetchCalls = 0;
  const fetchStarted = createDeferred();
  const releaseFetch = createDeferred();
  const sharedFetch = async () => {
    fetchCalls += 1;
    fetchStarted.resolve();
    await releaseFetch.promise;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 2005,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  };

  const worker = loadServiceWorker(sharedFetch);
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "shared-batch-token",
    jobTitle: "Shared Batch Job",
  });
  const pendingRecord = await worker.context.BossLocalWebIntake.buildPendingRecord({
    settings: {
      apiBase: "http://127.0.0.1:17864",
      apiToken: "shared-batch-token",
      connectionMode: "web",
      jobTitle: "Shared Batch Job",
    },
    merged: {
      platform: "boss",
      cards: [{
        source_candidate_id: "shared-batch-1",
        name: "Shared Candidate",
        raw_card_text: "Shared Candidate Raw",
        detail_url: "https://www.zhipin.com/candidate/shared-batch-1",
      }],
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "shared-batch-1",
  });
  const pendingKey = worker.context.BossLocalWebIntake.pendingStorageKey(pendingRecord.batchKey);
  worker.chrome.__store[pendingKey] = pendingRecord;

  const popup = createPopupTestContext({
    store: worker.chrome.__store,
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: sharedFetch,
  });

  const popupPromise = popup.api.queueAndSendWebBatch(
    {
      apiBase: "http://127.0.0.1:17864",
      apiToken: "shared-batch-token",
      jobTitle: "Shared Batch Job",
    },
    "https://www.zhipin.com/web/geek/recommend",
    {
      platform: "boss",
      cards: [{
        source_candidate_id: "shared-batch-1",
        name: "Shared Candidate",
        raw_card_text: "Shared Candidate Raw",
        detail_url: "https://www.zhipin.com/candidate/shared-batch-1",
      }],
    },
    "shared-batch-1",
  );

  await fetchStarted.promise;
  await triggerRetryAlarm(worker);
  releaseFetch.resolve();
  await popupPromise;

  const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(worker.chrome.__store.connectionMode, "web");
  assert.strictEqual(worker.chrome.__store.connectionModeConfirmed, true);
  assert.strictEqual(fetchCalls, 1);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
  const completed = state.completedBatches[state.completedOrder[0]];
  assert.strictEqual(completed.idempotencyKey, "shared-batch-1");
  assert.notStrictEqual(String(completed.statusLabel || ""), "等待原连接");
  const serialized = JSON.stringify(worker.chrome.__store);
  assert(!serialized.includes("Shared Candidate"));
  assert(!serialized.includes("Shared Candidate Raw"));
  assert(!serialized.includes("candidate/shared-batch-1"));
  assert(!serialized.includes("\"payload\""));
  assert(!worker.chrome.__store[pendingKey]);
  await worker.api.restorePendingWebIntake();
  assert(!worker.chrome.__alarms.some((alarm) => alarm.name === worker.context.BossLocalWebIntake.RETRY_ALARM_NAME));
}

async function testMigrationWriteFailureKeepsPendingAndAlarm() {
  let fetchCalls = 0;
  const worker = loadServiceWorker(async () => {
    fetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 2003,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  Object.assign(worker.chrome.__store, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "migration-failure-token",
    jobTitle: "Migration Failure",
  });
  const record = await worker.context.BossLocalWebIntake.buildPendingRecord({
    settings: {
      apiBase: "http://127.0.0.1:17864",
      apiToken: "migration-failure-token",
      connectionMode: "web",
      jobTitle: "Migration Failure",
    },
    merged: {
      platform: "boss",
      cards: [{ source_candidate_id: "migration-failure-1", raw_card_text: "migration-failure-card" }],
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "migration-failure-1",
  });
  const pendingKey = worker.context.BossLocalWebIntake.pendingStorageKey(record.batchKey);
  worker.chrome.__store[pendingKey] = record;
  const pendingBefore = JSON.stringify(record.payload);

  const originalSet = worker.chrome.storage.local.set;
  worker.chrome.storage.local.set = async (value) => {
    if (Object.prototype.hasOwnProperty.call(value, "connectionMode")) {
      throw new Error("storage write blocked once");
    }
    return originalSet.call(worker.chrome.storage.local, value);
  };

  await triggerRetryAlarm(worker);

  assert.strictEqual(fetchCalls, 0);
  assert.strictEqual(worker.chrome.__store.connectionMode, undefined);
  assert.strictEqual(JSON.stringify(worker.chrome.__store[pendingKey].payload), pendingBefore);
  assert(worker.chrome.__alarms.some((alarm) => alarm.name === worker.context.BossLocalWebIntake.RETRY_ALARM_NAME));

  worker.chrome.storage.local.set = originalSet;
  await triggerRetryAlarm(worker);

  const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(fetchCalls, 1);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
}

async function testDesktopSettingsEditClearsCsvButtonEvenWhenAlreadyDesktop() {
  const popup = createPopupTestContext({
    store: {
      apiBase: "http://127.0.0.1:17863",
      apiToken: "desktop-token",
      connectionMode: "desktop",
      connectionModeConfirmed: true,
      lastCompletedBatchId: 88,
      lastCompletedBatchConnection: {
        connectionMode: "desktop",
        apiBase: "http://127.0.0.1:17863",
        apiToken: "desktop-token",
      },
    },
    runtimeHandler: createPopupWebRuntimeHandler(),
  });

  await popup.api.init();
  assert(popup.elements.downloadCurrentBatch.textContent.includes("#88"));

  popup.elements.apiBase.value = "http://127.0.0.1:19001";
  await popup.elements.apiBase.listeners.input();

  assert.strictEqual(popup.store.lastCompletedBatchId, null);
  assert.strictEqual(popup.store.lastCompletedBatchConnection, null);
  assert(!popup.elements.downloadCurrentBatch.textContent.includes("#88"));
}

async function testDesktopModeOpenWorkbenchShowsReadableChinesePrompt() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:19001",
    apiToken: "desktop-token",
    connectionMode: "desktop",
    fetchImpl: async (url) => {
      if (url === "http://127.0.0.1:17864/api/health") {
        return {
          ok: true,
          status: 200,
          async json() {
            return { service: "boss-local-web", status: "ok" };
          },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    },
  });

  await popup.api.openWebWorkbench();

  assert(
    popup.elements.status.textContent.includes(
      "当前是旧桌面兼容模式。将打开默认网页工作台 17864 入口；如果网页工作台使用自定义端口，请使用网页连接码重新配对。",
    ),
  );
  assert.strictEqual(popup.tabCreates[0]?.url, "http://127.0.0.1:17864/");
}
async function testConnectionModeKeepsWebAndDesktopStateIsolated() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "shared-token",
    connectionMode: "web",
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  const webSettings = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "shared-token",
    connectionMode: "web",
    jobTitle: "Shared Address",
  };
  const desktopSettings = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "shared-token",
    connectionMode: "desktop",
    jobTitle: "Shared Address",
  };
  const webIdentity = await popup.context.BossLocalWebIntake.connectionIdentity(webSettings);
  await popup.context.BossLocalWebIntake.upsertPendingRecord(
    {
      batchKey: "shared-web-batch",
      idempotencyKey: "shared-web-idem",
      connection: webIdentity,
      payload: {
        source_platform: "boss",
        source_url: "https://www.zhipin.com/web/geek/recommend",
        source_job_title: "Shared Address",
        idempotency_key: "shared-web-idem",
        candidates: [{ raw_card_text: "shared-web-card" }],
      },
      status: "completed",
      statusLabel: "入库成功",
      webResult: { batch_id: 777, status: "completed", received_count: 1, inserted_candidates: 1, updated_candidates: 0, skipped_candidates: 0, failed_candidates: 0 },
      updatedAt: new Date().toISOString(),
    },
    popup.chrome.storage.local,
  );
  await popup.context.BossLocalWebIntake.moveToCompleted(
    await popup.context.BossLocalWebIntake.readPendingRecord("shared-web-batch", popup.chrome.storage.local),
    popup.chrome.storage.local,
  );

  const webStatus = await popup.context.BossLocalWebIntake.getStatusView({ settings: webSettings, storageArea: popup.chrome.storage.local });
  const desktopStatus = await popup.context.BossLocalWebIntake.getStatusView({ settings: desktopSettings, storageArea: popup.chrome.storage.local });
  assert.strictEqual(webStatus.record?.webResult?.batch_id, 777);
  assert.strictEqual(desktopStatus.record, null);

  popup.store.lastCompletedBatchConnection = {
    connectionMode: "desktop",
    apiBase: "http://127.0.0.1:17864",
    apiToken: "shared-token",
  };
  popup.store.lastCompletedBatchId = 55;
  popup.store.connectionMode = "desktop";
  await popup.api.init();
  await popup.api.downloadCurrentBatch();
  assert.strictEqual(popup.store.lastMarkdownExport, undefined);
}

function testCollectorDoesNotPromoteGenericDataIdToPlatformUid() {
  const collector = loadCollectorForTest();
  const bossPlatform = collector.platforms.find((platform) => platform.id === "boss");
  const createCard = (attrs, text) => ({
    innerText: text,
    textContent: text,
    getAttribute(name) {
      return attrs[name] || "";
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
  });
  const first = collector.extractCardPayload(createCard({ "data-id": "same-data-id" }, "测试 原文"), bossPlatform);
  const second = collector.extractCardPayload(createCard({ "data-id": "same-data-id" }, "?? ??"), bossPlatform);
  assert.strictEqual(first.platform_uid, "");
  assert.strictEqual(second.platform_uid, "");
  assert.strictEqual(first.source_candidate_id, "same-data-id");
  assert.strictEqual(second.source_candidate_id, "same-data-id");
}

async function testCollectorAcceptsBossAndLiepinStableCardsOnly() {
  const bossDom = new JSDOM(`
    <main>
      <article class="candidate-card" data-geek-id="boss-alpha">
        <strong class="name">测试甲</strong>
        <span class="salary">30K-45K</span>
        <span class="experience">5年经验</span>
        <span class="education">本科</span>
        <p class="summary">高频交易系统经验</p>
        <a href="/geek/detail/boss-alpha">详情</a>
        <button>打招呼</button>
      </article>
      <article class="ad-card candidate-card">
        <strong>广告位</strong>
        <p>企业服务 首页 导航 筛选</p>
      </article>
      <article class="candidate-card" data-geek-id="hidden-alpha" style="display:none">
        <strong class="name">隐藏候选人</strong>
        <span class="salary">30K-45K</span>
        <span class="experience">5年经验</span>
        <span class="education">本科</span>
        <button>打招呼</button>
      </article>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveCardsLayout(bossDom);
  const bossCollector = loadCollectorForDom(bossDom);
  const boss = bossCollector.platforms.find((platform) => platform.id === "boss");
  const bossResult = await bossCollector.collectCards(boss, false, {});

  assert.strictEqual(bossResult.cards.length, 1);
  assert.strictEqual(bossResult.cards[0].name, "测试甲");
  assert.strictEqual(bossResult.cards[0].platform_uid, "boss:boss-alpha");
  assert.strictEqual(bossResult.cards[0].source_candidate_id, "boss-alpha");
  assert(!bossResult.cards[0].raw_card_text.includes("打招呼"));
  assert(bossResult.diagnostics.hidden >= 1);
  assert(bossResult.diagnostics.missing_name >= 1 || bossResult.diagnostics.missing_candidate_structure >= 1);

  const liepinDom = new JSDOM(`
    <main>
      <article class="resume-card" data-resume-id="lp-101">
        <strong class="resume-name">测试乙</strong>
        <span class="salary">40K-60K</span>
        <span class="work-exp">8年经验</span>
        <span class="degree">硕士</span>
        <p class="summary">当前职位 量化研究员，求职状态开放</p>
        <a href="/candidate/lp-101">查看简历</a>
      </article>
    </main>
  `, { url: "https://lpt.liepin.com/recommend" });
  giveCardsLayout(liepinDom);
  const liepinCollector = loadCollectorForDom(liepinDom, "https://lpt.liepin.com/recommend");
  const liepin = liepinCollector.platforms.find((platform) => platform.id === "liepin");
  const liepinResult = await liepinCollector.collectCards(liepin, false, {});

  assert.strictEqual(liepinResult.cards.length, 1);
  assert.strictEqual(liepinResult.cards[0].name, "测试乙");
  assert.strictEqual(liepinResult.cards[0].platform_uid, "liepin:lp-101");
}

async function testCollectorDedupesByStableUidButKeepsSameNameDifferentUid() {
  const dom = new JSDOM(`
    <main>
      <article class="candidate-card" data-geek-id="same-uid">
        <strong class="name">测试甲</strong>
        <span class="salary">30K-45K</span>
        <span class="experience">5年经验</span>
        <span class="education">本科</span>
        <p>Alpha</p>
        <button>打招呼</button>
      </article>
      <article class="candidate-card" data-geek-id="same-uid">
        <strong class="name">测试甲</strong>
        <span class="salary">30K-45K</span>
        <span class="experience">5年经验</span>
        <span class="education">本科</span>
        <p>Alpha duplicated</p>
        <button>打招呼</button>
      </article>
      <article class="candidate-card" data-geek-id="unique-uid">
        <strong class="name">测试甲</strong>
        <span class="salary">32K-50K</span>
        <span class="experience">6年经验</span>
        <span class="education">硕士</span>
        <p>Beta</p>
        <button>打招呼</button>
      </article>
      <article class="candidate-card" data-id="generic-only">
        <strong class="name">测试丙</strong>
        <span class="salary">25K-35K</span>
        <span class="experience">4年经验</span>
        <span class="education">本科</span>
        <p>无稳定 UID</p>
        <button>打招呼</button>
      </article>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveBossNestedCardsLayout(dom);
  const collector = loadCollectorForDom(dom);
  const boss = collector.platforms.find((platform) => platform.id === "boss");
  const result = await collector.collectCards(boss, false, {});

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result.cards.map((card) => card.platform_uid))), ["boss:same-uid", "boss:unique-uid", ""]);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(result.cards.map((card) => card.name))), ["测试甲", "测试甲", "测试丙"]);
  assert.strictEqual(result.diagnostics.duplicate_identity, 1);
  assert.strictEqual(result.diagnostics.missing_stable_identity, 1);
}

async function testCollectorFindsBossStableUidBeyondCardRoot() {
  const dom = new JSDOM(`
    <main>
      <article class="candidate-card">
        <div class="content">
          <strong class="name">测试甲</strong>
          <span class="salary">30K-45K</span>
          <span class="experience">5年经验</span>
          <span class="education">本科</span>
          <p>真实结构中稳定身份可能在内部节点。</p>
          <div class="geek-meta" data-geek-id="inner-alpha"></div>
          <button>打招呼</button>
        </div>
      </article>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveBossNestedCardsLayout(dom);
  const collector = loadCollectorForDom(dom);
  const boss = collector.platforms.find((platform) => platform.id === "boss");
  const result = await collector.collectCards(boss, false, {});

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result.cards.map((card) => card.platform_uid))), ["boss:inner-alpha"]);
  assert.strictEqual(result.diagnostics.accepted_cards, 1);
  assert.strictEqual(result.diagnostics.stable_identity_found, 1);
  assert.strictEqual(result.diagnostics.identity_from_descendant, 1);
  assert.strictEqual(Number(result.diagnostics.identity_from_bounded_ancestor || 0), 0);
  assert.strictEqual(result.diagnostics.missing_stable_identity, 0);
  assert.strictEqual(result.diagnostics.stable_identity_ambiguous, 0);
  assert.strictEqual(
    result.diagnostics.stable_identity_found + result.diagnostics.missing_stable_identity + result.diagnostics.stable_identity_ambiguous,
    result.diagnostics.accepted_cards,
  );

  const ancestorDom = new JSDOM(`
    <main>
      <section class="candidate-card-wrap" data-geek-id="ancestor-beta">
        <article class="card-inner">
          <strong class="name">测试乙</strong>
          <span class="salary">35K-55K</span>
          <span class="experience">6年经验</span>
          <span class="education">硕士</span>
          <p>真实结构中稳定身份可能在受控祖先。</p>
          <button>打招呼</button>
        </article>
      </section>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveBossNestedCardsLayout(ancestorDom);
  ancestorDom.window.document.querySelector(".candidate-card-wrap").getBoundingClientRect = () => ({
    width: 720,
    height: 5000,
    top: 0,
    left: 0,
    right: 720,
    bottom: 5000,
  });
  const ancestorCollector = loadCollectorForDom(ancestorDom);
  const ancestorBoss = ancestorCollector.platforms.find((platform) => platform.id === "boss");
  const ancestorResult = await ancestorCollector.collectCards(ancestorBoss, false, {});

  assert.deepStrictEqual(JSON.parse(JSON.stringify(ancestorResult.cards.map((card) => card.platform_uid))), ["boss:ancestor-beta"]);
  assert.strictEqual(ancestorResult.diagnostics.stable_identity_found, 1);
  assert.strictEqual(ancestorResult.diagnostics.identity_from_bounded_ancestor, 1);
  assert.strictEqual(ancestorResult.diagnostics.missing_stable_identity, 0);
}

async function testCollectorTreatsBossStableUidAmbiguityAsMissingIdentity() {
  const dom = new JSDOM(`
    <main>
      <article class="candidate-card">
        <strong class="name">测试丙</strong>
        <span class="salary">30K-45K</span>
        <span class="experience">5年经验</span>
        <span class="education">本科</span>
        <p>两个不同稳定身份不能随便选择。</p>
        <span data-geek-id="ambiguous-a"></span>
        <span data-candidate-id="ambiguous-b"></span>
        <button>打招呼</button>
      </article>
      <article class="candidate-card">
        <strong class="name">测试丁</strong>
        <span class="salary">32K-46K</span>
        <span class="experience">6年经验</span>
        <span class="education">硕士</span>
        <p>多个节点同一稳定身份可以采用。</p>
        <span data-geek-id="same-inner"></span>
        <span data-candidate-id="same-inner"></span>
        <button>打招呼</button>
      </article>
      <article class="candidate-card" data-id="generic-only">
        <strong class="name">测试戊</strong>
        <span class="salary">25K-35K</span>
        <span class="experience">4年经验</span>
        <span class="education">本科</span>
        <p>只有泛化 data-id。</p>
        <a href="/geek/detail/generic-only">详情</a>
        <button>打招呼</button>
      </article>
      <article class="candidate-card" data-geek-id="liepin:foreign">
        <strong class="name">测试己</strong>
        <span class="salary">28K-40K</span>
        <span class="experience">5年经验</span>
        <span class="education">本科</span>
        <p>其他平台前缀不能冒充 Boss 身份。</p>
        <button>打招呼</button>
      </article>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveCardsLayout(dom);
  const collector = loadCollectorForDom(dom);
  const boss = collector.platforms.find((platform) => platform.id === "boss");
  const result = await collector.collectCards(boss, false, {});

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result.cards.map((card) => card.platform_uid))), ["", "boss:same-inner", "", ""]);
  assert.strictEqual(result.diagnostics.accepted_cards, 4);
  assert.strictEqual(result.diagnostics.stable_identity_found, 1);
  assert.strictEqual(result.diagnostics.stable_identity_ambiguous, 1);
  assert.strictEqual(result.diagnostics.missing_stable_identity, 2);
  assert.strictEqual(
    result.diagnostics.stable_identity_found + result.diagnostics.missing_stable_identity + result.diagnostics.stable_identity_ambiguous,
    result.diagnostics.accepted_cards,
  );
}

async function testCollectorRawCardTextIgnoresPluginBadgesAndKeywordMarkup() {
  const dom = new JSDOM(`
    <main>
      <article class="candidate-card" data-geek-id="clean-uid">
        <span class="boss-local-rating-badge">1SSR</span>
        <strong class="name">测试丁</strong>
        <span class="salary">35K-55K</span>
        <span class="experience">7年经验</span>
        <span class="education">硕士</span>
        <p class="summary">熟悉<span class="boss-local-keyword-highlight must">Python</span>与交易系统</p>
        <span class="boss-local-keyword-badge">关键词 3</span>
        <div class="boss-local-keyword-filterbar"><button>风险 1</button></div>
        <button>打招呼</button>
      </article>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveCardsLayout(dom);
  const collector = loadCollectorForDom(dom);
  const boss = collector.platforms.find((platform) => platform.id === "boss");
  const payload = collector.extractCardPayload(dom.window.document.querySelector(".candidate-card"), boss);

  assert.strictEqual(payload.platform_uid, "boss:clean-uid");
  assert(payload.raw_card_text.includes("测试丁"));
  assert(payload.raw_card_text.includes("Python"));
  assert(!payload.raw_card_text.includes("1SSR"));
  assert(!payload.raw_card_text.includes("关键词 3"));
  assert(!payload.raw_card_text.includes("风险 1"));
  assert(!payload.raw_card_text.includes("打招呼"));
}

async function testCollectorIgnoresDetachedNodesAndUsesFreshDomSnapshots() {
  const dom = new JSDOM(`
    <main>
      <article class="candidate-card" data-geek-id="page-a">
        <strong class="name">页面甲</strong>
        <span class="salary">30K-45K</span>
        <span class="experience">5年经验</span>
        <span class="education">本科</span>
        <p>第一页候选人</p>
        <button>打招呼</button>
      </article>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveCardsLayout(dom);
  const collector = loadCollectorForDom(dom);
  const boss = collector.platforms.find((platform) => platform.id === "boss");
  const first = await collector.collectCards(boss, false, {});
  assert.strictEqual(first.cards.length, 1);
  assert.strictEqual(first.cards[0].platform_uid, "boss:page-a");

  const staleNode = dom.window.document.querySelector(".candidate-card");
  staleNode.remove();
  assert.strictEqual(collector.extractCardPayload(staleNode, boss).platform_uid, "boss:page-a");

  dom.window.document.querySelector("main").innerHTML = `
    <article class="candidate-card" data-geek-id="page-b">
      <strong class="name">页面乙</strong>
      <span class="salary">35K-55K</span>
      <span class="experience">6年经验</span>
      <span class="education">硕士</span>
      <p>第二页候选人</p>
      <button>打招呼</button>
    </article>
  `;
  giveCardsLayout(dom);
  const second = await collector.collectCards(boss, false, {});
  assert.strictEqual(second.cards.length, 1);
  assert.strictEqual(second.cards[0].platform_uid, "boss:page-b");
  assert.strictEqual(second.cards[0].name, "页面乙");
  assert(!second.cards.some((card) => card.platform_uid === "boss:page-a"));

  const reused = dom.window.document.querySelector(".candidate-card");
  reused.setAttribute("data-geek-id", "page-c");
  reused.querySelector(".name").textContent = "页面丙";
  reused.querySelector(".salary").textContent = "40K-60K";
  reused.querySelector(".experience").textContent = "7年经验";
  reused.querySelector(".education").textContent = "博士";
  const third = await collector.collectCards(boss, false, {});
  assert.strictEqual(third.cards.length, 1);
  assert.strictEqual(third.cards[0].platform_uid, "boss:page-c");
  assert.strictEqual(third.cards[0].name, "页面丙");
}

async function testCollectorExtractsBossCurrentDetailSafely() {
  const dom = new JSDOM(`
    <main>
      <section class="candidate-detail" data-geek-id="detail-alpha">
        <h2 class="name">详情测试甲</h2>
        <span class="salary">45K-65K</span>
        <span class="experience">8年经验</span>
        <span class="education">本科</span>
        <p>城市：上海</p>
        <p>职能：技术</p>
        <p>方向：策略平台</p>
        <p class="summary">长期做策略平台 Python</p>
        <span class="boss-local-rating-badge">1SSR</span>
        <span class="boss-local-keyword-badge">关键词 2</span>
        <button>打招呼</button>
        <p>邮箱：safe@example.invalid</p>
      </section>
      <article class="candidate-card" data-geek-id="list-alpha">
        <strong class="name">列表候选</strong>
        <span class="salary">35K-45K</span>
        <span class="experience">6年经验</span>
        <span class="education">本科</span>
        <button>打招呼</button>
      </article>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveCardsLayout(dom);
  giveDetailLayout(dom);
  const collector = loadCollectorForDom(dom);
  const boss = collector.platforms.find((platform) => platform.id === "boss");
  const result = collector.extractCurrentDetail(boss, { recruitmentTaskId: 11, jobProfileId: 22 });

  assert.strictEqual(result.status, "capturable");
  assert.strictEqual(result.detail.platform_uid, "boss:detail-alpha");
  assert.strictEqual(result.detail.recruitment_task_id, 11);
  assert.strictEqual(result.detail.job_profile_id, 22);
  assert.strictEqual(result.detail.city, "上海");
  assert.strictEqual(result.detail.years_experience, 8);
  assert.strictEqual(result.detail.job_family, "技术");
  assert.strictEqual(result.detail.job_track, "策略平台");
  assert(result.detail.raw_card_text.includes("详情测试甲"));
  assert(!result.detail.raw_card_text.includes("1SSR"));
  assert(!result.detail.raw_card_text.includes("关键词 2"));
  assert(!result.detail.raw_card_text.includes("打招呼"));
  assert(!result.detail.raw_card_text.includes("safe@example.invalid"));
}

async function testCollectorExtractsLiepinCurrentDetail() {
  const dom = new JSDOM(`
    <main>
      <section class="resume-detail" data-resume-id="resume-alpha">
        <h2 class="name">详情测试乙</h2>
        <span class="salary">35K-50K</span>
        <span class="experience">6年经验</span>
        <span class="education">硕士</span>
        <p>城市：深圳</p>
        <p>方向：数据工程</p>
        <p>候选人长期负责数据平台建设</p>
      </section>
    </main>
  `, { url: "https://lpt.liepin.com/recommend" });
  giveDetailLayout(dom);
  const collector = loadCollectorForDom(dom, "https://lpt.liepin.com/recommend");
  const liepin = collector.platforms.find((platform) => platform.id === "liepin");
  const result = collector.extractCurrentDetail(liepin, { recruitmentTaskId: 33, jobProfileId: 44 });

  assert.strictEqual(result.status, "capturable");
  assert.strictEqual(result.detail.platform_uid, "liepin:resume-alpha");
  assert.strictEqual(result.detail.source_platform, "liepin");
  assert.strictEqual(result.detail.city, "深圳");
  assert.strictEqual(result.detail.job_track, "数据工程");
}

async function testCollectorDetailRejectsHiddenLoadingMultipleAndUnconfirmed() {
  const hidden = new JSDOM(`
    <main>
      <section class="candidate-detail hidden-detail" data-geek-id="hidden-alpha" style="display:none">
        <h2 class="name">隐藏详情</h2><p>45K-65K</p><p>8年经验</p><p>本科</p>
      </section>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveDetailLayout(hidden);
  let collector = loadCollectorForDom(hidden);
  let boss = collector.platforms.find((platform) => platform.id === "boss");
  assert.strictEqual(collector.extractCurrentDetail(boss, {}).status, "not_opened");

  const loading = new JSDOM(`
    <main>
      <section class="candidate-detail loading-detail" data-geek-id="loading-alpha">
        <p>加载中</p><p>45K-65K</p><p>8年经验</p><p>本科</p>
      </section>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveDetailLayout(loading);
  collector = loadCollectorForDom(loading);
  boss = collector.platforms.find((platform) => platform.id === "boss");
  assert.strictEqual(collector.extractCurrentDetail(boss, {}).status, "not_opened");

  const multiple = new JSDOM(`
    <main>
      <section class="candidate-detail" data-geek-id="multi-a"><h2 class="name">多详情甲</h2><p>45K-65K</p><p>8年经验</p><p>本科</p><p>策略平台</p></section>
      <section class="candidate-detail" data-geek-id="multi-b"><h2 class="name">多详情乙</h2><p>35K-50K</p><p>6年经验</p><p>硕士</p><p>数据平台</p></section>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveDetailLayout(multiple);
  collector = loadCollectorForDom(multiple);
  boss = collector.platforms.find((platform) => platform.id === "boss");
  assert.strictEqual(collector.extractCurrentDetail(boss, {}).status, "ambiguous");

  const unconfirmed = new JSDOM(`
    <main>
      <section class="candidate-detail"><h2 class="name">无身份详情</h2><p>45K-65K</p><p>8年经验</p><p>本科</p><p>策略平台</p></section>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveDetailLayout(unconfirmed);
  collector = loadCollectorForDom(unconfirmed);
  boss = collector.platforms.find((platform) => platform.id === "boss");
  assert.strictEqual(collector.extractCurrentDetail(boss, {}).status, "unconfirmed");
}

async function testCollectorDetailUsesFreshDomAfterCandidateSwitchAndClose() {
  const dom = new JSDOM(`
    <main>
      <section class="candidate-detail" data-geek-id="detail-a">
        <h2 class="name">详情甲</h2><p>45K-65K</p><p>8年经验</p><p>本科</p><p>策略平台</p>
      </section>
    </main>
  `, { url: "https://www.zhipin.com/web/geek/recommend" });
  giveDetailLayout(dom);
  const collector = loadCollectorForDom(dom);
  const boss = collector.platforms.find((platform) => platform.id === "boss");
  const first = collector.extractCurrentDetail(boss, {});
  assert.strictEqual(first.detail.platform_uid, "boss:detail-a");

  dom.window.document.querySelector("main").innerHTML = `
    <section class="candidate-detail" data-geek-id="detail-b">
      <h2 class="name">详情乙</h2><p>35K-50K</p><p>6年经验</p><p>硕士</p><p>数据平台</p>
    </section>
  `;
  giveDetailLayout(dom);
  const second = collector.extractCurrentDetail(boss, {});
  assert.strictEqual(second.detail.platform_uid, "boss:detail-b");
  assert(!second.detail.raw_card_text.includes("详情甲"));

  dom.window.document.querySelector(".candidate-detail").remove();
  const closed = collector.extractCurrentDetail(boss, {});
  assert.strictEqual(closed.status, "not_opened");
}

async function testPopupCurrentDetailEnrichmentPostsSafePayloadInWebModeOnly() {
  const frameResults = [{ result: {
    status: "capturable",
    detail: {
      source_platform: "boss",
      platform_uid: "boss:detail-alpha",
      recruitment_task_id: 11,
      job_profile_id: 22,
      raw_card_text: "详情测试甲\n长期做策略平台",
      summary_text: "长期做策略平台",
    },
  } }];
  const fetchCalls = [];
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async (url, requestOptions = {}) => {
      fetchCalls.push({ url: String(url), options: requestOptions });
      if (String(url).endsWith("/api/plugin/context")) {
        return {
          ok: true,
          json: async () => ({
            recruitment_task_id: 11,
            job_profile_id: 22,
            job_profile_version: 3,
            job_title: "量化研究员",
            task_status: "running",
          }),
        };
      }
      if (String(url).endsWith("/api/plugin/candidate-detail/enrich")) {
        return { ok: true, json: async () => ({ status: "updated", updated_fields: ["summary_text"] }) };
      }
      throw new Error(`unexpected fetch ${String(url)}`);
    },
  });
  popup.chrome.scripting.executeScript = async (details) => {
    if (details.files) return [{ result: true }];
    return frameResults;
  };

  await popup.api.init();
  await popup.api.runCurrentDetailEnrichment();

  const enrichCalls = fetchCalls.filter((call) => call.url.endsWith("/api/plugin/candidate-detail/enrich"));
  assert.strictEqual(enrichCalls.length, 1);
  assert.strictEqual(enrichCalls[0].options.headers["X-Boss-Local-Token"], "web-token");
  assert(!enrichCalls[0].url.includes("web-token"));
  const body = JSON.parse(enrichCalls[0].options.body);
  assert.strictEqual(body.platform_uid, "boss:detail-alpha");
  assert(!("name" in body));
  assert(popup.elements.status.textContent.includes("已安全更新"));

  const desktop = createPopupTestContext({
    apiBase: "http://127.0.0.1:19001",
    apiToken: "desktop-token",
    connectionMode: "desktop",
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async () => {
      throw new Error("desktop mode must not fetch");
    },
  });
  await desktop.api.init();
  await desktop.api.runCurrentDetailEnrichment();
  assert(desktop.elements.status.textContent.includes("仅支持网页工作台模式"));
}

async function testPopupCurrentDetailEnrichmentRejectsUnconfirmedAndAllowsRetryAfterFailure() {
  let frameStatus = "unconfirmed";
  let failWrite = true;
  let enrichCount = 0;
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    runtimeHandler: createPopupWebRuntimeHandler(),
    fetchImpl: async (url) => {
      if (String(url).endsWith("/api/plugin/context")) {
        return {
          ok: true,
          json: async () => ({
            recruitment_task_id: 11,
            job_profile_id: 22,
            job_profile_version: 3,
            job_title: "量化研究员",
            task_status: "running",
          }),
        };
      }
      if (String(url).endsWith("/api/plugin/candidate-detail/enrich")) {
        enrichCount += 1;
        if (failWrite) {
          return { ok: false, json: async () => ({ error: { message: "无法确认当前详情对应的候选人。" } }) };
        }
        return { ok: true, json: async () => ({ status: "unchanged" }) };
      }
      throw new Error(`unexpected fetch ${String(url)}`);
    },
  });
  popup.chrome.scripting.executeScript = async (details) => {
    if (details.files) return [{ result: true }];
    if (frameStatus === "unconfirmed") {
      return [{ result: { status: "unconfirmed", detail: null } }];
    }
    return [{ result: { status: "capturable", detail: { source_platform: "boss", platform_uid: "boss:retry", raw_card_text: "安全详情" } } }];
  };

  await popup.api.init();
  await popup.api.runCurrentDetailEnrichment();
  assert.strictEqual(enrichCount, 0);
  assert(popup.elements.status.textContent.includes("当前页面暂不支持安全详情关联"));

  frameStatus = "capturable";
  await popup.api.runCurrentDetailEnrichment();
  assert.strictEqual(enrichCount, 1);
  assert(popup.elements.status.textContent.includes("采集当前详情失败"));

  failWrite = false;
  await popup.api.runCurrentDetailEnrichment();
  assert.strictEqual(enrichCount, 2);
  assert(popup.elements.status.textContent.includes("没有新的可更新信息"));
}

async function testWebIntakeStatusMatrixFollowsServerStatus() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "web-token" });
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "web-token", jobTitle: "Boss 测试岗位" };
  const runStatus = async (status) => {
    const queued = await popup.context.BossLocalWebIntake.queueCapturedBatch({
      settings,
      merged: { platform: "boss", cards: [{ source_candidate_id: `${status}-1`, raw_card_text: status }] },
      sourceUrl: "https://www.zhipin.com/web/geek/recommend",
      idempotencyKey: `status-${status}-${Date.now()}`,
      storageArea: popup.chrome.storage.local,
    });
    return popup.context.BossLocalWebIntake.sendQueuedBatch({
      settings,
      batchKey: queued.batchKey,
      storageArea: popup.chrome.storage.local,
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        async json() {
          return {
            batch_id: 500,
            status,
            reused: status === "reused",
            received_count: 1,
            inserted_candidates: 1,
            updated_candidates: 0,
            skipped_candidates: 0,
            failed_candidates: status === "failed" || status === "partial" ? 1 : 0,
          };
        },
      }),
    });
  };
  assert.strictEqual((await runStatus("failed")).status, "failed");
  assert.strictEqual((await runStatus("partial")).status, "partial");
  assert.strictEqual((await runStatus("completed")).status, "completed");
  assert.strictEqual((await runStatus("reused")).status, "reused");
}

async function testPopupWebModeAutoShowsDesktopOnlyBoundary() {
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  await popup.api.init();
  await popup.api.runAutomation();
  assert(popup.elements.automationAuto.title.includes("Web"));
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
    { connectionMode: "desktop", apiBase: "http://127.0.0.1:17863/", apiToken: "secret-token" },
    { connectionMode: "desktop", apiBase: "http://127.0.0.1:17863", apiToken: "secret-token" },
  ));
  assert(!context.BossLocalBatchExport.batchBelongsToConnection(
    { connectionMode: "desktop", apiBase: "http://127.0.0.1:17863", apiToken: "old-token" },
    { connectionMode: "desktop", apiBase: "http://127.0.0.1:17863", apiToken: "new-token" },
  ));
  assert(!context.BossLocalBatchExport.batchBelongsToConnection(
    { connectionMode: "desktop", apiBase: "http://127.0.0.1:17863", apiToken: "secret-token" },
    { connectionMode: "desktop", apiBase: "http://127.0.0.1:19000", apiToken: "secret-token" },
  ));
  assert(!context.BossLocalBatchExport.batchBelongsToConnection(
    { connectionMode: "desktop", apiBase: "http://127.0.0.1:17864", apiToken: "secret-token" },
    { connectionMode: "web", apiBase: "http://127.0.0.1:17864", apiToken: "secret-token" },
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

  const markdown = await context.BossLocalBatchExport.downloadBatchMarkdown({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    batchId: 160,
    fetchImpl: async (url, options) => {
      calls.push(["markdown-fetch", url, options.headers["X-Boss-Local-Token"]]);
      return {
        ok: true,
        headers: { get: () => "attachment; filename*=UTF-8''boss-%E6%89%B9%E6%AC%A1-160.md" },
        async blob() { return new Blob(["# batch"], { type: "text/markdown" }); },
      };
    },
    downloadsApi: {
      async download(options) {
        calls.push(["markdown-download", options.filename]);
        return 99;
      },
    },
    urlApi: context.URL,
  });
  assert.strictEqual(markdown.batchId, 160);
  assert(calls.some((entry) => entry[0] === "markdown-fetch"
    && entry[1] === "http://127.0.0.1:17864/api/capture-batches/160/export.md"));
  assert(calls.some((entry) => entry[0] === "markdown-download" && entry[1] === "boss-批次-160.md"));

  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(html.includes('id="downloadCurrentBatch"'));
  assert(html.includes('<script src="batch_export.js"></script>'));
  assert(popup.includes("lastCompletedBatchId"));
  assert(popup.includes("lastCompletedBatchConnection"));
  assert(popup.includes("batchBelongsToConnection"));
  assert(popup.includes("imported.batch_id"));
  assert(popup.includes("BossLocalBatchExport.downloadBatchCsv"));
  assert(popup.includes("BossLocalBatchExport.downloadBatchMarkdown"));
}

async function testPopupReopenRestoresWebBatchMarkdownExport() {
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(html.includes('id="apiBase" type="text" value="http://127.0.0.1:17863"'));
  assert(html.includes('<details class="advanced-settings" id="desktopAdvanced">'));
  assert(html.includes('id="apiToken" type="password"'));

  const store = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "reopen-web-token",
    connectionMode: "web",
    jobTitle: "Reopen Web Batch",
  };
  const popup = createPopupTestContext({
    store,
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  assert.strictEqual(popup.elements.apiBase.value, "http://127.0.0.1:17863");

  const connection = await popup.context.BossLocalWebIntake.connectionIdentity({
    apiBase: store.apiBase,
    apiToken: store.apiToken,
    connectionMode: "web",
  });
  const batchKey = "reopen-web-batch-160";
  store[`${popup.context.BossLocalWebIntake.COMPLETED_PREFIX}${batchKey}`] = {
    batchKey,
    idempotencyKey: "reopen-idempotency-160",
    connection,
    status: "completed",
    statusLabel: "入库成功",
    webResult: {
      batch_id: 160,
      status: "completed",
      received_count: 1,
      inserted_candidates: 1,
      updated_candidates: 0,
      skipped_candidates: 0,
      failed_candidates: 0,
    },
    completedAt: "2026-08-11T10:00:00.000Z",
  };

  await popup.api.init();

  assert.strictEqual(popup.elements.apiBase.value, "http://127.0.0.1:17864");
  assert.strictEqual(popup.elements.applyPairingCode.textContent, "重新配对");
  assert.strictEqual(popup.elements.downloadCurrentBatch.textContent, "导出本批次 #160 Markdown");
  await popup.api.downloadCurrentBatch();
  assert.deepStrictEqual(store.lastMarkdownExport, {
    apiBase: "http://127.0.0.1:17864",
    batchId: 160,
  });
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



async function testPopupExpiredSendingEnablesManualRetry() {
  const sharedStore = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "retry-ui-token",
  };
  const popup = createPopupTestContext({
    store: sharedStore,
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "retry-ui-token", jobTitle: "Retry UI" };
  const queued = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged: { platform: "boss", cards: [{ source_candidate_id: "retry-ui-1", raw_card_text: "retry-ui-card" }] },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "retry-ui-batch",
    storageArea: popup.chrome.storage.local,
  });
  await popup.context.BossLocalWebIntake.upsertPendingRecord(
    {
      ...(await popup.context.BossLocalWebIntake.readPendingRecord(queued.batchKey, popup.chrome.storage.local)),
      status: "sending",
      attemptCount: 1,
      sendingStartedAt: new Date(Date.now() - 1000).toISOString(),
      leaseOwner: "live-worker",
      leaseExpiresAt: new Date(Date.now() + 30000).toISOString(),
    },
    popup.chrome.storage.local,
  );
  await popup.api.refreshWebIntakeStatus(settings);
  assert.strictEqual(popup.elements.retryWebIntake.disabled, true);
  assert(popup.elements.webIntakeStatus.textContent.length > 0);

  await popup.context.BossLocalWebIntake.upsertPendingRecord(
    {
      ...(await popup.context.BossLocalWebIntake.readPendingRecord(queued.batchKey, popup.chrome.storage.local)),
      sendingStartedAt: new Date(Date.now() - 120000).toISOString(),
      leaseExpiresAt: new Date(Date.now() - 60000).toISOString(),
    },
    popup.chrome.storage.local,
  );
  await popup.api.refreshWebIntakeStatus(settings);
  assert.strictEqual(popup.elements.retryWebIntake.disabled, false);
  assert.notStrictEqual(popup.elements.webIntakeStatus.textContent, "");
}

async function testLegacyV2MigrationMatchesCurrentConnectionAndCanSend() {
  const worker = loadServiceWorker(async () => ({
    ok: true,
    status: 200,
    async json() {
      return {
        batch_id: 901,
        status: "completed",
        received_count: 1,
        inserted_candidates: 1,
        updated_candidates: 0,
        skipped_candidates: 0,
        failed_candidates: 0,
      };
    },
  }));
  const apiBase = "http://127.0.0.1:17864";
  const webApiBase = "http://127.0.0.1:17864";
  const apiToken = "legacy-token";
  Object.assign(worker.chrome.__store, { apiBase, apiToken, jobTitle: "Legacy Test" });
  const stableHash = worker.context.BossLocalWebIntake.stableHash;
  worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {
      "legacy-pending": {
        batchKey: "legacy-pending",
        idempotencyKey: "legacy-idem-1",
        payload: {
          source_platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          source_job_title: "Legacy Test",
          idempotency_key: "legacy-idem-1",
          candidates: [{ name: "Legacy Name", raw_card_text: "Legacy Raw Card", detail_url: "https://www.zhipin.com/candidate/legacy" }],
        },
        connection: {
          modeApiBase: apiBase,
          webApiBase,
          tokenFingerprint: stableHash(apiToken),
          key: stableHash(apiBase + "|" + webApiBase + "|" + apiToken),
        },
      },
    },
    completedBatches: {},
  };
  let state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY], undefined);
  assert.strictEqual(state.pendingOrder.length, 1);
  const pending = state.pendingBatches[state.pendingOrder[0]];
  assert.strictEqual(pending.idempotencyKey, "legacy-idem-1");
  await worker.context.BossLocalWebIntake.sendQueuedBatch({
    settings: { apiBase, apiToken, jobTitle: "Legacy Test" },
    batchKey: pending.batchKey,
    storageArea: worker.chrome.storage.local,
    fetchImpl: worker.context.fetch,
  });
  state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
  const serialized = JSON.stringify(worker.chrome.__store);
  assert(!serialized.includes("Legacy Name"));
  assert(!serialized.includes("Legacy Raw Card"));
}

async function testLegacyV2MigrationKeepsMismatchedPendingUntilOriginalConnectionReturns() {
  const worker = loadServiceWorker();
  const stableHash = worker.context.BossLocalWebIntake.stableHash;
  worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {
      "legacy-pending": {
        batchKey: "legacy-pending",
        idempotencyKey: "legacy-idem-keep",
        payload: {
          source_platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          source_job_title: "Legacy Keep",
          idempotency_key: "legacy-idem-keep",
          candidates: [{ name: "Keep Name", raw_card_text: "Keep Raw Card", detail_url: "https://www.zhipin.com/candidate/keep" }],
        },
        connection: {
          modeApiBase: "http://127.0.0.1:17864",
          webApiBase: "http://127.0.0.1:17864",
          tokenFingerprint: stableHash("original-token"),
          key: stableHash("http://127.0.0.1:17864|http://127.0.0.1:17864|original-token"),
        },
      },
    },
    completedBatches: {},
  };
  Object.assign(worker.chrome.__store, { apiBase: "http://127.0.0.1:17864", apiToken: "other-token" });
  let state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert(worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY]);
  let serialized = JSON.stringify(worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY]);
  assert(serialized.includes("Keep Name"));
  assert(serialized.includes("Keep Raw Card"));

  worker.chrome.__store.apiToken = "original-token";
  state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY], undefined);
  assert.strictEqual(state.pendingOrder.length, 1);
  const pending = state.pendingBatches[state.pendingOrder[0]];
  assert.strictEqual(pending.idempotencyKey, "legacy-idem-keep");
}

async function testCompletedTransitionScrubsSensitivePendingBeforeDelete() {
  const popup = createPopupTestContext({ apiBase: "http://127.0.0.1:17864", apiToken: "web-token" });
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "web-token", jobTitle: "Safe Transition" };
  const queued = await popup.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged: {
      platform: "boss",
      cards: [{ source_candidate_id: "boss-safe", detail_url: "https://www.zhipin.com/candidate/safe", raw_card_text: "Sensitive Raw Card", name: "Sensitive Name" }],
    },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "safe-transition",
    storageArea: popup.chrome.storage.local,
  });
  let fetchCalls = 0;
  const completedKey = popup.context.BossLocalWebIntake.completedStorageKey(queued.batchKey);
  const originalSet = popup.chrome.storage.local.set;
  popup.chrome.storage.local.set = async (value) => {
    if (Object.prototype.hasOwnProperty.call(value, completedKey)) {
      popup.chrome.storage.local.set = originalSet;
      throw new Error("completed write failed once");
    }
    return originalSet.call(popup.chrome.storage.local, value);
  };
  const firstResult = await popup.context.BossLocalWebIntake.sendQueuedBatch({
    settings,
    batchKey: queued.batchKey,
    storageArea: popup.chrome.storage.local,
    fetchImpl: async () => {
      fetchCalls += 1;
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            batch_id: 777,
            status: "completed",
            received_count: 1,
            inserted_candidates: 1,
            updated_candidates: 0,
            skipped_candidates: 0,
            failed_candidates: 0,
          };
        },
      };
    },
  });
  assert.strictEqual(firstResult.status, "waiting_retry");
  let serialized = JSON.stringify(popup.store);
  assert(!serialized.includes("Sensitive Name"));
  assert(!serialized.includes("Sensitive Raw Card"));
  assert(!serialized.includes("candidate/safe"));
  assert(!serialized.includes("payload"));
  const pendingAfterFailure = await popup.context.BossLocalWebIntake.readPendingRecord(queued.batchKey, popup.chrome.storage.local);
  assert.strictEqual(pendingAfterFailure.scrubbedPendingTransition, true);
  assert.strictEqual(Boolean(pendingAfterFailure.payload), false);
  await Promise.resolve();
  const secondResult = await popup.context.BossLocalWebIntake.sendQueuedBatch({
    settings,
    batchKey: queued.batchKey,
    storageArea: popup.chrome.storage.local,
    fetchImpl: async () => {
      fetchCalls += 1;
      throw new Error("should not send again");
    },
  });
  assert.strictEqual(secondResult.status, "completed");
  assert.strictEqual(fetchCalls, 1);
  await popup.context.BossLocalWebIntake.loadState(popup.chrome.storage.local);
  serialized = JSON.stringify(popup.store);
  assert(!serialized.includes("Sensitive Name"));
  assert(!serialized.includes("Sensitive Raw Card"));
  assert(!serialized.includes("payload"));
}

async function testAlarmExistsBeforeInitialSendAndCrashRecoveryCompletesAfterLeaseExpires() {
  let fakeNow = Date.now();
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "crash-token", jobTitle: "Crash Recovery" };
  const fetchStarted = createDeferred();
  const releaseFetch = createDeferred();
  const firstWorker = loadServiceWorker(async () => {
    fetchStarted.resolve();
    await releaseFetch.promise;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 991,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  firstWorker.context.__bossLocalWebIntakeNow = () => fakeNow;
  Object.assign(firstWorker.chrome.__store, settings);
  const sendPromise = firstWorker.api.enqueueAndSendWebIntake({
    settings,
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    merged: {
      platform: "boss",
      cards: [{ source_candidate_id: "crash-1", raw_card_text: "crash-card", name: "Crash Name", detail_url: "https://www.zhipin.com/candidate/crash-1" }],
    },
    idempotencyKey: "crash-batch",
  });
  await fetchStarted.promise;
  assert(firstWorker.chrome.__alarms.some((alarm) => alarm.name === firstWorker.context.BossLocalWebIntake.RETRY_ALARM_NAME));

  let recoveryFetchCalls = 0;
  const secondWorker = loadServiceWorker(async () => {
    recoveryFetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 992,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  secondWorker.context.__bossLocalWebIntakeNow = () => fakeNow;
  Object.assign(secondWorker.chrome.__store, firstWorker.chrome.__store);

  await triggerRetryAlarm(secondWorker);
  assert.strictEqual(recoveryFetchCalls, 0);
  assert(secondWorker.chrome.__alarms.some((alarm) => alarm.name === secondWorker.context.BossLocalWebIntake.RETRY_ALARM_NAME));

  fakeNow += secondWorker.context.BossLocalWebIntake.SEND_LEASE_MS + 1000;
  await triggerRetryAlarm(secondWorker);
  const state = await secondWorker.context.BossLocalWebIntake.loadState(secondWorker.chrome.storage.local);
  assert.strictEqual(recoveryFetchCalls, 1);
  assert.strictEqual(state.pendingOrder.length, 0);
  assert.strictEqual(state.completedOrder.length, 1);
  const serialized = JSON.stringify(secondWorker.chrome.__store);
  assert(!serialized.includes("Crash Name"));
  assert(!serialized.includes("crash-card"));
  assert(!serialized.includes("candidate/crash-1"));
  releaseFetch.resolve();
  void sendPromise;
}

async function testManualRetryCreatesAlarmBeforeFetchStarts() {
  const settings = { apiBase: "http://127.0.0.1:17864", apiToken: "manual-alarm-token", jobTitle: "Manual Retry Alarm" };
  const fetchStarted = createDeferred();
  const releaseFetch = createDeferred();
  const worker = loadServiceWorker(async () => {
    fetchStarted.resolve();
    await releaseFetch.promise;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 993,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    };
  });
  Object.assign(worker.chrome.__store, settings);
  const queued = await worker.context.BossLocalWebIntake.queueCapturedBatch({
    settings,
    merged: { platform: "boss", cards: [{ source_candidate_id: "manual-alarm-1", raw_card_text: "manual-alarm-card" }] },
    sourceUrl: "https://www.zhipin.com/web/geek/recommend",
    idempotencyKey: "manual-alarm-batch",
    storageArea: worker.chrome.storage.local,
  });
  await worker.context.BossLocalWebIntake.upsertPendingRecord(
    {
      ...(await worker.context.BossLocalWebIntake.readPendingRecord(queued.batchKey, worker.chrome.storage.local)),
      status: "waiting_retry",
      attemptCount: 1,
    },
    worker.chrome.storage.local,
  );
  const retryPromise = worker.api.retryWebIntake(settings);
  await fetchStarted.promise;
  assert(worker.chrome.__alarms.some((alarm) => alarm.name === worker.context.BossLocalWebIntake.RETRY_ALARM_NAME));
  releaseFetch.resolve();
  await retryPromise;
}

async function testLegacyV2CompletedMigrationSanitizesSensitiveData() {
  const worker = loadServiceWorker();
  worker.chrome.__store[worker.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {},
    completedBatches: {
      "legacy-completed": {
        batchKey: "legacy-completed",
        idempotencyKey: "legacy-idem-2",
        payload: {
          candidates: [
            {
              name: "Completed Name",
              raw_card_text: "Completed Raw Card",
              detail_url: "https://www.zhipin.com/candidate/completed",
            },
          ],
        },
        webResult: { batch_id: 901, status: "completed", received_count: 1 },
      },
    },
  };
  const state = await worker.context.BossLocalWebIntake.loadState(worker.chrome.storage.local);
  assert.strictEqual(state.completedOrder.length, 1);
  const serialized = JSON.stringify(worker.chrome.__store);
  assert(!serialized.includes("Completed Name"));
  assert(!serialized.includes("Completed Raw Card"));
  assert(!serialized.includes("candidate/completed"));
  assert(!serialized.includes("\"payload\""));
}

async function testLegacyV2MismatchShowsPopupBlockedStatusAndPreservesPayload() {
  const sharedStore = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "other-token",
  };
  const popup = createPopupTestContext({
    store: sharedStore,
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  const stableHash = popup.context.BossLocalWebIntake.stableHash;
  sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {
      "legacy-pending": {
        batchKey: "legacy-pending",
        idempotencyKey: "legacy-popup-1",
        payload: {
          source_platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          source_job_title: "Legacy Popup",
          idempotency_key: "legacy-popup-1",
          candidates: [{ name: "Popup Name", raw_card_text: "Popup Raw Card", detail_url: "https://www.zhipin.com/candidate/popup" }],
        },
        connection: {
          modeApiBase: "http://127.0.0.1:17864",
          webApiBase: "http://127.0.0.1:17864",
          tokenFingerprint: stableHash("original-token"),
          key: stableHash("http://127.0.0.1:17864|http://127.0.0.1:17864|original-token"),
        },
      },
    },
    completedBatches: {
      "legacy-done": {
        batchKey: "legacy-done",
        idempotencyKey: "legacy-done-1",
        payload: {
          candidates: [{ name: "Done Name", raw_card_text: "Done Raw Card", detail_url: "https://www.zhipin.com/candidate/done" }],
        },
        webResult: { batch_id: 902, status: "completed", received_count: 1 },
      },
    },
  };

  await popup.api.refreshWebIntakeStatus({ apiBase: sharedStore.apiBase, apiToken: sharedStore.apiToken, jobTitle: "Legacy Popup" });
  assert(popup.elements.webIntakeStatus.textContent.includes("存在属于旧连接的待发送批次，请切回原连接完成迁移。"));
  assert.strictEqual(popup.elements.retryWebIntake.disabled, true);

  const status = await popup.context.BossLocalWebIntake.getStatusView({
    settings: { apiBase: sharedStore.apiBase, apiToken: sharedStore.apiToken, jobTitle: "Legacy Popup" },
    storageArea: popup.chrome.storage.local,
  });
  assert.strictEqual(status.record.statusLabel, "等待原连接");
  const safeSerialized = JSON.stringify(status);
  assert(!safeSerialized.includes("Popup Name"));
  assert(!safeSerialized.includes("Popup Raw Card"));
  assert(!safeSerialized.includes("candidate/popup"));
  assert(sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY]);

  sharedStore.apiToken = "original-token";
  await popup.api.refreshWebIntakeStatus({ apiBase: sharedStore.apiBase, apiToken: sharedStore.apiToken, jobTitle: "Legacy Popup" });
  const state = await popup.context.BossLocalWebIntake.loadState(popup.chrome.storage.local, { apiBase: sharedStore.apiBase, apiToken: sharedStore.apiToken });
  assert.strictEqual(sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY], undefined);
  assert.strictEqual(state.pendingOrder.length, 1);
}

async function testLegacyWarningRemainsVisibleAlongsideCurrentCompleted() {
  const sharedStore = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "current-token",
  };
  const popup = createPopupTestContext({
    store: sharedStore,
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  const settings = {
    apiBase: sharedStore.apiBase,
    apiToken: sharedStore.apiToken,
    connectionMode: "web",
    jobTitle: "Legacy Popup",
  };
  const stableHash = popup.context.BossLocalWebIntake.stableHash;
  const currentIdentity = await popup.context.BossLocalWebIntake.connectionIdentity(settings);
  await popup.context.BossLocalWebIntake.upsertPendingRecord(
    {
      batchKey: "current-completed",
      idempotencyKey: "current-completed-idem",
      connection: currentIdentity,
      payload: {
        source_platform: "boss",
        source_url: "https://www.zhipin.com/web/geek/recommend",
        source_job_title: "Current Completed",
        idempotency_key: "current-completed-idem",
        candidates: [{ raw_card_text: "Current Completed Card" }],
      },
      webResult: {
        batch_id: 910,
        status: "completed",
        received_count: 1,
        inserted_candidates: 1,
        updated_candidates: 0,
        skipped_candidates: 0,
        failed_candidates: 0,
      },
      status: "completed",
      statusLabel: "入库成功",
      message: "网页工作台已接收批次 #910",
      updatedAt: new Date().toISOString(),
    },
    popup.chrome.storage.local,
  );
  await popup.context.BossLocalWebIntake.moveToCompleted(
    await popup.context.BossLocalWebIntake.readPendingRecord("current-completed", popup.chrome.storage.local),
    popup.chrome.storage.local,
  );
  sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {
      "legacy-pending": {
        batchKey: "legacy-pending",
        idempotencyKey: "legacy-popup-1",
        payload: {
          source_platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          source_job_title: "Legacy Popup",
          idempotency_key: "legacy-popup-1",
          candidates: [{ name: "Popup Name", raw_card_text: "Popup Raw Card", detail_url: "https://www.zhipin.com/candidate/popup" }],
        },
        connection: {
          modeApiBase: "http://127.0.0.1:17864",
          webApiBase: "http://127.0.0.1:17864",
          tokenFingerprint: stableHash("original-token"),
          key: stableHash("http://127.0.0.1:17864|http://127.0.0.1:17864|original-token"),
        },
      },
    },
    completedBatches: {},
  };

  await popup.api.refreshWebIntakeStatus(settings);
  assert(popup.elements.webIntakeStatus.textContent.includes("存在属于旧连接的待发送批次，请切回原连接完成迁移。"));
  assert(popup.elements.webIntakeStatus.textContent.includes("910"));
  assert.strictEqual(popup.elements.retryWebIntake.disabled, true);

  const status = await popup.context.BossLocalWebIntake.getStatusView({
    settings,
    storageArea: popup.chrome.storage.local,
  });
  assert.strictEqual(status.record.status, "completed");
  assert(status.legacyBlocked);
  const safeSerialized = JSON.stringify(status);
  assert(!safeSerialized.includes("Popup Name"));
  assert(!safeSerialized.includes("Popup Raw Card"));
  assert(!safeSerialized.includes("candidate/popup"));
  assert(!safeSerialized.includes("\"payload\""));
}

async function testLegacyWarningRemainsVisibleAlongsideCurrentWaitingRetry() {
  const sharedStore = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "current-retry-token",
  };
  let fetchCount = 0;
  const popup = createPopupTestContext({
    store: sharedStore,
    fetchImpl: async (url) => {
      if (String(url).endsWith("/api/plugin/context")) {
        return {
          ok: false,
          status: 409,
          async json() {
            return { error: { code: "context_unavailable", message: "当前未选择可用招聘任务。" } };
          },
        };
      }
      fetchCount += 1;
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            batch_id: 911,
            status: "completed",
            received_count: 1,
            inserted_candidates: 1,
            updated_candidates: 0,
            skipped_candidates: 0,
            failed_candidates: 0,
          };
        },
      };
    },
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  const settings = {
    apiBase: sharedStore.apiBase,
    apiToken: sharedStore.apiToken,
    connectionMode: "web",
    jobTitle: "Legacy Popup Retry",
  };
  const stableHash = popup.context.BossLocalWebIntake.stableHash;
  const currentIdentity = await popup.context.BossLocalWebIntake.connectionIdentity(settings);
  await popup.context.BossLocalWebIntake.upsertPendingRecord(
    {
      batchKey: "current-waiting",
      idempotencyKey: "current-waiting-idem",
      connection: currentIdentity,
      payload: {
        source_platform: "boss",
        source_url: "https://www.zhipin.com/web/geek/recommend",
        source_job_title: "Current Waiting Retry",
        idempotency_key: "current-waiting-idem",
        candidates: [{ raw_card_text: "Current Waiting Card" }],
      },
      webResult: {
        batch_id: 0,
        status: "failed",
        received_count: 1,
        inserted_candidates: 0,
        updated_candidates: 0,
        skipped_candidates: 0,
        failed_candidates: 1,
      },
      status: "waiting_retry",
      statusLabel: "等待重试",
      message: "等待重试",
      attemptCount: 1,
      updatedAt: new Date().toISOString(),
    },
    popup.chrome.storage.local,
  );
  sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {
      "legacy-pending": {
        batchKey: "legacy-pending",
        idempotencyKey: "legacy-popup-2",
        payload: {
          source_platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          source_job_title: "Legacy Popup Retry",
          idempotency_key: "legacy-popup-2",
          candidates: [{ name: "Legacy Name", raw_card_text: "Legacy Raw Card", detail_url: "https://www.zhipin.com/candidate/legacy" }],
        },
        connection: {
          modeApiBase: "http://127.0.0.1:17864",
          webApiBase: "http://127.0.0.1:17864",
          tokenFingerprint: stableHash("other-token"),
          key: stableHash("http://127.0.0.1:17864|http://127.0.0.1:17864|other-token"),
        },
      },
    },
    completedBatches: {},
  };
  const legacyBeforePayload = JSON.stringify(
    sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY].pendingBatches["legacy-pending"].payload,
  );

  await popup.api.init();
  await popup.api.refreshWebIntakeStatus(settings);
  assert(popup.elements.webIntakeStatus.textContent.includes("存在属于旧连接的待发送批次，请切回原连接完成迁移。"));
  assert.strictEqual(popup.elements.retryWebIntake.disabled, false);

  await popup.api.retryWebIntake();
  assert.strictEqual(fetchCount, 1);
  assert.strictEqual(
    JSON.stringify(sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY].pendingBatches["legacy-pending"].payload),
    legacyBeforePayload,
  );
  const state = await popup.context.BossLocalWebIntake.loadState(popup.chrome.storage.local, settings);
  assert.strictEqual(state.completedOrder.length, 1);
  const completed = state.completedBatches[state.completedOrder[0]];
  assert.strictEqual(completed.batchKey, "current-waiting");
  const safeSerialized = JSON.stringify(
    await popup.context.BossLocalWebIntake.getStatusView({
      settings,
      storageArea: popup.chrome.storage.local,
    }),
  );
  assert(!safeSerialized.includes("Legacy Name"));
  assert(!safeSerialized.includes("Legacy Raw Card"));
  assert(!safeSerialized.includes("candidate/legacy"));
}

async function testLegacyWarningDisappearsAfterSwitchingBackAndMigrating() {
  const sharedStore = {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "other-token",
  };
  const popup = createPopupTestContext({
    store: sharedStore,
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      async json() {
        return {
          batch_id: 912,
          status: "completed",
          received_count: 1,
          inserted_candidates: 1,
          updated_candidates: 0,
          skipped_candidates: 0,
          failed_candidates: 0,
        };
      },
    }),
    runtimeHandler: createPopupWebRuntimeHandler(),
  });
  const stableHash = popup.context.BossLocalWebIntake.stableHash;
  sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY] = {
    pendingBatches: {
      "legacy-pending": {
        batchKey: "legacy-pending",
        idempotencyKey: "legacy-popup-3",
        payload: {
          source_platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          source_job_title: "Legacy Popup Switch",
          idempotency_key: "legacy-popup-3",
          candidates: [{ name: "Switch Name", raw_card_text: "Switch Raw Card", detail_url: "https://www.zhipin.com/candidate/switch" }],
        },
        connection: {
          modeApiBase: "http://127.0.0.1:17864",
          webApiBase: "http://127.0.0.1:17864",
          tokenFingerprint: stableHash("original-token"),
          key: stableHash("http://127.0.0.1:17864|http://127.0.0.1:17864|original-token"),
        },
      },
    },
    completedBatches: {},
  };

  await popup.api.refreshWebIntakeStatus({ apiBase: sharedStore.apiBase, apiToken: sharedStore.apiToken, jobTitle: "Legacy Popup Switch" });
  assert(popup.elements.webIntakeStatus.textContent.includes("存在属于旧连接的待发送批次，请切回原连接完成迁移。"));

  sharedStore.apiToken = "original-token";
  const originalSettings = {
    apiBase: sharedStore.apiBase,
    apiToken: sharedStore.apiToken,
    connectionMode: "web",
    jobTitle: "Legacy Popup Switch",
  };
  await popup.api.refreshWebIntakeStatus(originalSettings);
  await popup.api.retryWebIntake();
  await popup.api.refreshWebIntakeStatus(originalSettings);

  assert(!popup.elements.webIntakeStatus.textContent.includes("存在属于旧连接的待发送批次，请切回原连接完成迁移。"));
  const status = await popup.context.BossLocalWebIntake.getStatusView({
    settings: originalSettings,
    storageArea: popup.chrome.storage.local,
  });
  assert.strictEqual(status.legacyBlocked, null);
  assert.strictEqual(sharedStore[popup.context.BossLocalWebIntake.LEGACY_STATE_KEY], undefined);
}

async function testPopupWebModeRefreshesSearchableRatingBadges() {
  const inserted = [];
  const removed = [];
  function makeCard(rawUid, label) {
    const nameNode = {
      innerText: label,
      textContent: label,
      insertAdjacentElement(_position, node) {
        inserted.push(node);
      },
    };
    return {
      getAttribute(name) {
        return name === "data-geek-id" ? rawUid : "";
      },
      querySelector(selector) {
        if (String(selector).includes("href")) {
          return { href: `https://www.zhipin.com/candidate/${rawUid}` };
        }
        return nameNode;
      },
    };
  }
  const cards = {
    alice: makeCard("alice", "Alice"),
    bob: makeCard("bob", "Bob"),
  };
  const fakeDocument = {
    querySelectorAll(selector) {
      if (String(selector).includes(".boss-local-rating-badge")) {
        return inserted.slice();
      }
      return [cards.alice, cards.bob];
    },
    createElement() {
      return {
        className: "",
        textContent: "",
        style: {},
        setAttribute(name, value) {
          this[name] = value;
        },
        remove() {
          removed.push(this);
          const index = inserted.indexOf(this);
          if (index >= 0) inserted.splice(index, 1);
        },
      };
    },
  };
  const badgeFetches = [];
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    fetchImpl: async (url, requestOptions = {}) => {
      badgeFetches.push({ url: String(url), headers: requestOptions.headers || {} });
      return {
        ok: true,
        json: async () => ({
          task_id: 11,
          badges: [
            {
              source_platform: "boss",
              platform_uid: "boss:alice",
              rating: "SR",
              badge_text: "1SR",
            },
            {
              source_platform: "boss",
              platform_uid: "boss:bob",
              rating: "SR",
              badge_text: "1SR",
            },
          ],
        }),
      };
    },
  });
  popup.chrome.scripting.executeScript = async (details) => {
    const previousDocument = global.document;
    const previousVmDocument = popup.context.document;
    global.document = fakeDocument;
    popup.context.document = fakeDocument;
    try {
      details.func(...(details.args || []));
    } finally {
      global.document = previousDocument;
      popup.context.document = previousVmDocument;
    }
    return [{ result: true }];
  };

  await popup.api.refreshRatingBadges(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });
  assert.strictEqual(badgeFetches[0].url, "http://127.0.0.1:17864/api/plugin/ratings/badges");
  assert.strictEqual(badgeFetches[0].headers["X-Boss-Local-Token"], "web-token");
  assert(!badgeFetches[0].url.includes("web-token"));
  assert.strictEqual(inserted.length, 2);
  assert.deepStrictEqual(inserted.map((node) => node.textContent), ["1SR", "1SR"]);
  await popup.api.refreshRatingBadges(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });
  assert.strictEqual(inserted.length, 2);
  assert.deepStrictEqual(inserted.map((node) => node.textContent), ["1SR", "1SR"]);
  assert(removed.length >= 2);
}

async function testPopupRatingBadgesIgnoreGenericDataId() {
  const inserted = [];
  const card = {
    getAttribute(name) {
      return name === "data-id" ? "shared-data-id" : "";
    },
    querySelector() {
      return {
        insertAdjacentElement(_position, node) {
          inserted.push(node);
        },
      };
    },
  };
  const fakeDocument = {
    querySelectorAll(selector) {
      if (String(selector).includes(".boss-local-rating-badge")) return [];
      return [card];
    },
    createElement() {
      return {
        textContent: "",
        style: {},
        setAttribute() {},
      };
    },
  };
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({
        badges: [{ platform_uid: "shared-data-id", rating: "SSR", badge_text: "1SSR" }],
      }),
    }),
  });
  popup.chrome.scripting.executeScript = async (details) => {
    const previousDocument = global.document;
    const previousVmDocument = popup.context.document;
    global.document = fakeDocument;
    popup.context.document = fakeDocument;
    try {
      details.func(...(details.args || []));
    } finally {
      global.document = previousDocument;
      popup.context.document = previousVmDocument;
    }
    return [{ result: true }];
  };

  await popup.api.refreshRatingBadges(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });

  assert.strictEqual(inserted.length, 0);
}

async function testPopupRatingBadgesIgnoreRowsWithoutStableIdentity() {
  const inserted = [];
  const card = {
    getAttribute(name) {
      return name === "data-geek-id" ? "boss:alice" : "";
    },
    querySelector() {
      return {
        insertAdjacentElement(_position, node) {
          inserted.push(node);
        },
      };
    },
  };
  const fakeDocument = {
    querySelectorAll(selector) {
      if (String(selector).includes(".boss-local-rating-badge")) return [];
      return [card];
    },
    createElement() {
      return {
        textContent: "",
        style: {},
        setAttribute() {},
      };
    },
  };
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({
        badges: [{ candidate_id: 1, rating: "SSR", badge_text: "1SSR" }],
      }),
    }),
  });
  popup.chrome.scripting.executeScript = async (details) => {
    const previousDocument = global.document;
    const previousVmDocument = popup.context.document;
    global.document = fakeDocument;
    popup.context.document = fakeDocument;
    try {
      details.func(...(details.args || []));
    } finally {
      global.document = previousDocument;
      popup.context.document = previousVmDocument;
    }
    return [{ result: true }];
  };

  await popup.api.refreshRatingBadges(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });

  assert.strictEqual(inserted.length, 0);
}

async function testPopupRatingBadgesDoNotCanonicalizeUnknownPlatform() {
  const inserted = [];
  const card = {
    getAttribute(name) {
      return name === "data-geek-id" ? "alice" : "";
    },
    querySelector() {
      return {
        insertAdjacentElement(_position, node) {
          inserted.push(node);
        },
      };
    },
  };
  const fakeDocument = {
    querySelectorAll(selector) {
      if (String(selector).includes(".boss-local-rating-badge")) return [];
      return [card];
    },
    createElement() {
      return {
        textContent: "",
        style: {},
        setAttribute() {},
      };
    },
  };
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({
        badges: [{ source_platform: "unknown", platform_uid: "unknown:alice", rating: "SSR", badge_text: "1SSR" }],
      }),
    }),
  });
  popup.chrome.scripting.executeScript = async (details) => {
    const previousDocument = global.document;
    const previousVmDocument = popup.context.document;
    global.document = fakeDocument;
    popup.context.document = fakeDocument;
    try {
      details.func(...(details.args || []));
    } finally {
      global.document = previousDocument;
      popup.context.document = previousVmDocument;
    }
    return [{ result: true }];
  };

  await popup.api.refreshRatingBadges(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });

  assert.strictEqual(inserted.length, 0);
}

async function testPopupDesktopModeDoesNotRequestRatingBadgesAndClearsOldBadges() {
  let fetchCount = 0;
  let clearCount = 0;
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:19001",
    apiToken: "desktop-token",
    connectionMode: "desktop",
    fetchImpl: async () => {
      fetchCount += 1;
      throw new Error("badge fetch should not happen");
    },
  });
  popup.chrome.scripting.executeScript = async (details) => {
    if (details.func && !details.args) {
      clearCount += 1;
    }
    return [{ result: true }];
  };

  await popup.api.refreshRatingBadges(7, {
    apiBase: "http://127.0.0.1:19001",
    apiToken: "desktop-token",
    connectionMode: "desktop",
  });
  assert.strictEqual(fetchCount, 0);
  assert.strictEqual(clearCount, 1);
}

function createKeywordHighlightDom() {
  const dom = new JSDOM(`
    <!doctype html>
    <html>
      <head></head>
      <body>
        <main id="feed">
          <article class="candidate-card" data-name="class-token" style="display:flex">
            <span class="boss-local-rating-badge">1SSR</span>
            <span class="name" data-source="class-value">Alice Python 外包 React class</span>
            <a class="profile-link" href="https://example.test/class">候选人详情</a>
            <button type="button">Python button</button>
            <span hidden>hidden</span>
            <span aria-hidden="true">hidden</span>
            <span style="display:none">hidden</span>
            <span style="visibility:hidden">hidden</span>
          </article>
          <article class="candidate-card unmatched-card" style="display:grid">
            <span class="boss-local-rating-badge">1SSR</span>
            <span class="name">Bob 普通候选人</span>
            <button type="button">Python button</button>
            <span hidden>class hidden</span>
          </article>
          <article class="candidate-card block-card" style="display:block">
            <span class="name">Carol 未命中</span>
          </article>
        </main>
      </body>
    </html>
  `);
  return {
    document: dom.window.document,
    window: dom.window,
    card: dom.window.document.querySelector(".candidate-card"),
    unmatchedCard: dom.window.document.querySelector(".unmatched-card"),
    blockCard: dom.window.document.querySelector(".block-card"),
  };
}

function installKeywordDomExecutor(popup, dom, onExecute = () => {}) {
  popup.chrome.scripting.executeScript = async (details) => {
    onExecute(details);
    const previousDocument = global.document;
    const previousVmDocument = popup.context.document;
    const previousGetComputedStyle = global.getComputedStyle;
    const previousVmGetComputedStyle = popup.context.getComputedStyle;
    global.document = dom.document;
    popup.context.document = dom.document;
    global.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
    popup.context.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
    try {
      details.func(...(details.args || []));
    } finally {
      global.document = previousDocument;
      popup.context.document = previousVmDocument;
      global.getComputedStyle = previousGetComputedStyle;
      popup.context.getComputedStyle = previousVmGetComputedStyle;
    }
    return [{ result: true }];
  };
}

async function testPopupWebModeRefreshesKeywordHighlights() {
  const dom = createKeywordHighlightDom();
  const keywordFetches = [];
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    fetchImpl: async (url, requestOptions = {}) => {
      keywordFetches.push({ url: String(url), headers: requestOptions.headers || {} });
      return {
        ok: true,
        json: async () => ({
          task_id: 11,
          keyword_rules: {
            must: ["python", "class", "SSR", "hidden"],
            plus: ["React"],
            risk: ["外包"],
            note: [],
          },
        }),
      };
    },
  });
  installKeywordDomExecutor(popup, dom);

  await popup.api.refreshKeywordHighlights(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });

  assert.strictEqual(keywordFetches[0].url, "http://127.0.0.1:17864/api/plugin/keyword-rules");
  assert.strictEqual(keywordFetches[0].headers["X-Boss-Local-Token"], "web-token");
  assert(!keywordFetches[0].url.includes("web-token"));
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-rating-badge").length, 1);
  assert.strictEqual(dom.card.querySelector(".boss-local-rating-badge").textContent, "1SSR");
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight.must").length, 2);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight.plus").length, 1);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight.risk").length, 1);
  assert.strictEqual(dom.card.querySelector(".boss-local-keyword-badge").textContent, "风险 1");
  assert.strictEqual(dom.document.querySelectorAll(".boss-local-keyword-filterbar").length, 1);
  assert.strictEqual(dom.unmatchedCard.querySelectorAll(".boss-local-keyword-highlight").length, 0);
  assert.strictEqual(dom.unmatchedCard.getAttribute("data-boss-local-keyword-groups"), null);
  assert.strictEqual(dom.blockCard.querySelectorAll(".boss-local-keyword-highlight").length, 0);
  assert.strictEqual(dom.card.getAttribute("data-name"), "class-token");
  assert.strictEqual(dom.card.querySelector(".name").getAttribute("data-source"), "class-value");
  assert.strictEqual(dom.card.querySelector(".profile-link").getAttribute("href"), "https://example.test/class");
  assert.strictEqual(dom.card.querySelector("button .boss-local-keyword-highlight"), null);
  assert.strictEqual(dom.card.textContent.includes("hidden"), true);

  await popup.api.refreshKeywordHighlights(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight").length, 4);
  assert.strictEqual(dom.document.querySelectorAll(".boss-local-keyword-filterbar").length, 1);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-badge").length, 2);
  assert.strictEqual(dom.unmatchedCard.querySelectorAll(".boss-local-keyword-highlight").length, 0);

  const mustButton = Array.from(dom.document.querySelectorAll(".boss-local-keyword-filterbar button"))
    .find((button) => button.textContent === "有必须");
  const allButton = Array.from(dom.document.querySelectorAll(".boss-local-keyword-filterbar button"))
    .find((button) => button.textContent === "全部");
  mustButton.click();
  assert.strictEqual(dom.card.style.display, "flex");
  assert.strictEqual(dom.unmatchedCard.style.display, "none");
  assert.strictEqual(dom.blockCard.style.display, "none");
  allButton.click();
  assert.strictEqual(dom.card.style.display, "flex");
  assert.strictEqual(dom.unmatchedCard.style.display, "grid");
  assert.strictEqual(dom.blockCard.style.display, "block");

  dom.card.querySelector(".boss-local-rating-badge").textContent = "1SR";
  await popup.api.refreshKeywordHighlights(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });
  assert.strictEqual(dom.card.querySelector(".boss-local-rating-badge").textContent, "1SR");
  await popup.api.clearKeywordHighlights(7);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight").length, 0);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-badge").length, 0);
  assert.strictEqual(dom.document.querySelectorAll(".boss-local-keyword-filterbar").length, 0);
  assert.strictEqual(dom.card.querySelector(".boss-local-rating-badge").textContent, "1SR");
  assert.strictEqual(dom.card.getAttribute("data-name"), "class-token");
  assert.strictEqual(dom.card.style.display, "flex");
  assert.strictEqual(dom.unmatchedCard.style.display, "grid");
  assert.strictEqual(dom.blockCard.style.display, "block");
}

async function testPopupKeywordHighlightsClearOnFailureAndDesktopMode() {
  const dom = createKeywordHighlightDom();
  let fetchCount = 0;
  let executeCount = 0;
  let failFetch = false;
  const popup = createPopupTestContext({
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
    fetchImpl: async () => {
      fetchCount += 1;
      if (failFetch) return { ok: false, json: async () => ({}) };
      return {
        ok: true,
        json: async () => ({
          keyword_rules: { must: ["Python"], plus: [], risk: ["外包"], note: [] },
        }),
      };
    },
  });
  installKeywordDomExecutor(popup, dom, () => {
    executeCount += 1;
  });

  await popup.api.refreshKeywordHighlights(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });
  assert.strictEqual(fetchCount, 1);
  assert.strictEqual(executeCount, 1);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight").length, 2);
  assert.strictEqual(dom.card.querySelector(".boss-local-rating-badge").textContent, "1SSR");
  const riskButton = Array.from(dom.document.querySelectorAll(".boss-local-keyword-filterbar button"))
    .find((button) => button.textContent === "有风险");
  riskButton.click();
  assert.strictEqual(dom.card.style.display, "flex");
  assert.strictEqual(dom.unmatchedCard.style.display, "none");
  assert.strictEqual(dom.blockCard.style.display, "none");

  failFetch = true;
  await popup.api.refreshKeywordHighlights(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });
  assert.strictEqual(fetchCount, 2);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight").length, 0);
  assert.strictEqual(dom.card.querySelector(".boss-local-rating-badge").textContent, "1SSR");
  assert.strictEqual(dom.card.style.display, "flex");
  assert.strictEqual(dom.unmatchedCard.style.display, "grid");
  assert.strictEqual(dom.blockCard.style.display, "block");

  failFetch = false;
  await popup.api.refreshKeywordHighlights(7, {
    apiBase: "http://127.0.0.1:17864",
    apiToken: "web-token",
    connectionMode: "web",
  });
  const restoredRiskButton = Array.from(dom.document.querySelectorAll(".boss-local-keyword-filterbar button"))
    .find((button) => button.textContent === "有风险");
  restoredRiskButton.click();
  await popup.api.refreshKeywordHighlights(7, {
    apiBase: "http://127.0.0.1:19001",
    apiToken: "desktop-token",
    connectionMode: "desktop",
  });
  assert.strictEqual(fetchCount, 3);
  assert.strictEqual(dom.card.querySelectorAll(".boss-local-keyword-highlight").length, 0);
  assert.strictEqual(dom.card.querySelector(".boss-local-rating-badge").textContent, "1SSR");
  assert.strictEqual(dom.card.style.display, "flex");
  assert.strictEqual(dom.unmatchedCard.style.display, "grid");
  assert.strictEqual(dom.blockCard.style.display, "block");
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
  await testCollectorExtractsBossCurrentDetailSafely();
  await testCollectorExtractsLiepinCurrentDetail();
  await testCollectorDetailRejectsHiddenLoadingMultipleAndUnconfirmed();
  await testCollectorDetailUsesFreshDomAfterCandidateSwitchAndClose();
  testAutoScrollCanBePausedFromPopup();
  testAutomationAutoButtonStartsDesktopWorkflow();
  testChatAutomationIsOptIn();
  testPopupClientFirstScreenKeepsCoreWebActionsVisibleAndLegacyFolded();
  testScrollWaitDefaultsToThirtyMillisecondsAndHasAdjusters();
  testHoldEndScrollStrategyIsDefault();
  testRuntimeFingerprintAndVersionAwareRunnerInjection();
  testPairingCodeParsesAndRejectsInvalidInput();
  testPopupSupportsPairingAndAuthenticatedConnectionCheck();
  await testPopupPairsWithSingleWebCodeAndRemembersConnection();
  await testPopupPairsAndUsesConfiguredWebPortEndToEnd();
  testCollectionCarriesCanonicalJobProfileId();
  await testPopupManualDesktopAdvancedSettingsOverrideWebMode();
  await testPopupPairingSuccessDoesNotReferenceCollectionVariables();
  await testPopupDesktopCustomPortRemainsDesktopMode();
  await testPopupClearsOldTaskContextWhenNewConnectionContextFails();
  await testPopupWebModeCollectCurrentPostsDirectlyToWebIntake();
  await testPopupWebModeCollectAutoPostsDirectlyToWebIntake();
  await testPopupDesktopModeStillUsesDesktopImportOnly();
  await testPopupRetryRestoresPendingStateAcrossInit();
  await testWebIntakeConnectionChangeDoesNotResendOldPendingBatch();
  await testWebIntakeSameRunIdDoesNotDuplicatePendingBatch();
  await testWebIntakeConcurrentCompletionDoesNotOverwriteQueuedBatch();
  await testSendingLeaseExpiryRecoversOnAlarm();
  await testAlarmExistsBeforeInitialSendAndCrashRecoveryCompletesAfterLeaseExpires();
  await testSameBatchConcurrentSendLockTwentyTimes();
  await testAutomaticRetryStopsAtMaxAndManualRetryStillWorks();
  await testManualRetryCreatesAlarmBeforeFetchStarts();
  await testPopupExpiredSendingEnablesManualRetry();
  await testLegacyV2CompletedMigrationSanitizesSensitiveData();
  await testLegacyV2MigrationMatchesCurrentConnectionAndCanSend();
  await testLegacyV2MigrationKeepsMismatchedPendingUntilOriginalConnectionReturns();
  await testLegacyWarningRemainsVisibleAlongsideCurrentCompleted();
  await testLegacyWarningRemainsVisibleAlongsideCurrentWaitingRetry();
  await testLegacyWarningDisappearsAfterSwitchingBackAndMigrating();
  await testPopupWebModeRefreshesSearchableRatingBadges();
  await testPopupRatingBadgesIgnoreGenericDataId();
  await testPopupRatingBadgesIgnoreRowsWithoutStableIdentity();
  await testPopupRatingBadgesDoNotCanonicalizeUnknownPlatform();
  await testPopupDesktopModeDoesNotRequestRatingBadgesAndClearsOldBadges();
  await testPopupWebModeRefreshesKeywordHighlights();
  await testPopupKeywordHighlightsClearOnFailureAndDesktopMode();
  await testPopupCurrentDetailEnrichmentPostsSafePayloadInWebModeOnly();
  await testPopupCurrentDetailEnrichmentRejectsUnconfirmedAndAllowsRetryAfterFailure();
  await testPendingLimitConcurrentEnqueueStaysWithinTen();
  await testWebIntakeSuccessSanitizesCompletedPayload();
  await testCompletedTransitionScrubsSensitivePendingBeforeDelete();
  await testWebIntakeQuotaFailureIsReportedSeparately();
  await testServiceWorkerRestoresPendingBatchViaAlarm();
  testWebIntakeIdentityUsesFullFieldsInsteadOfShortHash();
  await testLegacyStorageConnectionModeMigrationRules();
  await testLegacyStorageDefaultPortsMigrateOnce();
  await testExplicitModeBackfillsConfirmedAndPreservesJobTitle();
  await testWorkerMigratesLegacyWebConnectionBeforePopupAndRecoversPending();
  await testWorkerMigratesLegacyDesktopConnectionWithoutWebIntake();
  await testSendQueuedBatchUsesMigratedSettingsWhenMessageModeMissing();
  await testWorkerKeepsCustomPortPendingWhenMigrationNeedsRePair();
  await testPopupAndWorkerConcurrentMigrationIsIdempotent();
  await testPopupAndWorkerConcurrentSendSameBatchOnlyFetchesOnce();
  await testMigrationWriteFailureKeepsPendingAndAlarm();
  await testDesktopSettingsEditClearsCsvButtonEvenWhenAlreadyDesktop();
  await testDesktopModeOpenWorkbenchShowsReadableChinesePrompt();
  await testConnectionModeKeepsWebAndDesktopStateIsolated();
  testCollectorDoesNotPromoteGenericDataIdToPlatformUid();
  await testCollectorAcceptsBossAndLiepinStableCardsOnly();
  await testCollectorDedupesByStableUidButKeepsSameNameDifferentUid();
  await testCollectorFindsBossStableUidBeyondCardRoot();
  await testCollectorTreatsBossStableUidAmbiguityAsMissingIdentity();
  await testCollectorRawCardTextIgnoresPluginBadgesAndKeywordMarkup();
  await testCollectorIgnoresDetachedNodesAndUsesFreshDomSnapshots();
  await testWebIntakeStatusMatrixFollowsServerStatus();
  await testPopupWebModeAutoShowsDesktopOnlyBoundary();
  await testPopupReopenRestoresWebBatchMarkdownExport();
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
