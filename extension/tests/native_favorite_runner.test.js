const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXTENSION_DIR = path.resolve(__dirname, "..");

function loadExecutionContract() {
  const context = { URL };
  context.globalThis = context;
  vm.runInNewContext(
    fs.readFileSync(path.join(EXTENSION_DIR, "favorite_execution.js"), "utf8"),
    context,
    { filename: "favorite_execution.js" },
  );
  return context.__bossNativeFavoriteExecutionContract;
}

function response(result, ok = true, status = 200) {
  return {
    ok,
    status,
    async json() {
      return ok ? { ok: true, result } : { ok: false, error: String(result) };
    },
  };
}

function favoriteTask(overrides = {}) {
  return {
    task_id: 71,
    batch_id: 19,
    claim_token: "claim-71",
    platform: "boss",
    write_policy: "write_allowed",
    platform_identity: { attribute: "data-geekid", value: "trusted-71" },
    source_page_context: {
      tab_id: 91,
      document_id: "source-doc-91",
      platform: "boss",
      source_url: "https://www.zhipin.com/web/chat/recommend",
      candidate_documents: [{
        frame_id: 7,
        document_id: "candidate-doc-7",
        frame_url: "https://www.zhipin.com/web/frame/recommend/",
      }],
    },
    config_snapshot: { favorite_interval_seconds: 3 },
    attempt_count: 0,
    max_attempts: 2,
    source_tab_id: 91,
    ...overrides,
  };
}

function loadRunner({
  claims,
  executionResults,
  verificationClaims = [],
  verificationResults = [],
  initialStatus = null,
  sourceValidationResult = { ok: true },
  batchStatus = { status: "completed", pending_verification: 0 },
}) {
  const requests = [];
  const stored = [];
  const context = {
    URL,
    location: { href: "https://www.zhipin.com/web/chat/recommend" },
    setTimeout(callback) { callback(); },
    clearTimeout() {},
    chrome: {
      runtime: {
        onMessage: { addListener() {} },
        async sendMessage(message) {
          if (message.type === "native_favorite_execute") {
            return { ok: true, result: await executionResults.shift() };
          }
          if (message.type === "native_favorite_verify") {
            return { ok: true, result: await verificationResults.shift() };
          }
          if (message.type === "native_favorite_validate_source_context") {
            return { ok: true, result: sourceValidationResult };
          }
          assert.strictEqual(message.type, "native_favorite_api");
          requests.push({ url: message.path, payload: message.payload });
          if (message.path === "/api/favorites/claim") {
            return { ok: true, result: claims.shift() ?? null };
          }
          if (message.path === "/api/favorites/result") {
            return {
              ok: true,
              result: { task_id: message.payload.task_id, status: message.payload.status },
            };
          }
          if (message.path === "/api/favorites/retry") {
            return { ok: true, result: { task_id: message.payload.task_id, status: "pending" } };
          }
          if (message.path === "/api/favorites/reconcile") {
            return { ok: true, result: {
              batch_id: 19,
              running: 0,
              pending: 2,
              unknown: 1,
              can_resume_pending: true,
              source_page_context: favoriteTask().source_page_context,
            } };
          }
          if (message.path === "/api/favorites/verification/claim") {
            return { ok: true, result: verificationClaims.shift() ?? null };
          }
          if (message.path === "/api/favorites/verification/result") {
            return { ok: true, result: { task_id: message.payload.task_id, status: message.payload.status } };
          }
          if (message.path === "/api/favorites/status") {
            return { ok: true, result: batchStatus };
          }
          throw new Error(`Unexpected path: ${message.path}`);
        },
      },
      storage: {
        local: {
          async get() {
            return { boss_native_favorite_status: initialStatus };
          },
          async set(value) { stored.push(value); },
        },
      },
    },
  };
  context.globalThis = context;
  vm.runInNewContext(
    fs.readFileSync(path.join(EXTENSION_DIR, "favorite_runner.js"), "utf8"),
    context,
    { filename: "favorite_runner.js" },
  );
  return { runner: context.__bossNativeFavoriteRunner, requests, stored };
}

