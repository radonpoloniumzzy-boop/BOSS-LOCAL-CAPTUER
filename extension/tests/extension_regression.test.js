const assert = require("assert");
const { webcrypto } = require("crypto");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { runNativeFavoriteRunnerTests } = require("./native_favorite_runner.test.js");

const EXTENSION_DIR = path.resolve(__dirname, "..");

function createChromeMock() {
  const store = {};
  const downloadCalls = [];
  return {
    __store: store,
    __downloadCalls: downloadCalls,
    runtime: {
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
      onMessage: { addListener() {} },
    },
    tabs: {
      onRemoved: { addListener() {} },
      async get(id) {
        return { id: Number(id), windowId: 1, url: "https://www.zhipin.com/web/chat/index" };
      },
      async query() {
        return [];
      },
      async sendMessage() {
        return { ok: true };
      },
      async remove() {},
      async update() {},
    },
    scripting: {
      async executeScript() {
        return [];
      },
    },
    storage: {
      local: {
        async get(key) {
          if (typeof key === "string") {
            return { [key]: store[key] };
          }
          return { ...store };
        },
        async set(value) {
          Object.assign(store, value);
        },
      },
    },
    downloads: {
      async download(payload) {
        downloadCalls.push(payload);
        return 527;
      },
      async search() {
        return [];
      },
    },
  };
}

function createFetchMock(contentTypeByUrl = {}) {
  return async function fetchMock(url) {
    const textUrl = String(url || "");
    const contentType = Object.entries(contentTypeByUrl).find(([key]) => textUrl.includes(key))?.[1] || "text/html";
    return {
      ok: true,
      url: textUrl,
      headers: {
        get(name) {
          return String(name || "").toLowerCase() === "content-type" ? contentType : "";
        },
      },
      body: {
        cancel() {},
      },
    };
  };
}

function loadServiceWorker(fetch = createFetchMock()) {
  const chrome = createChromeMock();
  const code = `${fs.readFileSync(path.join(EXTENSION_DIR, "favorite_execution.js"), "utf8")}
${fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8")}
globalThis.__serviceTest = {
  downloadResume,
  executeNativeFavoriteTask,
  getBatchStatus,
  handleMessage,
  handleBatchProgress,
  hasDirectPdfSignal,
  isValidResumeDownload,
  proxyNativeFavoriteApi,
  saveBatchStatus,
  shouldVerifyPdfBeforeDownload,
  stopBatch,
};`;
  const context = {
    URL,
    chrome,
    clearTimeout,
    console,
    crypto: webcrypto,
    fetch,
    globalThis: {},
    setTimeout,
};
  context.globalThis = context;
  vm.runInNewContext(code, context, { filename: "service_worker.js" });
  return { chrome, api: context.__serviceTest };
}

function loadCollectorIdentityApi() {
  const code = `${fs.readFileSync(path.join(EXTENSION_DIR, "identity_contract.js"), "utf8")}
${fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8")}
globalThis.__collectorIdentityTestApi = globalThis.__bossLocalCollectorTest;`;
  const context = {
    URL,
    document: { title: "", body: null },
    globalThis: {},
    HTMLElement: class HTMLElement {},
    location: new URL("https://www.zhipin.com/web/geek/recommend"),
    setTimeout,
  };
  context.globalThis = context;
  vm.runInNewContext(code, context, { filename: "collector.js" });
  return context.__collectorIdentityTestApi;
}

function testBossIdentityEvidenceKeepsIdentifiersAndDropsSecrets() {
  const api = loadCollectorIdentityApi();
  const attributeNode = (entries) => ({
    attributes: entries.map(([name, value]) => ({ name, value })),
  });
  const card = attributeNode([
    ["data-geekid", "encrypted-geek-1"],
    ["data-friend-id", "friend-1"],
    ["data-id", "unrelated-component-id"],
    ["data-user-id", "unrelated-user-id"],
    ["data-token", "must-not-be-collected"],
  ]);
  card.querySelectorAll = () => [
    attributeNode([
      ["data-friend-source", "recommend"],
      ["data-security-id", "security-1"],
      ["data-lid", "lid-1"],
      ["data-job-id", "job-1"],
    ]),
  ];

  const identity = api.extractBossIdentityEvidence(
    card,
    "https://www.zhipin.com/web/geek/detail/example?securityId=url-security&lid=url-lid",
  );

  assert.deepStrictEqual(JSON.parse(JSON.stringify(identity)), {
    platform_uid: "encrypted-geek-1",
    friend_id: "friend-1",
    friend_source: "recommend",
    security_id: "security-1",
    lid: "lid-1",
    job_context_id: "job-1",
    raw_identity: {
      "data-geekid": "encrypted-geek-1",
    },
    raw_action_context: {
      "data-friend-id": "friend-1",
      "data-friend-source": "recommend",
      "data-job-id": "job-1",
      "data-lid": "lid-1",
      "data-security-id": "security-1",
    },
  });
  assert.strictEqual(JSON.stringify(identity).includes("must-not-be-collected"), false);
}

function testBossIdentityEvidenceReadsOnlyImmediateCandidateWrapperAndUsesTrustedMergeKey() {
  const api = loadCollectorIdentityApi();
  const node = (entries = [], parentElement = null, descendants = []) => ({
    attributes: entries.map(([name, value]) => ({ name, value })),
    parentElement,
    querySelectorAll() { return descendants; },
  });
  const wrapper = node([["data-geekid", "wrapper-geek-1"]]);
  const card = node([], wrapper);
  wrapper.querySelectorAll = () => [card];

  const identity = api.extractBossIdentityEvidence(card, "");
  assert.strictEqual(identity.platform_uid, "wrapper-geek-1");
  assert.deepStrictEqual(JSON.parse(JSON.stringify(identity.raw_identity)), {
    "data-geekid": "wrapper-geek-1",
  });

  const sharedContainer = node([["data-geekid", "wrong-shared-geek"]]);
  const identitylessWrapper = node([], sharedContainer);
  const nestedCard = node([], identitylessWrapper);
  identitylessWrapper.querySelectorAll = () => [nestedCard];
  assert.strictEqual(api.extractBossIdentityEvidence(nestedCard, "").platform_uid, "");

  const sharedImmediateWrapper = node([["data-geekid", "wrong-immediate-geek"]]);
  const firstPeer = node([], sharedImmediateWrapper);
  const secondPeer = node([], sharedImmediateWrapper);
  sharedImmediateWrapper.querySelectorAll = () => [firstPeer, secondPeer];
  assert.strictEqual(api.extractBossIdentityEvidence(firstPeer, "").platform_uid, "");

  const observations = new Map();
  api.mergeCollectedCard(observations, {
    raw_card_text: "candidate before active-state update",
    action_platform_uid: "wrapper-geek-1",
    raw_identity: { "data-geekid": "wrapper-geek-1" },
  });
  api.mergeCollectedCard(observations, {
    raw_card_text: "candidate after active-state update",
    action_platform_uid: "wrapper-geek-1",
    raw_identity: { "data-geekid": "wrapper-geek-1" },
  });
  assert.strictEqual(observations.size, 1);
  assert.strictEqual(
    Array.from(observations.values())[0].raw_card_text,
    "candidate after active-state update",
  );
}

function loadBossNativeFavoriteAdapter(identityNodes = [], documentOverrides = {}, contextOverrides = {}) {
  let queryCount = 0;
  const document = {
    querySelectorAll(selector) {
      queryCount += 1;
      return String(selector || "").startsWith("[data-") ? identityNodes : [];
    },
    querySelector() {
      return null;
    },
    addEventListener() {},
    removeEventListener() {},
    documentElement: {},
    ...documentOverrides,
  };
  const context = { clearTimeout, document, globalThis: {}, setTimeout, ...contextOverrides };
  context.globalThis = context;
  const code = `${fs.readFileSync(path.join(EXTENSION_DIR, "identity_contract.js"), "utf8")}
${fs.readFileSync(path.join(EXTENSION_DIR, "favorite_adapter.js"), "utf8")}`;
  vm.runInNewContext(code, context, { filename: "favorite_adapter.js" });
  return {
    adapter: context.__bossNativeFavoriteAdapter,
    getQueryCount: () => queryCount,
  };
}

