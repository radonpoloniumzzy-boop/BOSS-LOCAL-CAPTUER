(function installBossNativeFavoriteAdapter(globalScope) {
  const ADAPTER_VERSION = "favorite-adapter-readiness-v2";
  if (globalScope.__bossNativeFavoriteAdapter?.version === ADAPTER_VERSION) {
    return;
  }

  const TRUSTED_IDENTITY_ATTRIBUTES =
    globalScope.__bossLocalIdentityContract?.trustedPlatformUidAttributes || [];
  const TRUSTED_IDENTITY_SELECTOR = TRUSTED_IDENTITY_ATTRIBUTES.map((name) => `[${name}]`).join(",");
  const DETAIL_SELECTOR = ".resume-item-detail";
  const DETAIL_TIMEOUT_MS = 5000;
  const FAVORITE_TIMEOUT_MS = 3000;
  const POLL_INTERVAL_MS = 50;

  function inspectFrame(identitySnapshot) {
    const restriction = detectPlatformRestriction();
    const identityAttribute = String(identitySnapshot?.platform_identity?.attribute || "").trim().toLowerCase();
    const identityValue = String(identitySnapshot?.platform_identity?.value || "").trim();
    const identity_match_count = TRUSTED_IDENTITY_ATTRIBUTES.includes(identityAttribute) && identityValue
      ? Array.from(document.querySelectorAll(`[${identityAttribute}]`)).filter(
          (node) => String(node.getAttribute?.(identityAttribute) || "").trim() === identityValue,
        ).length
      : 0;
    return {
      frame_url: location.href,
      restriction,
      identity_match_count,
    };
  }

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
    const initialRestriction = detectPlatformRestriction();
    if (initialRestriction) {
      return { status: "failed", attempted: false, reason: initialRestriction };
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
        const restriction = detectPlatformRestriction();
        if (restriction) return { restriction };
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
      if (ready?.restriction) {
        return { status: "failed", attempted: false, reason: ready.restriction };
      }
      if (!ready) {
        const currentDetail = document.querySelector(DETAIL_SELECTOR);
        const currentFavoriteControl = findFavoriteControl(currentDetail);
        return {
          status: "failed",
          attempted: false,
          reason: "candidate_detail_not_ready",
          readiness_diagnostic: {
            candidate_node_connected: matches[0]?.isConnected === true,
            candidate_node_visible: isVisible(matches[0]),
            ...detailTracker.diagnostic(currentDetail, currentFavoriteControl),
          },
        };
      }
      if (isFavorited(ready.detailRoot)) {
        return {
          status: "unknown",
          attempted: false,
          reason: "favorite_state_active_pending_management_verification",
        };
      }
      const preWriteRestriction = detectPlatformRestriction();
      if (preWriteRestriction) {
        return { status: "failed", attempted: false, reason: preWriteRestriction };
      }

      try {
        ready.favoriteControl.click();
      } catch (_error) {
        return { status: "unknown", attempted: true, reason: "favorite_control_click_uncertain" };
      }
      const confirmation = await waitForValue(
        () => {
          const restriction = detectPlatformRestriction();
          if (restriction) return { restriction };
          return isFavorited(ready.detailRoot) ? { favorited: true } : null;
        },
        FAVORITE_TIMEOUT_MS,
      );
      if (selectionGuard.changed()) {
        return { status: "unknown", attempted: true, reason: "candidate_selection_changed_after_attempt" };
      }
      if (confirmation?.restriction) {
        return {
          status: "unknown",
          attempted: true,
          reason: "platform_restriction_after_favorite_attempt",
        };
      }
      if (!confirmation?.favorited) {
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

  function detectPlatformRestriction() {
    const localRestriction = detectPlatformRestrictionInDocument(document);
    if (localRestriction) return localRestriction;
    if (globalScope.top && globalScope.top !== globalScope) {
      try {
        return detectPlatformRestrictionInDocument(globalScope.top.document);
      } catch (_error) {
        return "platform_top_context_unavailable";
      }
    }
    return "";
  }

  function detectPlatformRestrictionInDocument(targetDocument) {
    const directSelectors = [
      "iframe[src*='captcha']",
      "iframe[src*='verify']",
      "[class*='captcha']",
      "[class*='geetest']",
    ];
    if (directSelectors.some((selector) =>
      Array.from(targetDocument.querySelectorAll?.(selector) || []).some(isVisible),
    )) {
      return "platform_captcha_or_security_verification";
    }
    const surfaces = Array.from(targetDocument.querySelectorAll?.(
      "[role='dialog'], .dialog-wrap, .boss-dialog, .toast, .message, .warning-dialog",
    ) || []).filter(isVisible);
    const text = surfaces.map((node) => String(node.textContent || "")).join(" ");
    if (/验证码|安全验证|滑块|人机验证/.test(text)) {
      return "platform_captcha_or_security_verification";
    }
    if (/重新登录|登录失效|请先登录|账号已退出/.test(text)) {
      return "platform_login_required";
    }
    if (/操作频繁|频繁操作|稍后再试|账号异常|风险|风控|访问受限/.test(text)) {
      return "platform_rate_or_risk_restriction";
    }
    if (/无权限|权限不足|没有权限|禁止操作/.test(text)) {
      return "platform_permission_denied";
    }
    return "";
  }

  function isVisible(node) {
    if (!node) return false;
    const style = typeof globalScope.getComputedStyle === "function"
      ? globalScope.getComputedStyle(node)
      : null;
    if (style && (style.display === "none" || style.visibility === "hidden" || style.opacity === "0")) {
      return false;
    }
    return typeof node.getClientRects !== "function" || node.getClientRects().length > 0;
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
      diagnostic(currentDetail, currentFavoriteControl) {
        return {
          baseline_detail_present: Boolean(baselineDetail),
          baseline_favorite_control_present: Boolean(baselineFavoriteControl),
          current_detail_present: Boolean(currentDetail),
          current_favorite_control_present: Boolean(currentFavoriteControl),
          detail_root_changed: currentDetail !== baselineDetail,
          favorite_control_changed: currentFavoriteControl !== baselineFavoriteControl,
          mutation_observed: mutationObserved,
        };
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

  globalScope.__bossNativeFavoriteAdapter = {
    version: ADAPTER_VERSION,
    favoriteOne,
    inspectFrame,
  };
})(globalThis);
