(function installBossFavoriteManagementVerifier(globalScope) {
  if (globalScope.__bossFavoriteManagementVerifier) return;

  const TRUSTED_IDENTITY_ATTRIBUTES =
    globalScope.__bossLocalIdentityContract?.trustedPlatformUidAttributes || [];

  async function verifyOne(request) {
    const platform = String(request?.platform || "").trim().toLowerCase();
    const identityAttribute = String(request?.platform_identity?.attribute || "").trim().toLowerCase();
    const identityValue = String(request?.platform_identity?.value || "").trim();
    const actionAttempted = request?.favorite_action_attempted;
    if (typeof actionAttempted !== "boolean") {
      return { status: "failed", attempted: false, reason: "invalid_favorite_action_attempted" };
    }
    const attempted = actionAttempted;
    if (platform !== "boss") {
      return { status: "failed", attempted, reason: "unsupported_platform" };
    }
    if (!TRUSTED_IDENTITY_ATTRIBUTES.includes(identityAttribute) || !identityValue) {
      return { status: "identity_incomplete", attempted, reason: "trusted_platform_identity_missing" };
    }
    if (!isFavoriteManagementContext()) {
      return { status: "failed", attempted, reason: "not_favorite_management_context" };
    }
    const matches = Array.from(document.querySelectorAll(`[${identityAttribute}]`)).filter(
      (node) => String(node.getAttribute?.(identityAttribute) || "").trim() === identityValue,
    );
    if (matches.length === 1) {
      return {
        status: attempted ? "success" : "already_favorited",
        attempted,
        reason: "favorite_management_identity_confirmed",
        match_count: 1,
      };
    }
    if (matches.length === 0) {
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
      match_count: matches.length,
    };
  }

  function isFavoriteManagementContext() {
    try {
      return globalScope.top?.location?.pathname === "/web/chat/interaction";
    } catch (_error) {
      return false;
    }
  }

  globalScope.__bossFavoriteManagementVerifier = { verifyOne };
})(globalThis);