async function testNativeFavoriteDoesNotUseOldControlAfterUnrelatedDetailMutation() {
  let observerCallback = null;
  let favoriteClickCount = 0;
  let now = 0;
  class FakeMutationObserver {
    constructor(callback) {
      observerCallback = callback;
    }
    observe() {}
    disconnect() {}
  }
  class FakeDate extends Date {
    static now() {
      now += 1000;
      return now;
    }
  }
  const staleControl = { click() { favoriteClickCount += 1; } };
  const reusedDetail = {
    contains() { return true; },
    querySelector(selector) {
      if (selector === ".like-icon.like-icon-active") return null;
      if (selector.includes(".like-icon-and-text")) return staleControl;
      return null;
    },
  };
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-1", () => {
    observerCallback?.([{ target: reusedDetail }]);
  });
  const { adapter } = loadBossNativeFavoriteAdapter(
    [candidate],
    {
      querySelector(selector) {
        return selector === ".resume-item-detail" ? reusedDetail : null;
      },
    },
    {
      Date: FakeDate,
      MutationObserver: FakeMutationObserver,
      setTimeout(resolve) { resolve(); },
    },
  );

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: false,
    reason: "candidate_detail_not_ready",
    readiness_diagnostic: {
      candidate_node_connected: false,
      candidate_node_visible: true,
      baseline_detail_present: true,
      baseline_favorite_control_present: true,
      current_detail_present: true,
      current_favorite_control_present: true,
      detail_root_changed: false,
      favorite_control_changed: false,
      mutation_observed: true,
    },
  });
  assert.strictEqual(favoriteClickCount, 0);
}

async function testNativeFavoriteReadinessDiagnosticReportsRemovedDetailAsChanged() {
  let observerCallback = null;
  let now = 0;
  class FakeMutationObserver {
    constructor(callback) { observerCallback = callback; }
    observe() {}
    disconnect() {}
  }
  class FakeDate extends Date {
    static now() { now += 1000; return now; }
  }
  const favoriteControl = {};
  const baselineDetail = {
    contains() { return true; },
    querySelector(selector) {
      return selector.includes(".like-icon-and-text") ? favoriteControl : null;
    },
  };
  let currentDetail = baselineDetail;
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-removed", () => {
    currentDetail = null;
    observerCallback?.([{ target: baselineDetail }]);
  });
  const { adapter } = loadBossNativeFavoriteAdapter(
    [candidate],
    { querySelector(selector) { return selector === ".resume-item-detail" ? currentDetail : null; } },
    { Date: FakeDate, MutationObserver: FakeMutationObserver, setTimeout(resolve) { resolve(); } },
  );

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-removed" },
  });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(result.readiness_diagnostic)), {
    candidate_node_connected: false,
    candidate_node_visible: true,
    baseline_detail_present: true,
    baseline_favorite_control_present: true,
    current_detail_present: false,
    current_favorite_control_present: false,
    detail_root_changed: true,
    favorite_control_changed: true,
    mutation_observed: true,
  });
}

async function testNativeFavoriteReportsControlledRestrictionCodeAfterAttempt() {
  let currentDetail = { querySelector() { return null; } };
  let restrictionVisible = false;
  const favoriteControl = { click() { restrictionVisible = true; } };
  const updatedDetail = {
    querySelector(selector) {
      if (selector === ".like-icon.like-icon-active") return null;
      if (selector.includes(".like-icon-and-text")) return favoriteControl;
      return null;
    },
  };
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-restricted", () => {
    currentDetail = updatedDetail;
  });
  const restrictionSurface = { textContent: "操作频繁，请稍后再试" };
  const { adapter } = loadBossNativeFavoriteAdapter([candidate], {
    querySelector(selector) {
      return selector === ".resume-item-detail" ? currentDetail : null;
    },
    querySelectorAll(selector) {
      if (selector === "[data-geekid]") return [candidate];
      if (String(selector).includes("[role='dialog']")) {
        return restrictionVisible ? [restrictionSurface] : [];
      }
      return [];
    },
  });

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-restricted" },
  });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "unknown",
    attempted: true,
    reason: "platform_restriction_after_favorite_attempt",
    restriction_code: "platform_rate_or_risk_restriction",
  });
}

async function testNativeFavoriteStopsForDeepTrustedInterveningSelection() {
  let trustedClickListener = null;
  let favoriteClickCount = 0;
  let active = false;
  class FakeElement {
    constructor(parentElement = null, geekId = "") {
      this.parentElement = parentElement;
      this.geekId = geekId;
    }
    getAttribute(name) {
      return name === "data-geekid" ? this.geekId : null;
    }
    closest() {
      let current = this;
      while (current) {
        if (current.geekId) return current;
        current = current.parentElement;
      }
      return null;
    }
  }
  const otherCandidate = new FakeElement(null, "other-geek");
  let deepTarget = otherCandidate;
  for (let depth = 0; depth < 11; depth += 1) {
    deepTarget = new FakeElement(deepTarget);
  }
  const originalDetail = { querySelector: () => null };
  const updatedDetail = {
    querySelector(selector) {
      if (selector === ".like-icon.like-icon-active") return active ? {} : null;
      if (selector.includes(".like-icon-and-text")) {
        return { click() { favoriteClickCount += 1; active = true; } };
      }
      return null;
    },
  };
  let currentDetail = originalDetail;
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-1", () => {
    currentDetail = updatedDetail;
    trustedClickListener?.({ isTrusted: true, target: deepTarget });
  });
  const { adapter } = loadBossNativeFavoriteAdapter(
    [candidate],
    {
      addEventListener(type, listener) {
        if (type === "click") trustedClickListener = listener;
      },
      querySelector(selector) {
        return selector === ".resume-item-detail" ? currentDetail : null;
      },
    },
    { Element: FakeElement },
  );

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: false,
    reason: "candidate_selection_changed",
  });
  assert.strictEqual(favoriteClickCount, 0);
}

async function testNativeFavoriteUsesUniqueCausalIdentityJoinAndAwaitsManagementVerification() {
  let candidateClickCount = 0;
  let favoriteClickCount = 0;
  let active = false;
  const originalDetail = { querySelector: () => null };
  const favoriteControl = {
    click() {
      favoriteClickCount += 1;
      active = true;
    },
  };
  const updatedDetail = {
    querySelector(selector) {
      if (selector === ".like-icon.like-icon-active") return active ? {} : null;
      if (selector.includes(".like-icon-and-text")) return favoriteControl;
      return null;
    },
  };
  let currentDetail = originalDetail;
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-1", () => {
    candidateClickCount += 1;
    currentDetail = updatedDetail;
  });
  const { adapter } = loadBossNativeFavoriteAdapter([candidate], {
    querySelector(selector) {
      return selector === ".resume-item-detail" ? currentDetail : null;
    },
  });

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "unknown",
    attempted: true,
    reason: "favorite_state_active_pending_management_verification",
  });
  assert.strictEqual(candidateClickCount, 1);
  assert.strictEqual(favoriteClickCount, 1);
}

async function testNativeFavoriteTreatsThrowDuringFavoriteClickAsUnknown() {
  const originalDetail = { querySelector: () => null };
  const updatedDetail = {
    querySelector(selector) {
      if (selector === ".like-icon.like-icon-active") return null;
      if (selector.includes(".like-icon-and-text")) {
        return { click() { throw new Error("page handler failed after dispatch"); } };
      }
      return null;
    },
  };
  let currentDetail = originalDetail;
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-1", () => {
    currentDetail = updatedDetail;
  });
  const { adapter } = loadBossNativeFavoriteAdapter([candidate], {
    querySelector(selector) {
      return selector === ".resume-item-detail" ? currentDetail : null;
    },
  });

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "unknown",
    attempted: true,
    reason: "favorite_control_click_uncertain",
  });
}

