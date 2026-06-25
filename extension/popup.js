const DEFAULTS = {
  jobTitle: "Boss 推荐牛人",
  apiBase: "http://127.0.0.1:17863",
  apiToken: "",
  scrollMode: "end",
  scrollStep: 900,
  scrollWaitMs: 30,
  maxScrollCount: 80,
  noNewStopRounds: 4,
  resumeMessage: "方便发一份你的简历过来吗？",
  waitSeconds: 45,
  pollIntervalMs: 2000,
  batchActionDelaySeconds: 5,
  maxBatchSessions: 50,
};

const OLD_DEFAULT_SCROLL_WAIT_MS = 1500;
const SCROLL_WAIT_DEFAULT_VERSION = 2;

const COLLECT_PLATFORMS = [
  {
    id: "boss",
    label: "Boss",
    defaultJobTitle: "Boss 推荐牛人",
    matches(url) {
      return /(^|\.)zhipin\.com$/i.test(url.hostname) || /(^|\.)bosszhipin\.com$/i.test(url.hostname);
    },
  },
  {
    id: "liepin",
    label: "猎聘",
    defaultJobTitle: "猎聘推荐人才",
    matches(url) {
      return /(^|\.)liepin\.com$/i.test(url.hostname) && (url.hostname === "lpt.liepin.com" || url.pathname.startsWith("/recommend"));
    },
  },
];

const fields = {
  jobTitle: document.getElementById("jobTitle"),
  apiBase: document.getElementById("apiBase"),
  apiToken: document.getElementById("apiToken"),
  scrollMode: document.getElementById("scrollMode"),
  scrollStep: document.getElementById("scrollStep"),
  scrollWaitMs: document.getElementById("scrollWaitMs"),
  maxScrollCount: document.getElementById("maxScrollCount"),
  noNewStopRounds: document.getElementById("noNewStopRounds"),
  resumeMessage: document.getElementById("resumeMessage"),
  waitSeconds: document.getElementById("waitSeconds"),
  pollIntervalMs: document.getElementById("pollIntervalMs"),
  batchActionDelaySeconds: document.getElementById("batchActionDelaySeconds"),
  maxBatchSessions: document.getElementById("maxBatchSessions"),
};

const statusEl = document.getElementById("status");
const batchStatusEl = document.getElementById("batchStatus");
const batchLogEl = document.getElementById("batchLog");
const automationAutoButton = document.getElementById("automationAuto");
let batchStatusTimer = null;

automationAutoButton.addEventListener("click", () => runAutomation());
document.getElementById("scrollWaitDown").addEventListener("click", () => adjustScrollWait(-30));
document.getElementById("scrollWaitUp").addEventListener("click", () => adjustScrollWait(30));
document.getElementById("collectCurrent").addEventListener("click", () => runCollection(false));
document.getElementById("collectAuto").addEventListener("click", () => runCollection(true));
document.getElementById("pauseScroll").addEventListener("click", () => requestScrollPause());
document.getElementById("requestResume").addEventListener("click", () => runSingleChatAction("request_resume"));
document.getElementById("downloadResume").addEventListener("click", () => runSingleChatAction("download_current_resume"));
document.getElementById("requestAndDownload").addEventListener("click", () => runSingleChatAction("request_and_download"));
document.getElementById("startBatchRequest").addEventListener("click", () => startBatch("request_resume"));
document.getElementById("startBatchDownload").addEventListener("click", () => startBatch("download_only"));
document.getElementById("stopBatch").addEventListener("click", () => stopBatch());

window.addEventListener("beforeunload", () => {
  if (batchStatusTimer) {
    window.clearInterval(batchStatusTimer);
  }
});

void init();

async function init() {
  const stored = await chrome.storage.local.get({ ...DEFAULTS, scrollWaitDefaultVersion: null });
  if (stored.scrollWaitDefaultVersion === null && Number(stored.scrollWaitMs) === OLD_DEFAULT_SCROLL_WAIT_MS) {
    stored.scrollWaitMs = DEFAULTS.scrollWaitMs;
    await chrome.storage.local.set({
      scrollWaitMs: stored.scrollWaitMs,
      scrollWaitDefaultVersion: SCROLL_WAIT_DEFAULT_VERSION,
    });
  } else if (stored.scrollWaitDefaultVersion === null) {
    await chrome.storage.local.set({ scrollWaitDefaultVersion: SCROLL_WAIT_DEFAULT_VERSION });
  }
  for (const [key, element] of Object.entries(fields)) {
    if (element) {
      element.value = stored[key];
    }
  }
  await refreshBatchStatus();
  batchStatusTimer = window.setInterval(() => {
    void refreshBatchStatus();
  }, 1000);
}

