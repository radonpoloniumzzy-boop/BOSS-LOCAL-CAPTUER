const BATCH_STATUS_KEY = "boss_batch_status";
const EXTENSION_VERSION = chrome.runtime.getManifest?.().version || "dev";
const SERVICE_WORKER_DOWNLOAD_CLICK_REVISION = "top-toolbar-first-v1";
const EXPECTED_CHAT_RUNNER_VERSION = EXTENSION_VERSION;
const DEFAULT_BATCH_STATUS = {
  running: false,
  stopRequested: false,
  phase: "idle",
  mode: "",
  tabId: null,
  windowId: null,
  sourceUrl: "",
  startedAt: "",
  updatedAt: "",
  currentSession: "",
  message: "就绪。",
  scanMessage: "",
  scanDebug: "",
  error: "",
  runtimeLogs: [],
  runtimeFingerprint: {
    manifestVersion: EXTENSION_VERSION,
    serviceWorkerRevision: SERVICE_WORKER_DOWNLOAD_CLICK_REVISION,
    chatRunnerVersion: "",
    runToken: "",
    runnerReplaced: false,
    staleRuntime: false,
  },
  stats: {
    processed: 0,
    requested: 0,
    skipped: 0,
    skippedNoAttachment: 0,
    failed: 0,
    downloaded: 0,
    discovered: 0,
    discoveredVisibleSessions: 0,
    eligibleUnreadSessions: 0,
    rejectedRows: 0,
  },
  recentEvents: [],
};
const STOP_GUARD_MS = 10 * 60 * 1000;
const stoppedBatchTabs = new Map();

chrome.runtime.onInstalled.addListener(() => {
  void ensureBatchStatus();
});

chrome.runtime.onStartup.addListener(() => {
  void ensureBatchStatus();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  void handleBatchTabRemoved(tabId);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then((result) => sendResponse(result))
    .catch((error) =>
      sendResponse({
        ok: false,
        error: error?.message || String(error),
      }),
    );
  return true;
});

async function handleMessage(message, sender) {
  switch (message?.type) {
    case "get_batch_status":
      return { ok: true, status: await getBatchStatus() };
    case "start_batch":
      return startBatchClean(message.tabId, message.settings || {}, message.mode || "request_resume");
    case "stop_batch":
      return stopBatch(message.tabId || null, message.reason || "");
    case "batch_progress":
      await handleBatchProgress(message.payload || {}, sender);
      return { ok: true };
    case "batch_finished":
      await handleBatchFinished(message.payload || {}, sender);
      return { ok: true };
    case "download_resume":
      return downloadResume(message.payload || {});
    case "wait_for_recent_download":
      return waitForRecentDownload(message.payload || {});
    case "click_preview_download_button":
      return clickPreviewDownloadButtonInFrames(message.payload || {}, sender);
    case "resolve_active_pdf_url":
      return resolveActivePdfUrl(message.payload || {}, sender);
    case "trusted_click":
      return trustedClick(message.payload || {}, sender);
    default:
      return { ok: false, error: `Unknown message type: ${String(message?.type || "")}` };
  }
}

async function ensureBatchStatus() {
  const current = await getBatchStatus();
  await chrome.storage.local.set({ [BATCH_STATUS_KEY]: current });
  return current;
}

async function getBatchStatus() {
  const stored = (await chrome.storage.local.get(BATCH_STATUS_KEY))[BATCH_STATUS_KEY];
  return mergeBatchStatus(stored);
}

async function saveBatchStatus(nextStatus) {
  const merged = mergeBatchStatus(nextStatus);
  await chrome.storage.local.set({ [BATCH_STATUS_KEY]: merged });
  return merged;
}

async function patchBatchStatus(patch, eventText = "") {
  const current = await getBatchStatus();
  const merged = mergeBatchStatus({
    ...current,
    ...patch,
    stats: {
      ...current.stats,
      ...(patch?.stats || {}),
    },
    runtimeFingerprint: {
      ...current.runtimeFingerprint,
      ...(patch?.runtimeFingerprint || {}),
    },
    runtimeLogs: mergeRuntimeLogs(current.runtimeLogs, patch?.runtimeLogs),
    recentEvents: mergeRecentEvents(current.recentEvents, eventText || patch?.message || ""),
    updatedAt: nowIso(),
  });
  await chrome.storage.local.set({ [BATCH_STATUS_KEY]: merged });
  return merged;
}

