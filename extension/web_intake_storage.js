(function (globalThis) {
  const { sameConnectionIdentity, connectionIdentity } = globalThis.BossLocalWebIntakeIdentity;

  const LEGACY_STATE_KEY = "boss_web_intake_state_v2";
  const PENDING_PREFIX = "boss_web_intake_pending_v4:";
  const COMPLETED_PREFIX = "boss_web_intake_completed_v4:";
  const MAX_PENDING_BATCHES = 10;
  const MAX_COMPLETED_BATCHES = 20;

  class WebIntakeStorageError extends Error {
    constructor(code, message) {
      super(message);
      this.name = "WebIntakeStorageError";
      this.code = code;
    }
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function pendingStorageKey(batchKey) {
    return `${PENDING_PREFIX}${String(batchKey || "")}`;
  }

  function completedStorageKey(batchKey) {
    return `${COMPLETED_PREFIX}${String(batchKey || "")}`;
  }

  function isQuotaError(error) {
    const message = String(error?.message || error || "");
    return (
      /QUOTA_BYTES/i.test(message)
      || /MAX_ITEMS/i.test(message)
      || /quota exceeded/i.test(message)
      || /exceeds the quota/i.test(message)
    );
  }

  async function withStorageWrite(operation) {
    try {
      return await operation();
    } catch (error) {
      if (isQuotaError(error)) {
        throw new WebIntakeStorageError(
          "storage_quota_exceeded",
          "扩展本地缓存空间已满，无法继续暂存待发送批次。请先完成发送或清理历史记录后再试。",
        );
      }
      throw error;
    }
  }

  function parseStoredEntries(entries) {
    const pending = {};
    const completed = {};
    for (const [key, value] of Object.entries(entries || {})) {
      if (key.startsWith(PENDING_PREFIX) && value && typeof value === "object") {
        pending[String(value.batchKey || key.slice(PENDING_PREFIX.length))] = value;
      }
      if (key.startsWith(COMPLETED_PREFIX) && value && typeof value === "object") {
        completed[String(value.batchKey || key.slice(COMPLETED_PREFIX.length))] = value;
      }
    }
    const sortKeys = (records, field) =>
      Object.keys(records).sort((left, right) => {
        const leftValue = Date.parse(records[left]?.[field] || records[left]?.updatedAt || 0) || 0;
        const rightValue = Date.parse(records[right]?.[field] || records[right]?.updatedAt || 0) || 0;
        return rightValue - leftValue;
      });
    return {
      pendingBatches: pending,
      pendingOrder: sortKeys(pending, "createdAt"),
      completedBatches: completed,
      completedOrder: sortKeys(completed, "completedAt"),
    };
  }

  function sanitizeCompletedRecord(record) {
    const safeResult = record?.webResult || {};
    return {
      batchKey: String(record?.batchKey || ""),
      idempotencyKey: String(record?.idempotencyKey || ""),
      connection: record?.connection || null,
      status: String(record?.status || ""),
      statusLabel: String(record?.statusLabel || ""),
      message: String(record?.message || ""),
      errorCode: String(record?.errorCode || ""),
      createdAt: String(record?.createdAt || nowIso()),
      updatedAt: String(record?.updatedAt || nowIso()),
      completedAt: nowIso(),
      webResult: {
        batch_id: Number(safeResult.batch_id || 0) || null,
        status: String(safeResult.status || ""),
        reused: Boolean(safeResult.reused),
        received_count: Number(safeResult.received_count || 0),
        inserted_candidates: Number(safeResult.inserted_candidates || 0),
        updated_candidates: Number(safeResult.updated_candidates || 0),
        skipped_candidates: Number(safeResult.skipped_candidates || 0),
        failed_candidates: Number(safeResult.failed_candidates || 0),
        total_unique: Number(safeResult.total_unique || 0),
        total_batch_items: Number(safeResult.total_batch_items || 0),
      },
    };
  }

  function sanitizeLegacyCompletedRecord(record, fallbackBatchKey) {
    return sanitizeCompletedRecord({
      batchKey: String(record?.batchKey || fallbackBatchKey || ""),
      idempotencyKey: String(record?.idempotencyKey || record?.idempotency_key || ""),
      connection: record?.connection || null,
      status: String(record?.status || ""),
      statusLabel: String(record?.statusLabel || ""),
      message: String(record?.message || ""),
      errorCode: String(record?.errorCode || ""),
      createdAt: String(record?.createdAt || nowIso()),
      updatedAt: String(record?.updatedAt || nowIso()),
      webResult: record?.webResult || record?.result || {},
    });
  }

  function sanitizeLegacyPendingRecord(record, fallbackBatchKey) {
    const connection = record?.connection || null;
    const safe = {
      ...record,
      batchKey: String(record?.batchKey || fallbackBatchKey || ""),
      idempotencyKey: String(record?.idempotencyKey || record?.idempotency_key || ""),
      createdAt: String(record?.createdAt || nowIso()),
      updatedAt: String(record?.updatedAt || nowIso()),
      attemptCount: Number(record?.attemptCount || 0),
      status: String(record?.status || "pending"),
      statusLabel: String(record?.statusLabel || "等待发送"),
      message: String(record?.message || "采集批次已完成，等待发送到网页工作台。"),
      errorCode: String(record?.errorCode || ""),
      connection,
    };
    if (
      !connection
      || !String(connection.mode || "")
      || !String(connection.apiBase || "")
      || !String(connection.webApiBase || "")
      || !String(connection.tokenDigest || "")
    ) {
      safe.status = "failed";
      safe.statusLabel = "等待原连接";
      safe.message = "该旧批次缺少可验证的连接身份，已阻止自动重发，请切回原连接后手动处理。";
      safe.payload = null;
    }
    return safe;
  }

  async function migrateLegacyState(storageArea) {
    const area = storageArea || chrome.storage.local;
    const allEntries = await area.get(null);
    const legacy = allEntries[LEGACY_STATE_KEY];
    if (!legacy || typeof legacy !== "object") {
      return;
    }

    const state = parseStoredEntries(allEntries);
    const pendingWrites = {};
    const completedWrites = {};
    const completedRemovals = [];

    for (const [batchKey, record] of Object.entries(legacy.pendingBatches || {})) {
      const finalBatchKey = String(record?.batchKey || batchKey);
      if (state.pendingBatches[finalBatchKey] || state.completedBatches[finalBatchKey]) {
        continue;
      }
      pendingWrites[pendingStorageKey(finalBatchKey)] = sanitizeLegacyPendingRecord(record, finalBatchKey);
    }

    for (const [batchKey, record] of Object.entries(legacy.completedBatches || {})) {
      const finalBatchKey = String(record?.batchKey || batchKey);
      if (state.completedBatches[finalBatchKey]) {
        continue;
      }
      completedWrites[completedStorageKey(finalBatchKey)] = sanitizeLegacyCompletedRecord(record, finalBatchKey);
    }

    const writes = { ...pendingWrites, ...completedWrites };
    if (Object.keys(writes).length) {
      await withStorageWrite(() => area.set(writes));
    }
    await area.remove(LEGACY_STATE_KEY);

    const migrated = parseStoredEntries(await area.get(null));
    const overflow = migrated.completedOrder.slice(MAX_COMPLETED_BATCHES);
    if (overflow.length) {
      completedRemovals.push(...overflow.map((batchKey) => completedStorageKey(batchKey)));
    }
    if (completedRemovals.length) {
      await area.remove(completedRemovals);
    }
  }

  async function loadState(storageArea) {
    const area = storageArea || chrome.storage.local;
    await migrateLegacyState(area);
    const entries = await area.get(null);
    return parseStoredEntries(entries);
  }

  async function enforcePendingLimit(state, batchKey) {
    if (state.pendingBatches[batchKey] || state.completedBatches[batchKey]) {
      return;
    }
    if (state.pendingOrder.length >= MAX_PENDING_BATCHES) {
      throw new WebIntakeStorageError(
        "pending_limit_exceeded",
        `待发送批次已达到上限 ${MAX_PENDING_BATCHES}，请先完成发送或清理旧批次后再继续。`,
      );
    }
  }

  async function upsertPendingRecord(record, storageArea) {
    const area = storageArea || chrome.storage.local;
    const state = await loadState(area);
    await enforcePendingLimit(state, record.batchKey);
    await withStorageWrite(() => area.set({ [pendingStorageKey(record.batchKey)]: record }));
    return record;
  }

  async function removePendingRecord(batchKey, storageArea) {
    const area = storageArea || chrome.storage.local;
    await area.remove(pendingStorageKey(batchKey));
  }

  async function moveToCompleted(record, storageArea) {
    const area = storageArea || chrome.storage.local;
    const sanitized = sanitizeCompletedRecord(record);
    await withStorageWrite(() => area.set({ [completedStorageKey(record.batchKey)]: sanitized }));
    await area.remove(pendingStorageKey(record.batchKey));
    const state = await loadState(area);
    const overflow = state.completedOrder.slice(MAX_COMPLETED_BATCHES);
    if (overflow.length) {
      await area.remove(overflow.map((batchKey) => completedStorageKey(batchKey)));
    }
    return sanitized;
  }

  async function readPendingRecord(batchKey, storageArea) {
    const area = storageArea || chrome.storage.local;
    const stored = await area.get(pendingStorageKey(batchKey));
    return stored[pendingStorageKey(batchKey)] || null;
  }

  async function readCompletedRecord(batchKey, storageArea) {
    const area = storageArea || chrome.storage.local;
    const stored = await area.get(completedStorageKey(batchKey));
    return stored[completedStorageKey(batchKey)] || null;
  }

  async function currentRecordForConnection(settings, storageArea) {
    const state = await loadState(storageArea);
    const identity = await connectionIdentity(settings);
    const pending = state.pendingOrder
      .map((batchKey) => state.pendingBatches[batchKey])
      .find((record) => sameConnectionIdentity(record?.connection, identity));
    if (pending) {
      return pending;
    }
    return (
      state.completedOrder
        .map((batchKey) => state.completedBatches[batchKey])
        .find((record) => sameConnectionIdentity(record?.connection, identity)) || null
    );
  }

  globalThis.BossLocalWebIntakeStorage = {
    LEGACY_STATE_KEY,
    PENDING_PREFIX,
    COMPLETED_PREFIX,
    MAX_PENDING_BATCHES,
    MAX_COMPLETED_BATCHES,
    WebIntakeStorageError,
    pendingStorageKey,
    completedStorageKey,
    sanitizeCompletedRecord,
    loadState,
    upsertPendingRecord,
    removePendingRecord,
    moveToCompleted,
    readPendingRecord,
    readCompletedRecord,
    currentRecordForConnection,
    migrateLegacyState,
  };
})(globalThis);
