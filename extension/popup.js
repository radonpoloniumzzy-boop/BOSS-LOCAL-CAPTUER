const DEFAULTS = {
  jobTitle: "Boss 推荐牛人",
  jobProfileId: null,
  recruitmentTaskId: null,
  apiBase: "http://127.0.0.1:17863",
  apiToken: "",
  connectionMode: "",
  connectionModeConfirmed: true,
  scrollMode: "hold_end",
  scrollStep: 900,
  scrollWaitMs: 30,
  maxScrollCount: 80,
  noNewStopRounds: 4,
  resumeMessage: "方便发一份你的简历过来吗？",
  waitSeconds: 45,
  pollIntervalMs: 2000,
  batchActionDelaySeconds: 5,
  maxBatchSessions: 50,
  chatAutomationEnabled: false,
  lastCompletedBatchId: null,
  lastCompletedBatchConnection: null,
};

const OLD_DEFAULT_SCROLL_WAIT_MS = 1500;
const SCROLL_WAIT_DEFAULT_VERSION = 2;
const SCROLL_MODE_DEFAULT_VERSION = 2;

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
  chatAutomationEnabled: document.getElementById("chatAutomationEnabled"),
};

const statusEl = document.getElementById("status");
const batchStatusEl = document.getElementById("batchStatus");
const batchLogEl = document.getElementById("batchLog");
const webIntakeStatusEl = document.getElementById("webIntakeStatus");
const pluginContextStatusEl = document.getElementById("pluginContextStatus");
const automationAutoButton = document.getElementById("automationAuto");
const pairingCodeInput = document.getElementById("pairingCode");
const applyPairingCodeButton = document.getElementById("applyPairingCode");
const downloadCurrentBatchButton = document.getElementById("downloadCurrentBatch");
const retryWebIntakeButton = document.getElementById("retryWebIntake");
const openWebWorkbenchButton = document.getElementById("openWebWorkbench");
let batchStatusTimer = null;
let activeJobProfileId = null;
let activeRecruitmentTaskId = null;
let activeConnectionMode = "";
let activeConnectionModeConfirmed = true;
let lastCompletedBatchId = null;
let lastCompletedBatchConnection = null;
let lastCompletedWebBatch = null;

automationAutoButton.addEventListener("click", () => runAutomation());
applyPairingCodeButton.addEventListener("click", () => applyPairingCodeAndTest());
downloadCurrentBatchButton.addEventListener("click", () => downloadCurrentBatch());
retryWebIntakeButton.addEventListener("click", () => retryWebIntake());
openWebWorkbenchButton.addEventListener("click", () => openWebWorkbench());
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
fields.apiBase.addEventListener("input", () => {
  return switchToDesktopCompatibilityMode();
});
fields.apiToken.addEventListener("input", () => {
  return switchToDesktopCompatibilityMode();
});

window.addEventListener("beforeunload", () => {
  if (batchStatusTimer) {
    window.clearInterval(batchStatusTimer);
  }
});

if (!globalThis.__bossLocalPopupTestMode) {
  void init();
}

async function clearDesktopBatchDownloadState() {
  lastCompletedBatchId = null;
  lastCompletedBatchConnection = null;
  await chrome.storage.local.set({
    lastCompletedBatchId: null,
    lastCompletedBatchConnection: null,
  });
}

async function switchToDesktopCompatibilityMode() {
  activeConnectionMode = "desktop";
  activeConnectionModeConfirmed = true;
  lastCompletedWebBatch = null;
  await clearDesktopBatchDownloadState();
  await chrome.storage.local.set({
    connectionMode: "desktop",
    connectionModeConfirmed: true,
  });
  syncConnectionControls();
  syncModeHints();
  updateBatchDownloadButton();
}