async function runAutomation() {
  const tab = await getActiveSupportedTab();
  if (!tab) {
    return;
  }
  const settings = collectSettings();
  automationAutoButton.disabled = true;
  setStatus("正在读取桌面端自动化方案...");
  try {
    const automation = await startDesktopAutomation(settings, tab.url);
    fields.jobTitle.value = automation.job_title || automation.profile_job_title || settings.jobTitle;
    await chrome.storage.local.set({ ...collectSettings(), jobTitle: fields.jobTitle.value });
    setStatus(
      [
        "自动化方案已确认，准备滚动采集...",
        `筛选方案: ${automation.profile_job_title || "-"}`,
        `采集岗位: ${fields.jobTitle.value || "-"}`,
        `AI 模型: ${automation.provider || "-"} / ${automation.model || "-"}`,
      ].join("\n"),
    );
    await runCollection(true, { automationRequested: true, automation });
  } catch (error) {
    setStatus(`AUTO 启动失败。\n${error.message || String(error)}`);
  } finally {
    automationAutoButton.disabled = false;
  }
}

async function startDesktopAutomation(settings, sourceUrl) {
  const apiBase = normalizeLocalApiBase(settings.apiBase);
  let response;
  try {
    response = await fetch(`${apiBase}/api/automation/start`, {
      method: "POST",
      headers: localApiHeaders(settings),
      body: JSON.stringify({ source_url: sourceUrl, trigger: "extension_auto" }),
    });
  } catch (error) {
    throw new Error(formatLocalApiFetchError(apiBase, error));
  }
  const result = await response.json();
  if (!response.ok || !result.ok) {
    throw new Error(result.error || `桌面端返回状态码 ${response.status}`);
  }
  if (!result.result?.ready) {
    throw new Error("桌面端自动化方案未配置完整，请先选择筛选方案并保存。 ");
  }
  return result.result;
}

async function adjustScrollWait(deltaMs) {
  const current = Number(fields.scrollWaitMs.value || DEFAULTS.scrollWaitMs);
  const next = Math.max(0, current + deltaMs);
  fields.scrollWaitMs.value = String(next);
  await chrome.storage.local.set({ scrollWaitMs: next });
  setStatus(`滚动等待毫秒已设置为 ${next}ms。`);
}

async function runCollection(autoScroll, options = {}) {
  const baseSettings = collectSettings();
  await chrome.storage.local.set(baseSettings);

  const tab = await getActiveSupportedTab();
  if (!tab) {
    return;
  }

  const platform = detectCollectPlatform(tab.url);
  const settings = applyPlatformDefaults(baseSettings, platform);
  await resetScrollPause(tab.id);
  setStatus(
    autoScroll
      ? `正在滚动到底并采集${platform.label}候选人卡片...`
      : `正在采集当前已加载的${platform.label}候选人卡片...`,
  );

  let frameResults;
  try {
    frameResults = await collectFromAllFrames(tab.id, autoScroll, settings);
  } catch (error) {
    setStatus(`读取页面 DOM 失败。\n${error.message || String(error)}`);
    return;
  }

  const merged = mergeFrameResults(frameResults);
  if (merged.cards.length === 0) {
    setStatus(
      [
        "采集失败。",
        "页面中没有识别到候选人卡片。",
        `扫描 frame: ${merged.framesSeen}`,
        `命中 frame: ${merged.framesWithCards}`,
        `调试信息: ${merged.debugSummary || "-"}`,
      ].join("\n"),
    );
    return;
  }

  try {
    const imported = await importCards(
      settings,
      tab.url,
      merged,
      Boolean(options.automationRequested),
    );
    setStatus(
      [
        options.automationRequested ? "AUTO 采集完成，已提交 AI 初筛。" : "采集完成。",
        `本地去重卡片: ${merged.cards.length}`,
        `来源平台: ${platform.label}`,
        `命中 frame: ${merged.framesWithCards}/${merged.framesSeen}`,
        `导入批次: ${imported.batch_id ?? "-"}`,
        `解析卡片: ${imported.parsed_cards ?? 0}`,
        `写入批次快照: ${imported.total_batch_items ?? 0}`,
      ].join("\n"),
    );
  } catch (error) {
    setStatus(`导入本地程序失败。\n${error.message || String(error)}`);
  }
}