async function testDestroyedSourceDocumentIsReconciledAsInterruptedAndCannotRestart() {
  const { runner, stored } = loadRunner({
    claims: [],
    executionResults: [],
    initialStatus: {
      running: true,
      batchId: 19,
      phase: "running",
      processed: 2,
      currentTaskId: 73,
      message: "Processing",
    },
  });

  await runner.ready;
  assert.strictEqual(runner.getStatus().phase, "interrupted");
  assert.strictEqual(runner.getStatus().running, false);
  assert.strictEqual(runner.getStatus().requiresManualResolution, true);
  await assert.rejects(
    () => runner.start({
      batchId: 19,
      apiBase: "http://127.0.0.1:17863",
      apiToken: "local-token",
    }),
    /manual resolution/i,
  );
  assert(stored.some((entry) => entry.boss_native_favorite_status?.phase === "interrupted"));
}

async function testPersistedInterruptionSurvivesAnotherReloadAndCanBeReconciled() {
  const { runner, requests } = loadRunner({
    claims: [],
    executionResults: [],
    initialStatus: {
      running: false,
      batchId: 19,
      phase: "interrupted",
      requiresManualResolution: true,
      currentTaskId: 73,
    },
  });
  await runner.ready;
  assert.strictEqual(runner.getStatus().requiresManualResolution, true);
  const status = await runner.resolveInterruption({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });
  assert.strictEqual(status.requiresManualResolution, false);
  assert.strictEqual(status.phase, "paused");
  assert.strictEqual(requests[0].url, "/api/favorites/reconcile");
}

async function testInterruptionStaysLockedWhenSourceContextChanged() {
  const { runner } = loadRunner({
    claims: [],
    executionResults: [],
    sourceValidationResult: { ok: false, reason: "source_page_context_document_mismatch" },
    initialStatus: {
      running: false,
      batchId: 19,
      phase: "interrupted",
      requiresManualResolution: true,
    },
  });
  await runner.ready;
  const status = await runner.resolveInterruption({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });
  assert.strictEqual(status.requiresManualResolution, true);
  assert.strictEqual(status.phase, "interrupted");
  assert.match(status.message, /fresh batch/i);
}

async function testExecutionContractRejectsWrongContextAndAmbiguousFrames() {
  const contract = loadExecutionContract();
  assert.deepStrictEqual(
    { ...contract.validateCandidateDocuments(favoriteTask().source_page_context, [{
      frameId: 7,
      documentId: "replacement-doc",
      result: { frame_url: "https://www.zhipin.com/web/frame/recommend/" },
    }]) },
    { ok: false, reason: "source_candidate_document_mismatch" },
  );
  assert.deepStrictEqual(
    { ...contract.validateSourceContext(favoriteTask(), {
      id: 92,
      url: "https://www.zhipin.com/web/chat/recommend",
    }, "source-doc-91") },
    { ok: false, reason: "source_page_context_tab_mismatch" },
  );
  assert.deepStrictEqual(
    { ...contract.validateSourceContext(favoriteTask(), {
      id: 91,
      url: "https://www.zhipin.com/web/geek/recommend",
    }, "source-doc-91") },
    { ok: false, reason: "source_page_context_url_mismatch" },
  );
  assert.deepStrictEqual(
    { ...contract.aggregateAdapterExecutions([
      { result: { status: "unknown", attempted: true, reason: "favorite_state_active_pending_management_verification" } },
      { result: { status: "unknown", attempted: true, reason: "favorite_state_active_pending_management_verification" } },
    ]) },
    {
      status: "failed",
      attempted: true,
      reason: "multiple_source_frame_identity_matches",
      stop_batch: true,
    },
  );
  assert.deepStrictEqual(
    { ...contract.aggregateManagementClassifications([
      { result: { status: "success", reason: "favorite_management_identity_confirmed" } },
    ], true) },
    {
      status: "success",
      attempted: true,
      reason: "favorite_management_identity_confirmed",
      stop_batch: false,
    },
  );
  assert.deepStrictEqual(
    { ...contract.aggregateManagementClassifications([
      { result: { status: "failed", reason: "not_favorite_management_context" } },
    ], false) },
    {
      status: "failed",
      attempted: false,
      reason: "favorite_management_tab_not_ready",
      stop_batch: true,
    },
  );
}