async function init() {
  let stored = await chrome.storage.local.get({
    ...DEFAULTS,
    scrollWaitDefaultVersion: null,
    scrollModeDefaultVersion: null,
  });
  const migratedConnection = await BossLocalWebIntake.ensureStoredConnectionMode(chrome.storage.local);
  stored = {
    ...stored,
    apiBase: migratedConnection.apiBase,
    connectionMode: migratedConnection.connectionMode,
    connectionModeConfirmed: migratedConnection.connectionModeConfirmed,
  };
  if (stored.scrollWaitDefaultVersion === null && Number(stored.scrollWaitMs) === OLD_DEFAULT_SCROLL_WAIT_MS) {
    stored.scrollWaitMs = DEFAULTS.scrollWaitMs;
    await chrome.storage.local.set({
      scrollWaitMs: stored.scrollWaitMs,
      scrollWaitDefaultVersion: SCROLL_WAIT_DEFAULT_VERSION,
    });
  } else if (stored.scrollWaitDefaultVersion === null) {
    await chrome.storage.local.set({ scrollWaitDefaultVersion: SCROLL_WAIT_DEFAULT_VERSION });
  }
  if (stored.scrollModeDefaultVersion === null && stored.scrollMode === "end") {
    stored.scrollMode = DEFAULTS.scrollMode;
    await chrome.storage.local.set({
      scrollMode: stored.scrollMode,
      scrollModeDefaultVersion: SCROLL_MODE_DEFAULT_VERSION,
    });
  } else if (stored.scrollModeDefaultVersion === null) {
    await chrome.storage.local.set({ scrollModeDefaultVersion: SCROLL_MODE_DEFAULT_VERSION });
  }
  for (const [key, element] of Object.entries(fields)) {
    if (element) {
      if (element.type === "checkbox") {
        element.checked = Boolean(stored[key]);
      } else {
        element.value = stored[key];
      }
    }
  }
  activeJobProfileId = stored.jobProfileId === null ? null : Number(stored.jobProfileId);
  activeRecruitmentTaskId = stored.recruitmentTaskId === null ? null : Number(stored.recruitmentTaskId);
  activeConnectionMode = BossLocalWebIntake.normalizeConnectionMode(stored.connectionMode);
  activeConnectionModeConfirmed = stored.connectionModeConfirmed !== false;
  syncConnectionControls();
  syncModeHints();
  lastCompletedBatchId = stored.lastCompletedBatchId === null ? null : Number(stored.lastCompletedBatchId);
  lastCompletedBatchConnection = stored.lastCompletedBatchConnection || null;
  if (!BossLocalBatchExport.batchBelongsToConnection(lastCompletedBatchConnection, collectSettings())) {
    await clearDesktopBatchDownloadState();
  }
  await refreshWebIntakeStatus(collectSettings(), { updateDownloadButton: false });
  await refreshPluginContext(collectSettings());
  updateBatchDownloadButton();
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
  if (isWebWorkbenchMode(settings)) {
    setStatus("AUTO 采集仍依赖桌面端自动化流程。请切回桌面模式接口地址后再使用。");
    return;
  }
  automationAutoButton.disabled = true;
  setStatus("正在读取桌面端自动化方案...");
  try {
    const automation = await startDesktopAutomation(settings, tab.url);
    fields.jobTitle.value = automation.job_title || automation.profile_job_title || settings.jobTitle;
    activeJobProfileId = automation.profile_id === null ? null : Number(automation.profile_id);
    activeRecruitmentTaskId = automation.task_id === null ? null : Number(automation.task_id);
    await chrome.storage.local.set({
      ...collectSettings(),
      jobTitle: fields.jobTitle.value,
      jobProfileId: activeJobProfileId,
      recruitmentTaskId: activeRecruitmentTaskId,
    });
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

async function applyPairingCodeAndTest() {
  applyPairingCodeButton.disabled = true;
  setStatus("正在验证本机工作台连接...");
  try {
    const pairing = BossLocalPairing.parsePairingCode(pairingCodeInput.value);
    let verifiedSettings;
    if (pairing.pairingCode) {
      const pairingApiBase = normalizeLocalApiBase(pairing.apiBase || "http://127.0.0.1:17864");
      let response;
      try {
        response = await fetch(`${pairingApiBase}/api/plugin/pair`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pairing_code: pairing.pairingCode }),
        });
      } catch (_error) {
        throw new Error("网页工作台尚未启动，请先运行‘启动网页工作台’。");
      }
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.error?.message || "连接码验证失败，请重新生成。");
      }
      verifiedSettings = {
        ...collectSettings(),
        apiBase: pairingApiBase,
        apiToken: String(payload.api_token || ""),
        connectionMode: BossLocalWebIntake.normalizeConnectionMode(pairing.connectionMode) || "web",
        connectionModeConfirmed: true,
      };
    } else {
      verifiedSettings = {
        ...collectSettings(),
        apiBase: normalizeLocalApiBase(pairing.apiBase),
        apiToken: pairing.apiToken,
        connectionMode: BossLocalWebIntake.normalizeConnectionMode(pairing.connectionMode) || "desktop",
        connectionModeConfirmed: true,
      };
    }
    await testLocalApiConnection(verifiedSettings);
    fields.apiBase.value = verifiedSettings.apiBase;
    fields.apiToken.value = verifiedSettings.apiToken;
    activeConnectionMode = BossLocalWebIntake.normalizeConnectionMode(verifiedSettings.connectionMode);
    activeConnectionModeConfirmed = verifiedSettings.connectionModeConfirmed !== false;
    if (!BossLocalBatchExport.batchBelongsToConnection(lastCompletedBatchConnection, verifiedSettings)) {
      await clearDesktopBatchDownloadState();
    }
    await chrome.storage.local.set({
      apiBase: fields.apiBase.value,
      apiToken: fields.apiToken.value,
      connectionMode: activeConnectionMode,
      connectionModeConfirmed: activeConnectionModeConfirmed,
      lastCompletedBatchId,
      lastCompletedBatchConnection,
    });
    syncConnectionControls(verifiedSettings);
    updateBatchDownloadButton();
    verifiedSettings = await refreshPluginContext(verifiedSettings);
    pairingCodeInput.value = "";
    const target = isWebWorkbenchMode(verifiedSettings) ? "网页工作台" : "桌面兼容模式";
    setStatus(`已连接${target}。\n服务地址：${fields.apiBase.value}\n连接已记住`);
  } catch (error) {
    setStatus(`连接失败。\n${error.message || String(error)}`);
  } finally {
    applyPairingCodeButton.disabled = false;
  }
}