async function requestScrollPause() {
  const tab = await getActiveSupportedTab();
  if (!tab) {
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => {
        if (typeof globalThis.__bossLocalRequestScrollPause === "function") {
          return globalThis.__bossLocalRequestScrollPause("popup");
        }
        globalThis.__bossLocalScrollControl = {
          ...(globalThis.__bossLocalScrollControl || {}),
          pauseRequested: true,
          reason: "popup",
          requestedAt: Date.now(),
        };
        return { ok: true, pauseRequested: true, fallback: true };
      },
    });
    setStatus("已发送暂停滚动请求。当前等待结束后会停止继续滚动，并导入已采集卡片。");
  } catch (error) {
    setStatus(`发送暂停滚动请求失败。\n${error.message || String(error)}`);
  }
}

async function runSingleChatAction(action) {
  const settings = collectSettings();
  await chrome.storage.local.set(settings);

  const tab = await getActiveBossTab();
  if (!tab) {
    return;
  }

  await ensureChatRunnerInjected(tab.id);
  if (action === "request_resume") {
    setStatus("正在当前会话中发送话术并执行求简历...");
  } else if (action === "download_current_resume") {
    setStatus("正在当前会话中解析并下载附件简历...");
  } else {
    setStatus("正在当前会话中发送求简历并等待附件下载...");
  }

  const result = await safeTabsSendMessage(tab.id, {
    type: "boss_chat_action",
    action,
    settings,
  });

  if (!result?.ok) {
    setStatus(`执行失败。\n${result?.error || "页面脚本没有返回成功结果。"}`);
    return;
  }

  setStatus(formatSingleActionStatus(action, result));
  await refreshBatchStatus();
}

async function startBatch(mode) {
  const settings = collectSettings();
  await chrome.storage.local.set(settings);

  const tab = await getActiveBossTab();
  if (!tab) {
    return;
  }
  if (!String(tab.url || "").includes("/web/chat/")) {
    setStatus("请先切到 Boss 的沟通聊天页，再启动批量任务。");
    return;
  }

  const response = await chrome.runtime.sendMessage({
    type: "start_batch",
    tabId: tab.id,
    settings,
    mode,
  });

  if (!response?.ok) {
    setStatus(`启动批量任务失败。\n${response?.error || "后台脚本没有返回成功结果。"}`);
    return;
  }

  setStatus(
    mode === "download_only"
      ? "已启动批量下载。任务会在当前聊天列表中持续扫描可下载的附件简历。"
      : "已启动批量求简历。任务会发送话术并点击求简历/附件简历功能按钮，不等待下载。",
  );
  await refreshBatchStatus();
}

async function stopBatch() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const tabId = isBossUrl(tab?.url) ? tab.id : null;
  const response = await chrome.runtime.sendMessage({
    type: "stop_batch",
    tabId,
  });

  if (!response?.ok) {
    setStatus(`停止批量任务失败。\n${response?.error || "后台脚本没有返回成功结果。"}`);
    return;
  }

  setStatus("已发送停止请求。后台会立即作废当前批量任务，页面 runner 会在当前可中断点退出。");
  await refreshBatchStatus();
}

async function refreshBatchStatus() {
  let response;
  try {
    response = await chrome.runtime.sendMessage({ type: "get_batch_status" });
  } catch (error) {
    batchStatusEl.textContent = `读取批量状态失败。\n${error.message || String(error)}`;
    if (batchLogEl) {
      batchLogEl.textContent = "Runtime log unavailable.";
    }
    return;
  }

  const status = response?.status;
  if (!response?.ok || !status) {
    batchStatusEl.textContent = `读取批量状态失败。\n${response?.error || "未知错误"}`;
    if (batchLogEl) {
      batchLogEl.textContent = "Runtime log unavailable.";
    }
    return;
  }

  batchStatusEl.textContent = formatBatchStatus(status);
  if (batchLogEl) {
    batchLogEl.textContent = formatBatchLog(status);
  }
}

async function ensureChatRunnerInjected(tabId) {
  const expectedVersion = chrome.runtime.getManifest().version;
  await chrome.scripting.executeScript({
    target: { tabId },
    args: [expectedVersion],
    func: (runnerVersion) => {
      const runner = globalThis.__bossLocalChatBatchRunner;
      if (!runner || runner.version === runnerVersion) {
        return;
      }
      try {
        runner.dispose?.("popup-version-mismatch");
      } catch (_error) {}
      delete globalThis.__bossLocalChatBatchRunner;
    },
  });
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["chat_batch_runner.js"],
  });
}