async function testSourceRunnerUsesDurableCompletedStatusWhenNoTasksRemain() {
  const { runner, requests, stored } = loadRunner({
    claims: [null],
    executionResults: [],
  });

  const finalStatus = await runner.start({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });

  assert.strictEqual(finalStatus.phase, "completed");
  assert.strictEqual(finalStatus.processed, 0);
  assert.deepStrictEqual(
    requests.map((request) => request.url.split("/api/")[1]),
    ["favorites/claim", "favorites/status"],
  );
  assert(stored.some((entry) => entry.boss_native_favorite_status?.phase === "completed"));
}

async function testSourceRunnerContinuesAfterDeferredVerification() {
  const { runner, requests } = loadRunner({
    claims: [favoriteTask(), favoriteTask({ task_id: 72, claim_token: "claim-72" }), null],
    executionResults: [
      { status: "verification_pending", attempted: true, reason: "favorite_state_active_pending_management_verification" },
      { status: "verification_pending", attempted: false, reason: "favorite_state_active_pending_management_verification" },
    ],
    batchStatus: { status: "awaiting_verification", pending_verification: 2 },
  });
  const finalStatus = await runner.start({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });
  assert.strictEqual(finalStatus.phase, "awaiting_verification");
  assert.strictEqual(finalStatus.processed, 2);
  assert.strictEqual(finalStatus.pendingVerification, 2);
  assert.strictEqual(finalStatus.failed, 0);
  assert.strictEqual(requests.filter((request) => request.url.endsWith("/claim")).length, 3);
}

async function testRunnerStopsAfterUnknownWithoutClaimingAnotherTask() {
  const { runner, requests } = loadRunner({
    claims: [favoriteTask(), favoriteTask({ task_id: 72, claim_token: "claim-72" })],
    executionResults: [{
      status: "unknown",
      attempted: true,
      reason: "favorite_management_identity_not_visible",
      method: "native_detail_control+management_identity",
      stop_batch: true,
    }],
  });

  const finalStatus = await runner.start({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });

  assert.strictEqual(finalStatus.phase, "paused");
  assert.strictEqual(finalStatus.processed, 1);
  assert.strictEqual(requests.filter((request) => request.url.endsWith("/claim")).length, 1);
  assert.strictEqual(requests[1].payload.status, "unknown");
}

async function testManualStopFinishesCurrentTaskWithoutClaimingAnother() {
  let finishExecution;
  const pendingExecution = new Promise((resolve) => {
    finishExecution = resolve;
  });
  const { runner, requests } = loadRunner({
    claims: [favoriteTask(), favoriteTask({ task_id: 72, claim_token: "claim-72" })],
    executionResults: [pendingExecution],
  });

  const runPromise = runner.start({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });
  for (let attempt = 0; attempt < 10 && requests.length === 0; attempt += 1) {
    await Promise.resolve();
  }
  runner.stop();
  finishExecution({
    status: "verification_pending",
    attempted: true,
    reason: "favorite_state_active_pending_management_verification",
  });
  const finalStatus = await runPromise;

  assert.strictEqual(finalStatus.phase, "stopped");
  assert.strictEqual(finalStatus.processed, 1);
  assert.strictEqual(requests.filter((request) => request.url.endsWith("/claim")).length, 1);
}

async function testExplicitRetryableFailureRetriesOnceButUnknownNeverRetries() {
  const firstAttempt = favoriteTask();
  const secondAttempt = favoriteTask({ attempt_count: 1 });
  const { runner, requests } = loadRunner({
    claims: [firstAttempt, secondAttempt, null],
    executionResults: [
      {
        status: "failed",
        attempted: false,
        reason: "candidate_detail_not_ready",
        retryable: true,
      },
      {
        status: "verification_pending",
        attempted: true,
        reason: "favorite_state_active_pending_management_verification",
      },
    ],
    batchStatus: { status: "awaiting_verification", pending_verification: 1 },
  });

  const finalStatus = await runner.start({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });

  assert.strictEqual(finalStatus.phase, "awaiting_verification");
  assert.deepStrictEqual(
    requests.map((request) => request.url),
    [
      "/api/favorites/claim",
      "/api/favorites/result",
      "/api/favorites/retry",
      "/api/favorites/claim",
      "/api/favorites/result",
      "/api/favorites/claim",
      "/api/favorites/status",
    ],
  );
}