async function testLocalApiConnection(settings) {
  const apiBase = normalizeLocalApiBase(settings.apiBase);
  const endpoint = isWebWorkbenchMode(settings) ? "/api/plugin/connection/check" : "/api/connection/check";
  let response;
  try {
    response = await fetch(`${apiBase}${endpoint}`, {
      method: "GET",
      headers: localApiHeaders(settings),
    });
  } catch (error) {
    throw new Error(formatLocalApiFetchError(apiBase, error));
  }
  let result = {};
  try {
    result = await response.json();
  } catch (_error) {
    result = {};
  }
  if (response.status === 401) {
    throw new Error("连接凭证已失效，请重新配对。");
  }
  if (!response.ok || !result.ok) {
    throw new Error(result.error || `桌面端返回状态码 ${response.status}`);
  }
  return result;
}

async function adjustScrollWait(deltaMs) {
  const current = Number(fields.scrollWaitMs.value || DEFAULTS.scrollWaitMs);
  const next = Math.max(0, current + deltaMs);
  fields.scrollWaitMs.value = String(next);
  await chrome.storage.local.set({ scrollWaitMs: next });
  setStatus(`滚动等待毫秒已设置为 ${next}ms。`);
}

function isWebWorkbenchMode(settings) {
  return BossLocalWebIntake.isWebWorkbenchMode(settings);
}

