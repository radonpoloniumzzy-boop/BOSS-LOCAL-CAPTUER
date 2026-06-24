if (typeof globalThis.__bossLocalExtract !== "function") {
  const EDUCATION_REGEX = /(博士|硕士|研究生|本科|大专|中专|高中|MBA|EMBA|统招本科|学历不限)/;
  const SALARY_REGEX = /(?:\b|￥)?\d{1,3}\s*[Kk]\s*[-~–—至]\s*\d{1,3}\s*[Kk](?:\b|·|\/|年|月)?|\b\d{1,3}\s*[-~–—至]\s*\d{1,3}\s*[Kk](?:\b|·|\/|年|月)?|薪资面议|面议/;
  const ACTIVE_REGEX = /(刚刚活跃|今日活跃|本周活跃|刚刚在线|\d+[天日周月]内活跃|活跃|在线)/;
  const EXPERIENCE_REGEX = /(\d+\s*(?:年|年以上|年经验|岁)|经验不限|应届|在校|实习)/;
  const DATE_RANGE_REGEX = /\d{4}[./-]\d{1,2}\s*[-~至]\s*(\d{4}[./-]\d{1,2}|至今|现在)/;

  const PLATFORM_ADAPTERS = [
    {
      id: "boss",
      label: "Boss",
      defaultJobTitle: "Boss 推荐牛人",
      actionTexts: ["打招呼", "立即沟通", "继续沟通", "立即开聊"],
      noMoreTexts: ["没有更多了", "没有更多内容了", "没有更多候选人了", "已经到底了", "到底了", "我是有底线的"],
      selectors: {
        card: [
          ".candidate-card-wrap",
          ".candidate-card",
          ".card-inner",
          "[data-testid='candidate-card']",
          "[class*='card'][class*='candidate']",
          "[class*='recommend'][class*='card']",
          "[class*='geek'][class*='card']",
          "[class*='list'] > li",
        ],
        name: [".name", ".geek-name", ".candidate-name", "[class*='name']"],
        activeStatus: [".active-time", ".online", ".active-status", "[class*='active']"],
        expectedSalary: [".salary", ".expect-salary", ".tag-salary", "[class*='salary']"],
        workExperience: [".experience", ".work-experience", ".resume-desc", "[class*='experience']"],
        education: [".education", ".edu", ".education-status", "[class*='education']"],
        tags: [".tags span", ".tag-list span", ".labels span", ".tag", "[class*='tag'] span"],
        summary: [".description", ".summary", ".card-desc", ".self-intro", "[class*='summary']", "[class*='desc']"],
        detailLink: ["a[href*='geek']", "a[href*='candidate']", "a[href*='zhipin.com']"],
        platformUidAttrs: ["data-geek-id", "data-id", "data-candidate-id", "data-user-id"],
      },
      broadScanSelector: "div, li, article, section",
      matches(url) {
        return /(^|\.)zhipin\.com$/i.test(url.hostname) || /(^|\.)bosszhipin\.com$/i.test(url.hostname);
      },
    },
    {
      id: "liepin",
      label: "猎聘",
      defaultJobTitle: "猎聘推荐人才",
      actionTexts: ["打招呼", "立即沟通", "继续沟通", "聊一聊", "开聊", "沟通", "查看简历", "下载简历", "邀请面试"],
      noMoreTexts: ["没有更多了", "没有更多内容了", "暂无更多", "已经到底了", "到底了", "没有更多推荐", "我是有底线的"],
      selectors: {
        card: [
          ".resume-card",
          ".talent-card",
          ".candidate-card",
          ".recommend-card",
          "[data-resume-id]",
          "[data-candidate-id]",
          "[data-talent-id]",
          "[class*='resume'][class*='card']",
          "[class*='talent'][class*='card']",
          "[class*='candidate'][class*='card']",
          "[class*='recommend'] [class*='card']",
          "[class*='recommend'] li",
        ],
        name: [
          ".name",
          ".user-name",
          ".candidate-name",
          ".talent-name",
          ".resume-name",
          "[class*='name']",
        ],
        activeStatus: [".active-time", ".online", ".active-status", "[class*='active']", "[class*='online']"],
        expectedSalary: [
          ".salary",
          ".expect-salary",
          ".salary-text",
          ".resume-salary",
          "[class*='salary']",
          "[class*='compensation']",
        ],
        workExperience: [
          ".experience",
          ".work-experience",
          ".resume-desc",
          ".work-exp",
          "[class*='experience']",
          "[class*='work']",
        ],
        education: [".education", ".edu", ".degree", "[class*='education']", "[class*='degree']", "[class*='edu']"],
        tags: [".tags span", ".tag-list span", ".labels span", ".tag", "[class*='tag'] span", "[class*='label'] span"],
        summary: [
          ".description",
          ".summary",
          ".card-desc",
          ".self-intro",
          ".advantage",
          "[class*='summary']",
          "[class*='desc']",
          "[class*='intro']",
        ],
        detailLink: [
          "a[href*='resume']",
          "a[href*='candidate']",
          "a[href*='talent']",
          "a[href*='liepin.com']",
          "a[href]",
        ],
        platformUidAttrs: [
          "data-resume-id",
          "data-candidate-id",
          "data-talent-id",
          "data-user-id",
          "data-id",
          "data-uid",
        ],
      },
      broadScanSelector: "div, li, article, section",
      matches(url) {
        return /(^|\.)liepin\.com$/i.test(url.hostname) && (url.hostname === "lpt.liepin.com" || url.pathname.startsWith("/recommend"));
      },
    },
  ];

  globalThis.__bossLocalCollectorPlatforms = PLATFORM_ADAPTERS.map((platform) => ({
    id: platform.id,
    label: platform.label,
  }));

  globalThis.__bossLocalRequestScrollPause = function bossLocalRequestScrollPause(reason) {
    const control = getScrollControl();
    control.pauseRequested = true;
    control.reason = String(reason || "manual");
    control.requestedAt = Date.now();
    return { ok: true, pauseRequested: true, reason: control.reason };
  };

  globalThis.__bossLocalResetScrollPause = function bossLocalResetScrollPause() {
    resetScrollControl(false);
    return { ok: true, pauseRequested: false };
  };

  globalThis.__bossLocalExtract = async function bossLocalExtract(autoScroll, settings) {
    resetScrollControl(Boolean(autoScroll));
    const platform = detectPlatform();
    if (!platform) {
      markScrollControlStopped();
      return {
        cards: [],
        debug: `unsupported-host:${location.hostname}`,
        meta: {
          platform: "unsupported",
          rounds_completed: 0,
          page_title: document.title,
        },
      };
    }

    const result = await collectCards(platform, Boolean(autoScroll), settings || {});
    markScrollControlStopped();
    const lastDebug = result.lastDebug || { strategy: "none", actionCount: 0, nodeCount: 0 };
    return {
      cards: result.cards,
      debug: [
        `platform=${platform.id}`,
        `strategy=${lastDebug.strategy}`,
        `candidateNodes=${lastDebug.nodeCount}`,
        `actionButtons=${lastDebug.actionCount}`,
        `rounds=${result.scrollInfo.roundsCompleted}`,
        `stop=${result.scrollInfo.stopReason}`,
        `noMore=${result.scrollInfo.noMoreDetected}`,
        `paused=${result.scrollInfo.pauseRequested}`,
        `unique=${result.cards.length}`,
      ].join(", "),
      meta: {
        platform: platform.id,
        platform_label: platform.label,
        rounds_completed: result.scrollInfo.roundsCompleted,
        pause_requested: result.scrollInfo.pauseRequested,
        page_title: document.title,
      },
    };
  };

  async function collectCards(platform, autoScroll, settings) {
    const cardsByKey = new Map();
    let roundsCompleted = 0;
    let noNewRounds = 0;
    let lastDebug = { strategy: "none", actionCount: 0, nodeCount: 0 };
    let noMoreDetected = hasNoMoreText(platform);
    let stopReason = autoScroll ? "max-rounds" : "current-page-only";
    const maxScrollCount = Math.max(Number(settings.maxScrollCount || 0), 0);
    const noNewStopRounds = Math.max(Number(settings.noNewStopRounds || 0), 1);

    while (true) {
      const beforeCount = cardsByKey.size;
      const extracted = extractLoadedCards(platform);
      lastDebug = extracted.debug;
      for (const card of extracted.cards) {
        cardsByKey.set(buildCardKey(card), card);
      }

      const newCount = cardsByKey.size - beforeCount;
      noNewRounds = newCount > 0 ? 0 : noNewRounds + 1;
      noMoreDetected = noMoreDetected || hasNoMoreText(platform);

      if (!autoScroll) {
        break;
      }
      if (isScrollPauseRequested()) {
        stopReason = "paused-by-user";
        break;
      }
      if (roundsCompleted >= maxScrollCount) {
        stopReason = "max-rounds";
        break;
      }
      if (noMoreDetected && noNewRounds >= 1) {
        stopReason = "found-no-more-text";
        break;
      }
      if (roundsCompleted > 0 && noNewRounds >= noNewStopRounds) {
        stopReason = noMoreDetected ? "stable-after-no-more" : "no-further-growth";
        break;
      }

      const previousSnapshot = getScrollSnapshot(platform);
      const scrollResult = performScroll(platform, settings.scrollMode, settings.scrollStep);
      roundsCompleted += 1;
      await waitForContentSettled(platform, settings.scrollWaitMs);
      if (isScrollPauseRequested()) {
        stopReason = "paused-by-user";
      }

      const currentSnapshot = getScrollSnapshot(platform);
      const changed =
        scrollResult.moved ||
        currentSnapshot.cardLikeCount > previousSnapshot.cardLikeCount ||
        currentSnapshot.actionCount > previousSnapshot.actionCount ||
        currentSnapshot.scrollHeight > previousSnapshot.scrollHeight + 4 ||
        currentSnapshot.textLength > previousSnapshot.textLength + 20 ||
        currentSnapshot.scrollTop > previousSnapshot.scrollTop + 4;
      if (!changed) {
        noNewRounds += 1;
      }
    }

    return {
      cards: Array.from(cardsByKey.values()),
      lastDebug,
      scrollInfo: {
        roundsCompleted,
        stopReason,
        noMoreDetected,
        pauseRequested: isScrollPauseRequested(),
      },
    };
  }

  function getScrollControl() {
    if (!globalThis.__bossLocalScrollControl || typeof globalThis.__bossLocalScrollControl !== "object") {
      globalThis.__bossLocalScrollControl = {
        pauseRequested: false,
        running: false,
        reason: "",
        requestedAt: 0,
        startedAt: 0,
        stoppedAt: 0,
      };
    }
    return globalThis.__bossLocalScrollControl;
  }

  function resetScrollControl(running) {
    globalThis.__bossLocalScrollControl = {
      pauseRequested: false,
      running: Boolean(running),
      reason: "",
      requestedAt: 0,
      startedAt: Date.now(),
      stoppedAt: 0,
    };
  }

  function markScrollControlStopped() {
    const control = getScrollControl();
    control.running = false;
    control.stoppedAt = Date.now();
  }

  function isScrollPauseRequested() {
    return Boolean(getScrollControl().pauseRequested);
  }

  function detectPlatform() {
    let url;
    try {
      url = new URL(location.href);
    } catch (_error) {
      return null;
    }
    return PLATFORM_ADAPTERS.find((platform) => platform.matches(url)) || null;
  }

  function getScrollSnapshot(platform) {
    const root = getScrollRoot(platform);
    const detection = detectCandidateCardNodes(platform);
    const actionCount = findActionNodes(document, platform).length;
    const bodyText = normalizeText(document.body?.innerText || "");
    return {
      cardLikeCount: Math.max(detection.debug.nodeCount, actionCount),
      actionCount,
      scrollHeight: Number(getScrollHeight(root)),
      scrollTop: Number(getScrollTop(root)),
      textLength: bodyText.length,
    };
  }

  async function waitForContentSettled(platform, waitMs) {
    const totalWaitMs = Math.max(Number(waitMs || 0), 600);
    const settleStepMs = 250;
    let lastHeight = getScrollSnapshot(platform).scrollHeight;
    let stableTicks = 0;
    const startedAt = Date.now();

    while (Date.now() - startedAt < totalWaitMs) {
      if (isScrollPauseRequested()) {
        break;
      }
      await delay(settleStepMs);
      const nextHeight = getScrollSnapshot(platform).scrollHeight;
      if (Math.abs(nextHeight - lastHeight) <= 4) {
        stableTicks += 1;
      } else {
        stableTicks = 0;
        lastHeight = nextHeight;
      }
      if (stableTicks >= 2 && Date.now() - startedAt >= 500) {
        break;
      }
    }
  }

  function performScroll(platform, mode, step) {
    const scrollRoot = getScrollRoot(platform);
    focusScrollTargets(scrollRoot);
    const before = getScrollTop(scrollRoot);

    if (mode === "fixed") {
      scrollByAmount(scrollRoot, Number(step || 900));
    } else if (mode === "page") {
      scrollByAmount(scrollRoot, window.innerHeight || Number(step || 900));
    } else {
      triggerEndScroll(scrollRoot);
    }

    const after = getScrollTop(scrollRoot);
    const atBottom = after + getClientHeight(scrollRoot) >= getScrollHeight(scrollRoot) - 4;
    return {
      moved: after > before + 1,
      atBottom,
    };
  }

  function scrollByAmount(scrollRoot, delta) {
    if (isDocumentScrollRoot(scrollRoot)) {
      window.scrollBy(0, delta);
      scrollRoot.scrollTop = scrollRoot.scrollTop + delta;
      return;
    }
    scrollRoot.scrollTop = Math.min(scrollRoot.scrollTop + delta, scrollRoot.scrollHeight);
    scrollRoot.dispatchEvent(new Event("scroll", { bubbles: true }));
  }

  function triggerEndScroll(scrollRoot) {
    for (let index = 0; index < 3; index += 1) {
      dispatchEndKey(document);
      if (document.body) {
        dispatchEndKey(document.body);
      }
      if (scrollRoot instanceof HTMLElement) {
        dispatchEndKey(scrollRoot);
      }
      if (document.activeElement instanceof HTMLElement) {
        dispatchEndKey(document.activeElement);
      }
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "End",
          code: "End",
          keyCode: 35,
          which: 35,
          bubbles: true,
        }),
      );
    }

    scrollRoot.scrollTop = scrollRoot.scrollHeight;
    if (isDocumentScrollRoot(scrollRoot)) {
      window.scrollTo(0, Math.max(document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0));
    } else {
      scrollRoot.dispatchEvent(new Event("scroll", { bubbles: true }));
    }
  }

  function dispatchEndKey(target) {
    target.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "End",
        code: "End",
        keyCode: 35,
        which: 35,
        bubbles: true,
      }),
    );
    target.dispatchEvent(
      new KeyboardEvent("keyup", {
        key: "End",
        code: "End",
        keyCode: 35,
        which: 35,
        bubbles: true,
      }),
    );
  }

  function focusScrollTargets(scrollRoot) {
    if (document.body instanceof HTMLElement) {
      document.body.tabIndex = -1;
      document.body.focus({ preventScroll: true });
    }
    if (scrollRoot instanceof HTMLElement) {
      scrollRoot.tabIndex = -1;
      scrollRoot.focus({ preventScroll: true });
    }
  }

  function getScrollRoot(platform) {
    const fallback = document.scrollingElement || document.documentElement || document.body;
    const cardNodes = detectCandidateCardNodes(platform).nodes.slice(0, 30);
    const candidates = uniqueElements([
      fallback,
      document.documentElement,
      document.body,
      ...cardNodes.flatMap((node) => collectAncestors(node, 6)),
      ...querySelectorAllSafe(
        document,
        "main, section, article, aside, ul, ol, div, [class*='scroll'], [class*='list'], [class*='recommend']",
      ),
    ]).filter((node) => node instanceof HTMLElement);

    const scored = candidates
      .map((node) => ({ node, score: scoreScrollRoot(node, cardNodes, fallback) }))
      .filter((item) => item.score > 0)
      .sort((left, right) => right.score - left.score);

    return scored[0]?.node || fallback;
  }

  function scoreScrollRoot(node, cardNodes, fallback) {
    if (!(node instanceof HTMLElement)) {
      return 0;
    }
    const scrollable = isElementScrollable(node);
    const cardCount = cardNodes.filter((card) => node === card || node.contains(card)).length;
    if (!scrollable && cardCount === 0 && node !== fallback) {
      return 0;
    }

    const classText = `${node.className || ""} ${node.id || ""}`.toLowerCase();
    let score = 0;
    if (node === fallback || node === document.documentElement || node === document.body) {
      score += 20;
    }
    if (scrollable) {
      score += 80;
    }
    score += cardCount * 120;
    if (/(scroll|list|recommend|resume|candidate|talent|geek)/i.test(classText)) {
      score += 35;
    }
    score += Math.min(Math.max(node.scrollHeight - node.clientHeight, 0) / 100, 60);
    return score;
  }

  function isElementScrollable(node) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    const overflowY = getComputedStyle(node).overflowY || "";
    return /(auto|scroll|overlay)/i.test(overflowY) && node.scrollHeight > node.clientHeight + 24;
  }

  function isDocumentScrollRoot(node) {
    return node === document.scrollingElement || node === document.documentElement || node === document.body;
  }

  function getScrollTop(node) {
    if (isDocumentScrollRoot(node)) {
      return Number(window.scrollY || document.documentElement?.scrollTop || document.body?.scrollTop || node?.scrollTop || 0);
    }
    return Number(node?.scrollTop || 0);
  }

  function getScrollHeight(node) {
    if (isDocumentScrollRoot(node)) {
      return Math.max(
        Number(document.body?.scrollHeight || 0),
        Number(document.documentElement?.scrollHeight || 0),
        Number(node?.scrollHeight || 0),
      );
    }
    return Number(node?.scrollHeight || 0);
  }

  function getClientHeight(node) {
    if (isDocumentScrollRoot(node)) {
      return Number(window.innerHeight || document.documentElement?.clientHeight || node?.clientHeight || 0);
    }
    return Number(node?.clientHeight || 0);
  }

  function hasNoMoreText(platform) {
    const text = normalizeText(document.body?.innerText || "");
    return platform.noMoreTexts.some((marker) => text.includes(marker));
  }

  function extractLoadedCards(platform) {
    const detection = detectCandidateCardNodes(platform);
    return {
      debug: detection.debug,
      cards: detection.nodes
        .map((card) => extractCardPayload(card, platform))
        .filter((card) => card.raw_card_text),
    };
  }

  function detectCandidateCardNodes(platform) {
    const direct = findCandidateCardsBySelectors(platform);
    const actionCount = findActionNodes(document, platform).length;
    if (direct.nodes.length) {
      return {
        nodes: uniqueElements(direct.nodes),
        debug: { strategy: `selector:${direct.selector}`, actionCount, nodeCount: direct.nodes.length },
      };
    }

    const actionNodes = findCandidateCardsByAction(platform);
    if (actionNodes.length) {
      return {
        nodes: uniqueElements(actionNodes),
        debug: { strategy: "action-button", actionCount, nodeCount: actionNodes.length },
      };
    }

    const broadNodes = findCandidateCardsByBroadScan(platform);
    return {
      nodes: uniqueElements(broadNodes),
      debug: { strategy: "broad-scan", actionCount, nodeCount: broadNodes.length },
    };
  }

  function findCandidateCardsBySelectors(platform) {
    for (const selector of platform.selectors.card) {
      const nodes = querySelectorAllSafe(document, selector).filter((node) => isLikelyCandidateCardNode(node, platform));
      if (nodes.length) {
        return { selector, nodes };
      }
    }
    return { selector: "none", nodes: [] };
  }

  function extractCardPayload(card, platform) {
    const rawText = normalizeCardText(card.innerText || card.textContent || "");
    const inferred = inferFieldsFromText(rawText, card, platform);
    const tags = allTexts(card, platform.selectors.tags);
    const detailUrl = firstHref(card, platform.selectors.detailLink) || inferred.detail_url;
    const platformUid = normalizePlatformUid(platform, firstAttr(card, platform.selectors.platformUidAttrs) || inferred.platform_uid);
    return {
      platform: platform.id,
      raw_card_text: rawText,
      name: firstText(card, platform.selectors.name) || inferred.name,
      active_status: firstText(card, platform.selectors.activeStatus) || inferred.active_status,
      expected_salary: firstText(card, platform.selectors.expectedSalary) || inferred.expected_salary,
      work_experience_text: firstText(card, platform.selectors.workExperience) || inferred.work_experience_text,
      education_text: firstText(card, platform.selectors.education) || inferred.education_text,
      tags_text: tags.length ? tags : inferred.tags_text,
      summary_text: firstText(card, platform.selectors.summary) || inferred.summary_text,
      detail_url: detailUrl,
      platform_uid: platformUid,
    };
  }

  function findCandidateCardsByAction(platform) {
    const actionNodes = findActionNodes(document, platform);
    const cards = [];
    for (const actionNode of actionNodes) {
      const card = findCardContainerFromAction(actionNode, platform);
      if (card) {
        cards.push(card);
      }
    }
    return cards;
  }

  function findCandidateCardsByBroadScan(platform) {
    const nodes = querySelectorAllSafe(document, platform.broadScanSelector || "div, li, article, section");
    return nodes.filter((node) => isLikelyCandidateCardNode(node, platform));
  }

  function findActionNodes(root, platform) {
    return querySelectorAllSafe(root, "button, a, [role='button'], div, span").filter((node) => {
      if (!(node instanceof HTMLElement)) {
        return false;
      }
      const text = normalizeText(node.innerText || node.textContent || "");
      return platform.actionTexts.some((label) => isActionTextLine(text, label, platform));
    });
  }

  function findCardContainerFromAction(actionNode, platform) {
    let current = actionNode;
    for (let depth = 0; depth < 8 && current; depth += 1) {
      if (current instanceof HTMLElement && isLikelyCandidateCardNode(current, platform)) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  function isLikelyCandidateCardNode(node, platform) {
    if (platform.id === "boss") {
      return isLikelyBossCardNode(node, platform);
    }
    if (platform.id === "liepin") {
      return isLikelyLiepinCardNode(node, platform);
    }
    return false;
  }

  function isLikelyBossCardNode(node, platform) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 500 || rect.height < 120 || rect.height > 4200) {
      return false;
    }
    const rawText = String(node.innerText || node.textContent || "");
    const lines = splitLines(rawText);
    const normalized = normalizeText(rawText);
    if (lines.length < 4) {
      return false;
    }
    if (!(SALARY_REGEX.test(normalized) || normalized.includes("期望"))) {
      return false;
    }
    if (!(EDUCATION_REGEX.test(normalized) || EXPERIENCE_REGEX.test(normalized) || DATE_RANGE_REGEX.test(normalized))) {
      return false;
    }
    const actionMatches = lines.filter((line) => platform.actionTexts.some((label) => isActionTextLine(line, label, platform)));
    return actionMatches.length === 1;
  }

  function isLikelyLiepinCardNode(node, platform) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 320 || rect.height < 80 || rect.height > 3200) {
      return false;
    }

    const rawText = String(node.innerText || node.textContent || "");
    const lines = splitLines(rawText);
    const normalized = normalizeText(rawText);
    if (lines.length < 3 || lines.length > 100) {
      return false;
    }
    if (isLikelyLiepinLoginOrMarketingBlock(normalized)) {
      return false;
    }
    if (countPatternMatches(normalized, SALARY_REGEX) > 5) {
      return false;
    }

    let score = 0;
    if (SALARY_REGEX.test(normalized)) {
      score += 3;
    }
    if (EDUCATION_REGEX.test(normalized)) {
      score += 2;
    }
    if (EXPERIENCE_REGEX.test(normalized) || DATE_RANGE_REGEX.test(normalized)) {
      score += 2;
    }
    if (ACTIVE_REGEX.test(normalized)) {
      score += 1;
    }
    if (/(当前职位|期望职位|最近工作|工作经历|工作经验|求职状态|到岗|简历|人才|候选人)/.test(normalized)) {
      score += 2;
    }
    if (findActionNodes(node, platform).length > 0) {
      score += 1;
    }
    if (firstHref(node, platform.selectors.detailLink)) {
      score += 1;
    }

    return score >= 5;
  }

  function isLikelyLiepinLoginOrMarketingBlock(text) {
    const markers = ["欢迎来到猎聘", "快捷登录", "密码登录", "获取验证码", "企业服务热线", "AI赋能招聘全流程", "立即注册", "用户协议"];
    const hits = markers.filter((marker) => text.includes(marker)).length;
    return hits >= 2 && !SALARY_REGEX.test(text);
  }

  function inferFieldsFromText(rawText, root, platform) {
    const lines = splitLines(rawText).filter((line) => !platform.actionTexts.some((label) => isActionTextLine(line, label, platform)));
    const firstLine = lines[0] || "";
    const detailLink = findFirstAbsoluteLink(root, platform);
    return {
      name: inferName(firstLine),
      active_status: matchFirst(rawText, ACTIVE_REGEX),
      expected_salary: matchFirst(rawText, SALARY_REGEX),
      work_experience_text: inferWorkExperience(lines),
      education_text: inferEducation(lines),
      tags_text: inferTags(lines),
      summary_text: inferSummary(lines),
      detail_url: detailLink,
      platform_uid: "",
    };
  }

  function inferName(firstLine) {
    const cleaned = normalizeText(firstLine).replace(ACTIVE_REGEX, "").trim();
    if (!cleaned) {
      return "";
    }
    const parts = cleaned.split(/\s+/).filter(Boolean);
    return parts[0] || "";
  }

  function inferWorkExperience(lines) {
    return (
      lines.find((line) => EXPERIENCE_REGEX.test(line)) ||
      lines.find((line) => DATE_RANGE_REGEX.test(line)) ||
      ""
    );
  }

  function inferEducation(lines) {
    return lines.find((line) => EDUCATION_REGEX.test(line)) || "";
  }

  function inferTags(lines) {
    return lines.filter((line) => {
      if (!line || line.length > 18) {
        return false;
      }
      if (SALARY_REGEX.test(line) || EDUCATION_REGEX.test(line) || ACTIVE_REGEX.test(line)) {
        return false;
      }
      if (EXPERIENCE_REGEX.test(line) || DATE_RANGE_REGEX.test(line)) {
        return false;
      }
      return /[\u4e00-\u9fa5A-Za-z+#]/.test(line);
    });
  }

  function inferSummary(lines) {
    return (
      lines.find((line) => line.startsWith("优势")) ||
      lines.find((line) => line.startsWith("自我评价")) ||
      lines.find((line) => line.length >= 12 && !DATE_RANGE_REGEX.test(line) && !SALARY_REGEX.test(line)) ||
      ""
    );
  }

  function findFirstAbsoluteLink(root, platform) {
    for (const selector of platform.selectors.detailLink) {
      const node = querySelectorSafe(root, selector);
      if (node instanceof HTMLAnchorElement) {
        return absolutizeUrl(node.getAttribute("href") || "");
      }
    }
    return "";
  }

  function buildCardKey(card) {
    return card.platform_uid || card.detail_url || card.raw_card_text || JSON.stringify(card);
  }

  function firstText(root, selectors) {
    for (const selector of selectors) {
      const node = querySelectorSafe(root, selector);
      if (node) {
        const text = normalizeText(node.innerText || node.textContent || "");
        if (text) {
          return text;
        }
      }
    }
    return "";
  }

  function allTexts(root, selectors) {
    for (const selector of selectors) {
      const nodes = querySelectorAllSafe(root, selector)
        .map((node) => normalizeText(node.innerText || node.textContent || ""))
        .filter(Boolean);
      if (nodes.length) {
        return nodes;
      }
    }
    return [];
  }

  function firstHref(root, selectors) {
    for (const selector of selectors) {
      const node = querySelectorSafe(root, selector);
      if (node) {
        const href = absolutizeUrl(node.getAttribute("href") || "");
        if (href) {
          return href;
        }
      }
    }
    return "";
  }

  function firstAttr(root, attrs) {
    for (const attr of attrs) {
      const value = normalizeText(root.getAttribute(attr) || "");
      if (value) {
        return value;
      }
    }
    return "";
  }

  function normalizePlatformUid(platform, value) {
    const cleaned = normalizeText(value);
    if (!cleaned) {
      return "";
    }
    if (platform.id === "boss" || cleaned.startsWith(`${platform.id}:`)) {
      return cleaned;
    }
    return `${platform.id}:${cleaned}`;
  }

  function isActionTextLine(text, label, platform) {
    if (!text || !label) {
      return false;
    }
    if (platform.id === "boss") {
      return text === label || text.includes(label);
    }
    return text === label || text.startsWith(label) || text.endsWith(label);
  }

  function collectAncestors(node, maxDepth) {
    const ancestors = [];
    let current = node;
    for (let depth = 0; depth < maxDepth && current; depth += 1) {
      ancestors.push(current);
      current = current.parentElement;
    }
    return ancestors;
  }

  function querySelectorSafe(root, selector) {
    try {
      return root.querySelector(selector);
    } catch (_error) {
      return null;
    }
  }

  function querySelectorAllSafe(root, selector) {
    try {
      return Array.from(root.querySelectorAll(selector));
    } catch (_error) {
      return [];
    }
  }

  function uniqueElements(nodes) {
    return Array.from(new Set(nodes.filter(Boolean)));
  }

  function splitLines(value) {
    return String(value || "")
      .split(/\n+/)
      .map((line) => normalizeText(line))
      .filter(Boolean);
  }

  function matchFirst(value, pattern) {
    const match = String(value || "").match(pattern);
    return match ? normalizeText(match[0]) : "";
  }

  function countPatternMatches(value, pattern) {
    const flags = pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`;
    const clone = new RegExp(pattern.source, flags);
    return Array.from(String(value || "").matchAll(clone)).length;
  }

  function normalizeCardText(value) {
    return splitLines(value).join("\n");
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function absolutizeUrl(value) {
    const href = normalizeText(value);
    if (!href || href.startsWith("javascript:")) {
      return "";
    }
    try {
      return new URL(href, location.href).toString();
    } catch (_error) {
      return href;
    }
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, Number(ms || 0)));
  }
}
