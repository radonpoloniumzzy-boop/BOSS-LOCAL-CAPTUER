if (!globalThis.__bossLocalCaptureInjected) {
  globalThis.__bossLocalCaptureInjected = true;

  const ACTION_TEXTS = ["打招呼", "立即沟通", "继续沟通", "立即开聊"];
  const EDUCATION_REGEX = /(博士|硕士|本科|大专|中专|MBA|EMBA)/;
  const SALARY_REGEX = /\b\d{1,3}\s*[-~]\s*\d{1,3}\s*[Kk]\b/;
  const ACTIVE_REGEX = /(刚刚活跃|今日活跃|本周活跃|刚刚在线|\d+[天日周月]内活跃|活跃)/;
  const DATE_RANGE_REGEX = /\d{4}[./-]\d{1,2}\s*[-~至]\s*(\d{4}[./-]\d{1,2}|至今|现在)/;

  const SELECTORS = {
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
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "boss_collect_cards") {
      return false;
    }

    collectBossCards(message.autoScroll, message.settings)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  });

  async function collectBossCards(autoScroll, settings) {
    if (!location.hostname.includes("zhipin.com")) {
      throw new Error("This tab is not on zhipin.com.");
    }

    const cardsByKey = new Map();
    let roundsCompleted = 0;
    let noNewRounds = 0;
    let lastDetection = { strategy: "none", actionCount: 0, nodeCount: 0 };

    do {
      roundsCompleted += 1;
      const beforeCount = cardsByKey.size;
      const extracted = extractLoadedCards();
      lastDetection = extracted.debug;
      for (const card of extracted.cards) {
        cardsByKey.set(buildKey(card), card);
      }
      const newCount = cardsByKey.size - beforeCount;
      noNewRounds = newCount === 0 ? noNewRounds + 1 : 0;

      if (!autoScroll) {
        break;
      }
      if (roundsCompleted >= settings.maxScrollCount || noNewRounds >= settings.noNewStopRounds) {
        break;
      }
      scrollPage(settings.scrollMode, settings.scrollStep);
      await delay(settings.scrollWaitMs);
    } while (true);

    if (cardsByKey.size === 0) {
      throw new Error(
        `No candidate cards found on page. strategy=${lastDetection.strategy}, ` +
          `candidateNodes=${lastDetection.nodeCount}, actionButtons=${lastDetection.actionCount}`,
      );
    }

    const payload = {
      job_title: settings.jobTitle,
      source_url: location.href,
      cards: Array.from(cardsByKey.values()),
      meta: {
        auto_scroll: autoScroll,
        rounds_completed: roundsCompleted,
        unique_cards: cardsByKey.size,
        page_title: document.title,
        detection_strategy: lastDetection.strategy,
      },
    };

    const apiBase = normalizeLocalApiBase(settings.apiBase);
    let response;
    try {
      response = await fetch(`${apiBase}/api/import/cards`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Boss-Local-Token": settings.apiToken || "",
        },
        body: JSON.stringify(payload),
      });
    } catch (error) {
      throw new Error(formatLocalApiFetchError(apiBase, error));
    }
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || `Local API returned ${response.status}`);
    }
    return {
      localUniqueCards: cardsByKey.size,
      importResult: result.result,
    };
  }

  function extractLoadedCards() {
    const detection = detectCandidateCardNodes();
    return {
      debug: detection.debug,
      cards: detection.nodes
        .map((card) => extractCardPayload(card))
        .filter((card) => card.raw_card_text),
    };
  }

  function detectCandidateCardNodes() {
    const directNodes = queryAllWithFallback(document, SELECTORS.card).filter(isLikelyCandidateCardNode);
    const actionCount = findActionNodes(document).length;
    if (directNodes.length) {
      return {
        nodes: uniqueElements(directNodes),
        debug: { strategy: "selector", actionCount, nodeCount: directNodes.length },
      };
    }

    const actionNodes = findCandidateCardsByAction();
    if (actionNodes.length) {
      return {
        nodes: uniqueElements(actionNodes),
        debug: { strategy: "action-button", actionCount, nodeCount: actionNodes.length },
      };
    }

    const broadNodes = findCandidateCardsByBroadScan();
    return {
      nodes: uniqueElements(broadNodes),
      debug: { strategy: "broad-scan", actionCount, nodeCount: broadNodes.length },
    };
  }

  function extractCardPayload(card) {
    const rawText = normalizeCardText(card.innerText || card.textContent || "");
    const inferred = inferFieldsFromText(rawText, card);
    return {
      raw_card_text: rawText,
      name: firstText(card, SELECTORS.name) || inferred.name,
      active_status: firstText(card, SELECTORS.activeStatus) || inferred.active_status,
      expected_salary: firstText(card, SELECTORS.expectedSalary) || inferred.expected_salary,
      work_experience_text: firstText(card, SELECTORS.workExperience) || inferred.work_experience_text,
      education_text: firstText(card, SELECTORS.education) || inferred.education_text,
      tags_text: allTexts(card, SELECTORS.tags).length ? allTexts(card, SELECTORS.tags) : inferred.tags_text,
      summary_text: firstText(card, SELECTORS.summary) || inferred.summary_text,
      detail_url: firstHref(card, SELECTORS.detailLink) || inferred.detail_url,
      platform_uid: firstAttr(card, SELECTORS.platformUidAttrs) || inferred.platform_uid,
    };
  }

  function findCandidateCardsByAction() {
    const actionNodes = findActionNodes(document);
    const cards = [];
    for (const actionNode of actionNodes) {
      const card = findCardContainerFromAction(actionNode);
      if (card) {
        cards.push(card);
      }
    }
    return cards;
  }

  function findCandidateCardsByBroadScan() {
    const nodes = Array.from(document.querySelectorAll("div, li, article, section"));
    return nodes.filter(isLikelyCandidateCardNode);
  }

  function findActionNodes(root) {
    return Array.from(root.querySelectorAll("button, a, [role='button'], div, span")).filter((node) => {
      if (!(node instanceof HTMLElement)) {
        return false;
      }
      const text = normalizeText(node.innerText || node.textContent || "");
      return ACTION_TEXTS.some((label) => text === label || text.startsWith(label));
    });
  }

  function findCardContainerFromAction(actionNode) {
    let current = actionNode;
    for (let depth = 0; depth < 8 && current; depth += 1) {
      if (current instanceof HTMLElement && isLikelyCandidateCardNode(current)) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  function isLikelyCandidateCardNode(node) {
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
    if (!(EDUCATION_REGEX.test(normalized) || /\d+\s*年/.test(normalized) || DATE_RANGE_REGEX.test(normalized))) {
      return false;
    }
    const actionMatches = lines.filter((line) => ACTION_TEXTS.some((label) => line === label || line.includes(label)));
    if (actionMatches.length !== 1) {
      return false;
    }
    return true;
  }

  function inferFieldsFromText(rawText, root) {
    const lines = splitLines(rawText).filter((line) => !ACTION_TEXTS.some((label) => line.includes(label)));
    const firstLine = lines[0] || "";
    const detailLink = findFirstAbsoluteLink(root);
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
      lines.find((line) => /\d+\s*岁/.test(line) || /\d+\s*年/.test(line)) ||
      lines.find((line) => DATE_RANGE_REGEX.test(line)) ||
      ""
    );
  }

  function inferEducation(lines) {
    return lines.find((line) => EDUCATION_REGEX.test(line)) || "";
  }

  function inferTags(lines) {
    return lines.filter((line) => {
      if (!line || line.length > 16) {
        return false;
      }
      if (SALARY_REGEX.test(line) || EDUCATION_REGEX.test(line) || ACTIVE_REGEX.test(line)) {
        return false;
      }
      if (/\d+\s*岁/.test(line) || /\d+\s*年/.test(line) || DATE_RANGE_REGEX.test(line)) {
        return false;
      }
      return /[\u4e00-\u9fa5A-Za-z+#]/.test(line);
    });
  }

  function inferSummary(lines) {
    return (
      lines.find((line) => line.startsWith("优势")) ||
      lines.find((line) => line.length >= 12 && !DATE_RANGE_REGEX.test(line) && !SALARY_REGEX.test(line)) ||
      ""
    );
  }

  function findFirstAbsoluteLink(root) {
    const node = root.querySelector("a[href*='geek'], a[href*='candidate'], a[href*='zhipin.com']");
    if (!(node instanceof HTMLAnchorElement)) {
      return "";
    }
    return absolutizeUrl(node.getAttribute("href") || "");
  }

  function buildKey(card) {
    return card.platform_uid || card.detail_url || card.raw_card_text;
  }

  function scrollPage(mode, step) {
    const delta = mode === "page" ? window.innerHeight : Number(step || 900);
    window.scrollBy(0, delta);
  }

  function firstText(root, selectors) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
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
      const nodes = Array.from(root.querySelectorAll(selector))
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
      const node = root.querySelector(selector);
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

  function queryAllWithFallback(root, selectors) {
    for (const selector of selectors) {
      const nodes = Array.from(root.querySelectorAll(selector));
      if (nodes.length) {
        return nodes;
      }
    }
    return [];
  }

  function uniqueElements(nodes) {
    return Array.from(new Set(nodes));
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

  function normalizeCardText(value) {
    return splitLines(value).join("\n");
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function trimTrailingSlash(value) {
    return String(value || "").replace(/\/+$/, "");
  }

  function normalizeLocalApiBase(value) {
    let raw = String(value || "http://127.0.0.1:17863").trim() || "http://127.0.0.1:17863";
    if (!/^[a-z][a-z\d+.-]*:\/\//i.test(raw)) {
      raw = `http://${raw}`;
    }
    try {
      const url = new URL(raw);
      const hostname = url.hostname.toLowerCase();
      if (hostname === "localhost" || hostname === "::1" || hostname === "[::1]") {
        url.hostname = "127.0.0.1";
      }
      return trimTrailingSlash(url.toString());
    } catch (_error) {
      return trimTrailingSlash(raw.replace(/^http:\/\/(?:localhost|\[::1\])(?=[:/]|$)/i, "http://127.0.0.1"));
    }
  }

  function formatLocalApiFetchError(apiBase, error) {
    return [
      `无法连接本地接口：${apiBase}`,
      "请确认桌面端已启动；扩展里的接口地址使用 http://127.0.0.1:17863；Token 与桌面端设置页一致。",
      "如果刚更新或重新安装过扩展，请在 chrome://extensions 里点击重新加载。",
      `浏览器错误：${error?.message || String(error)}`,
    ].join("\n");
  }

  function absolutizeUrl(value) {
    const href = normalizeText(value);
    if (!href) {
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
