(function installBossFavoriteManagementVerifier(globalScope) {
  if (globalScope.__bossFavoriteManagementVerifier) return;

  const INSPECTION_VERSION = "favorite-management-frame-v1";
  const TOP_PATH = "/web/chat/interaction";
  const CONTEXT_FRAME_PATH = "/web/frame/recommend/interaction";
  const CANDIDATE_FRAME_PATH = "/web/frame/recommend/";
  const TRUSTED_IDENTITY_ATTRIBUTES =
    globalScope.__bossLocalIdentityContract?.trustedPlatformUidAttributes || [];

  async function inspectFrame(request) {
    const invalid = validateRequest(request);
    const context = readFrameContext();
    if (invalid) return { version: INSPECTION_VERSION, ...context, error: invalid };
    const identityBinding = await createIdentityBinding(request);
    if (!identityBinding) {
      return {
        version: INSPECTION_VERSION,
        ...context,
        error: { status: "failed", attempted: request.favorite_action_attempted, reason: "identity_binding_unavailable" },
      };
    }
    const identityAttribute = request.platform_identity.attribute.trim().toLowerCase();
    const identityValue = request.platform_identity.value.trim();
    return {
      version: INSPECTION_VERSION,
      inspection_id: request.inspection_id,
      tab_id: request.tab_id,
      identity_binding: identityBinding,
      ...context,
      favorite_subview_selected:
        context.frame_path === CONTEXT_FRAME_PATH && hasSelectedFavoriteSubviewMarker(),
      identity_match_count:
        context.frame_path === CANDIDATE_FRAME_PATH
          ? countScopedIdentityMatches(identityAttribute, identityValue)
          : 0,
    };
  }

  async function classify(request, frameObservations) {
    const invalid = validateRequest(request);
    if (invalid) return invalid;
    const attempted = request.favorite_action_attempted;
    const expectedBinding = await createIdentityBinding(request);
    if (!expectedBinding) {
      return { status: "failed", attempted, reason: "identity_binding_unavailable" };
    }
    const suppliedObservations = Array.isArray(frameObservations) ? frameObservations : [];
    if (
      !suppliedObservations.length ||
      suppliedObservations.some((observation) => observation?.version !== INSPECTION_VERSION)
    ) {
      return { status: "failed", attempted, reason: "favorite_management_observation_mismatch" };
    }
    const observations = suppliedObservations.filter(
      (observation) =>
        observation.inspection_id === request.inspection_id &&
        observation.tab_id === request.tab_id &&
        observation.identity_binding === expectedBinding,
    );
    if (!observations.length || observations.length !== suppliedObservations.length) {
      return { status: "failed", attempted, reason: "favorite_management_observation_mismatch" };
    }
    const managementFrames = observations.filter(
      (observation) =>
        isBossHost(observation.top_host) &&
        isBossHost(observation.frame_host) &&
        observation.top_path === TOP_PATH,
    );
    if (!managementFrames.length) {
      return { status: "failed", attempted, reason: "not_favorite_management_context" };
    }
    const selectedContexts = managementFrames.filter(
      (observation) =>
        observation.frame_path === CONTEXT_FRAME_PATH &&
        observation.favorite_subview_selected === true,
    );
    if (selectedContexts.length !== 1) {
      return {
        status: "failed",
        attempted,
        reason: selectedContexts.length > 1
          ? "ambiguous_favorite_management_subview"
          : "favorite_management_subview_not_confirmed",
      };
    }
    const candidateFrames = managementFrames.filter(
      (observation) => observation.frame_path === CANDIDATE_FRAME_PATH,
    );
    if (candidateFrames.length !== 1) {
      return {
        status: "failed",
        attempted,
        reason: candidateFrames.length > 1
          ? "ambiguous_favorite_management_candidate_frame"
          : "favorite_management_candidate_frame_not_confirmed",
      };
    }
    if (!isSafeMatchCount(candidateFrames[0].identity_match_count)) {
      return { status: "failed", attempted, reason: "invalid_favorite_management_observation" };
    }
    const matchCount = candidateFrames[0].identity_match_count;
    if (matchCount === 1) {
      return {
        status: attempted ? "success" : "already_favorited",
        attempted,
        reason: "favorite_management_identity_confirmed",
        match_count: 1,
      };
    }
    if (matchCount === 0) {
      return {
        status: "unknown",
        attempted,
        reason: "favorite_management_identity_not_visible",
        match_count: 0,
      };
    }
    return {
      status: "identity_conflict",
      attempted,
      reason: "multiple_favorite_management_identity_matches",
      match_count: matchCount,
    };
  }

  function validateRequest(request) {
    if (typeof request?.favorite_action_attempted !== "boolean") {
      return { status: "failed", attempted: false, reason: "invalid_favorite_action_attempted" };
    }
    const attempted = request.favorite_action_attempted;
    if (
      !/^[a-zA-Z0-9_-]{8,128}$/.test(String(request?.inspection_id || "")) ||
      !Number.isSafeInteger(request?.tab_id) ||
      request.tab_id <= 0
    ) {
      return { status: "failed", attempted, reason: "invalid_favorite_management_inspection" };
    }
    if (String(request?.platform || "").trim().toLowerCase() !== "boss") {
      return { status: "failed", attempted, reason: "unsupported_platform" };
    }
    const attribute = String(request?.platform_identity?.attribute || "").trim().toLowerCase();
    const value = String(request?.platform_identity?.value || "").trim();
    if (!TRUSTED_IDENTITY_ATTRIBUTES.includes(attribute) || !value) {
      return { status: "identity_incomplete", attempted, reason: "trusted_platform_identity_missing" };
    }
    return null;
  }

  function readFrameContext() {
    try {
      return {
        top_host: String(globalScope.top?.location?.hostname || "").toLowerCase(),
        top_path: String(globalScope.top?.location?.pathname || ""),
        frame_host: String(globalScope.location?.hostname || "").toLowerCase(),
        frame_path: String(globalScope.location?.pathname || ""),
      };
    } catch (_error) {
      return { top_host: "", top_path: "", frame_host: "", frame_path: "" };
    }
  }

  function hasSelectedFavoriteSubviewMarker() {
    return Array.from(document.querySelectorAll("li.tab-item.curr")).some((element) =>
      normalizeText(element.innerText || element.textContent) === "收藏牛人" && hasLayout(element),
    );
  }

  function countScopedIdentityMatches(attribute, value) {
    return Array.from(document.querySelectorAll(`[${attribute}]`)).filter((node) =>
      String(node.getAttribute?.(attribute) || "").trim() === value &&
      node.classList?.contains?.("card-inner") &&
      node.isConnected !== false &&
      hasLayout(node),
    ).length;
  }

  function hasLayout(element) {
    const rect = element.getBoundingClientRect?.();
    if (!rect || rect.width <= 0 || rect.height <= 0 || typeof globalScope.getComputedStyle !== "function") {
      return false;
    }
    try {
      for (let current = element; current; current = current.parentElement) {
        const style = globalScope.getComputedStyle(current);
        const opacity = Number.parseFloat(style?.opacity);
        if (
          style?.display === "none" ||
          style?.visibility === "hidden" ||
          style?.visibility === "collapse" ||
          (Number.isFinite(opacity) && opacity <= 0)
        ) {
          return false;
        }
      }
      return true;
    } catch (_error) {
      return false;
    }
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function isBossHost(value) {
    return /(^|\.)(zhipin\.com|bosszhipin\.com)$/i.test(String(value || ""));
  }

  function isSafeMatchCount(value) {
    return Number.isSafeInteger(value) && value >= 0;
  }

  async function createIdentityBinding(request) {
    if (!globalScope.crypto?.subtle || typeof globalScope.TextEncoder !== "function") return "";
    const attribute = String(request.platform_identity.attribute || "").trim().toLowerCase();
    const value = String(request.platform_identity.value || "").trim();
    const bytes = new globalScope.TextEncoder().encode(
      `${request.inspection_id}\u0000${request.tab_id}\u0000${attribute}\u0000${value}`,
    );
    const digest = await globalScope.crypto.subtle.digest("SHA-256", bytes);
    return `sha256:${Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("")
      .slice(0, 32)}`;
  }

  globalScope.__bossFavoriteManagementVerifier = { inspectFrame, classify };
})(globalThis);