async function startBatchClean(tabId, settings, mode) {
  if (!Number.isInteger(Number(tabId))) {
    return { ok: false, error: "缺少有效的聊天标签页。" };
  }

  const tab = await chrome.tabs.get(Number(tabId));
  stoppedBatchTabs.delete(tab.id);
  if (!String(tab.url || "").includes("zhipin.com")) {
    return { ok: false, error: "当前标签页不是 Boss 页面。" };
  }

  const current = await getBatchStatus();
  if (current.running && current.tabId) {
    await stopBatch(current.tabId, "已切换到新的批量任务");
    await delay(250);
  }

  const normalizedMode = normalizeBatchMode(mode);
  const isDownloadOnly = normalizedMode === "download_only";
  const startMessage = isDownloadOnly
    ? "批量下载任务已启动，等待页面执行。"
    : "批量求简历任务已启动，等待页面执行。";
  const startEvent = isDownloadOnly ? "批量下载任务已启动" : "批量求简历任务已启动";

  await saveBatchStatus({
    ...DEFAULT_BATCH_STATUS,
    running: true,
    stopRequested: false,
    phase: "starting",
    mode: normalizedMode,
    tabId: tab.id,
    windowId: tab.windowId,
    sourceUrl: tab.url || "",
    startedAt: nowIso(),
    updatedAt: nowIso(),
    message: startMessage,
    runtimeLogs: [
      `${formatClock(new Date())} background start: ${normalizedMode} | manifest=${EXTENSION_VERSION} worker=${SERVICE_WORKER_DOWNLOAD_CLICK_REVISION} expectedRunner=${EXPECTED_CHAT_RUNNER_VERSION}`,
    ],
    recentEvents: mergeRecentEvents([], startEvent),
  });

  const injection = await ensureChatRunnerInjected(tab.id);
  await patchBatchStatus({
    runtimeFingerprint: buildRuntimeFingerprint({
      chatRunnerVersion: injection.chatRunnerVersion || "",
      runToken: injection.runToken || "",
      runnerReplaced: Boolean(injection.runnerReplaced),
      staleRuntime: Boolean(injection.staleRuntime),
    }),
  });
  await appendBatchRuntimeLog(
    `runner injection: expected=${injection.expectedVersion || EXPECTED_CHAT_RUNNER_VERSION} actual=${injection.chatRunnerVersion || "-"} replaced=${Boolean(injection.runnerReplaced)} previous=${injection.previousVersion || "-"}`,
  );
  if (!injection.ok || injection.staleRuntime) {
    const message = injection.error || "Page chat runner version is stale. Reload the extension or retry runner injection.";
    const failedStatus = await patchBatchStatus(
      {
        running: false,
        stopRequested: false,
        phase: "failed",
        message,
        error: message,
        runtimeFingerprint: buildRuntimeFingerprint({
          chatRunnerVersion: injection.chatRunnerVersion || "",
          runToken: injection.runToken || "",
          runnerReplaced: Boolean(injection.runnerReplaced),
          staleRuntime: true,
        }),
      },
      message,
    );
    return { ok: false, error: message, status: failedStatus };
  }
  const commandResult = await safeTabsSendMessage(tab.id, {
    type: "boss_batch_command",
    command: "start",
    settings,
    mode: normalizedMode,
  });
  if (!commandResult.ok) {
    const failedStatus = await patchBatchStatus(
      {
        running: false,
        stopRequested: false,
        phase: "failed",
        message: commandResult.error || "启动页面批量任务失败。",
        error: commandResult.error || "start failed",
        runtimeLogs: [`${formatClock(new Date())} background start failed: ${commandResult.error || "unknown error"}`],
      },
      commandResult.error || "启动页面批量任务失败",
    );
    return { ...commandResult, status: failedStatus };
  }

  await patchBatchStatus({
    runtimeFingerprint: buildRuntimeFingerprint({
      chatRunnerVersion: commandResult.runnerVersion || injection.chatRunnerVersion || "",
      runToken: commandResult.runToken || "",
      runnerReplaced: Boolean(injection.runnerReplaced),
      staleRuntime: isRunnerVersionStale(commandResult.runnerVersion || injection.chatRunnerVersion || ""),
    }),
  });
  return { ok: true, status: await getBatchStatus() };
}

async function startBatchLegacyUnused(tabId, settings, mode) {
  if (!Number.isInteger(Number(tabId))) {
    return { ok: false, error: "缺少有效的聊天标签页。" };
  }

  const tab = await chrome.tabs.get(Number(tabId));
  if (!String(tab.url || "").includes("zhipin.com")) {
    return { ok: false, error: "当前标签页不是 Boss 页面。" };
  }

  const current = await getBatchStatus();
  if (current.running && current.tabId && current.tabId !== tab.id) {
    await stopBatch(current.tabId, "已切换到新的批量任务");
    await delay(250);
  }

  const normalizedModeFinal = normalizeBatchMode(mode);
  const normalizedMode = normalizedModeFinal;
  const startMessage = normalizedMode === "download_only" ? "Batch download started." : "Batch request started.";
  const startEvent = normalizedMode === "download_only" ? "批量下载任务已启动" : "批量求简历任务已启动";
  const startMessageFinal = ""; /*
    normalizedMode === "download_only" ? "鎵归噺涓嬭浇浠诲姟宸插惎鍔紝绛夊緟椤甸潰鎵ц銆? : "鎵归噺姹傜畝鍘嗕换鍔″凡鍚姩锛岀瓑寰呴〉闈㈡墽琛屻€?;
  */ const startEventFinal = ""; /*
    normalizedMode === "download_only" ? "鎵归噺涓嬭浇浠诲姟宸插惎鍔? : "鎵归噺姹傜畝鍘嗕换鍔″凡鍚姩";
  */ await saveBatchStatus({
    ...DEFAULT_BATCH_STATUS,
    running: true,
    phase: "starting",
    mode: normalizedMode,
    tabId: tab.id,
    windowId: tab.windowId,
    sourceUrl: tab.url || "",
    startedAt: nowIso(),
    updatedAt: nowIso(),
    message: startMessage,
    runtimeLogs: [`${formatClock(new Date())} background start: ${normalizedMode}`],
    recentEvents: mergeRecentEvents([], startEvent),
  });

  await ensureChatRunnerInjected(tab.id);
  const commandResult = await safeTabsSendMessage(tab.id, {
    type: "boss_batch_command",
    command: "start",
    settings,
    mode,
  });
  if (!commandResult.ok) {
    const failedStatus = await patchBatchStatus(
      {
        running: false,
        stopRequested: false,
        phase: "failed",
        message: commandResult.error || "start failed",
        error: commandResult.error || "start failed",
        runtimeLogs: [`${formatClock(new Date())} background start failed: ${commandResult.error || "unknown error"}`],
      },
      commandResult.error || "start failed",
    );
    return { ...commandResult, status: failedStatus };
  }

  return { ok: true, status: await getBatchStatus() };

  const normalizedModeAfterCommand = normalizedMode;
  const startMessageAfterCommand =
    normalizedMode === "download_only" ? "批量下载任务已启动，等待页面执行。" : "批量求简历任务已启动，等待页面执行。";
  const startEventAfterCommand =
    normalizedMode === "download_only" ? "批量下载任务已启动" : "批量求简历任务已启动";

  const statusFinal = await saveBatchStatus({
    ...DEFAULT_BATCH_STATUS,
    running: true,
    phase: "starting",
    mode: normalizedMode,
    tabId: tab.id,
    windowId: tab.windowId,
    sourceUrl: tab.url || "",
    startedAt: nowIso(),
    updatedAt: nowIso(),
    message: startMessage,
    runtimeLogs: [`${formatClock(new Date())} background start: ${normalizedMode}`],
    recentEvents: mergeRecentEvents([], startEvent),
  });
  return { ok: true, status: statusFinal };
}

