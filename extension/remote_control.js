const REMOTE_CONTROL_DEFAULTS = {
  apiBase: "http://127.0.0.1:17863",
  apiToken: "",
  jobTitle: "Boss 推荐牛人",
  jobProfileId: null,
  recruitmentTaskId: null,
  scrollMode: "hold_end",
  scrollStep: 900,
  scrollWaitMs: 30,
  maxScrollCount: 80,
  noNewStopRounds: 4,
};

const SUPPORTED_REMOTE_ACTIONS = new Set([
  "automation_auto",
  "collect_current",
  "collect_auto",
  "pause_scroll",
  "stop_capture",
]);

let remoteControlTimer = null;

function startRemoteControlPolling() {
  if (remoteControlTimer !== null) {
    return;
  }
  const poll = () => {
    void pollRemoteCommand().catch(() => {
      // The desktop app may be closed. The next poll reconnects automatically.
    });
  };
  remoteControlTimer = setInterval(poll, 1200);
  poll();
}

async function pollRemoteCommand() {
  const settings = await loadRemoteSettings();
  if (!settings.apiToken) {
    return;
  }
  const response = await fetch(`${settings.apiBase}/api/extension/commands/next`, {
    headers: remoteHeaders(settings),
  });
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  const command = payload?.result;
  if (!command?.id) {
    return;
  }

  let ok = false;
  let message = "";
  try {
    message = await executeRemoteCommand(command, settings);
    ok = true;
  } catch (error) {
    message = error?.message || String(error);
  }
  await completeRemoteCommand(settings, command.id, ok, message);
}

async function executeRemoteCommand(command, storedSettings) {
  const action = String(command?.action || "");
  if (!SUPPORTED_REMOTE_ACTIONS.has(action)) {
    throw new Error(`不支持的远程操作：${action || "-"}`);
  }
  const tab = await findActiveSupportedRecruitingTab();
  if (!tab?.id) {
    throw new Error("未找到已打开的 Boss 或猎聘招聘页面，请先打开招聘平台。")
  }

  if (action === "pause_scroll" || action === "stop_capture") {
    await requestRemoteScrollPause(tab.id, action);
    return action === "stop_capture" ? "已发送停止采集请求" : "已发送暂停滚动请求";
  }

  let settings = { ...storedSettings };
  const automationRequested = action === "automation_auto";
  if (automationRequested) {
    const automation = await startRemoteDesktopAutomation(settings, tab.url, command);
    settings = {
      ...settings,
      jobTitle: automation.job_title || automation.profile_job_title || settings.jobTitle,
      jobProfileId: automation.profile_id,
      recruitmentTaskId: automation.task_id,
    };
  } else {
    settings = await loadRemoteDesktopJob(settings);
  }

  const expectedTaskId = Number(command.recruitment_task_id);
  if (!Number.isInteger(expectedTaskId) || Number(settings.recruitmentTaskId) !== expectedTaskId) {
    throw new Error("前端任务与插件当前任务不一致，请重新启动招聘任务后再试。")
  }
  await chrome.storage.local.set(settings);
  await resetRemoteScrollPause(tab.id);
  const autoScroll = action !== "collect_current";
  const frameResults = await collectRemoteFrames(tab.id, autoScroll, settings);
  const merged = mergeRemoteFrameResults(frameResults);
  if (merged.cards.length === 0) {
    throw new Error(`页面没有识别到候选人卡片。${merged.debugSummary || ""}`.trim());
  }
  const imported = await importRemoteCards(
    settings,
    tab.url,
    merged,
    automationRequested,
  );
  return `采集完成：识别 ${merged.cards.length} 人，导入批次 #${imported.batch_id ?? "-"}`;
}

async function loadRemoteSettings() {
  const stored = await chrome.storage.local.get(REMOTE_CONTROL_DEFAULTS);
  return {
    ...REMOTE_CONTROL_DEFAULTS,
    ...stored,
    apiBase: normalizeRemoteApiBase(stored.apiBase),
  };
}

async function loadRemoteDesktopJob(settings) {
  const response = await fetch(`${settings.apiBase}/api/extension/config`, {
    headers: remoteHeaders(settings),
  });
  const payload = await response.json();
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.error || `读取桌面岗位失败：${response.status}`);
  }
  if (payload.result?.job_profile_id === null || payload.result?.job_profile_id === undefined) {
    throw new Error("桌面端尚未选择有效岗位。")
  }
  return {
    ...settings,
    jobProfileId: Number(payload.result.job_profile_id),
    recruitmentTaskId:
      payload.result.recruitment_task_id === null ||
      payload.result.recruitment_task_id === undefined
        ? null
        : Number(payload.result.recruitment_task_id),
    jobTitle: String(payload.result.job_title || settings.jobTitle),
  };
}