async function testNativeFavoriteSkipsWriteAndAwaitsManagementVerificationForActiveDetail() {
  let favoriteClickCount = 0;
  const originalDetail = { querySelector: () => null };
  const updatedDetail = {
    querySelector(selector) {
      if (selector === ".like-icon.like-icon-active") return {};
      if (selector.includes(".like-icon-and-text")) {
        return { click() { favoriteClickCount += 1; } };
      }
      return null;
    },
  };
  let currentDetail = originalDetail;
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-1", () => {
    currentDetail = updatedDetail;
  });
  const { adapter } = loadBossNativeFavoriteAdapter([candidate], {
    querySelector(selector) {
      return selector === ".resume-item-detail" ? currentDetail : null;
    },
  });

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "unknown",
    attempted: false,
    reason: "favorite_state_active_pending_management_verification",
  });
  assert.strictEqual(favoriteClickCount, 0);
}

async function testNativeFavoriteRejectsNonBossPlatformBeforeReadingThePage() {
  const { adapter, getQueryCount } = loadBossNativeFavoriteAdapter([
    bossIdentityNode("data-geek-id", "trusted-geek-1"),
  ]);

  const result = await adapter.favoriteOne({
    platform: "liepin",
    platform_identity: { attribute: "data-geek-id", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: false,
    reason: "unsupported_platform",
  });
  assert.strictEqual(getQueryCount(), 0);
}

function bossIdentityNode(attributeName, value, onClick = () => {}) {
  return {
    click: onClick,
    getAttribute(name) {
      return name === attributeName ? value : null;
    },
  };
}

function loadBossFavoriteManagementVerifier(identityNodes = [], topPath = "/web/chat/interaction", options = {}) {
  const document = {
    querySelectorAll(selector) {
      return selector === "li.tab-item.curr" ? (options.markers || []) : identityNodes;
    },
  };
  const context = {
    crypto: webcrypto,
    document,
    getComputedStyle(element) {
      return element.hiddenStyle
        ? { display: "block", visibility: "hidden", opacity: "1" }
        : { display: "block", visibility: "visible", opacity: "1" };
    },
    globalThis: {},
    location: { hostname: "www.zhipin.com", pathname: options.framePath || "/web/frame/recommend/" },
    top: { location: { hostname: "www.zhipin.com", pathname: topPath } },
    TextEncoder,
  };
  context.globalThis = context;
  const code = `${fs.readFileSync(path.join(EXTENSION_DIR, "identity_contract.js"), "utf8")}
${fs.readFileSync(path.join(EXTENSION_DIR, "favorite_management_verifier.js"), "utf8")}`;
  vm.runInNewContext(code, context, { filename: "favorite_management_verifier.js" });
  return context.__bossFavoriteManagementVerifier;
}

async function testNativeFavoriteRefusesWriteWhenPlatformRestrictionIsVisible() {
  let candidateClickCount = 0;
  const candidate = bossIdentityNode("data-geekid", "trusted-geek-1", () => {
    candidateClickCount += 1;
  });
  const restriction = {
    textContent: "操作频繁，请稍后再试",
    getClientRects() { return [{}]; },
  };
  const { adapter } = loadBossNativeFavoriteAdapter(
    [candidate],
    {
      querySelectorAll(selector) {
        if (String(selector).startsWith("[data-")) return [candidate];
        if (String(selector).includes("[role='dialog']")) return [restriction];
        return [];
      },
    },
    {
      getComputedStyle() {
        return { display: "block", visibility: "visible", opacity: "1" };
      },
    },
  );

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: false,
    reason: "platform_rate_or_risk_restriction",
  });
  assert.strictEqual(candidateClickCount, 0);
}

async function testNativeFavoriteWorkerRejectsWrongSourceTabBeforeAnyWrite() {
  const { api } = loadServiceWorker();
  const result = await api.executeNativeFavoriteTask(
    {
      platform: "boss",
      write_policy: "establish_or_verify",
      platform_identity: { attribute: "data-geekid", value: "trusted-71" },
      source_page_context: {
        tab_id: 91,
        document_id: "source-doc-91",
        platform: "boss",
        source_url: "https://www.zhipin.com/web/chat/recommend",
      },
    },
    {
      frameId: 0,
      documentId: "source-doc-91",
      tab: { id: 92, url: "https://www.zhipin.com/web/chat/recommend" },
    },
  );
  assert.strictEqual(result.ok, true);
  assert.deepStrictEqual(
    { ...result.result },
    {
      status: "failed",
      attempted: false,
      reason: "source_page_context_tab_mismatch",
      method: "source_context_guard",
      stop_batch: true,
    },
  );
}