async function stopBatch(tabId, reason = "") {
  const current = await getBatchStatus();
  const targetTabId = Number.isInteger(Number(tabId)) ? Number(tabId) : current.tabId;
  if (!targetTabId) {
    const status = await patchBatchStatus(
      {
        running: false,
        stopRequested: false,
        phase: "stopped",
        message: reason || "没有正在运行的批量任务。",
      },
      reason || "批量任务已停止",
    );
    return { ok: true, status };
  }
  stoppedBatchTabs.set(Number(targetTabId), Date.now());
  await appendBatchRuntimeLog(`background stop requested: tab=${targetTabId} reason=${reason || "manual stop"}`);

  await safeTabsSendMessage(targetTabId, {
    type: "boss_batch_command",
    command: "stop",
    reason: reason || "用户手动停止",
  });
  await forceStopBatchRunner(targetTabId, reason || "用户手动停止");

  const status = await patchBatchStatus(
    {
      running: false,
      stopRequested: false,
      phase: "stopped",
      runtimeLogs: [`${formatClock(new Date())} background stop requested: ${reason || "manual stop"}`, ...(current.runtimeLogs || [])].slice(0, 120),
      message: reason || "批量任务已强制停止。",
    },
    reason || "批量任务已停止",
  );
  return { ok: true, status };
}

async function forceStopBatchRunner(tabId, reason) {
  if (!Number.isInteger(Number(tabId))) {
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: Number(tabId), allFrames: true },
      func: (stopReason) => {
        const runner = globalThis.__bossLocalChatBatchRunner;
        if (runner?.state) {
          runner.state.stopRequested = true;
          runner.state.running = false;
          runner.state.runToken = "";
          if (Array.isArray(runner.state.runtimeLogs)) {
            runner.state.runtimeLogs.unshift(`${new Date().toLocaleTimeString()} forced stop: ${stopReason || "manual stop"}`);
            runner.state.runtimeLogs = runner.state.runtimeLogs.slice(0, 120);
          }
          runner.state.lastMessage = stopReason || "已收到停止请求。";
        }
      },
      args: [reason || "已收到停止请求。"],
    });
  } catch (_error) {
    // Ignore executeScript stop failures and keep the message-based stop path.
  }
}

async function handleBatchProgress(payload, sender) {
  if (shouldIgnoreStoppedBatchMessage(payload, sender, false)) {
    return;
  }
  const current = await getBatchStatus();
  await patchBatchStatus(
    {
      running: payload.running ?? true,
      stopRequested: Boolean(payload.stopRequested),
      phase: payload.phase || current.phase,
      mode: normalizeBatchMode(payload.mode || current.mode),
      tabId: sender?.tab?.id ?? current.tabId,
      windowId: sender?.tab?.windowId ?? current.windowId,
      sourceUrl: sender?.tab?.url || current.sourceUrl,
      currentSession: payload.currentSession || current.currentSession,
      message: payload.message || current.message,
      scanMessage: payload.scanMessage ?? current.scanMessage,
      scanDebug: payload.scanDebug ?? current.scanDebug,
      error: payload.error || "",
      stats: payload.stats || current.stats,
      runtimeFingerprint: buildRuntimeFingerprint({
        chatRunnerVersion: payload.runnerVersion || current.runtimeFingerprint.chatRunnerVersion || "",
        runToken: payload.runToken ?? current.runtimeFingerprint.runToken ?? "",
        runnerReplaced: Boolean(current.runtimeFingerprint.runnerReplaced),
        staleRuntime: isRunnerVersionStale(payload.runnerVersion || current.runtimeFingerprint.chatRunnerVersion || ""),
      }),
      runtimeLogs: mergeRuntimeLogSources(payload.runtimeLogs, current.runtimeLogs),
    },
    payload.eventText || "",
  );
}

async function handleBatchFinished(payload, sender) {
  if (shouldIgnoreStoppedBatchMessage(payload, sender, true)) {
    return;
  }
  const current = await getBatchStatus();
  await patchBatchStatus(
    {
      running: false,
      stopRequested: false,
      phase: payload.phase || "completed",
      mode: normalizeBatchMode(payload.mode || ""),
      tabId: sender?.tab?.id ?? null,
      windowId: sender?.tab?.windowId ?? null,
      sourceUrl: sender?.tab?.url || "",
      currentSession: payload.currentSession || "",
      message: payload.message || "批量任务已完成。",
      scanMessage: payload.scanMessage ?? current.scanMessage,
      scanDebug: payload.scanDebug ?? current.scanDebug,
      error: payload.error || "",
      stats: payload.stats || undefined,
      runtimeFingerprint: buildRuntimeFingerprint({
        chatRunnerVersion: payload.runnerVersion || current.runtimeFingerprint.chatRunnerVersion || "",
        runToken: payload.runToken ?? "",
        runnerReplaced: Boolean(current.runtimeFingerprint.runnerReplaced),
        staleRuntime: isRunnerVersionStale(payload.runnerVersion || current.runtimeFingerprint.chatRunnerVersion || ""),
      }),
      runtimeLogs: mergeRuntimeLogSources(payload.runtimeLogs, current.runtimeLogs),
    },
    payload.eventText || payload.message || "",
  );
}