async function startRemoteDesktopAutomation(settings, sourceUrl, command) {
  const response = await fetch(`${settings.apiBase}/api/automation/start`, {
    method: "POST",
    headers: remoteHeaders(settings),
    body: JSON.stringify({
      source_url: sourceUrl,
      trigger: "desktop_remote_control",
      recruitment_task_id: command.recruitment_task_id,
    }),
  });
  const payload = await response.json();
  if (!response.ok || !payload?.ok || !payload.result?.ready) {
    throw new Error(payload?.error || "桌面端自动化方案尚未准备好。")
  }
  return payload.result;
}

async function findActiveSupportedRecruitingTab() {
  const tabs = await chrome.tabs.query({ active: true });
  return tabs.find((tab) => isRemoteSupportedUrl(tab?.url)) || null;
}

function isRemoteSupportedUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return (
      /(^|\.)zhipin\.com$/i.test(url.hostname) ||
      /(^|\.)bosszhipin\.com$/i.test(url.hostname) ||
      ((url.hostname === "lpt.liepin.com" || /(^|\.)liepin\.com$/i.test(url.hostname)) &&
        url.pathname.startsWith("/recommend"))
    );
  } catch (_error) {
    return false;
  }
}

async function resetRemoteScrollPause(tabId) {
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
      return { ok: true };
    },
  });
}

async function requestRemoteScrollPause(tabId, reason) {
  await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    args: [reason],
    func: (requestReason) => {
      if (typeof globalThis.__bossLocalRequestScrollPause === "function") {
        return globalThis.__bossLocalRequestScrollPause(requestReason);
      }
      globalThis.__bossLocalScrollControl = {
        ...(globalThis.__bossLocalScrollControl || {}),
        pauseRequested: true,
        reason: requestReason,
        requestedAt: Date.now(),
      };
      return { ok: true, pauseRequested: true };
    },
  });
}

async function collectRemoteFrames(tabId, autoScroll, settings) {
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

function mergeRemoteFrameResults(frameResults) {
  const cardsByKey = new Map();
  const debugLines = [];
  const platforms = new Set();
  let framesSeen = 0;
  let framesWithCards = 0;
  let roundsCompleted = 0;
  for (const frameResult of frameResults || []) {
    const result = frameResult?.result;
    if (!result) continue;
    framesSeen += 1;
    const cards = Array.isArray(result.cards) ? result.cards : [];
    if (cards.length) framesWithCards += 1;
    if (result.meta?.platform) platforms.add(String(result.meta.platform));
    roundsCompleted = Math.max(roundsCompleted, Number(result.meta?.rounds_completed || 0));
    for (const card of cards) {
      cardsByKey.set(
        card.platform_uid || card.detail_url || card.raw_card_text || JSON.stringify(card),
        card,
      );
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
    roundsCompleted,
    platform: platforms.size === 1 ? Array.from(platforms)[0] : "",
    debugSummary: debugLines.join(" || "),
  };
}

async function importRemoteCards(settings, sourceUrl, merged, automationRequested) {
  const response = await fetch(`${settings.apiBase}/api/import/cards`, {
    method: "POST",
    headers: remoteHeaders(settings),
    body: JSON.stringify({
      job_profile_id: settings.jobProfileId,
      recruitment_task_id: settings.recruitmentTaskId,
      job_title: settings.jobTitle,
      source_url: sourceUrl,
      cards: merged.cards,
      meta: {
        platform: merged.platform || "",
        frames_seen: merged.framesSeen,
        frames_with_cards: merged.framesWithCards,
        rounds_completed: merged.roundsCompleted,
        unique_cards: merged.cards.length,
        automation_requested: automationRequested,
        trigger: "desktop_remote_control",
        debug: merged.debugSummary,
      },
    }),
  });
  const payload = await response.json();
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.error || `导入桌面端失败：${response.status}`);
  }
  return payload.result || {};
}

async function completeRemoteCommand(settings, commandId, ok, message) {
  await fetch(
    `${settings.apiBase}/api/extension/commands/${encodeURIComponent(commandId)}/complete`,
    {
      method: "POST",
      headers: remoteHeaders(settings),
      body: JSON.stringify({ ok, message }),
    },
  );
}

function remoteHeaders(settings) {
  return {
    "Content-Type": "application/json",
    "X-Boss-Local-Token": settings.apiToken || "",
  };
}

function normalizeRemoteApiBase(value) {
  let raw = String(value || REMOTE_CONTROL_DEFAULTS.apiBase).trim();
  if (!/^[a-z][a-z\d+.-]*:\/\//i.test(raw)) raw = `http://${raw}`;
  try {
    const url = new URL(raw);
    if (["localhost", "::1", "[::1]"].includes(url.hostname.toLowerCase())) {
      url.hostname = "127.0.0.1";
    }
    return url.toString().replace(/\/+$/, "");
  } catch (_error) {
    return raw.replace(/\/+$/, "");
  }
}

globalThis.BossLocalRemoteControl = {
  actions: SUPPORTED_REMOTE_ACTIONS,
  executeRemoteCommand,
  mergeRemoteFrameResults,
  start: startRemoteControlPolling,
};

startRemoteControlPolling();
