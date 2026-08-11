(function (globalThis) {
  const { buildPayload, connectionIdentity, sameConnectionIdentity, createBatchKey } =
    globalThis.BossLocalWebIntakeIdentity;
  const {
    loadState,
    upsertPendingRecord,
    moveToCompleted,
    readPendingRecord,
    readCompletedRecord,
    currentRecordForConnection,
    getStatusRecordsForConnection,
    createScrubbedPendingTransition,
    WebIntakeStorageError,
  } = globalThis.BossLocalWebIntakeStorage;
  const { classifySuccessfulStatus, formatStatus } = globalThis.BossLocalWebIntakeUi;

  const RETRY_ALARM_NAME = "boss_web_intake_retry";
  const RETRY_ALARM_DELAY_MINUTES = 0.5;
  const MAX_AUTO_ATTEMPTS = 3;
  const SEND_LEASE_MS = 60 * 1000;
  const sendLocks = new Map();

  function nowMs() {
    if (typeof globalThis.__bossLocalWebIntakeNow === "function") {
      return Number(globalThis.__bossLocalWebIntakeNow()) || Date.now();
    }
    return Date.now();
  }

  function nowIso() {
    return new Date(nowMs()).toISOString();
  }

  function sanitizeResult(result) {
    return {
      batch_id: Number(result?.batch_id || 0) || null,
      status: String(result?.status || ""),
      reused: Boolean(result?.reused),
      received_count: Number(result?.received_count || 0),
      inserted_candidates: Number(result?.inserted_candidates || 0),
      updated_candidates: Number(result?.updated_candidates || 0),
      skipped_candidates: Number(result?.skipped_candidates || 0),
      failed_candidates: Number(result?.failed_candidates || 0),
      total_unique: Number(result?.total_unique || 0),
      total_batch_items: Number(result?.total_batch_items || 0),
    };
  }

  function createLeaseOwner() {
    return `${nowMs().toString(36)}-${Math.random().toString(16).slice(2, 8)}`;
  }

  function hasBrokenLeaseTiming(record, currentNow = nowMs()) {
    const startedAt = Date.parse(record?.sendingStartedAt || "");
    const expiresAt = Date.parse(record?.leaseExpiresAt || "");
    if (!Number.isFinite(startedAt) || !Number.isFinite(expiresAt)) {
      return true;
    }
    if (currentNow < startedAt) {
      return true;
    }
    const leaseSpan = expiresAt - startedAt;
    if (leaseSpan <= 0 || leaseSpan > SEND_LEASE_MS * 2) {
      return true;
    }
    return false;
  }

  function isLeaseExpired(record, currentNow = nowMs()) {
    const expiresAt = Date.parse(record?.leaseExpiresAt || "");
    if (!Number.isFinite(expiresAt)) {
      return true;
    }
    if (hasBrokenLeaseTiming(record, currentNow)) {
      return true;
    }
    return expiresAt <= currentNow;
  }

  function clearLeaseFields(record) {
    return {
      ...record,
      sendingStartedAt: "",
      leaseOwner: "",
      leaseExpiresAt: "",
    };
  }

  function createCompletedWriteFailedRecord(record) {
    return {
      ...createScrubbedPendingTransition(record),
      status: "waiting_retry",
      statusLabel: "等待重试",
      message: "服务端已成功接收，但本地完成状态写入失败，请重试恢复。",
      errorCode: "complete_write_failed",
      updatedAt: nowIso(),
    };
  }

  function normalizeRecoveredCompletedRecord(record) {
    if (!record?.scrubbedPendingTransition || record?.errorCode !== "complete_write_failed") {
      return record;
    }
    const success = classifySuccessfulStatus(record.webResult || {});
    return {
      ...record,
      status: success.status,
      statusLabel: success.statusLabel,
      message: success.message,
      updatedAt: nowIso(),
    };
  }

  function classifyFailure(response, payload) {
    const safeCode = String(payload?.error?.code || "");
    const safeMessage = String(payload?.error?.message || "");
    if (!response) {
      return {
        status: "waiting_retry",
        statusLabel: "等待重试",
        code: "network_error",
        message: "无法连接网页工作台，请确认 http://127.0.0.1:17864 已启动。",
        autoRetry: true,
      };
    }
    if (response.status === 401) {
      return {
        status: "failed",
        statusLabel: "鉴权失败",
        code: "auth_failed",
        message: "网页工作台 Token 校验失败，请检查当前连接配置。",
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
        autoRetry: true,
      };
    }
    return {
      status: "failed",
      statusLabel: "发送失败",
      code: safeCode || "request_failed",
      message: safeMessage || `网页工作台返回状态码 ${response.status}`,
      autoRetry: false,
    };
  }

  async function buildPendingRecord({ settings, merged, sourceUrl, idempotencyKey }) {
    const payload = buildPayload({ settings, merged, sourceUrl, idempotencyKey });
    if (!payload) {
      return null;
    }
    const connection = await connectionIdentity(settings);
    const batchKey = await createBatchKey(connection, payload.idempotency_key);
    return {
      batchKey,
      idempotencyKey: payload.idempotency_key,
      payload,
      connection,
      createdAt: nowIso(),
      updatedAt: nowIso(),
      attemptCount: 0,
      status: "pending",
      statusLabel: "等待发送",
      message: "采集批次已完成，等待发送到网页工作台。",
      errorCode: "",
      sendingStartedAt: "",
      leaseOwner: "",
      leaseExpiresAt: "",
      webResult: null,
    };
  }

  async function queueCapturedBatch({ settings, merged, sourceUrl, idempotencyKey, storageArea }) {
    const record = await buildPendingRecord({ settings, merged, sourceUrl, idempotencyKey });
    if (!record) {
      return null;
    }
    const state = await loadState(storageArea);
    const existing = state.pendingBatches[record.batchKey] || state.completedBatches[record.batchKey];
    if (existing) {
      return existing;
    }
    return upsertPendingRecord(record, storageArea);
  }

  function getRetryableRecord(record, manualRetry) {
    if (!record) {
      return null;
    }
    if (manualRetry && ["failed", "waiting_retry"].includes(String(record.status || ""))) {
      return { ...record, attemptCount: 0 };
    }
    return record;
  }

  async function recoverExpiredLease(batchKey, storageArea) {
    const record = await readPendingRecord(batchKey, storageArea);
    if (!record || String(record.status || "") !== "sending" || !isLeaseExpired(record)) {
      return record;
    }
    const recovered = clearLeaseFields({
      ...record,
      status: "waiting_retry",
      statusLabel: "等待重试",
      message: "检测到上次发送中断，已恢复为可重试状态。",
      updatedAt: nowIso(),
    });
    await upsertPendingRecord(recovered, storageArea);
    return recovered;
  }

  async function processFailure(record, failure, storageArea) {
    const latestCompleted = await readCompletedRecord(record.batchKey, storageArea);
    if (latestCompleted) {
      return latestCompleted;
    }
    const failedRecord = clearLeaseFields({
      ...record,
      status: failure.status,
      statusLabel: failure.statusLabel,
      message: failure.message,
      errorCode: failure.code,
      updatedAt: nowIso(),
    });
    if (failure.autoRetry && Number(failedRecord.attemptCount || 0) >= MAX_AUTO_ATTEMPTS) {
      failedRecord.status = "failed";
      failedRecord.statusLabel = "发送失败";
      failedRecord.message = "自动重试次数已达上限，请手动重试。";
      failedRecord.errorCode = failure.code || "retry_limit_reached";
    }
    await upsertPendingRecord(failedRecord, storageArea);
    return failedRecord;
  }

  async function finalizeCompletedTransition(record, storageArea) {
    const completedRecord = normalizeRecoveredCompletedRecord(record);
    try {
      return await moveToCompleted(completedRecord, storageArea);
    } catch (_error) {
      const latestCompleted = await readCompletedRecord(completedRecord.batchKey, storageArea);
      if (latestCompleted) {
        return latestCompleted;
      }
      const scrubbed = createCompletedWriteFailedRecord(completedRecord);
      await upsertPendingRecord(scrubbed, storageArea);
      return scrubbed;
    }
  }

  async function performSend({ settings, batchKey, storageArea, fetchImpl, manualRetry = false, leaseOwner }) {
    let record = await recoverExpiredLease(batchKey, storageArea);
    record = getRetryableRecord(record, manualRetry);
    if (!record) {
      return readCompletedRecord(batchKey, storageArea) || currentRecordForConnection(settings, storageArea);
    }

    if (record.scrubbedPendingTransition && !record.payload && record.webResult) {
      return finalizeCompletedTransition(record, storageArea);
    }

    const currentIdentity = await connectionIdentity(settings);
    if (!sameConnectionIdentity(record.connection, currentIdentity)) {
      const blocked = clearLeaseFields({
        ...record,
        status: "failed",
        statusLabel: "等待原连接",
        message: "该待发送批次属于旧连接，不会误投到当前人才库。",
        updatedAt: nowIso(),
      });
      await upsertPendingRecord(blocked, storageArea);
      return blocked;
    }

    if (String(record.status || "") === "sending" && !isLeaseExpired(record) && record.leaseOwner !== leaseOwner) {
      return record;
    }
    if (
      !manualRetry
      && Number(record.attemptCount || 0) >= MAX_AUTO_ATTEMPTS
      && ["waiting_retry", "failed"].includes(String(record.status || ""))
    ) {
      return clearLeaseFields({
        ...record,
        status: "failed",
        statusLabel: "发送失败",
        message: "自动重试次数已达上限，请手动重试。",
      });
    }

    record = {
      ...record,
      status: "sending",
      statusLabel: "正在发送",
      message: "正在发送到网页工作台...",
      updatedAt: nowIso(),
      attemptCount: manualRetry ? 1 : Number(record.attemptCount || 0) + 1,
      sendingStartedAt: nowIso(),
      leaseOwner,
      leaseExpiresAt: new Date(nowMs() + SEND_LEASE_MS).toISOString(),
    };
    await upsertPendingRecord(record, storageArea);

    const executeFetch = fetchImpl || fetch;
    let response = null;
    let payload = {};
    try {
      response = await executeFetch(`${record.connection.webApiBase}/api/intake/candidates`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
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
        const safeResult = sanitizeResult(payload);
        const success = classifySuccessfulStatus(safeResult);
        const nextRecord = clearLeaseFields({
          ...record,
          status: success.status,
          statusLabel: success.statusLabel,
          message: success.message,
          updatedAt: nowIso(),
          webResult: safeResult,
        });
        if (success.status === "failed") {
          await upsertPendingRecord(nextRecord, storageArea);
          return nextRecord;
        }
        return finalizeCompletedTransition(nextRecord, storageArea);
      }
    } catch (_error) {
      response = null;
      payload = {};
    }

    return processFailure(record, classifyFailure(response, payload), storageArea);
  }

  async function sendQueuedBatch({ settings, batchKey, storageArea, fetchImpl, manualRetry = false }) {
    const existingPromise = sendLocks.get(batchKey);
    if (existingPromise) {
      return existingPromise;
    }
    const leaseOwner = createLeaseOwner();
    const promise = performSend({ settings, batchKey, storageArea, fetchImpl, manualRetry, leaseOwner }).finally(() => {
      if (sendLocks.get(batchKey) === promise) {
        sendLocks.delete(batchKey);
      }
    });
    sendLocks.set(batchKey, promise);
    return promise;
  }

  async function retryPendingForCurrentConnection({ settings, storageArea, fetchImpl }) {
    const current = await currentRecordForConnection(settings, storageArea);
    if (!current) {
      return current;
    }
    if (String(current.status || "") === "sending" && !isLeaseExpired(current)) {
      return current;
    }
    if (String(current.status || "") === "sending" && isLeaseExpired(current)) {
      await recoverExpiredLease(current.batchKey, storageArea);
    }
    const latest = await currentRecordForConnection(settings, storageArea);
    if (!latest || !["waiting_retry", "failed", "sending"].includes(String(latest.status || ""))) {
      return latest;
    }
    return sendQueuedBatch({ settings, batchKey: latest.batchKey, storageArea, fetchImpl, manualRetry: true });
  }

  async function readCurrentSettings(storageArea) {
    const area = storageArea || chrome.storage.local;
    const values = await area.get({
      apiBase: "http://127.0.0.1:17863",
      apiToken: "",
      connectionMode: "",
      jobTitle: "Boss 推荐牛人",
    });
    return {
      apiBase: values.apiBase,
      apiToken: values.apiToken,
      connectionMode: values.connectionMode,
      jobTitle: values.jobTitle,
    };
  }

  async function processPendingBatches({ storageArea, fetchImpl }) {
    const settings = await readCurrentSettings(storageArea);
    const state = await loadState(storageArea);
    const processed = [];
    for (const batchKey of state.pendingOrder) {
      let pending = state.pendingBatches[batchKey];
      if (!pending) {
        continue;
      }
      if (String(pending.status || "") === "sending") {
        pending = await recoverExpiredLease(batchKey, storageArea);
      }
      if (!pending || !["pending", "waiting_retry"].includes(String(pending.status || ""))) {
        continue;
      }
      if (Number(pending.attemptCount || 0) >= MAX_AUTO_ATTEMPTS) {
        const exhausted = clearLeaseFields({
          ...pending,
          status: "failed",
          statusLabel: "发送失败",
          message: "自动重试次数已达上限，请手动重试。",
          errorCode: "retry_limit_reached",
          updatedAt: nowIso(),
        });
        await upsertPendingRecord(exhausted, storageArea);
        processed.push(exhausted);
        continue;
      }
      processed.push(await sendQueuedBatch({ settings, batchKey, storageArea, fetchImpl }));
    }
    return processed;
  }

  async function hasAutoRetryablePending(storageArea) {
    const state = await loadState(storageArea);
    return state.pendingOrder.some((batchKey) => {
      const record = state.pendingBatches[batchKey];
      if (!record) {
        return false;
      }
      if (String(record.status || "") === "pending") {
        return true;
      }
      if (String(record.status || "") === "waiting_retry" && Number(record.attemptCount || 0) < MAX_AUTO_ATTEMPTS) {
        return true;
      }
      if (String(record.status || "") === "sending") {
        return true;
      }
      return false;
    });
  }

  async function getStatusView({ settings, storageArea }) {
    const { record, legacyBlocked } = await getStatusRecordsForConnection(settings, storageArea);
    const view = await formatStatus(record, settings, legacyBlocked);
    return { record, legacyBlocked, view };
  }

  globalThis.BossLocalWebIntakeSender = {
    RETRY_ALARM_NAME,
    RETRY_ALARM_DELAY_MINUTES,
    MAX_AUTO_ATTEMPTS,
    SEND_LEASE_MS,
    sanitizeResult,
    buildPendingRecord,
    queueCapturedBatch,
    sendQueuedBatch,
    retryPendingForCurrentConnection,
    processPendingBatches,
    hasAutoRetryablePending,
    getStatusView,
    readCurrentSettings,
    recoverExpiredLease,
    clearLeaseFields,
    isLeaseExpired,
    hasBrokenLeaseTiming,
    nowMs,
    createCompletedWriteFailedRecord,
    finalizeCompletedTransition,
    WebIntakeStorageError,
  };
})(globalThis);
