(function installBossNativeFavoriteExecutionContract(globalScope) {
  if (globalScope.__bossNativeFavoriteExecutionContract) {
    return;
  }

  const RECOMMENDATION_PATHS = new Set([
    "/web/chat/recommend",
    "/web/frame/recommend",
    "/web/geek/recommend",
  ]);

  function validateSourceContext(task, tab, documentId) {
    const context = task?.source_page_context;
    if (!context || String(context.platform || "").toLowerCase() !== "boss") {
      return { ok: false, reason: "source_page_context_platform_mismatch" };
    }
    if (Number(context.tab_id) !== Number(tab?.id)) {
      return { ok: false, reason: "source_page_context_tab_mismatch" };
    }
    if (!context.document_id || String(context.document_id) !== String(documentId || "")) {
      return { ok: false, reason: "source_page_context_document_mismatch" };
    }
    if (!isBossRecommendationUrl(tab?.url) || !isBossRecommendationUrl(context.source_url)) {
      return { ok: false, reason: "source_page_context_page_mismatch" };
    }
    if (normalizeRecommendationUrl(tab?.url) !== normalizeRecommendationUrl(context.source_url)) {
      return { ok: false, reason: "source_page_context_url_mismatch" };
    }
    return { ok: true, reason: "" };
  }

  function aggregateAdapterExecutions(executions) {
    const actionable = (executions || [])
      .map((execution) => execution?.result)
      .filter(Boolean)
      .filter((result) => result.reason !== "trusted_identity_not_found");
    if (actionable.length === 0) {
      return {
        status: "failed",
        attempted: false,
        reason: "source_identity_not_visible",
        stop_batch: true,
      };
    }
    if (actionable.length > 1) {
      return {
        status: "failed",
        attempted: actionable.some((result) => result.attempted === true),
        reason: "multiple_source_frame_identity_matches",
        stop_batch: true,
      };
    }
    const result = actionable[0];
    if (result.status === "identity_conflict" || result.status === "identity_incomplete") {
      return {
        status: "failed",
        attempted: result.attempted === true,
        reason: String(result.reason || "source_identity_invalid"),
        stop_batch: true,
      };
    }
    return {
      status: String(result.status || "failed"),
      attempted: result.attempted === true,
      reason: String(result.reason || ""),
      stop_batch: result.status === "failed",
    };
  }

  function validateCandidateDocuments(context, inspections) {
    const expected = Array.isArray(context?.candidate_documents) ? context.candidate_documents : [];
    if (expected.length === 0) {
      return { ok: false, reason: "source_candidate_documents_missing" };
    }
    const actual = new Map((inspections || []).map((item) => [
      `${Number(item?.frameId)}:${String(item?.documentId || "")}`,
      item,
    ]));
    for (const document of expected) {
      const key = `${Number(document?.frame_id)}:${String(document?.document_id || "")}`;
      const match = actual.get(key);
      if (!match || normalizeRecommendationUrl(match?.result?.frame_url) !== normalizeRecommendationUrl(document?.frame_url)) {
        return { ok: false, reason: "source_candidate_document_mismatch" };
      }
    }
    return { ok: true, reason: "" };
  }

  function aggregateManagementClassifications(classifications, attempted) {
    const results = (classifications || []).map((item) => item?.result).filter(Boolean);
    const conflicts = results.filter((result) =>
      result.reason === "multiple_favorite_management_identity_matches" ||
      result.reason === "favorite_management_identity_seen_in_multiple_tabs",
    );
    const confirmed = results.filter((result) =>
      result.status === "success" || result.status === "already_favorited",
    );
    if (conflicts.length > 0 || confirmed.length > 1) {
      return {
        status: "failed",
        attempted: attempted === true,
        reason: "favorite_management_identity_seen_in_multiple_tabs",
        stop_batch: true,
      };
    }
    if (confirmed.length === 1) {
      return {
        status: attempted === true ? "success" : "already_favorited",
        attempted: attempted === true,
        reason: "favorite_management_identity_confirmed",
        stop_batch: false,
      };
    }
    const managementContexts = results.filter(
      (result) => result.reason !== "not_favorite_management_context",
    );
    return {
      status: attempted === true ? "unknown" : "failed",
      attempted: attempted === true,
      reason: managementContexts.length > 0
        ? "favorite_management_identity_not_visible"
        : "favorite_management_tab_not_ready",
      stop_batch: true,
    };
  }

  function isBossRecommendationUrl(value) {
    try {
      const url = new URL(String(value || ""));
      const host = url.hostname.toLowerCase();
      const bossHost =
        host === "zhipin.com" || host.endsWith(".zhipin.com") ||
        host === "bosszhipin.com" || host.endsWith(".bosszhipin.com");
      return bossHost && RECOMMENDATION_PATHS.has(url.pathname.replace(/\/$/, ""));
    } catch (_error) {
      return false;
    }
  }

  function normalizeRecommendationUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return `${url.protocol}//${url.host.toLowerCase()}${url.pathname.replace(/\/$/, "")}${url.search}${url.hash}`;
    } catch (_error) {
      return "";
    }
  }

  globalScope.__bossNativeFavoriteExecutionContract = Object.freeze({
    validateSourceContext,
    validateCandidateDocuments,
    aggregateAdapterExecutions,
    aggregateManagementClassifications,
    isBossRecommendationUrl,
  });
})(globalThis);
