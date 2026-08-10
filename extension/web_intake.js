(function (globalThis) {
  const WEB_INTAKE_PORT = 17864;
  const STATE_KEY = "boss_web_intake_state_v1";
  const MAX_AUTO_RETRIES = 1;
  const AUTO_RETRY_DELAY_MS = 900;
  const COMPLETED_LIMIT = 20;

  function trimTrailingSlash(value) {
    return String(value || "").replace(/\/+$/, "");
  }

  function normalizeApiBase(value) {
    let raw = String(value || "http://127.0.0.1:17863").trim() || "http://127.0.0.1:17863";
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

  function deriveWebApiBase(apiBase) {
    const normalizedBase = normalizeApiBase(apiBase);
    try {
      const url = new URL(normalizedBase);
      url.port = String(WEB_INTAKE_PORT);
      url.pathname = "";
      url.search = "";
      url.hash = "";
      return trimTrailingSlash(url.toString());
    } catch (_error) {
      return `http://127.0.0.1:${WEB_INTAKE_PORT}`;
    }
  }

  function stableHash(value) {
    const text = String(value || "");
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
  }

  function connectionIdentity(settings) {
    const desktopApiBase = normalizeApiBase(settings?.apiBase || "");
    const webApiBase = deriveWebApiBase(desktopApiBase);
    return {
      desktopApiBase,
      webApiBase,
      tokenFingerprint: stableHash(String(settings?.apiToken || "")),
      key: stableHash(`${desktopApiBase}|${webApiBase}|${String(settings?.apiToken || "")}`),
    };
  }

  function sameConnection(identity, settings) {
    const current = connectionIdentity(settings);
    return identity && identity.key === current.key;
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function createEmptyState() {
    return {
      pendingBatches: {},
      pendingOrder: [],
      completedBatches: {},
      completedOrder: [],
      lastVisibleBatchKey: "",
    };
  }

  async function loadState(storageArea) {
    const area = storageArea || chrome.storage.local;
    const stored = await area.get(STATE_KEY);
    return {
      ...createEmptyState(),
      ...(stored?.[STATE_KEY] || {}),
    };
  }

  async function saveState(state, storageArea) {
    const area = storageArea || chrome.storage.local;
    await area.set({ [STATE_KEY]: state });
  }

  function sanitizeResult(result) {
    return {
      batch_id: Number(result?.batch_id || 0) || null,
      status: String(result?.status || ""),
      reused: Boolean(result?.reused),
      received_count: Number(result?.received_count || result?.received_cards || 0),
      inserted_candidates: Number(result?.inserted_candidates || 0),
      updated_candidates: Number(result?.updated_candidates || 0),
      skipped_candidates: Number(result?.skipped_candidates || 0),
      failed_candidates: Number(result?.failed_candidates || 0),
      total_unique: Number(result?.total_unique || 0),
      total_batch_items: Number(result?.total_batch_items || 0),
    };
  }

  function mapCardToCandidate(card, sourcePlatform) {
    return {
      source_platform: sourcePlatform,
      source_candidate_id: String(card?.source_candidate_id || "").trim(),
      platform_uid: String(card?.platform_uid || "").trim(),
      detail_url: String(card?.detail_url || "").trim(),
      raw_card_text: String(card?.raw_card_text || ""),
      name: String(card?.name || "").trim(),
      active_status: String(card?.active_status || "").trim(),
      expected_salary: String(card?.expected_salary || "").trim(),
      work_experience_text: String(card?.work_experience_text || "").trim(),
      education_text: String(card?.education_text || "").trim(),
      tags_text: Array.isArray(card?.tags_text) ? card.tags_text.slice() : String(card?.tags_text || "").trim(),
      summary_text: String(card?.summary_text || "").trim(),
      capture_time: String(card?.capture_time || "").trim(),
    };
  }

  function buildPayload({ settings, imported, merged, sourceUrl }) {
    const sourcePlatform = String(merged?.platform || settings?.platform || "").trim();
    const candidates = Array.isArray(merged?.cards)
      ? merged.cards
          .filter((card) => card && typeof card === "object" && String(card.raw_card_text || "").trim())
          .map((card) => mapCardToCandidate(card, sourcePlatform))
      : [];
    if (!candidates.length) {
      return null;
    }
    const desktopBatchId = Number(imported?.batch_id || 0);
    return {
      source_platform: sourcePlatform,
      source_url: String(sourceUrl || imported?.source_url || settings?.sourceUrl || "").trim(),
      source_job_title: String(imported?.job_title || settings?.jobTitle || "").trim(),
      job_profile_id: imported?.job_profile_id ?? settings?.jobProfileId ?? null,
      recruitment_task_id: imported?.recruitment_task_id ?? settings?.recruitmentTaskId ?? null,
      idempotency_key: desktopBatchId > 0 ? `ext-web-intake-${desktopBatchId}` : `ext-web-intake-${Date.now()}`,
      candidates,
    };
  }

  function buildPendingRecord({ settings, imported, merged, sourceUrl }) {
    const payload = buildPayload({ settings, imported, merged, sourceUrl });
    if (!payload) {
      return null;
    }
    const identity = connectionIdentity(settings);
    const desktopBatchId = Number(imported?.batch_id || 0);
    const batchKey = `${identity.key}:${desktopBatchId}:${payload.idempotency_key}`;
    return {
      batchKey,
      desktopBatchId,
      idempotencyKey: payload.idempotency_key,
      payload,
      connection: identity,
      source: "extension_capture",
      createdAt: nowIso(),
      updatedAt: nowIso(),
      attemptCount: 0,
      status: "pending",
      statusLabel: "等待发送",
      message: "采集批次已完成，等待发送到网页工作台。",
      webResult: null,
    };
  }

  function classifyFailure(response, payload, error) {
    const safeCode = String(payload?.error?.code || "");
    const safeMessage = String(payload?.error?.message || "");
    if (!response) {
      return {
        status: "waiting_retry",
        statusLabel: "网页工作台未启动",
        code: "workbench_unreachable",
        message: "无法连接网页工作台，请确认 http://127.0.0.1:17864 已启动。",
        autoRetry: true,
      };
    }
    if (response.status === 401) {
      return {
        status: "failed",
        statusLabel: "鉴权失败",
        code: "auth_failed",
        message: "网页工作台 Token 校验失败，请重新检查连接配置。",
        autoRetry: false,
      };
    }
    if (response.status === 409 && safeCode === "idempotency_conflict") {
      return {
        status: "failed",
        statusLabel: "发送失败",
        code: safeCode,
        message: "网页工作台发现幂等冲突，未创建第二个批次。",
        autoRetry: false,
      };
    }
    if (response.status >= 500) {
      return {
        status: "waiting_retry",
        statusLabel: "等待重试",
        code: safeCode || "server_error",
        message: safeMessage || "网页工作台暂时无法处理请求，请稍后重试。",
        autoRetry: safeCode === "internal_error",
      };
    }
    return {
      status: "failed",
      statusLabel: "发送失败",
      code: safeCode || "request_failed",
      message: safeMessage || error?.message || `网页工作台返回状态码 ${response.status}`,
      autoRetry: false,
    };
  }

  function classifySuccess(result) {
    const safe = sanitizeResult(result);
    if (safe.reused) {
      return {
        status: "reused",
        statusLabel: "已复用原批次",
        message: `网页工作台已复用批次 #${safe.batch_id || "-"}`,
      };
    }
    if (safe.status === "partial" || safe.failed_candidates > 0) {
      return {
        status: "partial",
        statusLabel: "部分成功",
        message: `网页工作台已接收，批次 #${safe.batch_id || "-"} 存在部分失败。`,
      };
    }
    return {
      status: "success",
      statusLabel: "入库成功",
      message: `网页工作台已接收批次 #${safe.batch_id || "-"}`,
    };
  }

  function upsertPending(state, record) {
    state.pendingBatches[record.batchKey] = record;
    state.pendingOrder = [record.batchKey, ...state.pendingOrder.filter((key) => key !== record.batchKey)];
    state.lastVisibleBatchKey = record.batchKey;
  }

  function moveToCompleted(state, record) {
    delete state.pendingBatches[record.batchKey];
    state.pendingOrder = state.pendingOrder.filter((key) => key !== record.batchKey);
    state.completedBatches[record.batchKey] = record;
    state.completedOrder = [record.batchKey, ...state.completedOrder.filter((key) => key !== record.batchKey)].slice(
      0,
      COMPLETED_LIMIT,
    );
    for (const key of Object.keys(state.completedBatches)) {
      if (!state.completedOrder.includes(key)) {
        delete state.completedBatches[key];
      }
    }
    state.lastVisibleBatchKey = record.batchKey;
  }

  function currentRecordForConnection(state, settings) {
    const pending = state.pendingOrder
      .map((key) => state.pendingBatches[key])
      .find((record) => sameConnection(record?.connection, settings));
    if (pending) {
      return pending;
    }
    const completed = state.completedOrder
      .map((key) => state.completedBatches[key])
      .find((record) => sameConnection(record?.connection, settings));
    if (completed) {
      return completed;
    }
    return null;
  }

  async function queueImportedBatch({ settings, imported, merged, sourceUrl, storageArea }) {
    const record = buildPendingRecord({ settings, imported, merged, sourceUrl });
    if (!record) {
      return null;
    }
    const state = await loadState(storageArea);
    const existing = state.pendingBatches[record.batchKey] || state.completedBatches[record.batchKey];
    if (existing) {
      state.lastVisibleBatchKey = existing.batchKey;
      await saveState(state, storageArea);
      return existing;
    }
    upsertPending(state, record);
    await saveState(state, storageArea);
    return record;
  }

  async function sendQueuedBatch({ settings, batchKey, storageArea, fetchImpl }) {
    const state = await loadState(storageArea);
    const record = state.pendingBatches[batchKey];
    if (!record) {
      return currentRecordForConnection(state, settings);
    }
    if (!sameConnection(record.connection, settings)) {
      record.status = "failed";
      record.statusLabel = "等待原连接";
      record.message = "该待发送批次属于旧连接，不会误发到当前人才库。";
      record.updatedAt = nowIso();
      upsertPending(state, record);
      await saveState(state, storageArea);
      return record;
    }

    const executeFetch = fetchImpl || fetch;
    let lastRecord = record;
    for (let attempt = Number(record.attemptCount || 0); attempt <= MAX_AUTO_RETRIES; attempt += 1) {
      lastRecord = {
        ...lastRecord,
        attemptCount: attempt,
        status: "sending",
        statusLabel: "正在发送",
        message: "正在发送到网页工作台...",
        updatedAt: nowIso(),
      };
      upsertPending(state, lastRecord);
      await saveState(state, storageArea);

      let response = null;
      let payload = null;
      try {
        response = await executeFetch(`${record.connection.webApiBase}/api/intake/candidates`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Origin: record.connection.webApiBase,
            "X-Boss-Local-Token": String(settings.apiToken || ""),
          },
          body: JSON.stringify(record.payload),
        });
        try {
          payload = await response.json();
        } catch (_error) {
          payload = {};
        }
        if (response.ok) {
          const success = classifySuccess(payload || {});
          lastRecord = {
            ...lastRecord,
            status: success.status,
            statusLabel: success.statusLabel,
            message: success.message,
            webResult: sanitizeResult(payload || {}),
            updatedAt: nowIso(),
          };
          moveToCompleted(state, lastRecord);
          await saveState(state, storageArea);
          return lastRecord;
        }
      } catch (error) {
        payload = {};
        response = null;
      }

      const failure = classifyFailure(response, payload, null);
      lastRecord = {
        ...lastRecord,
        status: failure.status,
        statusLabel: failure.statusLabel,
        message: failure.message,
        errorCode: failure.code,
        updatedAt: nowIso(),
      };
      upsertPending(state, lastRecord);
      await saveState(state, storageArea);
      if (!failure.autoRetry || attempt >= MAX_AUTO_RETRIES) {
        return lastRecord;
      }
      await new Promise((resolve) => setTimeout(resolve, AUTO_RETRY_DELAY_MS * (attempt + 1)));
    }
    return lastRecord;
  }

  async function retryPendingForCurrentConnection({ settings, storageArea, fetchImpl }) {
    const state = await loadState(storageArea);
    const pending = state.pendingOrder
      .map((key) => state.pendingBatches[key])
      .find((record) => sameConnection(record?.connection, settings));
    if (!pending) {
      return currentRecordForConnection(state, settings);
    }
    return sendQueuedBatch({ settings, batchKey: pending.batchKey, storageArea, fetchImpl });
  }

  function formatStatus(record, settings) {
    if (!record) {
      return {
        title: "等待发送",
        message: "采集完成后会自动尝试发送到网页工作台。",
        canRetry: false,
        belongsToCurrentConnection: true,
        openUrl: deriveWebApiBase(settings?.apiBase || ""),
      };
    }
    const belongsToCurrentConnection = sameConnection(record.connection, settings);
    const result = record.webResult || {};
    return {
      title: record.statusLabel || "等待发送",
      message: [
        record.message || "",
        result.batch_id ? `Web 批次 ID: ${result.batch_id}` : "",
        result.received_count ? `接收数: ${result.received_count}` : "",
        Number.isFinite(result.inserted_candidates) ? `新增: ${result.inserted_candidates || 0}` : "",
        Number.isFinite(result.updated_candidates) ? `更新: ${result.updated_candidates || 0}` : "",
        Number.isFinite(result.skipped_candidates) ? `跳过: ${result.skipped_candidates || 0}` : "",
        Number.isFinite(result.failed_candidates) ? `失败: ${result.failed_candidates || 0}` : "",
        !belongsToCurrentConnection ? "当前连接与该批次创建时不同，已阻止误发送。" : "",
      ]
        .filter(Boolean)
        .join("\n"),
      canRetry: belongsToCurrentConnection && ["waiting_retry", "failed"].includes(String(record.status || "")),
      belongsToCurrentConnection,
      openUrl: (record.connection && record.connection.webApiBase) || deriveWebApiBase(settings?.apiBase || ""),
    };
  }

  globalThis.BossLocalWebIntake = {
    STATE_KEY,
    normalizeApiBase,
    deriveWebApiBase,
    connectionIdentity,
    sameConnection,
    buildPayload,
    buildPendingRecord,
    queueImportedBatch,
    sendQueuedBatch,
    retryPendingForCurrentConnection,
    loadState,
    saveState,
    currentRecordForConnection,
    formatStatus,
  };
})(globalThis);
