(function installBossNativeFavoriteRunner(globalScope) {
  if (globalScope.__bossNativeFavoriteRunner) {
    return;
  }

  const STATUS_KEY = "boss_native_favorite_status";
  const state = {
    running: false,
    stopRequested: false,
    batchId: null,
    phase: "idle",
    processed: 0,
    succeeded: 0,
    failed: 0,
    currentTaskId: null,
    message: "Ready.",
    startedAt: "",
    updatedAt: "",
  };

  async function start(settings) {
    if (state.running) {
      throw new Error("A Native Favorite batch is already running in this source tab.");
    }
    const batchId = Number(settings?.batchId || 0);
    if (!Number.isInteger(batchId) || batchId <= 0) {
      throw new Error("Native Favorite batch ID is required.");
    }
    const apiBase = normalizeApiBase(settings?.apiBase);
    const apiToken = String(settings?.apiToken || "").trim();
    if (!apiToken) {
      throw new Error("Local API token is required.");
    }

    Object.assign(state, {
      running: true,
      stopRequested: false,
      batchId,
      phase: "running",
      processed: 0,
      succeeded: 0,
      failed: 0,
      currentTaskId: null,
      message: "Native Favorite batch started.",
      startedAt: new Date().toISOString(),
    });
    await persistStatus();

    try {
      while (!state.stopRequested) {
        const task = await post(apiBase, apiToken, "/api/favorites/claim", {
          batch_id: batchId,
          worker_id: `favorite-source-${batchId}`,
        });
        if (!task) {
          state.phase = "completed";
          state.message = "No more executable Native Favorite tasks.";
          break;
        }
        state.currentTaskId = Number(task.task_id);
        state.message = `Processing Native Favorite task #${state.currentTaskId}.`;
        await persistStatus();

        let outcome;
        try {
          const response = await chrome.runtime.sendMessage({
            type: "native_favorite_execute",
            task,
          });
          if (!response?.ok || !response.result) {
            throw new Error(response?.error || "Native Favorite execution unavailable.");
          }
          outcome = normalizeOutcome(response.result);
        } catch (error) {
          outcome = {
            status: "failed",
            attempted: false,
            reason: "native_favorite_executor_unavailable",
            method: "extension_execution_bridge",
            stop_batch: true,
            error: error?.message || String(error),
          };
        }

        await post(apiBase, apiToken, "/api/favorites/result", {
          task_id: Number(task.task_id),
          claim_token: String(task.claim_token || ""),
          status: outcome.status,
          attempted: outcome.attempted,
          reason: outcome.reason,
          method: outcome.method,
          result: { ...outcome, claim_token: undefined },
        });
        state.processed += 1;
        if (outcome.status === "success" || outcome.status === "already_favorited") {
          state.succeeded += 1;
        } else {
          state.failed += 1;
        }
        state.currentTaskId = null;
        state.message = `Task #${task.task_id}: ${outcome.status} (${outcome.reason || "no reason"}).`;
        await persistStatus();

        if (
          outcome.stop_batch ||
          outcome.status === "unknown" ||
          outcome.status === "failed"
        ) {
          state.phase = "paused";
          state.message += " Batch paused before claiming another candidate.";
          break;
        }
        if (state.stopRequested) {
          break;
        }
        const intervalSeconds = clampInterval(task?.config_snapshot?.favorite_interval_seconds);
        await delay(intervalSeconds * 1000);
      }
      if (state.stopRequested) {
        state.phase = "stopped";
        state.message = "Stopped before claiming another Native Favorite task.";
      }
    } catch (error) {
      state.phase = "failed";
      state.message = error?.message || String(error);
    } finally {
      state.running = false;
      state.currentTaskId = null;
      await persistStatus();
    }
    return snapshot();
  }

  function stop() {
    state.stopRequested = true;
    state.message = "Stop requested; the current action will finish before stopping.";
    void persistStatus();
    return snapshot();
  }

  function getStatus() {
    return snapshot();
  }

  async function post(apiBase, apiToken, path, payload) {
    const response = await chrome.runtime.sendMessage({
      type: "native_favorite_api",
      apiBase,
      apiToken,
      path,
      payload,
    });
    if (!response?.ok) {
      throw new Error(response?.error || "Local Native Favorite API unavailable.");
    }
    return response.result ?? null;
  }

  function normalizeOutcome(value) {
    const status = String(value?.status || "failed").toLowerCase();
    return {
      ...value,
      status: ["success", "already_favorited", "failed", "unknown"].includes(status)
        ? status
        : "failed",
      attempted: value?.attempted === true,
      reason: String(value?.reason || "native_favorite_result_invalid"),
      method: String(value?.method || "native_detail_control+management_identity"),
      stop_batch: value?.stop_batch === true,
    };
  }

  function normalizeApiBase(value) {
    const url = new URL(String(value || "http://127.0.0.1:17863"));
    if (!['http:', 'https:'].includes(url.protocol)) {
      throw new Error("Local API URL must use HTTP or HTTPS.");
    }
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
      throw new Error("Native Favorite runner only connects to the local API.");
    }
    return url.toString().replace(/\/$/, "");
  }

  function clampInterval(value) {
    return Math.min(8, Math.max(3, Number(value || 5)));
  }

  function delay(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  function snapshot() {
    return { ...state };
  }

  async function persistStatus() {
    state.updatedAt = new Date().toISOString();
    await chrome.storage.local.set({ [STATUS_KEY]: snapshot() });
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "boss_native_favorite_command") {
      return false;
    }
    if (message.command === "start") {
      start(message.settings || {})
        .then((status) => sendResponse({ ok: true, status }))
        .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
      return true;
    }
    if (message.command === "stop") {
      sendResponse({ ok: true, status: stop() });
      return false;
    }
    sendResponse({ ok: true, status: getStatus() });
    return false;
  });

  globalScope.__bossNativeFavoriteRunner = Object.freeze({ start, stop, getStatus });
})(globalThis);
