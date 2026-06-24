if (typeof globalThis.__bossLocalChatOps !== "function") {
  const REQUEST_RESUME_LABELS = ["求简历", "索要简历", "请求简历", "简历"];
  const SEND_LABELS = ["发送", "发 送", "发送消息"];
  const ATTACHMENT_HINTS = ["附件简历", "点击预览附件简历", ".pdf", "pdf"];
  const PDF_NAME_REGEX = /[^\\/:*?"<>|\r\n]+\.pdf/gi;
  const INPUT_SELECTORS = [
    ".bosschat-chat-input",
    ".chat-input",
    ".input-area",
    "[contenteditable='true']",
    "textarea",
  ];
  const BUTTON_SELECTORS = [
    "button",
    "a",
    "[role='button']",
    ".btn",
    ".button",
  ];

  globalThis.__bossLocalChatOps = async function bossLocalChatOps(action, options) {
    if (!location.hostname.includes("zhipin.com")) {
      return { ok: false, error: "Current page is not on zhipin.com." };
    }

    if (action === "request_resume") {
      return requestResume(options || {});
    }
    if (action === "find_resume") {
      return findResume(options || {});
    }
    if (action === "open_resume_preview") {
      return openResumePreview(options || {});
    }
    return { ok: false, error: `Unsupported action: ${String(action)}` };
  };

  async function requestResume(options) {
    const messageText = String(options.messageText || "").trim();
    const result = {
      ok: true,
      sentMessage: false,
      clickedRequestButton: false,
      logs: [],
    };

    if (messageText) {
      const input = findChatInput();
      if (!input) {
        result.ok = false;
        result.error = "Chat input box was not found on the current page.";
        return result;
      }
      focusElement(input);
      setChatInputValue(input, messageText);
      await delay(120);

      const sendButton = findVisibleButton(SEND_LABELS);
      if (sendButton) {
        clickElement(sendButton);
        result.sentMessage = true;
        result.logs.push("Sent the custom message.");
      } else {
        triggerEnter(input);
        result.sentMessage = true;
        result.logs.push("Sent the custom message with Enter.");
      }
      await delay(400);
    }

    const requestButton = findVisibleButton(REQUEST_RESUME_LABELS, { exact: false, preferShorterText: true });
    if (requestButton && isElementEnabled(requestButton)) {
      clickElement(requestButton);
      result.clickedRequestButton = true;
      result.logs.push("Clicked the built-in request-resume button.");
      await delay(600);
    } else {
      result.logs.push("No visible request-resume button was found.");
    }

    if (!result.sentMessage && !result.clickedRequestButton) {
      result.ok = false;
      result.error = "No message was sent and no request-resume button was found.";
    }
    return result;
  }

  function findResume() {
    const attachments = collectResumeAttachments();
    return {
      ok: attachments.length > 0,
      attachments: attachments.map(serializeAttachment),
      logs: attachments.length ? ["Found resume attachment candidates in the current conversation."] : [],
      error: attachments.length ? "" : "No resume attachment card was found in the current conversation.",
    };
  }

  function openResumePreview() {
    const attachments = collectResumeAttachments();
    const attachment = attachments[attachments.length - 1];
    if (!attachment) {
      return { ok: false, error: "No resume attachment card was found in the current conversation." };
    }
    const previewTarget = findPreviewTarget(attachment.root);
    if (!previewTarget) {
      return { ok: false, error: "A resume card was found, but there is no clickable preview target." };
    }
    clickElement(previewTarget);
    return {
      ok: true,
      attachment: serializeAttachment(attachment),
      logs: ["Clicked the resume preview target."],
    };
  }

  function collectResumeAttachments() {
    const attachmentRoots = uniqueElements(
      Array.from(document.querySelectorAll("a, button, div, article, section, li")).filter(isResumeAttachmentNode),
    );

    return attachmentRoots.map((root, index) => {
      const urls = collectCandidateUrls(root);
      const fileName = inferPdfFileName(root);
      return {
        id: `attachment-${index + 1}`,
        fileName,
        urls,
        text: normalizeText(root.innerText || root.textContent || ""),
        root,
      };
    });
  }

  function serializeAttachment(attachment) {
    return {
      id: attachment.id,
      fileName: attachment.fileName,
      urls: Array.isArray(attachment.urls) ? attachment.urls : [],
      text: attachment.text || "",
    };
  }

  function isResumeAttachmentNode(node) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    if (!isElementVisible(node)) {
      return false;
    }
    const text = normalizeText(node.innerText || node.textContent || "");
    if (!text) {
      return false;
    }
    if (!ATTACHMENT_HINTS.some((hint) => text.includes(hint))) {
      return false;
    }

    const hrefs = collectCandidateUrls(node);
    const hasPdfName = PDF_NAME_REGEX.test(text);
    PDF_NAME_REGEX.lastIndex = 0;
    return hasPdfName || hrefs.length > 0;
  }

  function inferPdfFileName(root) {
    const text = normalizeText(root.innerText || root.textContent || "");
    const matches = text.match(PDF_NAME_REGEX) || [];
    PDF_NAME_REGEX.lastIndex = 0;
    if (matches.length > 0) {
      return matches[0];
    }
    const urls = collectCandidateUrls(root);
    for (const url of urls) {
      const match = decodeURIComponentSafe(url).match(PDF_NAME_REGEX);
      PDF_NAME_REGEX.lastIndex = 0;
      if (match && match.length > 0) {
        return match[0];
      }
    }
    return "boss_resume.pdf";
  }

  function collectCandidateUrls(root) {
    const urls = new Set();
    collectUrlFromNode(root, urls);
    root.querySelectorAll("*").forEach((node) => collectUrlFromNode(node, urls));
    const parentAnchor = root.closest("a[href]");
    if (parentAnchor) {
      collectUrlFromNode(parentAnchor, urls);
    }
    return Array.from(urls);
  }

  function collectUrlFromNode(node, urls) {
    if (!(node instanceof HTMLElement)) {
      return;
    }
    const candidateValues = [];
    for (const attrName of node.getAttributeNames()) {
      if (/href|src|url|download/i.test(attrName)) {
        candidateValues.push(node.getAttribute(attrName) || "");
      }
    }
    if (node instanceof HTMLAnchorElement) {
      candidateValues.push(node.href || "");
    }
    if (node instanceof HTMLIFrameElement || node instanceof HTMLImageElement) {
      candidateValues.push(node.src || "");
    }
    for (const value of candidateValues) {
      const cleaned = absolutizeUrl(value);
      if (isProbablyDownloadableUrl(cleaned)) {
        urls.add(cleaned);
      }
    }
  }

  function findPreviewTarget(root) {
    if (!(root instanceof HTMLElement)) {
      return null;
    }
    const clickableNodes = [root, ...root.querySelectorAll("a, button, [role='button'], span, div")];
    return (
      clickableNodes.find((node) => {
        if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
          return false;
        }
        const text = normalizeText(node.innerText || node.textContent || "");
        return text.includes("预览") || text.includes("附件简历") || text.includes("pdf");
      }) || null
    );
  }

  function findChatInput() {
    for (const selector of INPUT_SELECTORS) {
      const candidates = Array.from(document.querySelectorAll(selector));
      for (const node of candidates) {
        if (!(node instanceof HTMLElement)) {
          continue;
        }
        if (!isElementVisible(node)) {
          continue;
        }
        const rect = node.getBoundingClientRect();
        if (rect.width < 120 || rect.height < 18) {
          continue;
        }
        return node;
      }
    }
    return null;
  }

  function findVisibleButton(labels, options = {}) {
    const { exact = false, preferShorterText = false } = options;
    const candidates = [];
    for (const selector of BUTTON_SELECTORS) {
      const nodes = document.querySelectorAll(selector);
      for (const node of nodes) {
        if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
          continue;
        }
        const text = normalizeText(node.innerText || node.textContent || "");
        if (!text) {
          continue;
        }
        const matched = labels.some((label) => (exact ? text === label : text.includes(label)));
        if (matched) {
          candidates.push({ node, text, rect: node.getBoundingClientRect() });
        }
      }
    }
    if (candidates.length === 0) {
      return null;
    }
    candidates.sort((left, right) => {
      if (preferShorterText && left.text.length !== right.text.length) {
        return left.text.length - right.text.length;
      }
      if (Math.abs(left.rect.top - right.rect.top) > 4) {
        return right.rect.top - left.rect.top;
      }
      return right.rect.left - left.rect.left;
    });
    return candidates[0].node;
  }

  function setChatInputValue(input, value) {
    if (input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement) {
      input.focus();
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    input.focus();
    input.textContent = value;
    input.dispatchEvent(new InputEvent("input", { bubbles: true, data: value, inputType: "insertText" }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function triggerEnter(input) {
    const eventInit = {
      key: "Enter",
      code: "Enter",
      keyCode: 13,
      which: 13,
      bubbles: true,
    };
    input.dispatchEvent(new KeyboardEvent("keydown", eventInit));
    input.dispatchEvent(new KeyboardEvent("keypress", eventInit));
    input.dispatchEvent(new KeyboardEvent("keyup", eventInit));
  }

  function clickElement(node) {
    focusElement(node);
    node.click();
  }

  function focusElement(node) {
    if (node instanceof HTMLElement) {
      node.focus({ preventScroll: false });
    }
  }

  function isElementVisible(node) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    const style = window.getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isElementEnabled(node) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    if ("disabled" in node && node.disabled) {
      return false;
    }
    const ariaDisabled = node.getAttribute("aria-disabled");
    return ariaDisabled !== "true";
  }

  function uniqueElements(nodes) {
    return Array.from(new Set(nodes));
  }

  function normalizeText(value) {
    return String(value || "")
      .replace(/\s+/g, " ")
      .replace(/\u00a0/g, " ")
      .trim();
  }

  function absolutizeUrl(value) {
    const text = String(value || "").trim();
    if (!text || text.startsWith("javascript:") || text.startsWith("#")) {
      return "";
    }
    try {
      return new URL(text, location.href).toString();
    } catch (_error) {
      return "";
    }
  }

  function decodeURIComponentSafe(value) {
    try {
      return decodeURIComponent(value);
    } catch (_error) {
      return value;
    }
  }

  function isProbablyDownloadableUrl(value) {
    if (!value) {
      return false;
    }
    const lower = value.toLowerCase();
    return (
      lower.includes(".pdf") ||
      lower.includes("resume") ||
      lower.includes("attachment") ||
      lower.includes("download") ||
      lower.includes("file")
    );
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }
}
