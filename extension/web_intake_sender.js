(function (globalThis) {
  const {
    buildPayload,
    connectionIdentity,
    sameConnectionIdentity,
    createBatchKey,
  } = globalThis.BossLocalWebIntakeIdentity;
  const {
    loadState,
    upsertPendingRecord,
    moveToCompleted,
    readPendingRecord,
    currentRecordForConnection,
    WebIntakeStorageError,
  } = globalThis.BossLocalWebIntakeStorage;
  const { classifySuccessfulStatus, formatStatus } = globalThis.BossLocalWebIntakeUi;

  const RETRY_ALARM_NAME = "boss_web_intake_retry";
  const RETRY_ALARM_DELAY_MINUTES = 0.25;

  function nowIso() {
    return new Date().toISOString();
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

  function buildPendingFailure(record, message, code, statusLabel) {
    return {
      ...record,
      status: "failed",
      statusLabel: statusLabel || "发送失败",
      message,
      errorCode: code || "request_failed",
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

  async function sendQueuedBatch({ settings, batchKey, storageArea, fetchImpl }) {
    let record = await readPendingRecord(batchKey, storageArea);
    if (!record) {
      return currentRecordForConnection(settings, storageArea);
    }
    const currentIdentity = await connectionIdentity(settings);
    if (!sameConnectionIdentity(record.connection, currentIdentity)) {
      record = {
        ...record,
        status: "failed",
        statusLabel: "等待原连接",
        message: "该待发送批次属于旧连接，不会误发到当前人才库。",
        updatedAt: nowIso(),
      };
      await upsertPendingRecord(record, storageArea);
      return record;
    }

    record = {
      ...record,
      status: "sending",
      statusLabel: "正在发送",
      message: "正在发送到网页工作台...",
      updatedAt: nowIso(),
      attemptCount: Number(record.attemptCount || 0) + 1,
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
        const nextRecord = {
          ...record,
          status: success.status,
          statusLabel: success.statusLabel,
          message: success.message,
          updatedAt: nowIso(),
          webResult: safeResult,
        };
        if (success.status === "failed") {
          await upsertPendingRecord(nextRecord, storageArea);
          return nextRecord;
        }
        return moveToCompleted(nextRecord, storageArea);
      }
    } catch (_error) {
      response = null;
      payload = {};
    }

    const failure = classifyFailure(response, payload);
    const failedRecord = {
      ...record,
      status: failure.status,
      statusLabel: failure.statusLabel,
      message: failure.message,
      errorCode: failure.code,
      updatedAt: nowIso(),
    };
    await upsertPendingRecord(failedRecord, storageArea);
    return failedRecord;
  }

  async function retryPendingForCurrentConnection({ settings, storageArea, fetchImpl }) {
    const current = await currentRecordForConnection(settings, storageArea);
    if (!current || !["waiting_retry", "failed"].includes(String(current.status || ""))) {
      return current;
    }
    return sendQueuedBatch({ settings, batchKey: current.batchKey, storageArea, fetchImpl });
  }

  async function readCurrentSettings(storageArea) {
    const area = storageArea || chrome.storage.local;
    const values = await area.get({
      apiBase: "http://127.0.0.1:17863",
      apiToken: "",
      jobTitle: "Boss 推荐牛人",
    });
    return {
      apiBase: values.apiBase,
      apiToken: values.apiToken,
      jobTitle: values.jobTitle,
    };
  }

  async function processPendingBatches({ storageArea, fetchImpl }) {
    const settings = await readCurrentSettings(storageArea);
    const state = await loadState(storageArea);
    const processed = [];
    for (const batchKey of state.pendingOrder) {
      const pending = state.pendingBatches[batchKey];
      if (!pending || !["pending", "waiting_retry"].includes(String(pending.status || ""))) {
        continue;
      }
      processed.push(await sendQueuedBatch({ settings, batchKey, storageArea, fetchImpl }));
    }
    return processed;
  }

  async function getStatusView({ settings, storageArea }) {
    const record = await currentRecordForConnection(settings, storageArea);
    const view = await formatStatus(record, settings);
    return { record, view };
  }

  globalThis.BossLocalWebIntakeSender = {
    RETRY_ALARM_NAME,
    RETRY_ALARM_DELAY_MINUTES,
    sanitizeResult,
    buildPendingRecord,
    queueCapturedBatch,
    sendQueuedBatch,
    retryPendingForCurrentConnection,
    processPendingBatches,
    getStatusView,
    readCurrentSettings,
    buildPendingFailure,
    WebIntakeStorageError,
  };
})(globalThis);