async function testNativeFavoriteSourcePhaseWorksWithOnlyOneBossPage() {
  const { chrome, api } = loadServiceWorker();
  chrome.tabs.query = async () => [
    { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
  ];
  chrome.scripting.executeScript = async (request) => {
    if (request.files) return [];
    if (Array.isArray(request.target?.documentIds)) {
      return [{ frameId: 7, documentId: "candidate-doc-7", result: {
        status: "unknown",
        attempted: true,
        reason: "favorite_state_active_pending_management_verification",
      } }];
    }
    return [
      { frameId: 0, documentId: "source-doc-91", result: {
        frame_url: "https://www.zhipin.com/web/chat/recommend",
        restriction: "",
        identity_match_count: 0,
      } },
      { frameId: 7, documentId: "candidate-doc-7", result: {
        frame_url: "https://www.zhipin.com/web/frame/recommend/",
        restriction: "",
        identity_match_count: 1,
      } },
    ];
  };
  const result = await api.executeNativeFavoriteTask(favoriteTaskForWorker(), {
    frameId: 0,
    documentId: "source-doc-91",
    tab: { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
  });
  assert.strictEqual(result.result.status, "verification_pending");
  assert.strictEqual(result.result.attempted, true);
  assert.strictEqual(result.result.stop_batch, false);
}

async function testNativeFavoriteManagementPhaseVerifiesInCurrentSinglePage() {
  const { chrome, api } = loadServiceWorker();
  chrome.tabs.query = async () => [
    { id: 93, url: "https://www.zhipin.com/web/chat/interaction" },
  ];
  chrome.scripting.executeScript = async (request) => {
    if (request.files) return [];
    if (request.target?.allFrames) {
      return [{ frameId: 7, documentId: "management-candidate-doc", result: {} }];
    }
    return [{ result: {
      status: "success",
      attempted: true,
      reason: "favorite_management_identity_confirmed",
    } }];
  };
  const result = await api.handleMessage({
    type: "native_favorite_verify",
    task: {
      task_id: 71,
      batch_id: 19,
      platform: "boss",
      platform_identity: { attribute: "data-geekid", value: "trusted-71" },
      source_action_attempted: true,
      source_tab_id: 93,
    },
  }, {
    frameId: 0,
    documentId: "management-top-doc",
    tab: { id: 93, url: "https://www.zhipin.com/web/chat/interaction" },
  });
  assert.strictEqual(result.result.status, "success");
  assert.strictEqual(result.result.reason, "favorite_management_identity_confirmed");
}

async function testNativeFavoriteWrongManagementContextStaysPending() {
  const { chrome, api } = loadServiceWorker();
  chrome.tabs.query = async () => [
    { id: 93, url: "https://www.zhipin.com/web/chat/interaction" },
  ];
  chrome.scripting.executeScript = async (request) => {
    if (request.files) return [];
    if (request.target?.allFrames) {
      return [{ frameId: 0, documentId: "wrong-context", result: {} }];
    }
    return [{ result: {
      status: "failed",
      attempted: true,
      reason: "not_favorite_management_context",
    } }];
  };
  const result = await api.handleMessage({
    type: "native_favorite_verify",
    task: {
      platform: "boss",
      platform_identity: { attribute: "data-geekid", value: "trusted-71" },
      source_action_attempted: false,
      source_tab_id: 93,
    },
  }, {
    frameId: 0,
    tab: { id: 93, url: "https://www.zhipin.com/web/chat/interaction" },
  });
  assert.strictEqual(result.result.status, "unknown");
  assert.strictEqual(result.result.stop_batch, true);
}

async function testNativeFavoriteManagementPhaseRejectsAnotherBossTabWithoutConsumingTask() {
  const { api } = loadServiceWorker();
  const result = await api.handleMessage({
    type: "native_favorite_verify",
    task: {
      platform: "boss",
      platform_identity: { attribute: "data-geekid", value: "trusted-71" },
      source_action_attempted: true,
      source_tab_id: 91,
    },
  }, {
    frameId: 0,
    tab: { id: 104, url: "https://www.zhipin.com/web/chat/interaction" },
  });
  assert.strictEqual(result.result.status, "unknown");
  assert.strictEqual(result.result.reason, "favorite_management_same_source_tab_required");
  assert.strictEqual(result.result.stop_batch, true);
}

async function testNativeFavoriteApiProxyRejectsExternalHostsAndArbitraryPaths() {
  let fetchCount = 0;
  const { api } = loadServiceWorker(async () => {
    fetchCount += 1;
    throw new Error("must not fetch");
  });
  const external = await api.proxyNativeFavoriteApi({
    apiBase: "https://example.com",
    apiToken: "secret-token",
    path: "/api/favorites/claim",
    payload: { batch_id: 19 },
  });
  const arbitrary = await api.proxyNativeFavoriteApi({
    apiBase: "http://127.0.0.1:17863",
    apiToken: "secret-token",
    path: "/api/import/cards",
    payload: {},
  });
  assert.strictEqual(external.ok, false);
  assert.strictEqual(arbitrary.ok, false);
  assert.strictEqual(fetchCount, 0);
}

async function testNativeFavoriteVerifyOnlyDefersToLaterManagementPhase() {
  const { chrome, api } = loadServiceWorker();
  chrome.tabs.query = async () => [
    { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
    { id: 93, url: "https://www.zhipin.com/web/chat/interaction" },
  ];
  let executionCount = 0;
  chrome.scripting.executeScript = async (request) => {
    executionCount += 1;
    if (request.files) return [];
    if (request.target?.allFrames) {
      return [{ frameId: 0, documentId: "management-doc", result: {} }];
    }
    return [{
      result: {
        status: "already_favorited",
        attempted: false,
        reason: "favorite_management_identity_confirmed",
      },
    }];
  };

  const result = await api.executeNativeFavoriteTask(
    {
      platform: "boss",
      write_policy: "verify_only",
      platform_identity: { attribute: "data-geekid", value: "trusted-71" },
      source_page_context: {
        tab_id: 91,
        document_id: "source-doc-91",
        platform: "boss",
        source_url: "https://www.zhipin.com/web/chat/recommend",
      },
    },
    {
      frameId: 0,
      documentId: "source-doc-91",
      tab: { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
    },
  );

  assert.strictEqual(result.result.status, "verification_pending");
  assert.strictEqual(result.result.attempted, false);
  assert.strictEqual(result.result.method, "source_phase_deferred_verification");
  assert.strictEqual(executionCount, 0);
}

async function testNativeFavoriteWholeTabRestrictionPreflightPreventsFrameWrite() {
  const { chrome, api } = loadServiceWorker();
  chrome.tabs.query = async () => [
    { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
    { id: 93, url: "https://www.zhipin.com/web/chat/interaction" },
  ];
  const requests = [];
  chrome.scripting.executeScript = async (request) => {
    requests.push(request);
    if (request.files) return [];
    if (request.target?.tabId === 93 && request.target?.allFrames) {
      return [{ frameId: 0, documentId: "management-doc", result: {} }];
    }
    if (request.target?.tabId === 93) {
      return [{ result: {
        status: "failed",
        attempted: false,
        reason: "favorite_management_identity_not_visible",
      } }];
    }
    return [
      { frameId: 0, documentId: "source-doc-91", result: {
        frame_url: "https://www.zhipin.com/web/chat/recommend",
        restriction: "platform_rate_or_risk_restriction",
        identity_match_count: 0,
      } },
      { frameId: 7, documentId: "candidate-doc-7", result: {
        frame_url: "https://www.zhipin.com/web/frame/recommend/",
        restriction: "",
        identity_match_count: 1,
      } },
    ];
  };
  const result = await api.executeNativeFavoriteTask(favoriteTaskForWorker(), {
    frameId: 0,
    documentId: "source-doc-91",
    tab: { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
  });
  assert.strictEqual(result.result.reason, "platform_rate_or_risk_restriction");
  assert.strictEqual(result.result.attempted, false);
  assert.strictEqual(requests.some((request) => Array.isArray(request.target?.documentIds)), false);
}

async function testNativeFavoriteFinalTopContextBarrierPreventsSpaStateWrite() {
  const { chrome, api } = loadServiceWorker();
  chrome.tabs.query = async () => [
    { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
    { id: 93, url: "https://www.zhipin.com/web/chat/interaction" },
  ];
  let sourceInspectionCount = 0;
  const requests = [];
  chrome.scripting.executeScript = async (request) => {
    requests.push(request);
    if (request.files) return [];
    if (request.target?.tabId === 93 && request.target?.allFrames) {
      return [{ frameId: 0, documentId: "management-doc", result: {} }];
    }
    if (request.target?.tabId === 93) {
      return [{ result: {
        status: "failed",
        attempted: false,
        reason: "favorite_management_identity_not_visible",
      } }];
    }
    sourceInspectionCount += 1;
    const topUrl = sourceInspectionCount === 1
      ? "https://www.zhipin.com/web/chat/recommend"
      : "https://www.zhipin.com/web/geek/recommend?job=changed";
    return [
      { frameId: 0, documentId: "source-doc-91", result: {
        frame_url: topUrl,
        restriction: "",
        identity_match_count: 0,
      } },
      { frameId: 7, documentId: "candidate-doc-7", result: {
        frame_url: "https://www.zhipin.com/web/frame/recommend/",
        restriction: "",
        identity_match_count: 1,
      } },
    ];
  };
  const result = await api.executeNativeFavoriteTask(favoriteTaskForWorker(), {
    frameId: 0,
    documentId: "source-doc-91",
    tab: { id: 91, url: "https://www.zhipin.com/web/chat/recommend" },
  });
  assert.strictEqual(result.result.reason, "source_page_context_url_mismatch");
  assert.strictEqual(result.result.attempted, false);
  assert.strictEqual(requests.some((request) => Array.isArray(request.target?.documentIds)), false);
}

function favoriteTaskForWorker() {
  return {
    platform: "boss",
    write_policy: "establish_or_verify",
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
  };
}

function managementIdentityNode(value, visible = true) {
  return {
    hiddenStyle: !visible,
    isConnected: true,
    classList: { contains(name) { return name === "card-inner"; } },
    getAttribute(name) { return name === "data-geekid" ? value : null; },
    getBoundingClientRect() { return { width: 320, height: 120 }; },
  };
}

function favoriteManagementFrameObservations(matchCount = 1, selected = true, topPath = "/web/chat/interaction") {
  const shared = {
    version: "favorite-management-frame-v1",
    inspection_id: "inspection-0001",
    tab_id: 17,
    identity_binding: "sha256:2b4b5e8a4e87c94c8dd4717c78743cc5",
    top_host: "www.zhipin.com",
    top_path: topPath,
    frame_host: "www.zhipin.com",
  };
  return [
    {
      ...shared,
      frame_path: "/web/frame/recommend/interaction",
      favorite_subview_selected: selected,
      identity_match_count: 0,
    },
    {
      ...shared,
      frame_path: "/web/frame/recommend/",
      favorite_subview_selected: false,
      identity_match_count: matchCount,
    },
  ];
}

function favoriteManagementExecutionEnvelope(matchCount = 1, selected = true, topPath = "/web/chat/interaction") {
  return {
    inspection_id: "inspection-0001",
    tab_id: 17,
    executions: favoriteManagementFrameObservations(matchCount, selected, topPath).map((observation, index) => ({
      frame_id: index === 0 ? 540 : 423,
      document_id: index === 0 ? "document-context-0001" : "document-candidate-0001",
      observation,
    })),
  };
}

function favoriteManagementRequest(attempted = true, overrides = {}) {
  return {
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-1" },
    favorite_action_attempted: attempted,
    inspection_id: "inspection-0001",
    tab_id: 17,
    ...overrides,
  };
}

async function testFavoriteManagementVerifierRequiresSelectedFavoriteSubviewObservation() {
  const verifier = loadBossFavoriteManagementVerifier([
    bossIdentityNode("data-geekid", "trusted-geek-1"),
  ]);

  const request = favoriteManagementRequest();
  const result = await verifier.classify(request, favoriteManagementExecutionEnvelope(1, false));

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: true,
    reason: "favorite_management_subview_not_confirmed",
  });
}

async function testFavoriteManagementVerifierInspectsSelectedSubviewAndScopedVisibleIdentity() {
  const request = favoriteManagementRequest();
  const marker = {
    innerText: "收藏牛人",
    getBoundingClientRect() { return { width: 80, height: 24 }; },
  };
  const contextVerifier = loadBossFavoriteManagementVerifier([], "/web/chat/interaction", {
    framePath: "/web/frame/recommend/interaction",
    markers: [marker],
  });
  const candidateVerifier = loadBossFavoriteManagementVerifier([
    managementIdentityNode("trusted-geek-1", true),
    managementIdentityNode("trusted-geek-1", false),
  ]);
  const hiddenMarkerVerifier = loadBossFavoriteManagementVerifier([], "/web/chat/interaction", {
    framePath: "/web/frame/recommend/interaction",
    markers: [{ ...marker, hiddenStyle: true }],
  });

  const contextObservation = await contextVerifier.inspectFrame(request);
  const candidateObservation = await candidateVerifier.inspectFrame(request);
  const hiddenContextObservation = await hiddenMarkerVerifier.inspectFrame(request);

  assert.strictEqual(contextObservation.favorite_subview_selected, true);
  assert.strictEqual(contextObservation.identity_match_count, 0);
  assert.strictEqual(candidateObservation.favorite_subview_selected, false);
  assert.strictEqual(candidateObservation.identity_match_count, 1);
  assert.strictEqual(hiddenContextObservation.favorite_subview_selected, false);
}

async function testFavoriteManagementVerifierConfirmsSuccessAfterAttempt() {
  const verifier = loadBossFavoriteManagementVerifier([
    bossIdentityNode("data-geekid", "trusted-geek-1"),
  ]);

  const request = favoriteManagementRequest();
  const result = await verifier.classify(request, favoriteManagementExecutionEnvelope());

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "success",
    attempted: true,
    reason: "favorite_management_identity_confirmed",
    match_count: 1,
  });
}

async function testFavoriteManagementVerifierConfirmsAlreadyFavoritedWithoutAttempt() {
  const verifier = loadBossFavoriteManagementVerifier([
    bossIdentityNode("data-geekid", "trusted-geek-1"),
  ]);

  const request = favoriteManagementRequest(false);
  const result = await verifier.classify(request, favoriteManagementExecutionEnvelope());

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "already_favorited",
    attempted: false,
    reason: "favorite_management_identity_confirmed",
    match_count: 1,
  });
}

async function testFavoriteManagementVerifierKeepsZeroVisibleMatchesUnknown() {
  const verifier = loadBossFavoriteManagementVerifier([]);

  const request = favoriteManagementRequest();
  const result = await verifier.classify(request, favoriteManagementExecutionEnvelope(0));

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "unknown",
    attempted: true,
    reason: "favorite_management_identity_not_visible",
    match_count: 0,
  });
}