function shouldIgnoreStoppedBatchMessage(payload, sender, isFinished) {
  const tabId = Number(sender?.tab?.id);
  if (!Number.isInteger(tabId)) {
    return false;
  }
  const stoppedAt = stoppedBatchTabs.get(tabId);
  if (!stoppedAt || Date.now() - stoppedAt > STOP_GUARD_MS) {
    stoppedBatchTabs.delete(tabId);
    return false;
  }
  if (payload?.phase === "stopped") {
    return false;
  }
  if (isFinished) {
    return true;
  }
  return true;
}

async function isBatchStopped() {
  const status = await getBatchStatus();
  return !status.running || status.stopRequested || status.phase === "stopped";
}

async function appendBatchRuntimeLog(message) {
  const text = String(message || "").trim();
  if (!text) {
    return;
  }
  const current = await getBatchStatus();
  const line = `${formatClock(new Date())} ${text}`;
  await patchBatchStatus({
    runtimeLogs: [line, ...(Array.isArray(current.runtimeLogs) ? current.runtimeLogs : [])].slice(0, 120),
  });
}

async function downloadResume(payload) {
  const url = String(payload.url || "").trim();
  const fileName = String(payload.fileName || "").trim();
  await appendBatchRuntimeLog(`background download request: ${fileName || "-"} | ${url.slice(0, 180)}`);
  let finalUrl = url;
  if (!payload.trustedPdf && shouldVerifyPdfBeforeDownload(url, fileName)) {
    const probed = await probePdfCandidateUrl(url);
    if (!probed.ok) {
      await appendBatchRuntimeLog(`background download rejected: url is not pdf after probe | ${url.slice(0, 180)}`);
      return {
        ok: false,
        error: "当前解析到的是预览页或 HTML 页面，不是 PDF 文件。请通过预览页下载按钮触发真实 PDF 下载。",
        url,
      };
    }
    finalUrl = probed.url || url;
    await appendBatchRuntimeLog(`background download verified pdf: ${finalUrl.slice(0, 180)}`);
  } else if (!payload.trustedPdf && !isValidResumeDownload(url, fileName)) {
    await appendBatchRuntimeLog(`background download rejected: invalid pdf url | ${url.slice(0, 180)}`);
    return {
      ok: false,
      error: "当前解析到的链接不是可下载的 PDF 简历。",
      url,
    };
  }

  let downloadId;
  try {
    downloadId = await chrome.downloads.download({
      url: finalUrl,
      filename: fileName || buildFallbackFileName(),
      conflictAction: "uniquify",
      saveAs: false,
    });
  } catch (error) {
    await appendBatchRuntimeLog(`background chrome.downloads.download failed: ${error?.message || String(error)}`);
    return {
      ok: false,
      error: error?.message || String(error),
      url,
    };
  }
  await appendBatchRuntimeLog(`background chrome.downloads.download ok: id=${downloadId}`);

  return {
    ok: true,
    downloadId,
    fileName: fileName || buildFallbackFileName(),
    url: finalUrl,
  };
}

async function waitForRecentDownload(payload) {
  const sinceMs = Number(payload.sinceMs || 0);
  const fileNameHint = String(payload.fileNameHint || "").toLowerCase();
  const timeoutMs = Math.max(Number(payload.timeoutMs || 2200), 500);
  const abortOnBatchStop = Boolean(payload.abortOnBatchStop);
  const startedAt = Date.now();

  while (Date.now() - startedAt <= timeoutMs) {
    if (abortOnBatchStop) {
      const status = await getBatchStatus();
      if (!status.running || status.stopRequested || status.phase === "stopped") {
        return { ok: false, found: false, error: "download wait aborted by stop request" };
      }
    }
    const items = await chrome.downloads.search({
      limit: 10,
      orderBy: ["-startTime"],
    });
    const matched = items.find((item) => isMatchingRecentDownload(item, sinceMs, fileNameHint));
    if (matched) {
      return {
        ok: true,
        found: true,
        downloadId: matched.id,
        filename: matched.filename || "",
        mime: matched.mime || "",
        url: matched.finalUrl || matched.url || "",
        state: matched.state || "",
      };
    }
    await delay(300);
  }

  return { ok: true, found: false };
}

async function clickPreviewDownloadButtonInFrames(payload, sender) {
  const targetTab = Number.isInteger(Number(payload.tabId))
    ? await chrome.tabs.get(Number(payload.tabId))
    : sender?.tab || null;
  if (!targetTab?.id) {
    return { ok: false, clicked: false, error: "无法确定附件预览所在标签页。" };
  }
  if (payload.abortOnBatchStop && (await isBatchStopped())) {
    return { ok: false, clicked: false, error: "preview download click aborted by stop request" };
  }

  let execution = [];
  try {
    execution = await chrome.scripting.executeScript({
      target: { tabId: targetTab.id, allFrames: true },
      func: clickPreviewDownloadButtonInFrame,
    });
  } catch (error) {
    await appendBatchRuntimeLog(`preview frame download execute failed: ${error?.message || String(error)}`);
    return { ok: false, clicked: false, error: error?.message || String(error) };
  }

  const frameResults = execution.map((item) => item?.result).filter(Boolean);
  const clicked = frameResults.find((item) => item.clicked);
  if (clicked) {
    if (/\bpicked=span\b/i.test(String(clicked.debug || ""))) {
      await patchBatchStatus({
        runtimeFingerprint: buildRuntimeFingerprint({
          staleRuntime: true,
        }),
      });
      await appendBatchRuntimeLog(
        `stale runtime suspected: worker=${SERVICE_WORKER_DOWNLOAD_CLICK_REVISION} received text-span preview click shape | ${clicked.debug || "-"}`,
      );
    }
    await appendBatchRuntimeLog(`preview frame download click ok: ${clicked.frameUrl || "-"} | ${clicked.debug || "-"}`);
    return { ok: true, clicked: true, frameUrl: clicked.frameUrl || "", debug: clicked.debug || "" };
  }

  const debug = frameResults
    .filter((item) => item.previewFrame || item.debug)
    .slice(0, 4)
    .map((item) => `${item.frameUrl || "-"} ${item.debug || item.reason || "no-candidate"}`)
    .join(" | ");
  await appendBatchRuntimeLog(`preview frame download click miss: ${debug || "no preview frame result"}`);
  return { ok: true, clicked: false, debug: debug || "未在预览 frame 中识别到下载按钮。" };
}