function buildCollectionRunId() {
  return BossLocalWebIntake.createClientBatchId();
}

function createWebIntakeError(response, fallbackMessage) {
  const error = new Error(response?.error || fallbackMessage);
  error.code = String(response?.code || "");
  return error;
}

function formatWebIntakeError(error) {
  switch (String(error?.code || "")) {
    case "storage_quota_exceeded":
      return "网页入库缓存空间已满，请先清理或完成旧批次后再试。";
    case "pending_limit_exceeded":
      return "待发送批次已达到上限，请先完成发送或清理旧批次后再继续。";
    case "network_error":
      return "无法连接网页工作台，请确认本地网页工作台已启动。";
    default:
      return error?.message || String(error);
  }
}

function syncModeHints(settings = collectSettings()) {
  const webMode = isWebWorkbenchMode(settings);
  automationAutoButton.textContent = webMode ? "AUTO：桌面兼容模式专用" : "AUTO：滚动采集 + AI 初筛";
  automationAutoButton.title = webMode
    ? "Web 工作台模式下不使用桌面 AUTO 流程。"
    : "桌面兼容模式下可直接触发桌面 AUTO 流程。";
}

function syncConnectionControls(settings = collectSettings()) {
  applyPairingCodeButton.textContent = isWebWorkbenchMode(settings) && Boolean(settings.apiToken)
    ? "重新配对"
    : "连接并记住";
}

async function refreshWebIntakeStatus(settingsOverride = null, options = {}) {
  const { updateDownloadButton: shouldUpdateDownloadButton = true } = options;
  const settings = settingsOverride ? { ...DEFAULTS, ...settingsOverride } : collectSettings();
  syncModeHints(settings);
  const response = await chrome.runtime.sendMessage({
    type: "web_intake_get_status",
    settings,
  });
  if (!response?.ok || !response.view) {
    webIntakeStatusEl.textContent = `当前模式：${BossLocalWebIntake.modeLabel(settings)}\n网页入库状态读取失败。`;
    retryWebIntakeButton.disabled = true;
    return;
  }
  const view = response.view;
  webIntakeStatusEl.textContent = `${view.title}\n${view.message}`;
  retryWebIntakeButton.disabled = !view.canRetry;
  const record = response.record || null;
  if (["completed", "partial", "reused"].includes(String(record?.status || "")) && Number(record?.webResult?.batch_id) > 0) {
    lastCompletedWebBatch = record;
  }
  if (shouldUpdateDownloadButton) {
    updateBatchDownloadButton();
  }
}