async function resetScrollPause(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => {
        if (typeof globalThis.__bossLocalResetScrollPause === "function") {
          return globalThis.__bossLocalResetScrollPause();
        }
        globalThis.__bossLocalScrollControl = {
          pauseRequested: false,
          running: false,
          reason: "",
          requestedAt: 0,
          startedAt: Date.now(),
          stoppedAt: 0,
        };
        return { ok: true, pauseRequested: false, fallback: true };
      },
    });
  } catch (_error) {
    // The collector file is injected immediately after this. A reset failure here should not block collection.
  }
}

async function collectFromAllFrames(tabId, autoScroll, settings) {
  await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    files: ["collector.js"],
  });

  return chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    args: [autoScroll, settings],
    func: async (autoScrollArg, settingsArg) => {
      if (typeof globalThis.__bossLocalExtract !== "function") {
        return { ok: false, cards: [], debug: "collector-missing", frameUrl: location.href };
      }
      try {
        const result = await globalThis.__bossLocalExtract(autoScrollArg, settingsArg);
        return { ok: true, ...result, frameUrl: location.href };
      } catch (error) {
        return {
          ok: false,
          cards: [],
          debug: error?.message || String(error),
          frameUrl: location.href,
        };
      }
    },
  });
}

function mergeFrameResults(frameResults) {
  const cardsByKey = new Map();
  const debugLines = [];
  const platforms = new Set();
  let framesSeen = 0;
  let framesWithCards = 0;
  let maxRoundsCompleted = 0;

  for (const frameResult of frameResults || []) {
    const result = frameResult?.result;
    if (!result) {
      continue;
    }
    framesSeen += 1;
    const cards = Array.isArray(result.cards) ? result.cards : [];
    if (cards.length > 0) {
      framesWithCards += 1;
    }
    if (result.meta?.platform) {
      platforms.add(String(result.meta.platform));
    }
    maxRoundsCompleted = Math.max(maxRoundsCompleted, Number(result.meta?.rounds_completed || 0));
    for (const card of cards) {
      cardsByKey.set(buildKey(card), card);
    }
    debugLines.push(
      [result.frameUrl || frameResult.frameId || "frame", result.debug || "", `cards=${cards.length}`]
        .filter(Boolean)
        .join(" | "),
    );
  }

  return {
    cards: Array.from(cardsByKey.values()),
    framesSeen,
    framesWithCards,
    roundsCompleted: maxRoundsCompleted,
    platform: platforms.size === 1 ? Array.from(platforms)[0] : "",
    debugSummary: debugLines.join(" || "),
  };
}

async function importCards(settings, sourceUrl, merged, automationRequested = false) {
  const apiBase = normalizeLocalApiBase(settings.apiBase);
  let response;
  try {
    response = await fetch(`${apiBase}/api/import/cards`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Boss-Local-Token": settings.apiToken || "",
      },
      body: JSON.stringify({
        job_title: settings.jobTitle,
        source_url: sourceUrl,
        cards: merged.cards,
        meta: {
          platform: merged.platform || settings.platform || "",
          frames_seen: merged.framesSeen,
          frames_with_cards: merged.framesWithCards,
          rounds_completed: merged.roundsCompleted,
          unique_cards: merged.cards.length,
          automation_requested: automationRequested,
          debug: merged.debugSummary,
        },
      }),
    });
  } catch (error) {
    throw new Error(formatLocalApiFetchError(apiBase, error));
  }
  const result = await response.json();
  if (!response.ok || !result.ok) {
    throw new Error(result.error || `本地接口返回状态码 ${response.status}`);
  }
  return result.result || {};
}

async function getActiveSupportedTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    setStatus("未找到当前活动标签页。");
    return null;
  }
  if (!detectCollectPlatform(tab.url)) {
    setStatus("请先在当前标签页打开 Boss 推荐页或猎聘推荐页。");
    return null;
  }
  return tab;
}

async function getActiveBossTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    setStatus("未找到当前活动标签页。");
    return null;
  }
  if (!isBossUrl(tab.url)) {
    setStatus("请先在当前标签页打开 Boss 页面。");
    return null;
  }
  return tab;
}

function detectCollectPlatform(value) {
  let url;
  try {
    url = new URL(String(value || ""));
  } catch (_error) {
    return null;
  }
  return COLLECT_PLATFORMS.find((platform) => platform.matches(url)) || null;
}