async function testFavoriteManagementVerifierRefusesMultipleTypedMatches() {
  const verifier = loadBossFavoriteManagementVerifier([
    bossIdentityNode("data-geekid", "trusted-geek-1"),
    bossIdentityNode("data-geekid", "trusted-geek-1"),
  ]);

  const request = favoriteManagementRequest();
  const result = await verifier.classify(request, favoriteManagementExecutionEnvelope(2));

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "identity_conflict",
    attempted: true,
    reason: "multiple_favorite_management_identity_matches",
    match_count: 2,
  });
}

async function testFavoriteManagementVerifierRejectsNonManagementContext() {
  const verifier = loadBossFavoriteManagementVerifier(
    [bossIdentityNode("data-geekid", "trusted-geek-1")],
    "/web/chat/recommend",
  );

  const request = favoriteManagementRequest();
  const result = await verifier.classify(
    request,
    favoriteManagementExecutionEnvelope(1, true, "/web/chat/recommend"),
  );

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: true,
    reason: "not_favorite_management_context",
  });
}

async function testFavoriteManagementVerifierRejectsIncompleteIdentity() {
  const verifier = loadBossFavoriteManagementVerifier([]);

  const result = await verifier.classify(favoriteManagementRequest(false, {
    platform_identity: null,
  }), []);

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "identity_incomplete",
    attempted: false,
    reason: "trusted_platform_identity_missing",
  });
}

async function testFavoriteManagementVerifierRejectsNonBooleanAttemptFlag() {
  const verifier = loadBossFavoriteManagementVerifier([
    bossIdentityNode("data-geekid", "trusted-geek-1"),
  ]);

  const result = await verifier.classify(favoriteManagementRequest("false"), favoriteManagementExecutionEnvelope());

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: false,
    reason: "invalid_favorite_action_attempted",
  });
}

async function testFavoriteManagementVerifierRejectsObservationsFromAnotherInspection() {
  const verifier = loadBossFavoriteManagementVerifier([]);
  const request = {
    platform: "boss",
    platform_identity: { attribute: "data-geekid", value: "trusted-geek-2" },
    favorite_action_attempted: true,
    inspection_id: "inspection-current",
    tab_id: 27,
  };
  const observations = favoriteManagementExecutionEnvelope();
  observations.inspection_id = "inspection-stale";
  observations.tab_id = 26;
  observations.executions = observations.executions.map((execution) => ({
    ...execution,
    observation: {
      ...execution.observation,
      inspection_id: "inspection-stale",
      tab_id: 26,
      identity_binding: "sha256:stale",
    },
  }));

  const result = await verifier.classify(request, observations);

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: true,
    reason: "favorite_management_observation_mismatch",
  });
}

async function testFavoriteManagementVerifierRejectsMixedDocumentEnvelope() {
  const verifier = loadBossFavoriteManagementVerifier([]);
  const envelope = favoriteManagementExecutionEnvelope();
  envelope.executions[1].document_id = envelope.executions[0].document_id;

  const result = await verifier.classify(favoriteManagementRequest(), envelope);

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "failed",
    attempted: true,
    reason: "favorite_management_execution_envelope_invalid",
  });
}

async function testNativeFavoriteRefusesIncompleteIdentityWithoutClicking() {
  let pageClickCount = 0;
  const { adapter, getQueryCount } = loadBossNativeFavoriteAdapter([
    bossIdentityNode("data-geek-id", "trusted-geek-1", () => { pageClickCount += 1; }),
  ]);

  const result = await adapter.favoriteOne({ platform: "boss", platform_identity: null });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "identity_incomplete",
    attempted: false,
    reason: "trusted_platform_identity_missing",
  });
  assert.strictEqual(getQueryCount(), 0);
  assert.strictEqual(pageClickCount, 0);
}

async function testNativeFavoriteRefusesAmbiguousTrustedIdentityWithoutClicking() {
  let pageClickCount = 0;
  const nodes = [
    bossIdentityNode("data-geek-id", "trusted-geek-1", () => { pageClickCount += 1; }),
    bossIdentityNode("data-geek-id", "trusted-geek-1", () => { pageClickCount += 1; }),
  ];
  const { adapter } = loadBossNativeFavoriteAdapter(nodes);

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geek-id", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "identity_conflict",
    attempted: false,
    reason: "multiple_trusted_identity_matches",
    match_count: 2,
  });
  assert.strictEqual(pageClickCount, 0);
}