async function refreshPluginContext(settingsOverride = null) {
  const settings = settingsOverride ? { ...DEFAULTS, ...settingsOverride } : collectSettings();
  async function clearContextIds(message) {
    activeJobProfileId = null;
    activeRecruitmentTaskId = null;
    await chrome.storage.local.set({ jobProfileId: null, recruitmentTaskId: null });
    pluginContextStatusEl.textContent = message;
    return { ...settings, jobProfileId: null, recruitmentTaskId: null };
  }
  if (!isWebWorkbenchMode(settings)) {
    activeJobProfileId = null;
    activeRecruitmentTaskId = null;
    await chrome.storage.local.set({ jobProfileId: null, recruitmentTaskId: null });
    pluginContextStatusEl.textContent = "当前为桌面兼容模式，岗位上下文由桌面端自动化流程决定。";
    return { ...settings, jobProfileId: null, recruitmentTaskId: null };
  }
  if (!settings.apiToken) {
    return clearContextIds("当前未选择招聘任务；仍可进行无岗位采集。");
  }

  const apiBase = BossLocalWebIntake.deriveWebApiBase(settings);
  await chrome.storage.local.set({ jobProfileId: null, recruitmentTaskId: null });
  activeJobProfileId = null;
  activeRecruitmentTaskId = null;
  try {
    const response = await fetch(`${apiBase}/api/plugin/context`, {
      method: "GET",
      headers: {
        "X-Boss-Local-Token": settings.apiToken || "",
      },
    });
    if (response.status === 409) {
      return clearContextIds("上下文未确认，将按无岗位采集。");
    }
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload?.error?.message || `网页工作台返回状态码 ${response.status}`);
    }
    activeJobProfileId = Number(payload.job_profile_id);
    activeRecruitmentTaskId = Number(payload.recruitment_task_id);
    fields.jobTitle.value = String(payload.job_title || settings.jobTitle || DEFAULTS.jobTitle);
    const synced = {
      ...settings,
      jobTitle: fields.jobTitle.value,
      jobProfileId: activeJobProfileId,
      recruitmentTaskId: activeRecruitmentTaskId,
    };
    await chrome.storage.local.set({
      jobTitle: synced.jobTitle,
      jobProfileId: activeJobProfileId,
      recruitmentTaskId: activeRecruitmentTaskId,
    });
    pluginContextStatusEl.textContent = [
      "当前招聘任务已连接。",
      `任务 #${payload.recruitment_task_id}`,
      `岗位：${payload.job_title || "-"}`,
      `版本：v${payload.job_profile_version || "-"}`,
      `状态：${payload.task_status || "-"}`,
    ].join("\n");
    return synced;
  } catch (_error) {
    return clearContextIds("上下文未确认，将按无岗位采集。");
  }
}

async function queueAndSendWebBatch(settings, sourceUrl, merged, runId) {
  const response = await chrome.runtime.sendMessage({
    type: "web_intake_enqueue_and_send",
    settings,
    sourceUrl,
    merged,
    idempotencyKey: runId,
  });
  if (!response?.ok) {
    throw createWebIntakeError(response, "网页工作台发送失败。");
  }
  await refreshWebIntakeStatus(settings);
  return response.record || null;
}

async function retryWebIntake() {
  retryWebIntakeButton.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({
      type: "web_intake_retry",
      settings: collectSettings(),
    });
    if (!response?.ok) {
      throw createWebIntakeError(response, "网页入库重试失败。");
    }
    const result = response.record || null;
    if (result?.message) {
      setStatus(`网页入库状态已更新。\n${result.message}`);
    }
  } catch (error) {
    setStatus(`重试网页入库失败。\n${error.message || String(error)}`);
  } finally {
    await refreshWebIntakeStatus();
  }
}

async function openWebWorkbench() {
  const settings = collectSettings();
  const url = `${BossLocalWebIntake.deriveWebApiBase(settings)}/`;
  if (!isWebWorkbenchMode(settings)) {
    setStatus("当前是旧桌面兼容模式。将打开默认网页工作台 17864 入口；如果网页工作台使用自定义端口，请使用网页连接码重新配对。");
  }
  try {
    const response = await fetch(`${url}api/health`);
    if (!response.ok) throw new Error("health failed");
  } catch (_error) {
    setStatus("网页工作台尚未启动，请先运行‘启动网页工作台’。");
    return;
  }
  await chrome.tabs.create({ url });
}