function clickPreviewDownloadButtonInFrame() {
  const frameUrl = location.href;
  const urlLooksPreview = /preview4boss|bzl-office|office\.weizhipin/i.test(frameUrl);
  const appLooksPreview = Boolean(document.querySelector("#app canvas, #app iframe, #app [class*='toolbar'], [class*='office']"));
  if (!urlLooksPreview && !appLooksPreview) {
    return { ok: true, clicked: false, previewFrame: false, frameUrl, reason: "not-preview-frame" };
  }

  const visible = (node) => {
    if (!(node instanceof HTMLElement || node instanceof SVGElement)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 3 && rect.height > 3 && style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  };
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const hintFor = (node) => {
    const values = [
      node.innerText || node.textContent || "",
      node.getAttribute?.("title") || "",
      node.getAttribute?.("aria-label") || "",
      node.getAttribute?.("data-title") || "",
      node.getAttribute?.("data-testid") || "",
      node.getAttribute?.("class") || "",
    ];
    return normalize(values.join(" ")).toLowerCase();
  };
  const isCloseLike = (hint) => /close|cancel|back|关闭|返回|取消|popup__close|modal-close/.test(hint);
  const isDownloadLike = (hint) => /download|save|export|下载|保存/.test(hint);
  const describe = (item) => {
    const tag = item.target.tagName.toLowerCase();
    const rect = item.rect;
    const hint = normalize(item.hint).slice(0, 36);
    return `${tag} [${Math.round(rect.left)},${Math.round(rect.top)} ${Math.round(rect.width)}x${Math.round(rect.height)}]${hint ? ` ${hint}` : ""}`;
  };
  const semanticSelectors = [
    "button.bzl-office-toolbar-button[name='download-pdf']",
    "button[name='download-pdf']",
    "button.bzl-office-toolbar-button[name='download-image']",
    "button[name='download-image']",
    "button.bzl-office-toolbar-button[name*='download']",
    "button[name*='download']",
    "[class*='toolbar'] button[data-title]",
    "[class*='toolbar'] button[title]",
    "[class*='toolbar'] button[aria-label]",
    "[class*='toolbar'] [role='button'][data-title]",
    "[class*='toolbar'] [role='button'][aria-label]",
    "a[download]",
  ];
  const candidateMap = new Map();
  semanticSelectors.forEach((selector, selectorPriority) => {
    Array.from(document.querySelectorAll(selector)).forEach((target) => {
      if (!(target instanceof HTMLElement) || !visible(target) || target.matches(":disabled,[aria-disabled='true']") || candidateMap.has(target)) {
        return;
      }
      const hint = hintFor(target);
      if (isCloseLike(hint)) {
        return;
      }
      const explicitDownloadName = /download-(pdf|image)/i.test(target.getAttribute("name") || "");
      if (!explicitDownloadName && !isDownloadLike(hint) && !target.matches("a[download]")) {
        return;
      }
      candidateMap.set(target, {
        target,
        rect: target.getBoundingClientRect(),
        hint,
        selectorPriority,
        explicitDownloadName,
        toolbarControl: Boolean(target.closest(".bzl-office-pdf-toolbar, [class*='toolbar']")),
      });
    });
  });
  const candidates = Array.from(candidateMap.values()).sort((left, right) => {
    if (left.explicitDownloadName !== right.explicitDownloadName) {
      return Number(right.explicitDownloadName) - Number(left.explicitDownloadName);
    }
    if (left.toolbarControl !== right.toolbarControl) {
      return Number(right.toolbarControl) - Number(left.toolbarControl);
    }
    return left.selectorPriority - right.selectorPriority;
  });
  const selected = candidates[0];
  if (!selected) {
    const visibleControls = Array.from(document.querySelectorAll("button, a, [role='button']"))
      .filter((node) => visible(node))
      .slice(0, 6)
      .map((node) => normalize(`${node.tagName.toLowerCase()} ${hintFor(node)}`).slice(0, 48))
      .join(" || ");
    return {
      ok: true,
      clicked: false,
      previewFrame: true,
      frameUrl,
      debug: `semantic download button missing${visibleControls ? ` controls=${visibleControls}` : ""}`,
    };
  }

  selected.target.scrollIntoView({ block: "nearest", inline: "nearest" });
  selected.target.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, pointerType: "mouse" }));
  selected.target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
  selected.target.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, cancelable: true, pointerType: "mouse" }));
  selected.target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, button: 0 }));
  selected.target.click();
  return {
    ok: true,
    clicked: true,
    previewFrame: true,
    frameUrl,
    debug: `picked=${describe(selected)} candidates=${candidates.slice(0, 4).map(describe).join(" || ")}`,
  };
}