async function testNativeFavoriteRefusesWhenTrustedIdentityIsNotOnThePage() {
  let pageClickCount = 0;
  const { adapter } = loadBossNativeFavoriteAdapter([
    bossIdentityNode("data-encrypt-geek-id", "trusted-geek-1", () => { pageClickCount += 1; }),
  ]);

  const result = await adapter.favoriteOne({
    platform: "boss",
    platform_identity: { attribute: "data-geek-id", value: "trusted-geek-1" },
  });

  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), {
    status: "identity_incomplete",
    attempted: false,
    reason: "trusted_identity_not_found",
    match_count: 0,
  });
  assert.strictEqual(pageClickCount, 0);
}

async function testDownloadEndpointValidation() {
  const { api } = loadServiceWorker();
  const downloadUrl = "https://www.zhipin.com/wflow/zpgeek/download/preview4boss/abc123?d=1&id=xyz";
  assert.strictEqual(api.hasDirectPdfSignal(downloadUrl, ""), false);
  assert.strictEqual(api.isValidResumeDownload(downloadUrl, "candidate.pdf"), false);
  assert.strictEqual(api.shouldVerifyPdfBeforeDownload(downloadUrl, "candidate.pdf"), true);
  assert.strictEqual(api.isValidResumeDownload("https://img.bosszhipin.com/static/file/icon.png", "candidate.pdf"), false);
}

async function testStopGuardIgnoresStaleProgress() {
  const { api } = loadServiceWorker();
  await api.saveBatchStatus({
    running: true,
    stopRequested: false,
    phase: "running",
    mode: "download_only",
    tabId: 7,
    stats: { processed: 1 },
    runtimeLogs: [],
  });

  await api.stopBatch(7, "manual stop");
  let status = await api.getBatchStatus();
  assert.strictEqual(status.running, false);
  assert.strictEqual(status.phase, "stopped");

  await api.handleBatchProgress(
    {
      running: true,
      phase: "running",
      message: "stale runner progress",
      stats: { processed: 99 },
      runtimeLogs: ["stale"],
    },
    { tab: { id: 7, windowId: 1, url: "https://www.zhipin.com/web/chat/index" } },
  );

  status = await api.getBatchStatus();
  assert.strictEqual(status.running, false);
  assert.strictEqual(status.phase, "stopped");
  assert.notStrictEqual(status.message, "stale runner progress");
  assert.notStrictEqual(status.stats.processed, 99);
}

async function testBackgroundDownloadIsCalledAndLogged() {
  const { api, chrome } = loadServiceWorker(createFetchMock({ "real-pdf": "application/pdf" }));
  await api.saveBatchStatus({ running: true, phase: "running", tabId: 7, runtimeLogs: [] });
  const url = "https://www.zhipin.com/wflow/zpgeek/download/real-pdf/abc123?d=1&id=xyz";

  const result = await api.downloadResume({
    url,
    fileName: "BossResumes/candidate.pdf",
    trustedPdf: false,
  });

  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.downloadId, 527);
  assert.strictEqual(chrome.__downloadCalls.length, 1);
  assert.strictEqual(chrome.__downloadCalls[0].url, url);
  const status = await api.getBatchStatus();
  assert(status.runtimeLogs.some((line) => line.includes("background download request")));
  assert(status.runtimeLogs.some((line) => line.includes("background download verified pdf")));
  assert(status.runtimeLogs.some((line) => line.includes("chrome.downloads.download ok")));
}

async function testHtmlPreviewPageIsNotDownloadedAsPdf() {
  const { api, chrome } = loadServiceWorker(createFetchMock({ preview4boss: "text/html" }));
  await api.saveBatchStatus({ running: true, phase: "running", tabId: 7, runtimeLogs: [] });
  const url = "https://www.zhipin.com/wflow/zpgeek/download/preview4boss/abc123?d=1&id=xyz";

  const result = await api.downloadResume({
    url,
    fileName: "BossResumes/candidate.pdf",
    trustedPdf: false,
  });

  assert.strictEqual(result.ok, false);
  assert.strictEqual(chrome.__downloadCalls.length, 0);
  assert(String(result.error || "").includes("不是 PDF"));
  const status = await api.getBatchStatus();
  assert(status.runtimeLogs.some((line) => line.includes("url is not pdf after probe")));
}

function testChatRunnerHasPendingAttachmentFlow() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("async function acceptPendingAttachmentRequests"));
  assert(source.includes("isPendingAttachmentRequestText"));
  assert(source.includes("accepted pending attachment requests"));
  assert(source.includes("includePending: true"));
  assert(source.includes("pendingAccept"));
}

function testChatRunnerHandlesTwoResumeRequestButtons() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("topRequestResume"));
  assert(source.includes("isLikelyHeaderResumeActionButton"));
  assert(source.includes("waitForRequestResumeButton"));
  assert(source.includes("messageContainer?.contains(node)"));
  assert(source.includes("isLikelyRequestResumeAction"));
  assert(source.includes("isRequestResumeButtonUsable"));
  assert(source.includes("messageOnly"));
  assert(source.includes("双方回复后可用"));
}

function testBatchModesAreSeparated() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("已完成 ${runnerState.currentSession} 的话术发送和求简历/附件简历操作。"));
  assert(source.includes("async function requestAndDownload"));
  assert(source.includes("async function processDownloadOnlySession"));
  assert(!source.includes("request flow download ok"));
  assert(!source.includes("开始等待附件简历"));
}

function testPreviewClickAvoidsAttachmentCardFalsePositive() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("async function openAttachmentPreview"));
  assert(source.includes("function findPreviewTargets"));
  assert(source.includes("isExplicitPreviewActionText"));
  assert(source.includes("open preview attempt"));
  assert(source.includes("messageContainer && messageContainer.contains(node)"));
  assert(source.includes("已找到预览入口，但未能打开附件预览。"));
}

function testBatchPausesOnVerification() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("function detectAccountVerificationBlock"));
  assert(source.includes("账号登录异常"));
  assert(source.includes("检测到账号验证/登录异常"));
  assert(source.includes("batchActionDelayMs"));
}

function testBatchThrottlingAndLimit() {
  const runner = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(runner.includes("function hasReachedBatchLimit"));
  assert(runner.includes("本批次已达到"));
  assert(runner.includes("maxBatchSessions"));
  assert(runner.includes("5000"));
  assert(popup.includes("batchActionDelaySeconds: 5"));
  assert(popup.includes("maxBatchSessions: 50"));
  assert(html.includes("每人间隔秒数"));
  assert(html.includes("每批最多人数"));
}

function testRequestResumeConfirmIsRequired() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("waitForConfirmButton(3600"));
  assert(source.includes("function findRequestResumeConfirmButton"));
  assert(source.includes("request confirm button found"));
  assert(source.includes("request confirm still visible, retry same button"));
  assert(source.includes("findDialogLikeAncestorText"));
}

function testBatchRequestSkipsAlreadyRequestedConversation() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  assert(source.includes("function hasSentResumeRequestInConversation"));
  assert(source.includes("hasSentResumeRequestInConversation(runnerState.settings)"));
  assert(source.includes("session skipped: resume request already sent"));
  assert(source.includes("已发过求简历"));
  assert(source.includes("简历请求已发送"));
  assert(source.includes("buildResumeRequestHistoryPatterns"));
}