function applyPlatformDefaults(settings, platform) {
  if (!platform) {
    return settings;
  }
  const jobTitle = settings.jobTitle === DEFAULTS.jobTitle ? platform.defaultJobTitle : settings.jobTitle;
  return {
    ...settings,
    jobTitle,
    platform: platform.id,
  };
}

function isBossUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return /(^|\.)zhipin\.com$/i.test(url.hostname) || /(^|\.)bosszhipin\.com$/i.test(url.hostname);
  } catch (_error) {
    return false;
  }
}

function collectSettings() {
  const apiBase = normalizeLocalApiBase(fields.apiBase.value.trim() || DEFAULTS.apiBase);
  fields.apiBase.value = apiBase;
  return {
    jobTitle: fields.jobTitle.value.trim() || DEFAULTS.jobTitle,
    apiBase,
    apiToken: fields.apiToken.value.trim(),
    scrollMode: fields.scrollMode.value,
    scrollStep: Number(fields.scrollStep.value || DEFAULTS.scrollStep),
    scrollWaitMs: Math.max(Number(fields.scrollWaitMs.value || DEFAULTS.scrollWaitMs), 0),
    maxScrollCount: Number(fields.maxScrollCount.value || DEFAULTS.maxScrollCount),
    noNewStopRounds: Number(fields.noNewStopRounds.value || DEFAULTS.noNewStopRounds),
    resumeMessage: fields.resumeMessage.value.trim() || DEFAULTS.resumeMessage,
    waitSeconds: Number(fields.waitSeconds.value || DEFAULTS.waitSeconds),
    pollIntervalMs: Number(fields.pollIntervalMs.value || DEFAULTS.pollIntervalMs),
    batchActionDelayMs: Math.max(Number(fields.batchActionDelaySeconds.value || DEFAULTS.batchActionDelaySeconds), 1) * 1000,
    maxBatchSessions: Math.min(Math.max(Number(fields.maxBatchSessions.value || DEFAULTS.maxBatchSessions), 1), 50),
  };
}

function localApiHeaders(settings) {
  return {
    "Content-Type": "application/json",
    "X-Boss-Local-Token": settings.apiToken || "",
  };
}

async function safeTabsSendMessage(tabId, message) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (error) {
    return { ok: false, error: error?.message || String(error) };
  }
}