async function resolveActivePdfUrl(payload, sender) {
  const windowId = payload.windowId ?? sender?.tab?.windowId;
  let targetTab = null;

  if (Number.isInteger(Number(payload.tabId))) {
    targetTab = await chrome.tabs.get(Number(payload.tabId));
  } else if (Number.isInteger(Number(windowId))) {
    const [activeTab] = await chrome.tabs.query({ active: true, windowId: Number(windowId) });
    targetTab = activeTab || null;
  }

  if (!targetTab && sender?.tab?.id) {
    targetTab = sender.tab;
  }

  if (!targetTab?.id) {
    return { ok: false, error: "无法确定要解析 PDF 的标签页。" };
  }

  let collected = { urls: [], summary: "" };
  let resolvedUrl = "";
  let verifiedByFetch = false;
  for (let attempt = 0; attempt < 3 && !resolvedUrl; attempt += 1) {
    if (payload.abortOnBatchStop && (await isBatchStopped())) {
      if (payload.closePreviewTab && sender?.tab?.id && targetTab.id !== sender.tab.id) {
        await chrome.tabs.remove(targetTab.id).catch(() => undefined);
        await chrome.tabs.update(sender.tab.id, { active: true }).catch(() => undefined);
      }
      return { ok: false, error: "resolve aborted by stop request" };
    }
    collected = await collectPdfCandidatesFromTab(targetTab.id);
    resolvedUrl = pickBestPdfUrl(collected.urls || []);
    if (!resolvedUrl) {
      const probed = await probePdfCandidateUrls(collected.urls || []);
      if (probed.url) {
        resolvedUrl = probed.url;
        verifiedByFetch = Boolean(probed.verifiedByFetch);
        collected.summary = [collected.summary, probed.summary || ""].filter(Boolean).join(" || ");
      }
    }
    if (!resolvedUrl && attempt < 2) {
      await delay(800);
    }
  }

  if (payload.closePreviewTab && sender?.tab?.id && targetTab.id !== sender.tab.id) {
    await chrome.tabs.remove(targetTab.id).catch(() => undefined);
    await chrome.tabs.update(sender.tab.id, { active: true }).catch(() => undefined);
  }

  return {
    ok: Boolean(resolvedUrl),
    url: resolvedUrl,
    verifiedByFetch,
    urls: collected.urls,
    summary: collected.summary,
    inspectedTabId: targetTab.id,
    inspectedTabUrl: targetTab.url || "",
  };
}

async function trustedClick(payload, sender) {
  const tabId = sender?.tab?.id;
  const x = Number(payload.x);
  const y = Number(payload.y);
  if (!Number.isInteger(Number(tabId)) || !Number.isFinite(x) || !Number.isFinite(y)) {
    return { ok: false, error: "invalid trusted click target" };
  }

  const debuggee = { tabId: Number(tabId) };
  let attached = false;
  try {
    await chrome.debugger.attach(debuggee, "1.3");
    attached = true;
  } catch (error) {
    const message = error?.message || String(error);
    if (!message.includes("Another debugger is already attached")) {
      return { ok: false, error: message };
    }
  }

  try {
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x,
      y,
      button: "none",
    });
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mousePressed",
      x,
      y,
      button: "left",
      clickCount: 1,
    });
    await delay(60);
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mouseReleased",
      x,
      y,
      button: "left",
      clickCount: 1,
    });
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error?.message || String(error) };
  } finally {
    if (attached) {
      await chrome.debugger.detach(debuggee).catch(() => undefined);
    }
  }
}

async function collectPdfCandidatesFromTab(tabId) {
  const execution = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => {
      const urls = new Set();
      const URL_TOKEN_REGEX = /https?:\/\/[^\s"'<>]+|\/[^\s"'<>]+/g;
      const addCandidate = (value) => {
        const text = String(value || "").trim();
        if (!text || text.startsWith("javascript:") || text.startsWith("#")) {
          return;
        }
        try {
          const absolute = new URL(text, location.href).toString();
          urls.add(absolute);
          for (const key of ["src", "file", "url"]) {
            const nested = new URL(absolute).searchParams.get(key);
            if (nested) {
              urls.add(nested);
            }
          }
        } catch (_error) {
          // Ignore invalid URLs.
        }
      };
      const addTextCandidates = (text) => {
        const source = String(text || "");
        const matches = source.match(URL_TOKEN_REGEX) || [];
        matches.forEach((value) => addCandidate(value));
      };

      addCandidate(location.href);
      document.querySelectorAll("a[href], iframe[src], embed[src], object[data], img[src], source[src], [data-url], [data-src], [data-download]").forEach((node) => {
        if (node instanceof HTMLAnchorElement) {
          addCandidate(node.href);
        } else if (
          node instanceof HTMLIFrameElement ||
          node instanceof HTMLEmbedElement ||
          node instanceof HTMLImageElement
        ) {
          addCandidate(node.src);
        } else if (node instanceof HTMLObjectElement) {
          addCandidate(node.data);
        } else if (node instanceof HTMLElement) {
          addCandidate(node.getAttribute("data-url"));
          addCandidate(node.getAttribute("data-src"));
          addCandidate(node.getAttribute("data-download"));
        }
      });
      document.querySelectorAll("script").forEach((node) => addTextCandidates(node.textContent || ""));
      document.querySelectorAll("style").forEach((node) => addTextCandidates(node.textContent || ""));
      addTextCandidates(document.documentElement?.innerHTML || "");
      try {
        performance.getEntriesByType("resource").slice(-200).forEach((entry) => addCandidate(entry?.name || ""));
      } catch (_error) {
        // Ignore performance entry access failures.
      }

      return {
        frameUrl: location.href,
        title: document.title,
        contentType: document.contentType || "",
        urls: Array.from(urls),
      };
    },
  });

  const urls = new Set();
  const summaries = [];
  for (const item of execution || []) {
    const result = item?.result;
    if (!result) {
      continue;
    }
    for (const candidate of result.urls || []) {
      urls.add(candidate);
    }
    summaries.push(
      [
        result.frameUrl || "",
        result.title || "",
        result.contentType || "",
        `urls=${(result.urls || []).length}`,
      ]
        .filter(Boolean)
        .join(" | "),
    );
  }

  return {
    urls: Array.from(urls),
    summary: summaries.join(" || "),
  };
}

