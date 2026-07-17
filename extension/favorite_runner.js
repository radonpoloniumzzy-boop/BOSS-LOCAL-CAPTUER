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
    pendingVerification: 0,
    currentTaskId: null,
    message: "Ready.",
    startedAt: "",
    updatedAt: "",
    requiresManualResolution: false,
  };
  const ready = reconcilePersistedRunnerState();

  async function start(settings) {
    await ready;
    if (state.running) {
      throw new Error("A Native Favorite batch is already running in this source tab.");
    }
    if (state.requiresManualResolution) {
      throw new Error(
        "The previous source document was interrupted. Native Favorite requires manual resolution before another batch can start.",
      );
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
      pendingVerification: 0,
      currentTaskId: null,
      message: "Native Favorite batch started.",
      startedAt: new Date().toISOString(),
      requiresManualResolution: false,
    });
    await persistStatus();

    try {
      while (!state.stopRequested) {
        const task = await post(apiBase, apiToken, "/api/favorites/claim", {
          batch_id: batchId,
          worker_id: `favorite-source-${batchId}`,
        });
        if (!task) {
          state.phase = state.pendingVerification > 0 ? "awaiting_verification" : "completed";
          state.message = state.pendingVerification > 0
            ? "Source actions finished. Open Boss Favorite Talent later and verify this batch."
            : "No more executable Native Favorite tasks.";
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
            status: "unknown",
            attempted: true,
            reason: "native_favorite_execution_bridge_outcome_unknown",
            method: "extension_execution_bridge",
            stop_batch: true,
            retryable: false,
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
        if (outcome.status === "verification_pending") {
          state.pendingVerification += 1;
        } else if (outcome.status === "success" || outcome.status === "already_favorited") {
          state.succeeded += 1;
        } else {
          state.failed += 1;
        }
        state.currentTaskId = null;
        state.message = `Task #${task.task_id}: ${outcome.status} (${outcome.reason || "no reason"}).`;
        await persistStatus();

        const retryAvailable =
          outcome.status === "failed" &&
          outcome.retryable === true &&
          !state.stopRequested &&
          Number(task.attempt_count || 0) + 1 < Number(task.max_attempts || 1);
        if (retryAvailable) {
          await post(apiBase, apiToken, "/api/favorites/retry", {
            task_id: Number(task.task_id),
          });
          state.message += " Explicit failure queued for its single retry.";
          await persistStatus();
          await delay(clampInterval(task?.config_snapshot?.favorite_interval_seconds) * 1000);
          continue;
        }

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

  async function startVerification(settings) {
    await ready;
    if (state.running) throw new Error("A Native Favorite operation is already running in this tab.");
    const batchId = Number(settings?.batchId || 0);
    if (!Number.isInteger(batchId) || batchId <= 0) {
      throw new Error("Native Favorite batch ID is required.");
    }
    const apiBase = normalizeApiBase(settings?.apiBase);
    const apiToken = String(settings?.apiToken || "").trim();
    if (!apiToken) throw new Error("Local API token is required.");
    Object.assign(state, {
      running: true,
      stopRequested: false,
      batchId,
      phase: "verifying",
      processed: 0,
      succeeded: 0,
      failed: 0,
      pendingVerification: 0,
      currentTaskId: null,
      message: "Native Favorite management verification started.",
      startedAt: new Date().toISOString(),
      requiresManualResolution: false,
    });
    await persistStatus();
    try {
      while (!state.stopRequested) {
        const task = await post(apiBase, apiToken, "/api/favorites/verification/claim", {
          batch_id: batchId,
          worker_id: `favorite-management-${batchId}`,
        });
        if (!task) {
          state.phase = "verification_completed";
          state.message = "No more Native Favorite items are waiting for management verification.";
          break;
        }
        state.currentTaskId = Number(task.task_id);
        await persistStatus();
        let outcome;
        try {
          const response = await chrome.runtime.sendMessage({
            type: "native_favorite_verify",
            task,
          });
          if (!response?.ok || !response.result) {
            throw new Error(response?.error || "Native Favorite management verification unavailable.");
          }
          outcome = normalizeVerificationOutcome(response.result, task);
        } catch (error) {
          outcome = {
            status: "verification_pending",
            attempted: task.source_action_attempted === true,
            reason: "management_verification_bridge_unavailable",
            method: "management_identity_verification_bridge",
            stop_batch: true,
            error: error?.message || String(error),
          };
        }
        await post(apiBase, apiToken, "/api/favorites/verification/result", {
          task_id: Number(task.task_id),
          claim_token: String(task.claim_token || ""),
          status: outcome.status,
          reason: outcome.reason,
          method: outcome.method,
          result: { ...outcome },
        });
        state.processed += 1;
        if (outcome.status === "success" || outcome.status === "already_favorited") {
          state.succeeded += 1;
        } else if (outcome.status === "verification_pending") {
          state.pendingVerification += 1;
        } else {
          state.failed += 1;
        }
        state.currentTaskId = null;
        state.message = `Verification #${task.task_id}: ${outcome.status} (${outcome.reason}).`;
        await persistStatus();
        if (outcome.stop_batch || outcome.status === "verification_pending" || outcome.status === "failed") {
          state.phase = "verification_paused";
          state.message += " Verification paused without changing the source favorite action.";
          break;
        }
        if (!state.stopRequested) {
          await delay(clampInterval(task?.config_snapshot?.favorite_interval_seconds) * 1000);
        }
      }
      if (state.stopRequested) {
        state.phase = "verification_stopped";
        state.message = "Stopped before verifying another Native Favorite item.";
      }
    } catch (error) {
      state.phase = "verification_failed";
      state.message = error?.message || String(error);
    } finally {
      state.running = false;
      state.currentTaskId = null;
      await persistStatus();
    }
    return snapshot();
  }

  function stop() {
    if (state.requiresManualResolution) {
      state.message = "Interrupted Native Favorite state still requires manual resolution.";
      void persistStatus();
      return snapshot();
    }
    state.stopRequested = true;
    state.message = "Stop requested; the current action will finish before stopping.";
    void persistStatus();
    return snapshot();
  }

  function getStatus() {
    return snapshot();
  }

  async function resolveInterruption(settings) {
    await ready;
    if (state.running) throw new Error("Cannot reconcile while Native Favorite is running.");
    const batchId = Number(settings?.batchId || state.batchId || 0);
    if (!Number.isInteger(batchId) || batchId <= 0) {
      throw new Error("Native Favorite batch ID is required for reconciliation.");
    }
    if (state.batchId && Number(state.batchId) !== batchId) {
      throw new Error("Reconciliation must use the interrupted Native Favorite batch ID.");
    }
    const apiToken = String(settings?.apiToken || "").trim();
    if (!apiToken) throw new Error("Local API token is required.");
    const result = await post(
      normalizeApiBase(settings?.apiBase),
      apiToken,
      "/api/favorites/reconcile",
      { batch_id: batchId },
    );
    if (!result?.can_resume_pending) {
      state.message = "The previous claim lease is still active; try reconciliation after it expires.";
      await persistStatus();
      return snapshot();
    }
    if (Number(result?.batch_id || 0) !== batchId) {
      throw new Error("Native Favorite reconciliation returned the wrong batch.");
    }
    const sourceValidation = await chrome.runtime.sendMessage({
      type: "native_favorite_validate_source_context",
      sourcePageContext: result?.source_page_context || {},
    });
    if (!sourceValidation?.ok || !sourceValidation?.result?.ok) {
      state.message = "The original Source Page Context changed. This batch stays locked; collect a fresh batch instead of consuming pending tasks.";
      await persistStatus();
      return snapshot();
    }
    state.requiresManualResolution = false;
    state.stopRequested = false;
    state.currentTaskId = null;
    state.phase = "paused";
    state.message = `Interruption reconciled; ${Number(result.unknown || 0)} unknown task(s) remain terminal. Pending tasks may now resume.`;
    await persistStatus();
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
      status: ["success", "already_favorited", "failed", "unknown", "verification_pending"].includes(status)
        ? status
        : "failed",
      attempted: value?.attempted === true,
      reason: String(value?.reason || "native_favorite_result_invalid"),
      method: String(value?.method || "native_detail_control+management_identity"),
      stop_batch: value?.stop_batch === true,
    };
  }

  function normalizeVerificationOutcome(value, task) {
    const rawStatus = String(value?.status || "").toLowerCase();
    const status = rawStatus === "unknown" ? "verification_pending" : rawStatus;
    return {
      ...value,
      status: ["success", "already_favorited", "failed", "verification_pending"].includes(status)
        ? status
        : "verification_pending",
      attempted: task?.source_action_attempted === true,
      reason: String(value?.reason || "favorite_management_verification_inconclusive"),
      method: String(value?.method || "management_identity_verification"),
      stop_batch: value?.stop_batch === true || status === "verification_pending",
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

  async function reconcilePersistedRunnerState() {
    const stored = await chrome.storage.local.get({ [STATUS_KEY]: null });
    const previous = stored?.[STATUS_KEY];
    if (!previous?.running && !previous?.requiresManualResolution && previous?.phase !== "interrupted") {
      return snapshot();
    }
    Object.assign(state, {
      batchId: Number(previous.batchId || 0) || null,
      phase: "interrupted",
      processed: Number(previous.processed || 0),
      succeeded: Number(previous.succeeded || 0),
      failed: Number(previous.failed || 0),
      pendingVerification: Number(previous.pendingVerification || 0),
      currentTaskId: previous.currentTaskId || null,
      running: false,
      stopRequested: true,
      requiresManualResolution: true,
      startedAt: String(previous.startedAt || ""),
      message: "The source document was destroyed while Native Favorite was running. The current claim must resolve to unknown before any restart.",
    });
    await persistStatus();
    return snapshot();
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
    if (message.command === "start_verification") {
      startVerification(message.settings || {})
        .then((status) => sendResponse({ ok: true, status }))
        .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
      return true;
    }
    if (message.command === "stop") {
      sendResponse({ ok: true, status: stop() });
      return false;
    }
    if (message.command === "reconcile") {
      resolveInterruption(message.settings || {})
        .then((status) => sendResponse({ ok: true, status }))
        .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
      return true;
    }
    sendResponse({ ok: true, status: getStatus() });
    return false;
  });

  globalScope.__bossNativeFavoriteRunner = Object.freeze({
    start,
    startVerification,
    stop,
    getStatus,
    resolveInterruption,
    ready,
  });
})(globalThis);
