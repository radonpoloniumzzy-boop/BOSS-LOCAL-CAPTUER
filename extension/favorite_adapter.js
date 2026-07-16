(function installBossNativeFavoriteAdapter(globalScope) {
  if (globalScope.__bossNativeFavoriteAdapter) {
    return;
  }

  const TRUSTED_IDENTITY_ATTRIBUTES =
    globalScope.__bossLocalIdentityContract?.trustedPlatformUidAttributes || [];

  async function favoriteOne(identitySnapshot) {
    const platform = String(identitySnapshot?.platform || "").trim().toLowerCase();
    if (platform !== "boss") {
      return {
        status: "failed",
        attempted: false,
        reason: "unsupported_platform",
      };
    }
    const identityAttribute = String(identitySnapshot?.platform_identity?.attribute || "").trim().toLowerCase();
    const identityValue = String(identitySnapshot?.platform_identity?.value || "").trim();
    if (!TRUSTED_IDENTITY_ATTRIBUTES.includes(identityAttribute) || !identityValue) {
      return {
        status: "identity_incomplete",
        attempted: false,
        reason: "trusted_platform_identity_missing",
      };
    }
    const matches = Array.from(document.querySelectorAll(`[${identityAttribute}]`)).filter(
      (node) => String(node.getAttribute?.(identityAttribute) || "").trim() === identityValue,
    );
    if (matches.length === 0) {
      return {
        status: "identity_incomplete",
        attempted: false,
        reason: "trusted_identity_not_found",
        match_count: 0,
      };
    }
    if (matches.length > 1) {
      return {
        status: "identity_conflict",
        attempted: false,
        reason: "multiple_trusted_identity_matches",
        match_count: matches.length,
      };
    }
    return {
      status: "unknown",
      attempted: false,
      reason: "identity_match_not_implemented",
    };
  }

  globalScope.__bossNativeFavoriteAdapter = { favoriteOne };
})(globalThis);
