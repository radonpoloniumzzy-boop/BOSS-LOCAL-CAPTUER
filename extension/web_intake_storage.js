(function (globalThis) {
  const {
    sameConnectionIdentity,
    connectionIdentity,
    normalizeApiBase,
    deriveWebApiBase,
    resolveConnectionMode,
    sha256Hex,
    createBatchKey,
  } = globalThis.BossLocalWebIntakeIdentity;

  const LEGACY_STATE_KEY = "boss_web_intake_state_v2";
  const PENDING_PREFIX = "boss_web_intake_pending_v4:";
  const COMPLETED_PREFIX = "boss_web_intake_completed_v4:";
  const MAX_PENDING_BATCHES = 10;
  const MAX_COMPLETED_BATCHES = 20;
  const LEGACY_PENDING_BLOCKED_MESSAGE = "请切回原连接完成旧批次迁移。";

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

  function stableHash(value) {
    const text = String(value || "");
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
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
          "扩展本地缓存空间已满，请先完成发送或清理历史记录后再试。",
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
    return {
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
      connection: record?.connection || null,
    };
  }

  async function resolveCurrentConnection(storageArea, settingsOverride = null) {
    const stored = settingsOverride || await storageArea.get({
      apiBase: "http://127.0.0.1:17863",
      apiToken: "",
      connectionMode: "",
    });
    const apiBase = normalizeApiBase(stored?.apiBase || "");
    const mode = resolveConnectionMode(stored || {});
    const webApiBase = deriveWebApiBase({ connectionMode: mode, apiBase });
    const token = String(stored?.apiToken || "");
    return {
      mode,
      apiBase,
      webApiBase,
      tokenFingerprint: stableHash(token),
      tokenDigest: await sha256Hex(token),
      legacyKey: stableHash(`${apiBase}|${webApiBase}|${token}`),
    };
  }

  function legacyConnectionMatches(connection, currentConnection) {
    if (!connection || !currentConnection) {
      return false;
    }
    const legacyApiBase = normalizeApiBase(connection.modeApiBase || connection.apiBase || "");
    const legacyWebApiBase = normalizeApiBase(connection.webApiBase || deriveWebApiBase(legacyApiBase));
    const legacyFingerprint = String(connection.tokenFingerprint || "");
    const legacyKey = String(connection.key || "");
    if (!legacyApiBase || !legacyWebApiBase || !legacyFingerprint) {
      return false;
    }
    if (legacyApiBase !== currentConnection.apiBase) {
      return false;
    }
    if (legacyWebApiBase !== currentConnection.webApiBase) {
      return false;
    }
    if (legacyFingerprint !== currentConnection.tokenFingerprint) {
      return false;
    }
    if (legacyKey && legacyKey !== currentConnection.legacyKey) {
      return false;
    }
    return true;
  }

  async function migrateLegacyPendingRecord(record, currentConnection) {
    const safe = sanitizeLegacyPendingRecord(record, record?.batchKey || "");
    if (!safe.connection || !legacyConnectionMatches(safe.connection, currentConnection)) {
      return {
        migrated: null,
        blocked: {
          ...safe,
          status: "failed",
          statusLabel: "等待原连接",
          message: LEGACY_PENDING_BLOCKED_MESSAGE,
        },
      };
    }
    const connection = {
      mode: currentConnection.mode,
      apiBase: currentConnection.apiBase,
      webApiBase: currentConnection.webApiBase,
      tokenDigest: currentConnection.tokenDigest,
    };
    return {
      migrated: {
        ...safe,
        batchKey: await createBatchKey(connection, safe.idempotencyKey),
        connection,
      },
      blocked: null,
    };
  }

  function createScrubbedPendingTransition(record) {
    return {
      batchKey: String(record?.batchKey || ""),
      idempotencyKey: String(record?.idempotencyKey || ""),
      connection: record?.connection || null,
      createdAt: String(record?.createdAt || nowIso()),
      updatedAt: String(record?.updatedAt || nowIso()),
      attemptCount: Number(record?.attemptCount || 0),
      status: String(record?.status || ""),
      statusLabel: String(record?.statusLabel || ""),
      message: String(record?.message || ""),
      errorCode: String(record?.errorCode || ""),
      sendingStartedAt: "",
      leaseOwner: "",
      leaseExpiresAt: "",
      webResult: sanitizeCompletedRecord(record).webResult,
      scrubbedPendingTransition: true,
    };
  }

  function buildLegacyBlockedStatus() {
    return {
      batchKey: "legacy-blocked",
      idempotencyKey: "",
      connection: null,
      status: "failed",
      statusLabel: "等待原连接",
      message: "存在属于旧连接的待发送批次，请切回原连接完成迁移。",
      errorCode: "legacy_connection_mismatch",
      createdAt: nowIso(),
      updatedAt: nowIso(),
      webResult: null,
      legacyBlocked: true,
    };
  }

  async function migrateLegacyState(storageArea, settingsOverride = null) {
    const area = storageArea || chrome.storage.local;
    const allEntries = await area.get(null);
    const legacy = allEntries[LEGACY_STATE_KEY];
    if (!legacy || typeof legacy !== "object") {
      return;
    }

    const state = parseStoredEntries(allEntries);
    const currentConnection = await resolveCurrentConnection(area, settingsOverride);
    const pendingWrites = {};
    const completedWrites = {};
    const blockedLegacy = {};

    for (const [batchKey, record] of Object.entries(legacy.pendingBatches || {})) {
      const safeRecord = sanitizeLegacyPendingRecord(record, batchKey);
      if (state.pendingBatches[safeRecord.batchKey] || state.completedBatches[safeRecord.batchKey]) {
        continue;
      }
      const migrated = await migrateLegacyPendingRecord(safeRecord, currentConnection);
      if (migrated.migrated) {
        pendingWrites[pendingStorageKey(migrated.migrated.batchKey)] = migrated.migrated;
      } else if (migrated.blocked) {
        blockedLegacy[safeRecord.batchKey] = migrated.blocked;
      }
    }

    for (const [batchKey, record] of Object.entries(legacy.completedBatches || {})) {
      const safeRecord = sanitizeLegacyCompletedRecord(record, batchKey);
      if (state.completedBatches[safeRecord.batchKey]) {
        continue;
      }
      completedWrites[completedStorageKey(safeRecord.batchKey)] = safeRecord;
    }

    const writes = { ...pendingWrites, ...completedWrites };
    if (Object.keys(writes).length) {
      await withStorageWrite(() => area.set(writes));
    }

    if (Object.keys(blockedLegacy).length) {
      await withStorageWrite(() =>
        area.set({
          [LEGACY_STATE_KEY]: {
            ...legacy,
            pendingBatches: blockedLegacy,
            pendingOrder: Object.keys(blockedLegacy),
            completedBatches: {},
            completedOrder: [],
          },
        }));
    } else {
      await area.remove(LEGACY_STATE_KEY);
    }

    const migratedState = parseStoredEntries(await area.get(null));
    const overflow = migratedState.completedOrder.slice(MAX_COMPLETED_BATCHES);
    if (overflow.length) {
      await area.remove(overflow.map((batchKey) => completedStorageKey(batchKey)));
    }
  }

  async function loadState(storageArea, settingsOverride = null) {
    const area = storageArea || chrome.storage.local;
    await migrateLegacyState(area, settingsOverride);
    const entries = await area.get(null);
    const state = parseStoredEntries(entries);
    const duplicatePendingKeys = state.pendingOrder.filter(
      (batchKey) => state.completedBatches[batchKey] && state.pendingBatches[batchKey]?.scrubbedPendingTransition,
    );
    if (duplicatePendingKeys.length) {
      await area.remove(duplicatePendingKeys.map((batchKey) => pendingStorageKey(batchKey)));
      const refreshed = await area.get(null);
      return parseStoredEntries(refreshed);
    }
    return state;
  }

  async function enforcePendingLimit(state, batchKey) {
    if (state.pendingBatches[batchKey] || state.completedBatches[batchKey]) {
      return;
    }
    if (state.pendingOrder.length >= MAX_PENDING_BATCHES) {
      throw new WebIntakeStorageError(
        "pending_limit_exceeded",
        `待发送批次已达到上限 ${MAX_PENDING_BATCHES}，请先完成发送或清理旧批次后继续。`,
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
    const scrubbedPending = createScrubbedPendingTransition(record);
    const sanitized = sanitizeCompletedRecord(record);
    await withStorageWrite(() => area.set({ [pendingStorageKey(record.batchKey)]: scrubbedPending }));
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

  async function readLegacyBlockedRecord(storageArea, settingsOverride = null) {
    const area = storageArea || chrome.storage.local;
    await migrateLegacyState(area, settingsOverride);
    const stored = await area.get(LEGACY_STATE_KEY);
    const legacy = stored[LEGACY_STATE_KEY];
    if (!legacy || !Object.keys(legacy.pendingBatches || {}).length) {
      return null;
    }
    return buildLegacyBlockedStatus();
  }

  async function currentRecordForConnection(settings, storageArea) {
    const state = await loadState(storageArea, settings);
    const identity = await connectionIdentity(settings);
    const pending = state.pendingOrder
      .map((batchKey) => state.pendingBatches[batchKey])
      .find((record) => sameConnectionIdentity(record?.connection, identity));
    if (pending) {
      return pending;
    }
    const completed = (
      state.completedOrder
        .map((batchKey) => state.completedBatches[batchKey])
        .find((record) => sameConnectionIdentity(record?.connection, identity)) || null
    );
    if (completed) {
      return completed;
    }
    return null;
  }

  async function getStatusRecordsForConnection(settings, storageArea) {
    const record = await currentRecordForConnection(settings, storageArea);
    const legacyBlocked = await readLegacyBlockedRecord(storageArea, settings);
    return {
      record,
      legacyBlocked,
    };
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
    getStatusRecordsForConnection,
    migrateLegacyState,
    createScrubbedPendingTransition,
    readLegacyBlockedRecord,
    buildLegacyBlockedStatus,
    stableHash,
    LEGACY_PENDING_BLOCKED_MESSAGE,
  };
})(globalThis);