function testPreviewToolbarDownloadDoesNotSaveHtmlPreviewPage() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const service = fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8");
  const manifest = fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8");
  const topToolbarClickIndex = source.indexOf("const downloadButton = findVisibleDownloadButton()");
  const frameFallbackIndex = source.indexOf('type: "click_preview_download_button"');
  assert(source.includes("preview click download button"));
  assert(topToolbarClickIndex >= 0);
  assert(frameFallbackIndex > topToolbarClickIndex);
  assert(source.includes("top preview toolbar download"));
  assert(source.includes("frame semantic button"));
  assert(!source.includes("preview direct download url"));
  assert(!source.includes("downloadUrl: directUrl"));
  assert(!source.includes('type: "resolve_active_pdf_url"'));
  assert(!source.includes("fallback card download url"));
  assert(source.includes("function isHtmlDownloadResult"));
  assert(source.includes("html download rejected"));
  assert(source.includes("preview toolbar download failed"));
  assert(source.includes("function findPreviewToolbarDownloadByLayout"));
  assert(source.includes("preview toolbar download candidate"));
  assert(source.includes("preview toolbar layout candidates"));
  assert(source.includes("distanceToCloseLeft(left.rect, closeRect) - distanceToCloseLeft(right.rect, closeRect)"));
  assert(!source.includes("Math.abs(right.rect.right - closeRect.left) - Math.abs(left.rect.right - closeRect.left)"));
  assert(source.includes('type: "click_preview_download_button"'));
  assert(source.includes("preview frame download click"));
  assert(service.includes('case "click_preview_download_button"'));
  assert(service.includes("async function clickPreviewDownloadButtonInFrames"));
  assert(service.includes("target: { tabId: targetTab.id, allFrames: true }"));
  assert(service.includes("button[name='download-pdf']"));
  assert(service.includes("button[name='download-image']"));
  assert(service.includes("semantic download button missing"));
  assert(!service.includes('document.querySelectorAll("button, a, [role=\'button\'], [title], [aria-label], div, span, i, svg")'));
  assert(manifest.includes("https://*.weizhipin.com/*"));
  assert(source.includes('fileNameHint: ""'));
}

function testCollectionSupportsBossAndLiepinAdapters() {
  const collector = fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const manifest = fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8");
  assert(collector.includes("PLATFORM_ADAPTERS"));
  assert(collector.includes('id: "boss"'));
  assert(collector.includes('id: "liepin"'));
  assert(collector.includes("__bossLocalCollectorPlatforms"));
  assert(collector.includes("findCandidateCardsBySelectors"));
  assert(collector.includes("getScrollRoot(platform)"));
  assert(collector.includes("lpt.liepin.com"));
  assert(popup.includes("COLLECT_PLATFORMS"));
  assert(popup.includes('files: ["identity_contract.js", "favorite_adapter.js", "favorite_management_verifier.js", "collector.js"]'));
  assert(popup.includes("async function verifyFavoriteManagementAcrossFrames"));
  assert(popup.includes("target: { tabId, allFrames: true }"));
  assert(popup.includes("document_id: inspection.documentId"));
  assert(popup.includes("source_tab_id: sourceTabId"));
  assert(popup.includes("source_document_id: merged.sourceDocumentId"));
  assert(popup.includes("自动收藏评级"));
  assert(popup.includes("favorite_interval_seconds"));
  assert(popup.includes("getActiveSupportedTab"));
  assert(popup.includes("getActiveBossTab"));
  assert(popup.includes("applyPlatformDefaults"));
  assert(popup.includes("猎聘推荐人才"));
  assert(html.includes("猎聘推荐页"));
  assert(manifest.includes("https://*.liepin.com/*"));
  assert(manifest.includes("Recruiting Local Capture"));
}

function testAutoScrollCanBePausedFromPopup() {
  const collector = fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(html.includes('id="pauseScroll"'));
  assert(html.includes("暂停滚动"));
  assert(popup.includes("requestScrollPause"));
  assert(popup.includes("resetScrollPause"));
  assert(popup.includes("__bossLocalRequestScrollPause"));
  assert(collector.includes("__bossLocalRequestScrollPause"));
  assert(collector.includes("__bossLocalResetScrollPause"));
  assert(collector.includes("paused-by-user"));
  assert(collector.includes("pause_requested"));
}

function testAutomationAutoButtonStartsDesktopWorkflow() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const contentScript = fs.readFileSync(path.join(EXTENSION_DIR, "content_script.js"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8"));
  assert(html.includes('id="automationAuto"'));
  assert(html.includes("滚动采集 + AI 初筛"));
  assert(popup.includes("async function runAutomation"));
  assert(popup.includes("/api/automation/start"));
  assert(popup.includes("apiToken"));
  assert(popup.includes("X-Boss-Local-Token"));
  assert(contentScript.includes("X-Boss-Local-Token"));
  assert(html.includes('id="apiToken"'));
  assert(popup.includes("automation_requested"));
  assert(popup.includes("AUTO 采集完成，已提交 AI 初筛"));
  assert.strictEqual(manifest.version, "0.6.0");
}

function testNativeFavoriteBatchHasDedicatedRunnerAndManagementVerification() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const service = fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8"));
  assert(html.includes('id="favoriteBatchId"'));
  assert(html.includes('id="favoriteSection"'));
  assert(html.includes('id="startFavoriteBatch"'));
  assert(html.includes('id="stopFavoriteBatch"'));
  assert(html.includes('id="favoriteStatus"'));
  assert(popup.includes("startNativeFavoriteBatch"));
  assert(popup.includes("startNativeFavoriteVerification"));
  assert(popup.includes('command: "start_verification"'));
  assert(popup.includes("verifyFavoriteBatch"));
  assert(popup.includes('automationAutoButton.insertAdjacentElement("afterend", favoriteSection)'));
  assert(popup.includes('files: ["favorite_runner.js"]'));
  assert(popup.includes('type: "boss_native_favorite_command"'));
  assert(service.includes('importScripts("favorite_execution.js")'));
  assert(service.includes('case "native_favorite_execute"'));
  assert(service.includes('case "native_favorite_api"'));
  assert(service.includes("executeNativeFavoriteTask"));
  assert(service.includes("proxyNativeFavoriteApi"));
  assert(service.includes("inspectFavoriteManagementTabs"));
  assert(!service.includes("MAX_MANAGEMENT_VERIFICATION_ATTEMPTS"));
  assert(service.includes('files: ["identity_contract.js", "favorite_adapter.js"]'));
  assert(service.includes('files: ["identity_contract.js", "favorite_management_verifier.js"]'));
  assert.strictEqual(manifest.version, "0.6.0");
}

function testChatAutomationIsOptIn() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_DIR, "manifest.json"), "utf8"));
  const guardCalls = popup.match(/if \(!ensureChatAutomationEnabled\(settings\)\)/g) || [];
  assert(html.includes('id="chatAutomationEnabled"'));
  assert(html.includes('type="checkbox"'));
  assert(popup.includes("chatAutomationEnabled: false"));
  assert(popup.includes('element.type === "checkbox"'));
  assert(popup.includes("function ensureChatAutomationEnabled"));
  assert.strictEqual(guardCalls.length, 2);
  assert(popup.indexOf("if (!ensureChatAutomationEnabled(settings))") < popup.indexOf("await ensureChatRunnerInjected(tab.id)"));
  assert(manifest.description.includes("opt-in Boss chat"));
}

function testScrollWaitDefaultsToThirtyMillisecondsAndHasAdjusters() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(popup.includes("scrollWaitMs: 30"));
  assert(popup.includes("OLD_DEFAULT_SCROLL_WAIT_MS = 1500"));
  assert(popup.includes("scrollWaitDefaultVersion"));
  assert(popup.includes("adjustScrollWait(-30)"));
  assert(popup.includes("adjustScrollWait(30)"));
  assert(popup.includes("Math.max(Number(fields.scrollWaitMs.value || DEFAULTS.scrollWaitMs), 0)"));
  assert(html.includes('id="scrollWaitDown"'));
  assert(html.includes('id="scrollWaitUp"'));
  assert(html.includes('value="30"'));
  assert(html.includes('step="30"'));
}

