(function installCollectionContract(root) {
  function normalizedPath(frameUrl) {
    try {
      return new URL(String(frameUrl || "")).pathname.replace(/\/+$/, "") || "/";
    } catch (_error) {
      return "";
    }
  }

  function routeScore(frameUrl) {
    const path = normalizedPath(frameUrl);
    if (path === "/web/frame/recommend") return 30;
    if (path === "/web/geek/recommend") return 20;
    if (path.includes("/recommend")) return 10;
    return 0;
  }

  function selectAuthoritativeFrame(frameResults) {
    const candidates = (frameResults || [])
      .map((execution) => ({
        frameId: Number(execution?.frameId ?? -1),
        documentId: String(execution?.documentId || ""),
        frameUrl: String(execution?.result?.frameUrl || ""),
        cardCount: Math.max(0, Number(execution?.result?.cardCount || 0)),
        visible: execution?.result?.visible !== false,
      }))
      .filter((frame) => frame.frameId >= 0 && frame.cardCount > 0);

    if (candidates.length === 0) {
      return { ok: false, reason: "no_candidate_frame", candidateFrameCount: 0 };
    }
    const visible = candidates.filter((frame) => frame.visible);
    const pool = visible.length > 0 ? visible : candidates;
    const ranked = pool.slice().sort((left, right) => {
      const routeDifference = routeScore(right.frameUrl) - routeScore(left.frameUrl);
      if (routeDifference !== 0) return routeDifference;
      const countDifference = right.cardCount - left.cardCount;
      if (countDifference !== 0) return countDifference;
      return left.frameId - right.frameId;
    });
    const best = ranked[0];
    const equallyAuthoritative = ranked.filter(
      (frame) =>
        routeScore(frame.frameUrl) === routeScore(best.frameUrl) &&
        frame.cardCount === best.cardCount,
    );
    if (equallyAuthoritative.length > 1) {
      return {
        ok: false,
        reason: "ambiguous_candidate_frames",
        candidateFrameCount: candidates.length,
        frameIds: equallyAuthoritative.map((frame) => frame.frameId),
      };
    }
    return {
      ok: true,
      ...best,
      candidateFrameCount: candidates.length,
    };
  }

  function createStabilityTracker(requiredStableTicks = 3) {
    const required = Math.max(1, Number(requiredStableTicks || 0));
    let previous = null;
    let stableTicks = 0;
    return Object.freeze({
      observe(snapshot) {
        const current = {
          scrollHeight: Number(snapshot?.scrollHeight || 0),
          contentSignature: String(snapshot?.contentSignature || ""),
        };
        if (
          previous &&
          Math.abs(current.scrollHeight - previous.scrollHeight) <= 4 &&
          current.contentSignature === previous.contentSignature
        ) {
          stableTicks += 1;
        } else {
          stableTicks = 0;
        }
        previous = current;
        return stableTicks >= required;
      },
    });
  }

  root.BossLocalCollectionContract = Object.freeze({
    selectAuthoritativeFrame,
    createStabilityTracker,
  });
})(globalThis);