function formatSingleActionStatus(action, result) {
  if (action === "request_resume") {
    return [
      "已执行求简历动作。",
      result.sentMessage ? "已发送自定义话术。" : "未发送自定义话术。",
      result.clickedRequestButton ? "已点击页面内“求简历”按钮。" : "未点击“求简历”按钮。",
      result.clickedConfirm ? "已自动确认求简历弹窗。" : "未出现确认弹窗或无需确认。",
      Array.isArray(result.logs) ? result.logs.join("\n") : "",
    ]
      .filter(Boolean)
      .join("\n");
  }

  if (action === "download_current_resume") {
    return [
      "当前会话附件简历已开始下载。",
      result.downloadTriggered ? "已触发页面内下载按钮。" : "",
      result.fileName ? `文件名: ${result.fileName.split("/").pop()}` : "",
      result.downloadId ? `下载任务 ID: ${result.downloadId}` : "",
    ]
      .filter(Boolean)
      .join("\n");
  }

  return [
    "已执行发送后等待并下载。",
    result.request?.sentMessage ? "已发送自定义话术。" : "未发送自定义话术。",
    result.request?.clickedRequestButton ? "已点击页面内“求简历”按钮。" : "未点击“求简历”按钮。",
    result.request?.clickedConfirm ? "已自动确认求简历弹窗。" : "未出现确认弹窗或无需确认。",
    result.download?.downloadTriggered ? "已触发页面内下载按钮。" : "",
    result.download?.downloadId ? `下载任务 ID: ${result.download.downloadId}` : "",
    result.download?.fileName ? `文件名: ${result.download.fileName.split("/").pop()}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function formatBatchStatus(status) {
  const stats = status.stats || {};
  const recentEvents = Array.isArray(status.recentEvents) ? status.recentEvents : [];
  return [
    formatRuntimeFingerprint(status),
    status.runtimeFingerprint?.staleRuntime ? "运行态未更新：worker 与页面 runner 版本不一致。" : "",
    `模式: ${translateBatchMode(status.mode)}`,
    `状态: ${translateBatchPhase(status.phase)}`,
    `运行中: ${status.running ? "是" : "否"}`,
    status.currentSession ? `当前会话: ${status.currentSession}` : "",
    status.message ? `说明: ${status.message}` : "",
    status.scanMessage ? `扫描: ${status.scanMessage}` : "",
    status.error ? `错误: ${status.error}` : "",
    `统计: 已处理 ${stats.processed || 0} / 已请求 ${stats.requested || 0} / 已跳过 ${stats.skipped || 0} / 失败 ${stats.failed || 0} / 已下载 ${stats.downloaded || 0}`,
    `扫描统计: 可见会话 ${stats.discoveredVisibleSessions || 0} / 可确认未读 ${stats.eligibleUnreadSessions || 0} / 无附件跳过 ${stats.skippedNoAttachment || 0} / 拒绝候选行 ${stats.rejectedRows || 0}`,
    status.scanDebug ? `诊断:\n${status.scanDebug}` : "",
    recentEvents.length > 0 ? `最近事件:\n${recentEvents.join("\n")}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function formatRuntimeFingerprint(status) {
  const fingerprint = status?.runtimeFingerprint || {};
  if (!fingerprint.manifestVersion && !fingerprint.serviceWorkerRevision && !fingerprint.chatRunnerVersion && !fingerprint.runToken) {
    return "";
  }
  return [
    `运行指纹: manifest ${fingerprint.manifestVersion || "-"}`,
    `worker ${fingerprint.serviceWorkerRevision || "-"}`,
    `runner ${fingerprint.chatRunnerVersion || "-"}`,
    `token ${fingerprint.runToken || "-"}`,
    fingerprint.runnerReplaced ? "runner已替换" : "",
  ]
    .filter(Boolean)
    .join(" / ");
}

function formatBatchLog(status) {
  const logs = Array.isArray(status?.runtimeLogs) ? status.runtimeLogs : [];
  if (logs.length > 0) {
    return logs.join("\n");
  }
  const recentEvents = Array.isArray(status?.recentEvents) ? status.recentEvents : [];
  if (recentEvents.length > 0) {
    return ["No runtime log payload yet.", "Recent events:", ...recentEvents].join("\n");
  }
  const fallbacks = [
    status?.message ? `Message: ${status.message}` : "",
    status?.scanMessage ? `Scan: ${status.scanMessage}` : "",
    status?.scanDebug ? `Debug: ${status.scanDebug}` : "",
  ].filter(Boolean);
  return fallbacks.length > 0 ? fallbacks.join("\n") : "No runtime log yet.";
}

function translateBatchMode(value) {
  switch (value) {
    case "download_only":
      return "批量下载";
    case "request_resume":
      return "批量求简历";
    default:
      return "未启动";
  }
}

function translateBatchPhase(value) {
  switch (value) {
    case "idle":
      return "未启动";
    case "starting":
      return "启动中";
    case "running":
      return "运行中";
    case "stopping":
      return "停止中";
    case "completed":
      return "已完成";
    case "stopped":
      return "已停止";
    case "failed":
      return "失败";
    default:
      return value || "未知";
  }
}

function buildKey(card) {
  return card.platform_uid || card.detail_url || card.raw_card_text || JSON.stringify(card);
}

function trimTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function normalizeLocalApiBase(value) {
  let raw = String(value || DEFAULTS.apiBase).trim() || DEFAULTS.apiBase;
  if (!/^[a-z][a-z\d+.-]*:\/\//i.test(raw)) {
    raw = `http://${raw}`;
  }
  try {
    const url = new URL(raw);
    const hostname = url.hostname.toLowerCase();
    if (hostname === "localhost" || hostname === "::1" || hostname === "[::1]") {
      url.hostname = "127.0.0.1";
    }
    return trimTrailingSlash(url.toString());
  } catch (_error) {
    return trimTrailingSlash(raw.replace(/^http:\/\/(?:localhost|\[::1\])(?=[:/]|$)/i, "http://127.0.0.1"));
  }
}

function formatLocalApiFetchError(apiBase, error) {
  return [
    `无法连接本地接口：${apiBase}`,
    "请确认桌面端已启动；扩展里的接口地址使用 http://127.0.0.1:17863；Token 与桌面端“设置”页面一致。",
    "如果刚更新或重新安装过扩展，请在 chrome://extensions 里点击“重新加载”。",
    `浏览器错误：${error?.message || String(error)}`,
  ].join("\n");
}

function setStatus(text) {
  statusEl.textContent = text;
}
