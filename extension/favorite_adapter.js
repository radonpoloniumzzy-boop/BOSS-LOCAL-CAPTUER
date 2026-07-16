(function installBossNativeFavoriteAdapter(globalScope) {
  if (globalScope.__bossNativeFavoriteAdapter) {
    return;
  }

  const TRUSTED_IDENTITY_ATTRIBUTES =
    globalScope.__bossLocalIdentityContract?.trustedPlatformUidAttributes || [];
  const TRUSTED_IDENTITY_SELECTOR = TRUSTED_IDENTITY_ATTRIBUTES.map((name) => `[${name}]`).join(",");
  const DETAIL_SELECTOR = ".resume-item-detail";
  const DETAIL_TIMEOUT_MS = 5000;
  const FAVORITE_TIMEOUT_MS = 3000;
  const POLL_INTERVAL_MS = 50;

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

    const baselineDetail = document.querySelector(DETAIL_SELECTOR);
    const detailTracker = createDetailChangeTracker(baselineDetail);
    const selectionGuard = createSelectionGuard(identityAttribute, identityValue);
    try {
      try {
        matches[0].click();
      } catch (_error) {
        return { status: "failed", attempted: false, reason: "candidate_navigation_failed" };
      }

      const ready = await waitForValue(() => {
        if (selectionGuard.changed()) return { selectionChanged: true };
        const detailRoot = document.querySelector(DETAIL_SELECTOR);
        const favoriteControl = findFavoriteControl(detailRoot);
        return detailRoot && favoriteControl && detailTracker.changed(detailRoot, favoriteControl)
          ? { detailRoot, favoriteControl }
          : null;
      }, DETAIL_TIMEOUT_MS);
      if (selectionGuard.changed()) {
        return { status: "failed", attempted: false, reason: "candidate_selection_changed" };
      }
      if (!ready) {
        return { status: "failed", attempted: false, reason: "candidate_detail_not_ready" };
      }
      if (isFavorited(ready.detailRoot)) {
        return {
          status: "unknown",
          attempted: false,
          reason: "favorite_state_active_pending_management_verification",
        };
      }

      try {
        ready.favoriteControl.click();
      } catch (_error) {
        return { status: "unknown", attempted: true, reason: "favorite_control_click_uncertain" };
      }
      const confirmed = await waitForValue(
        () => isFavorited(ready.detailRoot),
        FAVORITE_TIMEOUT_MS,
      );
      if (selectionGuard.changed()) {
        return { status: "unknown", attempted: true, reason: "candidate_selection_changed_after_attempt" };
      }
      if (!confirmed) {
        return { status: "unknown", attempted: true, reason: "favorite_state_not_confirmed" };
      }
      return {
        status: "unknown",
        attempted: true,
        reason: "favorite_state_active_pending_management_verification",
      };
    } finally {
      detailTracker.dispose();
      selectionGuard.dispose();
    }
  }

  function findFavoriteControl(detailRoot) {
    if (!detailRoot) return null;
    return (
      detailRoot.querySelector?.(".like-icon-and-text .btn-text") ||
      detailRoot.querySelector?.(".like-icon-and-text") ||
      null
    );
  }

  function isFavorited(detailRoot) {
    return Boolean(detailRoot?.querySelector?.(".like-icon.like-icon-active"));
  }

  function createDetailChangeTracker(baselineDetail) {
    let mutationObserved = false;
    const baselineFavoriteControl = findFavoriteControl(baselineDetail);
    const Observer = globalScope.MutationObserver;
    const observer = typeof Observer === "function"
      ? new Observer((records) => {
          const currentDetail = document.querySelector(DETAIL_SELECTOR);
          mutationObserved ||= records.some((record) =>
            currentDetail?.contains?.(record.target) ||
            baselineDetail?.contains?.(record.target) ||
            record.target === currentDetail ||
            record.target === baselineDetail,
          );
        })
      : null;
    observer?.observe?.(document.documentElement, { subtree: true, childList: true, attributes: true });
    return {
      changed(currentDetail, currentFavoriteControl) {
        if (!currentDetail || !currentFavoriteControl) return false;
        if (currentDetail !== baselineDetail) return true;
        return mutationObserved && currentFavoriteControl !== baselineFavoriteControl;
      },
      dispose() {
        observer?.disconnect?.();
      },
    };
  }

  function createSelectionGuard(expectedAttribute, expectedValue) {
    let changed = false;
    const onTrustedClick = (event) => {
      if (!event.isTrusted || !(event.target instanceof Element)) return;
      const candidateRoot = TRUSTED_IDENTITY_SELECTOR
        ? event.target.closest?.(TRUSTED_IDENTITY_SELECTOR)
        : null;
      if (!candidateRoot) return;
      const identity = TRUSTED_IDENTITY_ATTRIBUTES
        .map((attribute) => ({ attribute, value: String(candidateRoot.getAttribute?.(attribute) || "").trim() }))
        .find((candidate) => candidate.value);
      if (identity && (identity.attribute !== expectedAttribute || identity.value !== expectedValue)) changed = true;
    };
    document.addEventListener?.("click", onTrustedClick, true);
    return {
      changed: () => changed,
      dispose: () => document.removeEventListener?.("click", onTrustedClick, true),
    };
  }

  async function waitForValue(read, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() <= deadline) {
      const value = read();
      if (value) return value;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    return null;
  }

  globalScope.__bossNativeFavoriteAdapter = { favoriteOne };
})(globalThis);