function testHoldEndScrollStrategyIsDefault() {
  const collector = fs.readFileSync(path.join(EXTENSION_DIR, "collector.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(popup.includes('scrollMode: "hold_end"'));
  assert(popup.includes("scrollModeDefaultVersion"));
  assert(html.includes('value="hold_end"'));
  assert(html.includes("长按 End 键到底"));
  assert(html.includes('value="end"'));
  assert(collector.includes("async function holdEndScroll"));
  assert(collector.includes("dispatchEndKeyDown(target, false)"));
  assert(collector.includes("dispatchEndKeyDown(target, true)"));
  assert(collector.includes("dispatchEndKeyUp(target)"));
  assert(collector.includes("bottom-reached"));
  assert(collector.includes("paused-by-user"));
}

function testRuntimeFingerprintAndVersionAwareRunnerInjection() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const service = fs.readFileSync(path.join(EXTENSION_DIR, "service_worker.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  assert(service.includes("SERVICE_WORKER_DOWNLOAD_CLICK_REVISION"));
  assert(service.includes("runtimeFingerprint"));
  assert(service.includes("manifestVersion"));
  assert(service.includes("chatRunnerVersion"));
  assert(service.includes("runnerReplaced"));
  assert(service.includes("delete globalThis.__bossLocalChatBatchRunner"));
  assert(service.includes("expectedVersion"));
  assert(service.includes("staleRuntime"));
  assert(source.includes("runnerVersion"));
  assert(source.includes("runToken: runnerState.runToken"));
  assert(popup.includes("formatRuntimeFingerprint"));
}

function testPairingCodeParsesAndRejectsInvalidInput() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "pairing.js"), "utf8");
  const context = { URL };
  context.globalThis = context;
  vm.runInNewContext(source, context, { filename: "pairing.js" });

  assert.deepStrictEqual(
    { ...context.BossLocalPairing.parsePairingCode(
      "boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A19001&apiToken=pair-token_123",
    ) },
    { apiBase: "http://127.0.0.1:19001", apiToken: "pair-token_123" },
  );
  assert.throws(
    () => context.BossLocalPairing.parsePairingCode("http://127.0.0.1:17863"),
    /连接码格式无效/,
  );
}

function testPopupSupportsPairingAndAuthenticatedConnectionCheck() {
  const popup = fs.readFileSync(path.join(EXTENSION_DIR, "popup.js"), "utf8");
  const html = fs.readFileSync(path.join(EXTENSION_DIR, "popup.html"), "utf8");
  assert(html.includes('id="pairingCode"'));
  assert(html.includes('id="applyPairingCode"'));
  assert(html.includes('<script src="pairing.js"></script>'));
  assert(popup.includes("applyPairingCodeAndTest"));
  assert(popup.includes("/api/connection/check"));
  assert(popup.includes("Token 不正确"));
}

function testFilenameTemplatesMatchDesktopFixtures() {
  const source = fs.readFileSync(path.join(EXTENSION_DIR, "chat_batch_runner.js"), "utf8");
  const start = source.indexOf("function renderFilenameTemplate(");
  assert(start >= 0, "renderFilenameTemplate must exist");
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  let end = bodyStart;
  for (; end < source.length; end += 1) {
    if (source[end] === "{") depth += 1;
    if (source[end] === "}") depth -= 1;
    if (depth === 0) break;
  }
  const functionSource = source.slice(start, end + 1);
  const render = vm.runInNewContext(`(${functionSource})`);
  const fixtures = JSON.parse(
    fs.readFileSync(path.resolve(EXTENSION_DIR, "..", "tests", "fixtures", "filename_templates.json"), "utf8"),
  );
  for (const fixture of fixtures) {
    assert.strictEqual(render(fixture.template, fixture.values), fixture.expected);
  }
}

async function main() {
  await runNativeFavoriteRunnerTests();
  await testNativeFavoriteWorkerRejectsWrongSourceTabBeforeAnyWrite();
  await testNativeFavoriteSourcePhaseWorksWithOnlyOneBossPage();
  await testNativeFavoriteManagementPhaseVerifiesInCurrentSinglePage();
  await testNativeFavoriteWrongManagementContextStaysPending();
  await testNativeFavoriteManagementPhaseRejectsAnotherBossTabWithoutConsumingTask();
  await testNativeFavoriteApiProxyRejectsExternalHostsAndArbitraryPaths();
  await testNativeFavoriteVerifyOnlyDefersToLaterManagementPhase();
  await testNativeFavoriteWholeTabRestrictionPreflightPreventsFrameWrite();
  await testNativeFavoriteFinalTopContextBarrierPreventsSpaStateWrite();
  testBossIdentityEvidenceKeepsIdentifiersAndDropsSecrets();
  testBossIdentityEvidenceReadsOnlyImmediateCandidateWrapperAndUsesTrustedMergeKey();
  await testNativeFavoriteReadinessDiagnosticReportsRemovedDetailAsChanged();
  await testNativeFavoriteReportsControlledRestrictionCodeAfterAttempt();
  await testFavoriteManagementVerifierRequiresSelectedFavoriteSubviewObservation();
  await testFavoriteManagementVerifierInspectsSelectedSubviewAndScopedVisibleIdentity();
  await testFavoriteManagementVerifierConfirmsSuccessAfterAttempt();
  await testFavoriteManagementVerifierConfirmsAlreadyFavoritedWithoutAttempt();
  await testFavoriteManagementVerifierKeepsZeroVisibleMatchesUnknown();
  await testFavoriteManagementVerifierRefusesMultipleTypedMatches();
  await testFavoriteManagementVerifierRejectsNonManagementContext();
  await testFavoriteManagementVerifierRejectsIncompleteIdentity();
  await testFavoriteManagementVerifierRejectsNonBooleanAttemptFlag();
  await testFavoriteManagementVerifierRejectsObservationsFromAnotherInspection();
  await testFavoriteManagementVerifierRejectsMixedDocumentEnvelope();
  await testNativeFavoriteUsesUniqueCausalIdentityJoinAndAwaitsManagementVerification();
  await testNativeFavoriteRefusesWriteWhenPlatformRestrictionIsVisible();
  await testNativeFavoriteDoesNotUseOldControlAfterUnrelatedDetailMutation();
  await testNativeFavoriteStopsForDeepTrustedInterveningSelection();
  await testNativeFavoriteTreatsThrowDuringFavoriteClickAsUnknown();
  await testNativeFavoriteSkipsWriteAndAwaitsManagementVerificationForActiveDetail();
  await testNativeFavoriteRejectsNonBossPlatformBeforeReadingThePage();
  await testNativeFavoriteRefusesIncompleteIdentityWithoutClicking();
  await testNativeFavoriteRefusesAmbiguousTrustedIdentityWithoutClicking();
  await testNativeFavoriteRefusesWhenTrustedIdentityIsNotOnThePage();
  await testDownloadEndpointValidation();
  await testStopGuardIgnoresStaleProgress();
  await testBackgroundDownloadIsCalledAndLogged();
  await testHtmlPreviewPageIsNotDownloadedAsPdf();
  testChatRunnerHasPendingAttachmentFlow();
  testChatRunnerHandlesTwoResumeRequestButtons();
  testBatchModesAreSeparated();
  testPreviewClickAvoidsAttachmentCardFalsePositive();
  testBatchPausesOnVerification();
  testBatchThrottlingAndLimit();
  testRequestResumeConfirmIsRequired();
  testBatchRequestSkipsAlreadyRequestedConversation();
  testPreviewToolbarDownloadDoesNotSaveHtmlPreviewPage();
  testCollectionSupportsBossAndLiepinAdapters();
  testAutoScrollCanBePausedFromPopup();
  testAutomationAutoButtonStartsDesktopWorkflow();
  testNativeFavoriteBatchHasDedicatedRunnerAndManagementVerification();
  testChatAutomationIsOptIn();
  testScrollWaitDefaultsToThirtyMillisecondsAndHasAdjusters();
  testHoldEndScrollStrategyIsDefault();
  testRuntimeFingerprintAndVersionAwareRunnerInjection();
  testPairingCodeParsesAndRejectsInvalidInput();
  testPopupSupportsPairingAndAuthenticatedConnectionCheck();
  testFilenameTemplatesMatchDesktopFixtures();
  console.log("extension regression tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
