(function (globalThis) {
  const {
    sameConnectionIdentity,
    connectionIdentity,
  } = globalThis.BossLocalWebIntakeIdentity;

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
    const message = String(error?.message || error || "").toLowerCase();
    return message.includes("quota") || message.includes("max") || message.includes("space");
  }

  async function withStorageWrite(operation) {
    try {
      return await operation();
    } catch (error) {
      if (isQuotaError(error)) {
        throw new WebIntakeStorageError(
          "storage_quota_exceeded",
          "扩展本地缓存空间已满，无法继续暂存待发送批次。请完成发送或清理历史记录后再试。",
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

  async function loadState(storageArea) {
    const area = storageArea || chrome.storage.local;
    const entries = await area.get(null);
    return parseStoredEntries(entries);
  }

  async function enforcePendingLimit(storageArea, state, batchKey) {
    if (state.pendingBatches[batchKey]) {
      return;
    }
    if (state.pendingOrder.length >= MAX_PENDING_BATCHES) {
      throw new WebIntakeStorageError(
        "pending_limit_exceeded",
        `待发送批次已达到上限 ${MAX_PENDING_BATCHES}，请先完成发送或清理旧批次后再继续。`,
      );
    }
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

  async function upsertPendingRecord(record, storageArea) {
    const area = storageArea || chrome.storage.local;
    const state = await loadState(area);
    await enforcePendingLimit(area, state, record.batchKey);
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
    PENDING_PREFIX,
    COMPLETED_PREFIX,
    MAX_PENDING_BATCHES,
    MAX_COMPLETED_BATCHES,
    WebIntakeStorageError,
    pendingStorageKey,
    completedStorageKey,
    loadState,
    upsertPendingRecord,
    removePendingRecord,
    moveToCompleted,
    readPendingRecord,
    readCompletedRecord,
    currentRecordForConnection,
    sanitizeCompletedRecord,
  };
})(globalThis);