async function runCollection(autoScroll, options = {}) {
  let baseSettings = collectSettings();
  const webMode = isWebWorkbenchMode(baseSettings);
  if (!options.automationRequested && !webMode) {
    try {
      baseSettings = await loadDesktopJobProfile(baseSettings);
    } catch (error) {
      setStatus(`无法读取当前岗位档案。\n${error.message || String(error)}`);
      return;
    }
  }
  await chrome.storage.local.set(baseSettings);

  const tab = await getActiveSupportedTab();
  if (!tab) {
    return;
  }

  const platform = detectCollectPlatform(tab.url);
  const settings = applyPlatformDefaults(baseSettings, platform);
  const webSettings = webMode ? await refreshPluginContext(settings) : settings;
  if (webMode) {
    await refreshRatingBadges(tab.id, webSettings);
  } else {
    await clearRatingBadges(tab.id);
  }
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

  const runId = buildCollectionRunId();
  try {
    if (webMode) {
      await clearDesktopBatchDownloadState();
      updateBatchDownloadButton();
      const webResult = await queueAndSendWebBatch(webSettings, tab.url, merged, runId);
      const resultStats = webResult?.webResult || {};
      const firstLine = ["completed", "partial", "reused"].includes(String(webResult?.status || ""))
        ? "采集完成，已发送到网页工作台。"
        : "采集完成，但网页入库未完成。";
      setStatus(
        [
          firstLine,
          `本地去重卡片: ${merged.cards.length}`,
          `来源平台: ${platform.label}`,
          `命中 frame: ${merged.framesWithCards}/${merged.framesSeen}`,
          `网页批次: ${resultStats.batch_id ?? "-"}`,
          `接收数: ${resultStats.received_count ?? 0}`,
          `新增数: ${resultStats.inserted_candidates ?? 0}`,
          `更新数: ${resultStats.updated_candidates ?? 0}`,
          `跳过数: ${resultStats.skipped_candidates ?? 0}`,
          `失败数: ${resultStats.failed_candidates ?? 0}`,
          webResult?.message || "",
        ].filter(Boolean).join("\n"),
      );
      return;
    }

    const imported = await importCards(settings, tab.url, merged, Boolean(options.automationRequested));
    lastCompletedBatchId = Number(imported.batch_id) || null;
    lastCompletedBatchConnection = {
      connectionMode: settings.connectionMode,
      apiBase: settings.apiBase,
      apiToken: settings.apiToken,
    };
    await chrome.storage.local.set({ lastCompletedBatchId, lastCompletedBatchConnection });
    updateBatchDownloadButton();
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
    setStatus(`${webMode ? "发送到网页工作台失败" : "导入本地程序失败"}。\n${formatWebIntakeError(error)}`);
  }
}

async function refreshRatingBadges(tabId, settings) {
  if (!isWebWorkbenchMode(settings) || !settings.apiToken) {
    await clearRatingBadges(tabId);
    return;
  }
  try {
    const apiBase = BossLocalWebIntake.deriveWebApiBase(settings);
    const response = await fetch(`${apiBase}/api/plugin/ratings/badges`, {
      headers: { "X-Boss-Local-Token": settings.apiToken || "" },
    });
    if (!response.ok) {
      await clearRatingBadges(tabId);
      return;
    }
    const payload = await response.json();
    await applyRatingBadges(tabId, Array.isArray(payload?.badges) ? payload.badges : []);
  } catch (_error) {
    await clearRatingBadges(tabId);
  }
}

async function clearRatingBadges(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => {
        document.querySelectorAll(".boss-local-rating-badge").forEach((node) => node.remove());
      },
    });
  } catch (_error) {}
}