async function ensureChatRunnerInjected(tabId) {
  const [before] = await chrome.scripting.executeScript({
    target: { tabId },
    args: [EXPECTED_CHAT_RUNNER_VERSION],
    func: (expectedVersion) => {
      const current = globalThis.__bossLocalChatBatchRunner;
      const previousVersion = String(current?.version || "");
      const shouldReplace = Boolean(current) && previousVersion !== expectedVersion;
      if (shouldReplace) {
        try {
          current?.dispose?.("version-mismatch");
        } catch (_error) {}
        if (current?.state) {
          current.state.stopRequested = true;
          current.state.running = false;
          current.state.runToken = "";
        }
        delete globalThis.__bossLocalChatBatchRunner;
      }
      return {
        expectedVersion,
        previousVersion,
        runnerReplaced: shouldReplace,
      };
    },
  });
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["chat_batch_runner.js"],
  });
  const [after] = await chrome.scripting.executeScript({
    target: { tabId },
    args: [EXPECTED_CHAT_RUNNER_VERSION],
    func: (expectedVersion) => {
      const runner = globalThis.__bossLocalChatBatchRunner;
      return {
        expectedVersion,
        chatRunnerVersion: String(runner?.version || ""),
        runToken: String(runner?.state?.runToken || ""),
      };
    },
  });
  const beforeResult = before?.result || {};
  const afterResult = after?.result || {};
  const chatRunnerVersion = afterResult.chatRunnerVersion || "";
  return {
    ok: Boolean(chatRunnerVersion),
    error: chatRunnerVersion ? "" : "Page chat runner injection did not expose a runtime version.",
    expectedVersion: afterResult.expectedVersion || beforeResult.expectedVersion || EXPECTED_CHAT_RUNNER_VERSION,
    previousVersion: beforeResult.previousVersion || "",
    chatRunnerVersion,
    runToken: afterResult.runToken || "",
    runnerReplaced: Boolean(beforeResult.runnerReplaced),
    staleRuntime: isRunnerVersionStale(chatRunnerVersion),
  };
}

async function safeTabsSendMessage(tabId, message) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (error) {
    return {
      ok: false,
      error: error?.message || String(error),
    };
  }
}

async function handleBatchTabRemoved(tabId) {
  const current = await getBatchStatus();
  if (current.running && current.tabId === tabId) {
    await patchBatchStatus(
      {
        running: false,
        stopRequested: false,
        phase: "stopped",
        tabId: null,
        windowId: null,
        currentSession: "",
        message: "批量任务所在标签页已关闭。",
      },
      "批量任务所在标签页已关闭",
    );
  }
}

function mergeBatchStatus(value) {
  return {
    ...DEFAULT_BATCH_STATUS,
    ...(value || {}),
    mode: normalizeBatchMode(value?.mode || ""),
    stats: {
      ...DEFAULT_BATCH_STATUS.stats,
      ...((value && value.stats) || {}),
    },
    runtimeFingerprint: buildRuntimeFingerprint(value?.runtimeFingerprint || {}),
    runtimeLogs: Array.isArray(value?.runtimeLogs) ? value.runtimeLogs.slice(0, 120) : [],
    recentEvents: Array.isArray(value?.recentEvents) ? value.recentEvents.slice(0, 8) : [],
  };
}

function buildRuntimeFingerprint(value = {}) {
  return {
    ...DEFAULT_BATCH_STATUS.runtimeFingerprint,
    ...(value || {}),
    manifestVersion: EXTENSION_VERSION,
    serviceWorkerRevision: SERVICE_WORKER_DOWNLOAD_CLICK_REVISION,
  };
}

function isRunnerVersionStale(version) {
  return Boolean(version) && version !== EXPECTED_CHAT_RUNNER_VERSION;
}

function normalizeBatchMode(value) {
  if (!value) {
    return "";
  }
  return value === "download_only" ? "download_only" : "request_resume";
}

function mergeRecentEvents(currentEvents, nextText) {
  const events = Array.isArray(currentEvents) ? currentEvents.slice(0, 7) : [];
  if (!nextText) {
    return events;
  }
  const stamped = `${formatClock(new Date())} ${nextText}`;
  if (events[0] === stamped) {
    return events;
  }
  return [stamped, ...events].slice(0, 8);
}

function mergeRuntimeLogs(currentLogs, nextLogs) {
  if (!Array.isArray(nextLogs)) {
    return Array.isArray(currentLogs) ? currentLogs.slice(0, 120) : [];
  }
  return nextLogs.map((line) => String(line || "").trim()).filter(Boolean).slice(0, 120);
}

function mergeRuntimeLogSources(primaryLogs, secondaryLogs) {
  const merged = [];
  const seen = new Set();
  for (const source of [primaryLogs, secondaryLogs]) {
    for (const line of Array.isArray(source) ? source : []) {
      const text = String(line || "").trim();
      if (!text || seen.has(text)) {
        continue;
      }
      seen.add(text);
      merged.push(text);
      if (merged.length >= 120) {
        return merged;
      }
    }
  }
  return merged;
}

function pickBestPdfUrl(urls) {
  const normalized = Array.isArray(urls)
    ? urls.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  for (const candidate of normalized) {
    if (isValidResumeDownload(candidate, "")) {
      return candidate;
    }
    const nested = extractNestedResumeUrl(candidate);
    if (nested) {
      return nested;
    }
  }
  return "";
}

async function probePdfCandidateUrls(urls) {
  const candidates = rankPotentialPdfUrls(urls).slice(0, 10);
  for (const candidate of candidates) {
    const probed = await probePdfCandidateUrl(candidate);
    if (probed.ok) {
      return {
        url: probed.url,
        verifiedByFetch: true,
        summary: `通过网络探测确认 PDF：${candidate}`,
      };
    }
  }
  return { url: "", verifiedByFetch: false, summary: "" };
}