async function testExecutionBridgeLossIsUnknownAndNeverRetries() {
  const { runner, requests } = loadRunner({
    claims: [favoriteTask(), favoriteTask({ task_id: 72, claim_token: "claim-72" })],
    executionResults: [Promise.reject(new Error("message port closed"))],
  });

  const finalStatus = await runner.start({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });

  assert.strictEqual(finalStatus.phase, "paused");
  assert.strictEqual(requests.filter((request) => request.url.endsWith("/claim")).length, 1);
  assert.strictEqual(requests[1].payload.status, "unknown");
  assert.strictEqual(requests[1].payload.attempted, true);
  assert.strictEqual(requests.some((request) => request.url.endsWith("/retry")), false);
}

async function testManagementRunnerFinalizesDeferredVerification() {
  const verificationTask = favoriteTask({
    status: "verifying",
    source_action_attempted: true,
    claim_token: "verify-71",
  });
  const { runner, requests } = loadRunner({
    claims: [],
    executionResults: [],
    verificationClaims: [verificationTask, null],
    verificationResults: [{
      status: "success",
      attempted: true,
      reason: "favorite_management_identity_confirmed",
    }],
  });
  const finalStatus = await runner.startVerification({
    batchId: 19,
    apiBase: "http://127.0.0.1:17863",
    apiToken: "local-token",
  });
  assert.strictEqual(finalStatus.phase, "verification_completed");
  assert.strictEqual(finalStatus.succeeded, 1);
  assert.deepStrictEqual(
    requests.map((request) => request.url),
    [
      "/api/favorites/verification/claim",
      "/api/favorites/verification/result",
      "/api/favorites/verification/claim",
      "/api/favorites/status",
    ],
  );
}

async function testManagementRunnerPausesAndKeepsInconclusiveItemPending() {
  const { runner, requests } = loadRunner({
    claims: [], executionResults: [],
    verificationClaims: [favoriteTask({
      status: "verifying", source_action_attempted: true, claim_token: "verify-71",
    })],
    verificationResults: [{
      status: "unknown", attempted: true,
      reason: "favorite_management_identity_not_visible", stop_batch: true,
    }],
  });
  const finalStatus = await runner.startVerification({
    batchId: 19, apiBase: "http://127.0.0.1:17863", apiToken: "local-token",
  });
  assert.strictEqual(finalStatus.phase, "verification_paused");
  assert.strictEqual(finalStatus.pendingVerification, 1);
  assert.strictEqual(requests[1].payload.status, "verification_pending");
}

async function runNativeFavoriteRunnerTests() {
  await testExecutionContractRejectsWrongContextAndAmbiguousFrames();
  await testDestroyedSourceDocumentIsReconciledAsInterruptedAndCannotRestart();
  await testPersistedInterruptionSurvivesAnotherReloadAndCanBeReconciled();
  await testInterruptionStaysLockedWhenSourceContextChanged();
  await testSourceRunnerUsesDurableCompletedStatusWhenNoTasksRemain();
  await testSourceRunnerContinuesAfterDeferredVerification();
  await testRunnerStopsAfterUnknownWithoutClaimingAnotherTask();
  await testManualStopFinishesCurrentTaskWithoutClaimingAnother();
  await testExplicitRetryableFailureRetriesOnceButUnknownNeverRetries();
  await testExecutionBridgeLossIsUnknownAndNeverRetries();
  await testManagementRunnerFinalizesDeferredVerification();
  await testManagementRunnerPausesAndKeepsInconclusiveItemPending();
}

module.exports = { runNativeFavoriteRunnerTests };