async function applyRatingBadges(tabId, badges) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      args: [badges],
      func: (badgeRows) => {
        const ratingClass = (rating) => `boss-local-rating-${String(rating || "").toLowerCase()}`;
        const candidateSelectors = [
          ".candidate-card-wrap",
          ".candidate-card",
          ".geek-card",
          "[data-testid='candidate-card']",
          "[class*='card'][class*='candidate']",
        ];
        const cards = Array.from(document.querySelectorAll(candidateSelectors.join(",")));
        const normalize = (value) => String(value || "").trim();
        const firstAttr = (node, attrs) => {
          for (const attr of attrs) {
            const value = normalize(node.getAttribute(attr));
            if (value) return value;
          }
          return "";
        };
        const sameBadge = (card, badge) => {
          const platformUid = firstAttr(card, ["data-geek-id", "data-candidate-id", "data-user-id"]);
          if (badge.platform_uid && platformUid && badge.platform_uid === platformUid) return true;
          return false;
        };
        const rows = (Array.isArray(badgeRows) ? badgeRows : []).filter((badge) =>
          ["UR", "SSR", "SR", "R", "N"].includes(String(badge?.rating || "")),
        );
        document.querySelectorAll(".boss-local-rating-badge").forEach((node) => node.remove());
        for (const card of cards) {
          const badge = rows.find((item) => sameBadge(card, item));
          if (!badge) continue;
          const node = document.createElement("span");
          node.className = `boss-local-rating-badge ${ratingClass(badge.rating)}`;
          node.textContent = String(badge.badge_text || `1${badge.rating}`);
          node.setAttribute("data-boss-local-rating", String(badge.rating));
          const palette = {
            UR: ["#fef3c7", "#7c3aed", "#c4b5fd"],
            SSR: ["#f5f3ff", "#6d28d9", "#ddd6fe"],
            SR: ["#fff7ed", "#c2410c", "#fed7aa"],
            R: ["#eff6ff", "#1d4ed8", "#bfdbfe"],
            N: ["#f8fafc", "#475569", "#e2e8f0"],
          }[String(badge.rating)] || ["#f8fafc", "#475569", "#e2e8f0"];
          node.style.cssText = [
            "display:inline-flex",
            "align-items:center",
            "margin-right:6px",
            "padding:2px 7px",
            "border-radius:999px",
            "font-size:12px",
            "font-weight:700",
            "line-height:1.4",
            `background:${palette[0]}`,
            `color:${palette[1]}`,
            `border:1px solid ${palette[2]}`,
          ].join(";");
          const target = card.querySelector(".name, .geek-name, .candidate-name, [class*='name']") || card;
          target.insertAdjacentElement("afterbegin", node);
        }
      },
    });
  } catch (_error) {}
}

function updateBatchDownloadButton() {
  const settings = collectSettings();
  if (isWebWorkbenchMode(settings)) {
    const webBatchId = Number(lastCompletedWebBatch?.webResult?.batch_id || 0);
    downloadCurrentBatchButton.disabled = !webBatchId;
    downloadCurrentBatchButton.textContent = webBatchId
      ? `导出本批次 #${webBatchId} Markdown`
      : "导出本批次 Markdown";
    return;
  }
  downloadCurrentBatchButton.disabled = !Number.isInteger(lastCompletedBatchId) || lastCompletedBatchId <= 0;
  downloadCurrentBatchButton.textContent = lastCompletedBatchId
    ? `下载当前批次 #${lastCompletedBatchId} CSV 到 Downloads`
    : "下载当前批次 CSV 到 Downloads";
}

async function downloadCurrentBatch() {
  const settings = collectSettings();
  if (isWebWorkbenchMode(settings)) {
    const batchId = Number(lastCompletedWebBatch?.webResult?.batch_id || 0);
    if (!batchId || !(await BossLocalWebIntake.sameConnection(lastCompletedWebBatch?.connection, settings))) {
      lastCompletedWebBatch = null;
      updateBatchDownloadButton();
      setStatus("当前连接没有可导出的 Web 批次，请先完成一次采集。");
      return;
    }
    downloadCurrentBatchButton.disabled = true;
    try {
      const result = await BossLocalBatchExport.downloadBatchMarkdown({
        apiBase: settings.apiBase,
        apiToken: settings.apiToken,
        batchId,
      });
      setStatus(`批次 #${result.batchId} Markdown 已保存到 Downloads。\n文件：${result.filename}`);
    } catch (error) {
      setStatus(`导出 Markdown 失败。\n${error.message || String(error)}`);
    } finally {
      updateBatchDownloadButton();
    }
    return;
  }
  if (!lastCompletedBatchId) {
    setStatus("当前没有可下载的采集批次，请先完成一次采集。");
    return;
  }
  if (!BossLocalBatchExport.batchBelongsToConnection(lastCompletedBatchConnection, settings)) {
    lastCompletedBatchId = null;
    lastCompletedBatchConnection = null;
    await chrome.storage.local.set({ lastCompletedBatchId: null, lastCompletedBatchConnection: null });
    updateBatchDownloadButton();
    setStatus("本地接口连接已变化，旧批次已清除。请先在当前桌面端完成一次采集。");
    return;
  }
  downloadCurrentBatchButton.disabled = true;
  setStatus(`正在导出批次 #${lastCompletedBatchId} 到 Downloads...`);
  try {
    const result = await BossLocalBatchExport.downloadBatchCsv({
      apiBase: settings.apiBase,
      apiToken: settings.apiToken,
      batchId: lastCompletedBatchId,
    });
    setStatus(`批次 #${result.batchId} 已提交下载。\n文件：${result.filename}\n位置：Chrome 默认 Downloads 目录`);
  } catch (error) {
    setStatus(`下载当前批次失败。\n${error.message || String(error)}`);
  } finally {
    updateBatchDownloadButton();
  }
}