function isValidResumeDownload(url, fileName) {
  const lowerUrl = String(url || "").toLowerCase();
  const lowerName = String(fileName || "").toLowerCase();
  if (isPageLocalPdfUrl(lowerUrl)) {
    return true;
  }
  if (isKnownHtmlPreviewUrl(lowerUrl)) {
    return false;
  }
  const looksImage = /\.(png|jpg|jpeg|gif|webp|svg)(?:$|[?#])/i.test(lowerUrl);
  if (!lowerUrl || looksImage) {
    return false;
  }

  if (hasDirectPdfSignal(lowerUrl, lowerName)) {
    return true;
  }

  return Boolean(extractNestedResumeUrl(url));
}

function extractNestedResumeUrl(url) {
  const visited = new Set();
  let currentUrl = String(url || "").trim();
  for (let depth = 0; depth < 3 && currentUrl && !visited.has(currentUrl); depth += 1) {
    visited.add(currentUrl);
    let parsed;
    try {
      parsed = new URL(currentUrl);
    } catch (_error) {
      return "";
    }

    let advanced = false;
    for (const key of ["src", "file", "url"]) {
      const nestedValue = parsed.searchParams.get(key);
      if (!nestedValue) {
        continue;
      }
      const resolved = safeResolveUrl(nestedValue, parsed.toString());
      if (!resolved) {
        continue;
      }
      const lowerResolved = resolved.toLowerCase();
      if (hasDirectPdfSignal(lowerResolved, lowerResolved)) {
        return resolved;
      }
      currentUrl = resolved;
      advanced = true;
      break;
    }

    if (!advanced) {
      return "";
    }
  }

  return "";
}

function hasDirectPdfSignal(url, fileName) {
  if (isPageLocalPdfUrl(url)) {
    return true;
  }
  if (/\.pdf(?:$|[?#])/i.test(String(url || ""))) {
    return true;
  }
  if (looksLikeDownloadEndpoint(url) && String(fileName || "").endsWith(".pdf")) {
    return true;
  }
  return false;
}

function looksLikeDownloadEndpoint(url) {
  return /\/file\/|download|attachment|resume|preview|export/i.test(String(url || ""));
}

function isKnownHtmlPreviewUrl(url) {
  return /\/wflow\/zpgeek\/download\/preview4boss\//i.test(String(url || "")) || /bzl-office|office\.weizhipin/i.test(String(url || ""));
}

function shouldVerifyPdfBeforeDownload(url, fileName) {
  const lowerUrl = String(url || "").toLowerCase();
  const lowerName = String(fileName || "").toLowerCase();
  if (!lowerUrl || isPageLocalPdfUrl(lowerUrl) || /\.pdf(?:$|[?#])/i.test(lowerUrl)) {
    return false;
  }
  return isKnownHtmlPreviewUrl(lowerUrl) || (looksLikeDownloadEndpoint(lowerUrl) && lowerName.endsWith(".pdf"));
}

function isPageLocalPdfUrl(url) {
  const text = String(url || "").toLowerCase();
  return text.startsWith("blob:") || text.startsWith("data:application/pdf");
}

function rankPotentialPdfUrls(urls) {
  const normalized = Array.isArray(urls)
    ? Array.from(new Set(urls.map((value) => String(value || "").trim()).filter(Boolean)))
    : [];
  return normalized
    .filter((value) => !/\.(png|jpg|jpeg|gif|webp|svg)(?:$|[?#])/i.test(value))
    .sort((left, right) => scorePotentialPdfUrl(right) - scorePotentialPdfUrl(left));
}

function scorePotentialPdfUrl(url) {
  const text = String(url || "").toLowerCase();
  let score = 0;
  if (/\.pdf(?:$|[?#])/.test(text)) {
    score += 10;
  }
  if (/download|attachment|resume|preview|export|file/.test(text)) {
    score += 6;
  }
  if (/token=|sign=|auth=|expires=/.test(text)) {
    score += 2;
  }
  return score;
}

async function probePdfCandidateUrl(url) {
  const candidate = String(url || "").trim();
  if (!candidate) {
    return { ok: false, url: "" };
  }
  try {
    const headResponse = await fetch(candidate, {
      method: "HEAD",
      redirect: "follow",
      credentials: "include",
      cache: "no-store",
    });
    const contentType = String(headResponse.headers.get("content-type") || "").toLowerCase();
    if (headResponse.ok && contentType.includes("pdf")) {
      return { ok: true, url: headResponse.url || candidate };
    }
  } catch (_error) {
    // Ignore HEAD probe failure and fall back to range GET.
  }

  try {
    const getResponse = await fetch(candidate, {
      method: "GET",
      redirect: "follow",
      credentials: "include",
      cache: "no-store",
      headers: {
        Range: "bytes=0-0",
      },
    });
    const contentType = String(getResponse.headers.get("content-type") || "").toLowerCase();
    if (getResponse.ok && contentType.includes("pdf")) {
      try {
        getResponse.body?.cancel?.();
      } catch (_error) {
        // Ignore stream cancel failures.
      }
      return { ok: true, url: getResponse.url || candidate };
    }
  } catch (_error) {
    return { ok: false, url: "" };
  }

  return { ok: false, url: "" };
}

function safeResolveUrl(value, baseUrl) {
  try {
    return new URL(String(value || ""), baseUrl).toString();
  } catch (_error) {
    return "";
  }
}

function isMatchingRecentDownload(item, sinceMs, fileNameHint) {
  const started = item?.startTime ? Date.parse(item.startTime) : 0;
  if (sinceMs && started && started < sinceMs - 1000) {
    return false;
  }
  if (!fileNameHint) {
    return true;
  }
  const haystack = [item?.filename || "", item?.url || "", item?.finalUrl || ""].join(" ").toLowerCase();
  const normalizedHint = fileNameHint.replace(/\.pdf$/i, "");
  return haystack.includes(fileNameHint) || (normalizedHint && haystack.includes(normalizedHint));
}

function buildFallbackFileName() {
  return `BossResumes/resume_${timestampToken(new Date())}.pdf`;
}

function timestampToken(date) {
  return [
    date.getFullYear(),
    pad2(date.getMonth() + 1),
    pad2(date.getDate()),
    "_",
    pad2(date.getHours()),
    pad2(date.getMinutes()),
    pad2(date.getSeconds()),
  ].join("");
}

function nowIso() {
  return new Date().toISOString();
}

function formatClock(date) {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
}

function pad2(value) {
  return String(value).padStart(2, "0");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
