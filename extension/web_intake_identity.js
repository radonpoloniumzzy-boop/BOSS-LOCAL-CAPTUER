(function (globalThis) {
  const WEB_INTAKE_PORT = 17864;
  const DESKTOP_COMPAT_PORT = 17863;
  const DEFAULT_WEB_API_BASE = `http://127.0.0.1:${WEB_INTAKE_PORT}`;
  const DEFAULT_DESKTOP_API_BASE = `http://127.0.0.1:${DESKTOP_COMPAT_PORT}`;

  function trimTrailingSlash(value) {
    return String(value || "").replace(/\/+$/, "");
  }

  function normalizeApiBase(value) {
    let raw = String(value || DEFAULT_DESKTOP_API_BASE).trim() || DEFAULT_DESKTOP_API_BASE;
    if (!/^[a-z][a-z\d+.-]*:\/\//i.test(raw)) {
      raw = `http://${raw}`;
    }
    try {
      const url = new URL(raw);
      if (["localhost", "::1", "[::1]"].includes(url.hostname.toLowerCase())) {
        url.hostname = "127.0.0.1";
      }
      return trimTrailingSlash(url.toString());
    } catch (_error) {
      return trimTrailingSlash(raw);
    }
  }

  function getApiPort(value) {
    try {
      const url = new URL(normalizeApiBase(value));
      if (url.port) {
        return Number(url.port);
      }
      return url.protocol === "https:" ? 443 : 80;
    } catch (_error) {
      return 0;
    }
  }

  function normalizeConnectionMode(value) {
    const mode = String(value || "").trim().toLowerCase();
    return mode === "web" || mode === "desktop" ? mode : "";
  }

  function inferStoredConnectionMode(apiBase) {
    const port = getApiPort(apiBase);
    if (port === WEB_INTAKE_PORT) {
      return "web";
    }
    return "desktop";
  }

  function resolveConnectionMode(settings) {
    return normalizeConnectionMode(settings?.connectionMode);
  }

  function needsConnectionModeConfirmation(settings) {
    return settings?.connectionModeConfirmed === false;
  }

  function isWebWorkbenchMode(settings) {
    return resolveConnectionMode(settings) === "web";
  }

  function deriveWebApiBase(settingsOrApiBase) {
    if (settingsOrApiBase && typeof settingsOrApiBase === "object") {
      if (normalizeConnectionMode(settingsOrApiBase.connectionMode) === "web") {
        return normalizeApiBase(settingsOrApiBase.apiBase || DEFAULT_WEB_API_BASE);
      }
      return DEFAULT_WEB_API_BASE;
    }
    return DEFAULT_WEB_API_BASE;
  }

  async function sha256Hex(value) {
    const cryptoApi = globalThis.crypto?.subtle;
    if (!cryptoApi) {
      throw new Error("Web Crypto API is unavailable.");
    }
    const data = new TextEncoder().encode(String(value || ""));
    const digest = await cryptoApi.digest("SHA-256", data);
    return Array.from(new Uint8Array(digest))
      .map((item) => item.toString(16).padStart(2, "0"))
      .join("");
  }

  async function connectionIdentity(settings) {
    const mode = resolveConnectionMode(settings);
    const apiBase = normalizeApiBase(settings?.apiBase || "");
    const webApiBase = deriveWebApiBase({ connectionMode: mode, apiBase });
    return {
      mode,
      apiBase,
      webApiBase,
      tokenDigest: await sha256Hex(String(settings?.apiToken || "")),
    };
  }

  function sameConnectionIdentity(left, right) {
    return Boolean(left) && Boolean(right)
      && String(left.mode || "") === String(right.mode || "")
      && String(left.apiBase || "") === String(right.apiBase || "")
      && String(left.webApiBase || "") === String(right.webApiBase || "")
      && String(left.tokenDigest || "") === String(right.tokenDigest || "");
  }

  async function sameConnection(identity, settings) {
    return sameConnectionIdentity(identity, await connectionIdentity(settings));
  }

  async function createBatchKey(identity, idempotencyKey) {
    const safeIdentity = identity || {};
    const keyDigest = await sha256Hex(
      JSON.stringify({
        mode: safeIdentity.mode || "",
        apiBase: safeIdentity.apiBase || "",
        webApiBase: safeIdentity.webApiBase || "",
        tokenDigest: safeIdentity.tokenDigest || "",
        idempotencyKey: String(idempotencyKey || ""),
      }),
    );
    return `webintake:${keyDigest}`;
  }

  function createClientBatchId() {
    return `webcap-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 10)}`;
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

  function buildPayload({ settings, merged, sourceUrl, idempotencyKey }) {
    const sourcePlatform = String(merged?.platform || settings?.platform || "").trim();
    const candidates = Array.isArray(merged?.cards)
      ? merged.cards
          .filter((card) => card && typeof card === "object" && String(card.raw_card_text || "").trim())
          .map((card) => mapCardToCandidate(card, sourcePlatform))
      : [];
    if (!candidates.length) {
      return null;
    }
    return {
      source_platform: sourcePlatform,
      source_url: String(sourceUrl || "").trim(),
      source_job_title: String(settings?.jobTitle || "").trim(),
      job_profile_id: null,
      recruitment_task_id: null,
      idempotency_key: String(idempotencyKey || "").trim(),
      candidates,
    };
  }

  globalThis.BossLocalWebIntakeIdentity = {
    WEB_INTAKE_PORT,
    DESKTOP_COMPAT_PORT,
    DEFAULT_WEB_API_BASE,
    DEFAULT_DESKTOP_API_BASE,
    normalizeApiBase,
    getApiPort,
    normalizeConnectionMode,
    inferStoredConnectionMode,
    resolveConnectionMode,
    needsConnectionModeConfirmation,
    isWebWorkbenchMode,
    deriveWebApiBase,
    sha256Hex,
    connectionIdentity,
    sameConnectionIdentity,
    sameConnection,
    createBatchKey,
    createClientBatchId,
    mapCardToCandidate,
    buildPayload,
  };
})(globalThis);