async function loadDesktopJobProfile(settings) {
  const apiBase = normalizeLocalApiBase(settings.apiBase);
  let response;
  try {
    response = await fetch(`${apiBase}/api/extension/config`, {
      headers: localApiHeaders(settings),
    });
  } catch (error) {
    throw new Error(formatLocalApiFetchError(apiBase, error));
  }
  const payload = await response.json();
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.error || `桌面端返回状态码 ${response.status}`);
  }
  const profileId = payload.result?.job_profile_id;
  if (profileId === null || profileId === undefined) {
    throw new Error("请先在桌面端仪表盘选择招聘中的岗位档案。")
  }
  activeJobProfileId = Number(profileId);
  activeRecruitmentTaskId = payload.result?.recruitment_task_id === null || payload.result?.recruitment_task_id === undefined
    ? null
    : Number(payload.result.recruitment_task_id);
  fields.jobTitle.value = String(payload.result?.job_title || settings.jobTitle);
  const synced = {
    ...settings,
    jobProfileId: activeJobProfileId,
    recruitmentTaskId: activeRecruitmentTaskId,
    jobTitle: fields.jobTitle.value,
  };
  await chrome.storage.local.set(synced);
  return synced;
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
  if (!ensureChatAutomationEnabled(settings)) {
    return;
  }

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
  if (!ensureChatAutomationEnabled(settings)) {
    return;
  }

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
        job_profile_id: settings.jobProfileId,
        recruitment_task_id: settings.recruitmentTaskId,
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
    jobProfileId: activeJobProfileId,
    recruitmentTaskId: activeRecruitmentTaskId,
    jobTitle: fields.jobTitle.value.trim() || DEFAULTS.jobTitle,
    apiBase,
    apiToken: fields.apiToken.value.trim(),
    connectionMode: activeConnectionMode,
    connectionModeConfirmed: activeConnectionModeConfirmed,
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
    chatAutomationEnabled: Boolean(fields.chatAutomationEnabled?.checked),
  };
}

function ensureChatAutomationEnabled(settings = collectSettings()) {
  if (settings.chatAutomationEnabled) {
    return true;
  }
  const message = "Boss 聊天自动化默认关闭。请先勾选“启用 Boss 聊天自动化”，再执行求简历、批量求简历或附件下载。";
  setStatus(message);
  if (batchStatusEl) {
    batchStatusEl.textContent = `批量任务：未启动。\n${message}`;
  }
  return false;
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

globalThis.BossLocalPopup = {
  init,
  runCollection,
  runAutomation,
  applyPairingCodeAndTest,
  retryWebIntake,
  openWebWorkbench,
  downloadCurrentBatch,
  refreshWebIntakeStatus,
  refreshPluginContext,
  refreshRatingBadges,
  clearRatingBadges,
  queueAndSendWebBatch,
  collectSettings,
  isWebWorkbenchMode,
};
