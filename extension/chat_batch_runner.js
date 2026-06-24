if (!globalThis.__bossLocalChatBatchRunner) {
  const CHAT_RUNNER_VERSION = "0.3.25";
  const TEXTS = {
    requestResume: ["求简历", "索要简历", "请求简历"],
    send: ["发送", "发 送", "发送消息"],
    confirm: ["确认", "确定"],
    download: ["下载", "下载简历", "保存"],
    close: ["关闭", "返回", "取消"],
    acceptAttachment: ["同意", "同意接收", "接收", "接受", "确认"],
    topRequestResume: ["附件简历"],
    attachmentResume: ["附件简历", "点击预览附件简历"],
    preview: ["预览", "点击预览附件简历", "查看附件"],
    requestSent: ["简历请求已发送", "已请求简历"],
  };
  const TIME_TEXT_REGEX = /^(?:\d{1,2}:\d{2}|昨天|前天|今天|刚刚|\d{1,2}[/-]\d{1,2}|\d{4}[./-]\d{1,2}[./-]\d{1,2})$/;

  const SELECTORS = {
    sessionScrollContainer: ["div.geek-list-scroll-wrap", "[class*='geek-list-scroll-wrap']", "[class*='scroll-wrap']"],
    sessionItem: ["div.geek-item", ".geek-item", "[class*='geek-item']", "[class*='chat-item']"],
    sessionItemWrap: ["div.geek-item-warp", ".geek-item-warp", "[class*='item-wrap']"],
    sessionActive: ["div.geek-active", ".geek-active", "[aria-selected='true']", "[class*='active']"],
    sessionName: ["span.name", ".name", "[class*='name']"],
    sessionTime: ["span.time", ".time", "[class*='time']"],
    sessionPreview: ["p.gray", ".gray", "[class*='preview']", "[class*='summary']"],
    sessionStatus: ["p.gray span", ".gray span", "[class*='status'] span", "[class*='status']"],
    unreadBadge: ["[class*='unread']", "[class*='badge']", "[class*='dot']", "[class*='red']", ".badge", ".dot"],
    messageContainer: [
      ".chat-message-list",
      ".message-list",
      ".chat-record",
      ".chat-content",
      "[class*='message-list']",
      "[class*='chat-message']",
    ],
    composerInput: [".bosschat-chat-input", ".chat-input", "[contenteditable='true']", "textarea"],
    sendButton: [".btn-send", "[class*='btn-send']", "button", "[role='button']", "a"],
    requestResumeButton: ["span.btn-doc button", ".btn-doc button", "[class*='btn-doc'] button", "button", "[role='button']", "a"],
    modalRoot: [".dialog-wrap", ".dialog-container", ".boss-popup", ".ui-dialog", "[role='dialog']", "[class*='dialog']"],
  };

  const runnerState = {
    running: false,
    stopRequested: false,
    runToken: "",
    mode: "request_resume",
    settings: null,
    processedKeys: new Set(),
    downloadedAttachmentKeys: new Set(),
    stats: createEmptyStats(),
    currentSession: "",
    lastMessage: "就绪。",
    scanMessage: "",
    scanDebug: "",
    error: "",
    runtimeLogs: [],
  };

  const onRunnerMessage = (message, _sender, sendResponse) => {
    if (message?.type === "boss_chat_action") {
      handleChatAction(message.action, message.settings || {})
        .then((result) => sendResponse(result))
        .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
      return true;
    }
    if (message?.type === "boss_batch_command") {
      handleBatchCommand(message.command, message.settings || {}, message.reason || "", message.mode || "")
        .then((result) => sendResponse(result))
        .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
      return true;
    }
    return false;
  };
  chrome.runtime.onMessage.addListener(onRunnerMessage);

  globalThis.__bossLocalChatBatchRunner = {
    state: runnerState,
    version: CHAT_RUNNER_VERSION,
    dispose(reason = "") {
      runnerState.stopRequested = true;
      runnerState.running = false;
      runnerState.runToken = "";
      runnerState.lastMessage = reason || runnerState.lastMessage;
      chrome.runtime.onMessage.removeListener(onRunnerMessage);
    },
  };

  function createRunToken() {
    return `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
  }

  function appendRunnerLog(message) {
    const text = String(message || "").trim();
    if (!text) {
      return "";
    }
    const line = `${formatClock(new Date())} ${text}`;
    runnerState.runtimeLogs = [line, ...(Array.isArray(runnerState.runtimeLogs) ? runnerState.runtimeLogs : [])].slice(0, 120);
    try {
      console.debug("[BossBatch]", line);
    } catch (_error) {}
    return line;
  }

  function getRunnerLogs(limit = 80) {
    return Array.isArray(runnerState.runtimeLogs) ? runnerState.runtimeLogs.slice(0, limit) : [];
  }

  function isRunTokenActive(runToken) {
    return Boolean(runToken) && runnerState.runToken === runToken;
  }

  function shouldAbortRunner(options = {}) {
    const respectStop = options.respectStop !== false;
    const runToken = String(options.runToken || "");
    if (runToken && !isRunTokenActive(runToken)) {
      return true;
    }
    if (respectStop && runnerState.stopRequested) {
      return true;
    }
    if (runToken && !runnerState.running) {
      return true;
    }
    return false;
  }

  async function handleChatAction(action, settings) {
    if (!isBossPage()) {
      return { ok: false, error: "当前页面不是 Boss 站点。" };
    }
    switch (action) {
      case "request_resume":
        return performRequestResume(settings);
      case "download_current_resume":
        return downloadCurrentResume(settings);
      case "request_and_download":
        return requestAndDownload(settings);
      case "get_batch_debug":
        return scanVisibleSessions();
      default:
        return { ok: false, error: `未知动作：${String(action || "")}` };
    }
  }

  async function handleBatchCommand(command, settings, reason, mode) {
    if (!isBossPage()) {
      return { ok: false, error: "当前页面不是 Boss 站点。" };
    }
    if (command === "start") {
      return startBatch(settings, mode);
    }
    if (command === "stop") {
      runnerState.stopRequested = true;
      runnerState.running = false;
      runnerState.runToken = "";
      runnerState.lastMessage = reason || "已收到停止请求。";
      appendRunnerLog(`stop requested: ${runnerState.lastMessage}`);
      await reportProgress({ phase: "stopping", mode: runnerState.mode, message: runnerState.lastMessage, eventText: runnerState.lastMessage });
      return { ok: true, message: runnerState.lastMessage };
    }
    return { ok: false, error: `未知批量命令：${String(command || "")}` };
  }

  async function startBatch(settings, mode) {
    if (runnerState.running) {
      runnerState.stopRequested = true;
      runnerState.running = false;
      runnerState.runToken = "";
      await waitForRunner(250, { respectStop: false });
    }
    const runToken = createRunToken();
    runnerState.running = true;
    runnerState.stopRequested = false;
    runnerState.runToken = runToken;
    runnerState.mode = normalizeBatchMode(mode);
    runnerState.settings = normalizeSettings(settings);
    runnerState.processedKeys = new Set();
    runnerState.downloadedAttachmentKeys = new Set();
    runnerState.stats = createEmptyStats();
    runnerState.currentSession = "";
    runnerState.error = "";
    runnerState.scanMessage = "";
    runnerState.scanDebug = "";
    runnerState.runtimeLogs = [];
    runnerState.lastMessage = runnerState.mode === "download_only" ? "批量下载任务已启动。" : "批量求简历任务已启动。";
    appendRunnerLog(`start batch mode=${runnerState.mode} token=${runToken}`);
    await reportProgress({ phase: "running", mode: runnerState.mode, message: runnerState.lastMessage, eventText: runnerState.lastMessage });
    void runBatchLoop(runToken);
    return { ok: true, message: runnerState.lastMessage, runnerVersion: CHAT_RUNNER_VERSION, runToken };
  }

  async function runBatchLoop(runToken) {
    let stagnantRounds = 0;
    let completionMessage = "";
    try {
      while (!shouldAbortRunner({ runToken })) {
        if (hasReachedBatchLimit()) {
          completionMessage = buildBatchLimitMessage();
          appendRunnerLog(`batch limit reached: processed=${runnerState.stats.processed} max=${runnerState.settings.maxBatchSessions}`);
          break;
        }
        const verificationBlock = detectAccountVerificationBlock();
        if (verificationBlock) {
          runnerState.stopRequested = true;
          runnerState.running = false;
          completionMessage = `检测到账号验证/登录异常：${verificationBlock}。已暂停批量任务，请手动验证后重新启动。`;
          appendRunnerLog(`verification block detected: ${verificationBlock}`);
          await reportProgress({
            phase: "stopped",
            mode: runnerState.mode,
            message: completionMessage,
            eventText: "检测到账号验证，批量任务已暂停",
          });
          break;
        }
        const scan = scanVisibleSessions();
        applyScanDiagnostics(scan);
        const queue = scan.items.filter((item) => shouldProcessSession(item));
        const scanProgressMessage = buildScanProgressMessage(scan, queue.length);
        appendRunnerLog(`scan visible=${scan.items.length} eligible=${queue.length} mode=${runnerState.mode}`);
        if (queue.length === 0) {
          const scrollResult = scrollSessionList(runnerState.settings.scrollStep);
          appendRunnerLog(`scroll moved=${scrollResult.moved ? "yes" : "no"} bottom=${scrollResult.atBottom ? "yes" : "no"}`);
          if (!scrollResult.moved) {
            stagnantRounds += 1;
          } else {
            const shouldContinue = await waitForRunner(runnerState.settings.scrollWaitMs, { runToken });
            if (!shouldContinue) {
              break;
            }
            const afterScroll = scanVisibleSessions();
            applyScanDiagnostics(afterScroll);
            stagnantRounds = afterScroll.items.some((item) => shouldProcessSession(item)) ? 0 : stagnantRounds + 1;
          }
          if ((scrollResult.atBottom && stagnantRounds >= 1) || stagnantRounds >= runnerState.settings.noNewStopRounds) {
            completionMessage = buildBatchCompletionMessage(scan);
            break;
          }
          await reportProgress({
            phase: "running",
            mode: runnerState.mode,
            message: scanProgressMessage,
            scanMessage: runnerState.scanMessage,
            scanDebug: runnerState.scanDebug,
          });
          continue;
        }

        stagnantRounds = 0;
        for (const item of queue) {
          if (shouldAbortRunner({ runToken })) {
            break;
          }
          if (hasReachedBatchLimit()) {
            completionMessage = buildBatchLimitMessage();
            appendRunnerLog(`batch limit reached before session: processed=${runnerState.stats.processed} max=${runnerState.settings.maxBatchSessions}`);
            break;
          }
          runnerState.processedKeys.add(item.key);
          await processBatchSession(item, runToken);
          const verificationAfterSession = detectAccountVerificationBlock();
          if (verificationAfterSession) {
            runnerState.stopRequested = true;
            runnerState.running = false;
            completionMessage = `检测到账号验证/登录异常：${verificationAfterSession}。已暂停批量任务，请手动验证后重新启动。`;
            appendRunnerLog(`verification block detected after session: ${verificationAfterSession}`);
            break;
          }
          if (!(await waitForRunner(runnerState.settings.batchActionDelayMs, { runToken }))) {
            break;
          }
        }
      }

      const stopped = shouldAbortRunner({ runToken });
      const message = completionMessage || (stopped ? "批量任务已停止。" : buildBatchCompletionMessage(scanVisibleSessions()));
      appendRunnerLog(stopped ? "batch loop stopped" : `batch loop completed: ${message}`);
      await finishBatch(stopped ? "stopped" : "completed", message, "", runToken);
    } catch (error) {
      runnerState.error = error?.message || String(error);
      appendRunnerLog(`batch loop failed: ${runnerState.error}`);
      await finishBatch("failed", `批量任务失败：${runnerState.error}`, runnerState.error, runToken);
    }
  }

  function shouldProcessSession(session) {
    if (runnerState.processedKeys.has(session.key)) {
      return false;
    }
    return runnerState.mode === "download_only" ? true : Boolean(session.unread);
  }

  function hasReachedBatchLimit() {
    const maxBatchSessions = Math.min(Math.max(Number(runnerState.settings?.maxBatchSessions || 50), 1), 50);
    return Number(runnerState.stats?.processed || 0) >= maxBatchSessions;
  }

  function buildBatchLimitMessage() {
    const maxBatchSessions = Math.min(Math.max(Number(runnerState.settings?.maxBatchSessions || 50), 1), 50);
    return `本批次已达到 ${maxBatchSessions} 人上限，已自动停止。`;
  }

  async function processBatchSession(session, runToken) {
    runnerState.currentSession = session.name || session.preview || session.key;
    runnerState.stats.processed += 1;
    appendRunnerLog(`session start: ${runnerState.currentSession}`);
    await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: `正在处理：${runnerState.currentSession}`, eventText: `处理会话：${runnerState.currentSession}` });

    const activated = await openSession(session, { runToken });
    if (!activated.ok) {
      runnerState.stats.failed += 1;
      appendRunnerLog(`session open failed: ${runnerState.currentSession} | ${activated.error || "unknown error"}`);
      await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: activated.error, eventText: `打开会话失败：${runnerState.currentSession}` });
      return;
    }

    appendRunnerLog(`session open ok: ${runnerState.currentSession}`);
    if (!(await waitForRunner(700, { runToken }))) {
      appendRunnerLog(`session interrupted before action: ${runnerState.currentSession}`);
      return;
    }

    if (runnerState.mode === "download_only") {
      await processDownloadOnlySession(session.key, runToken);
      return;
    }

    if (hasAttachmentResumeInConversation()) {
      runnerState.stats.skipped += 1;
      appendRunnerLog(`session skipped: attachment already exists in ${runnerState.currentSession}`);
      await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: `跳过 ${runnerState.currentSession}：当前会话已存在附件简历。`, eventText: `跳过：${runnerState.currentSession} 已有附件简历` });
      return;
    }

    if (hasSentResumeRequestInConversation(runnerState.settings)) {
      runnerState.stats.skipped += 1;
      appendRunnerLog(`session skipped: resume request already sent in ${runnerState.currentSession}`);
      await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: `跳过 ${runnerState.currentSession}：当前会话已发过求简历信息。`, eventText: `跳过：${runnerState.currentSession} 已发过求简历` });
      return;
    }

    const requestResult = await performRequestResume(runnerState.settings, { respectStop: true, runToken });
    if (!requestResult.ok) {
      runnerState.stats.failed += 1;
      appendRunnerLog(`request resume failed: ${runnerState.currentSession} | ${requestResult.error || "unknown error"}`);
      await reportProgress({
        phase: "running",
        mode: runnerState.mode,
        currentSession: runnerState.currentSession,
        message: [requestResult.error || "求简历失败。", Array.isArray(requestResult.logs) ? requestResult.logs.join(" / ") : ""].filter(Boolean).join(" "),
        eventText: `失败：${runnerState.currentSession} 求简历未完成`,
      });
      return;
    }

    runnerState.stats.requested += 1;
    appendRunnerLog(`request resume ok: ${runnerState.currentSession}${requestResult.messageOnly ? " message-only" : ""}`);
    await reportProgress({
      phase: "running",
      mode: runnerState.mode,
      currentSession: runnerState.currentSession,
      message: requestResult.messageOnly
        ? `已向 ${runnerState.currentSession} 发送求简历话术；页面求简历按钮当前需双方回复后才可用。`
        : `已完成 ${runnerState.currentSession} 的话术发送和求简历/附件简历操作。`,
      eventText: requestResult.messageOnly
        ? `完成：${runnerState.currentSession} 已发送求简历话术`
        : `完成：${runnerState.currentSession} 已发送话术并点击求简历`,
    });
  }

  async function processDownloadOnlySession(sessionKey, runToken) {
    const attachments = collectResumeAttachments({ downloadableOnly: false, includePending: true });
    appendRunnerLog(`download scan: ${runnerState.currentSession} attachments=${attachments.length}`);
    if (attachments.length === 0) {
      runnerState.stats.skipped += 1;
      runnerState.stats.skippedNoAttachment += 1;
      appendRunnerLog(`download skipped, no attachment: ${runnerState.currentSession}`);
      await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: `跳过 ${runnerState.currentSession}：当前会话没有附件简历。`, eventText: `跳过：${runnerState.currentSession} 没有附件简历` });
      return;
    }

    const downloadResult = await downloadAttachmentsInConversation(sessionKey, runnerState.settings, {
      downloadAll: true,
      runToken,
      downloadableOnly: false,
    });
    if (!downloadResult.ok) {
      runnerState.stats.failed += 1;
      appendRunnerLog(`download failed: ${runnerState.currentSession} | ${downloadResult.error || "unknown error"}`);
      await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: downloadResult.error || "附件简历下载失败。", eventText: `失败：${runnerState.currentSession} 附件简历下载失败` });
      return;
    }

    if (downloadResult.downloadedCount === 0) {
      runnerState.stats.skipped += 1;
      appendRunnerLog(`download skipped, already downloaded: ${runnerState.currentSession}`);
      await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: `跳过 ${runnerState.currentSession}：附件简历已在本轮下载过。`, eventText: `跳过：${runnerState.currentSession} 附件已下载` });
      return;
    }

    await reportProgress({ phase: "running", mode: runnerState.mode, currentSession: runnerState.currentSession, message: `已开始下载 ${runnerState.currentSession} 的 ${downloadResult.downloadedCount} 份附件简历。`, eventText: `完成：${runnerState.currentSession} 已开始下载 ${downloadResult.downloadedCount} 份简历` });
  }

  async function requestAndDownload(settings) {
    const requestResult = await performRequestResume(settings, { respectStop: false });
    if (!requestResult.ok) {
      return requestResult;
    }
    const downloadResult = await waitForAttachmentAndDownload(normalizeSettings(settings), { respectStop: false, allowAlreadyDownloaded: true });
    return { ok: downloadResult.ok, request: requestResult, download: downloadResult, error: downloadResult.error || "" };
  }

  async function downloadCurrentResume(settings) {
    return downloadAttachmentsInConversation(runnerState.currentSession || "current", normalizeSettings(settings), {
      downloadAll: false,
      allowAlreadyDownloaded: true,
      downloadableOnly: false,
    });
  }

  async function waitForAttachmentAndDownload(settings, options = {}) {
    const waitMs = Math.max(Number(settings.waitSeconds || 45), 5) * 1000;
    const pollMs = Math.max(Number(settings.pollIntervalMs || 2000), 500);
    const startedAt = Date.now();
    appendRunnerLog(`wait attachment for download: timeout=${waitMs} poll=${pollMs}`);
    while (Date.now() - startedAt <= waitMs) {
      if (shouldAbortRunner(options)) {
        return { ok: false, error: "批量任务已收到停止请求。" };
      }
      if (hasAttachmentResumeInConversation()) {
        return downloadAttachmentsInConversation(runnerState.currentSession || "current", settings, {
          downloadAll: false,
          allowAlreadyDownloaded: Boolean(options.allowAlreadyDownloaded),
          runToken: options.runToken,
          downloadableOnly: false,
        });
      }
      const shouldContinue = await waitForRunner(pollMs, { respectStop: Boolean(options.respectStop), runToken: options.runToken });
      if (!shouldContinue && options.respectStop) {
        return { ok: false, error: "批量任务已收到停止请求。" };
      }
    }
    return { ok: false, error: "等待超时，当前会话中未收到附件简历。" };
  }

  async function acceptPendingAttachmentRequests(options = {}) {
    const messageContainer = findMessageContainer();
    if (!messageContainer) {
      return { clicked: 0 };
    }
    const cards = collectResumeAttachments({ downloadableOnly: false, includePending: true })
      .filter((item) => item.pendingAccept);
    let clicked = 0;
    for (const card of cards) {
      if (shouldAbortRunner(options)) {
        break;
      }
      const button = findAttachmentAcceptButton(card.root);
      if (!button) {
        appendRunnerLog(`pending attachment accept button missing: ${card.fileName || card.id}`);
        continue;
      }
      appendRunnerLog(`accept pending attachment: ${card.fileName || card.id} via ${describeElement(button)}`);
      await trustedClickElement(button);
      clicked += 1;
      const shouldContinue = await waitForRunner(700, {
        respectStop: options.respectStop !== false,
        runToken: options.runToken,
      });
      if (!shouldContinue) {
        break;
      }
    }
    return { clicked };
  }

  async function waitForAttachmentMaterialized(timeoutMs, options = {}) {
    const startedAt = Date.now();
    while (Date.now() - startedAt <= timeoutMs) {
      if (shouldAbortRunner(options)) {
        return false;
      }
      const attachments = collectResumeAttachments({ downloadableOnly: false, includePending: false });
      if (attachments.length > 0) {
        appendRunnerLog(`attachment materialized: ${attachments.length}`);
        return true;
      }
      const shouldContinue = await waitForRunner(300, {
        respectStop: options.respectStop !== false,
        runToken: options.runToken,
      });
      if (!shouldContinue) {
        return false;
      }
    }
    appendRunnerLog("attachment materialize timeout after accept");
    return false;
  }

  async function downloadAttachmentsInConversation(sessionKey, settings, options = {}) {
    const acceptResult = await acceptPendingAttachmentRequests({
      respectStop: !options.allowAlreadyDownloaded,
      runToken: options.runToken,
    });
    if (acceptResult.clicked > 0) {
      appendRunnerLog(`accepted pending attachment requests: ${acceptResult.clicked}`);
      await waitForAttachmentMaterialized(5200, {
        respectStop: !options.allowAlreadyDownloaded,
        runToken: options.runToken,
      });
    }
    const attachments = collectResumeAttachments({ downloadableOnly: Boolean(options.downloadableOnly) });
    if (attachments.length === 0) {
      return {
        ok: false,
        error: acceptResult.clicked > 0
          ? "已同意接收附件简历，但当前会话中还没有出现可下载的 PDF 附件卡片。"
          : "当前会话中没有检测到附件简历。",
      };
    }

    const normalizedSettings = normalizeSettings(settings);
    const targets = options.downloadAll ? attachments : [attachments[attachments.length - 1]];
    const downloadedFiles = [];
    appendRunnerLog(`download targets: ${targets.map((item) => item.fileName || item.text || item.id).join(" | ")}`);

    for (const attachment of targets) {
      if (shouldAbortRunner({ respectStop: !options.allowAlreadyDownloaded, runToken: options.runToken }) && !options.allowAlreadyDownloaded) {
        break;
      }
      const attachmentKey = buildAttachmentRunKey(sessionKey, attachment);
      if (!options.allowAlreadyDownloaded && runnerState.downloadedAttachmentKeys.has(attachmentKey)) {
        appendRunnerLog(`attachment skipped, already handled: ${attachment.fileName || attachment.id}`);
        continue;
      }

      const result = await resolveAndDownloadAttachment(attachment, normalizedSettings, { respectStop: !options.allowAlreadyDownloaded, runToken: options.runToken });
      if (!result.ok) {
        appendRunnerLog(`attachment download failed: ${attachment.fileName || attachment.id} | ${result.error || "unknown error"}`);
        if (downloadedFiles.length > 0) {
          return { ok: true, downloadedCount: downloadedFiles.length, files: downloadedFiles, partialError: result.error || "" };
        }
        return result;
      }

      runnerState.downloadedAttachmentKeys.add(attachmentKey);
      appendRunnerLog(`attachment download ok: ${attachment.fileName || attachment.id}`);
      downloadedFiles.push(result);
    }

    return {
      ok: true,
      downloadedCount: downloadedFiles.length,
      files: downloadedFiles,
      downloadId: downloadedFiles[downloadedFiles.length - 1]?.downloadId,
      fileName: downloadedFiles[downloadedFiles.length - 1]?.fileName || "",
    };
  }

  async function resolveAndDownloadAttachment(attachment, settings, options = {}) {
    if (shouldAbortRunner(options)) {
      return { ok: false, error: "批量任务已收到停止请求。" };
    }
    let downloadUrl = "";
    let resolveSummary = "";
    let trustedPdf = false;
    let previewOpened = false;
    appendRunnerLog(`resolve attachment: ${attachment.fileName || attachment.id}`);

    const previewOpen = await openAttachmentPreview(attachment, options);
    previewOpened = previewOpen.opened;
    if (previewOpen.attempted && !previewOpened) {
      resolveSummary = "已找到预览入口，但未能打开附件预览。";
      appendRunnerLog(`open preview failed: ${attachment.fileName || attachment.id}`);
    }
    if (previewOpened) {
      if (shouldAbortRunner(options)) {
        await closeAttachmentPreview({ force: true });
        return { ok: false, error: "Batch task stopped." };
      }
      const uiDownload = await tryResolveDownloadFromPreviewUi(attachment, options);
      appendRunnerLog(`preview download probe: ${attachment.fileName || attachment.id} | ${uiDownload.summary || (uiDownload.ok ? "ok" : "failed")}`);
      if (uiDownload.ok && uiDownload.downloadTriggered) {
        runnerState.stats.downloaded += 1;
        const fileName = uiDownload.observedDownload?.filename || buildDownloadFileName(attachment.fileName || "", settings.downloadFolder || "BossResumes");
        await closeAttachmentPreview({ force: true });
        return {
          ok: true,
          downloadTriggered: true,
          downloadId: uiDownload.observedDownload?.downloadId,
          fileName,
          url: uiDownload.observedDownload?.url || "",
        };
      }
      if (!uiDownload.ok) {
        resolveSummary = uiDownload.summary || "";
      }
      if (shouldAbortRunner(options)) {
        await closeAttachmentPreview({ force: true });
        return { ok: false, error: "Batch task stopped." };
      }
      await closeAttachmentPreview({ force: true });
      appendRunnerLog(`preview toolbar download failed: ${attachment.fileName || attachment.id} | ${resolveSummary || "no browser download observed"}`);
      return { ok: false, error: resolveSummary || "已打开附件预览，但未能通过顶部下载按钮触发 PDF 下载。" };
    }

    if (!downloadUrl) {
      if (previewOpened) {
        await closeAttachmentPreview({ force: true });
      }
      appendRunnerLog(`resolve attachment failed: ${attachment.fileName || attachment.id} | ${resolveSummary || "no downloadable pdf url"}`);
      return { ok: false, error: `已找到附件简历卡片，但没有拿到可下载的 PDF 链接。${resolveSummary ? ` ${resolveSummary}` : ""}` };
    }

    const fileName = buildDownloadFileName(attachment.fileName || "", settings.downloadFolder || "BossResumes");
    if (shouldAbortRunner(options)) {
      if (previewOpened) {
        await closeAttachmentPreview({ force: true });
      }
      return { ok: false, error: "Batch task stopped." };
    }
    if (isPageLocalPdfUrl(downloadUrl)) {
      appendRunnerLog(`page-local pdf download: ${downloadUrl.slice(0, 96)}`);
      const pageDownload = await triggerPagePdfDownload(downloadUrl, fileName, options);
      if (pageDownload.ok) {
        runnerState.stats.downloaded += 1;
        appendRunnerLog(`page-local pdf download ok: ${pageDownload.filename || fileName}`);
        await closeAttachmentPreview({ force: true });
        return {
          ok: true,
          downloadTriggered: true,
          downloadId: pageDownload.downloadId,
          fileName: pageDownload.filename || fileName,
          url: downloadUrl,
        };
      }
      if (previewOpened) {
        await closeAttachmentPreview({ force: true });
      }
      return { ok: false, error: pageDownload.error || "页面内 PDF 下载未成功触发。", url: downloadUrl };
    }
    appendRunnerLog(`background download url: ${downloadUrl}`);
    const downloadResult = await sendBackgroundMessage({
      type: "download_resume",
      payload: {
        url: downloadUrl,
        fileName,
        trustedPdf,
      },
    });

    if (!downloadResult?.ok) {
      if (previewOpened) {
        await closeAttachmentPreview({ force: true });
      }
      appendRunnerLog(`background download failed: ${downloadResult?.error || "unknown error"}`);
      return { ok: false, error: downloadResult?.error || "创建下载任务失败。", url: downloadUrl };
    }

    runnerState.stats.downloaded += 1;
    appendRunnerLog(`background download ok: id=${downloadResult.downloadId}`);
    await closeAttachmentPreview({ force: true });
    return { ok: true, downloadId: downloadResult.downloadId, url: downloadUrl, fileName };
  }

  async function tryResolveDownloadFromPreviewUi(attachment, options = {}) {
    if (shouldAbortRunner(options)) {
      return { ok: false, summary: "批量任务已收到停止请求。" };
    }
    const downloadButton = findVisibleDownloadButton();
    if (downloadButton) {
      const startedAt = Date.now();
      await trustedClickElement(downloadButton);
      appendRunnerLog(`top preview toolbar download click: ${describeElement(downloadButton)}`);
      appendRunnerLog(`preview click download button: ${describeElement(downloadButton)}`);
      const topToolbarDownload = await waitForPreviewDownloadAfterClick(attachment, startedAt, options);
      if (topToolbarDownload.ok) {
        return topToolbarDownload;
      }
      appendRunnerLog(`top preview toolbar download wait failed: ${topToolbarDownload.summary || "no browser download observed"}`);
    } else {
      appendRunnerLog(`top preview toolbar download missing: ${attachment.fileName || attachment.id}`);
    }
    const frameStartedAt = Date.now();
    const frameClick = await sendBackgroundMessage({
      type: "click_preview_download_button",
      payload: {
        abortOnBatchStop: Boolean(options.respectStop),
      },
    });
    if (frameClick?.ok && frameClick.clicked) {
      appendRunnerLog(`frame semantic button click: ${frameClick.frameUrl || "-"}${frameClick.debug ? ` | ${frameClick.debug}` : ""}`);
      appendRunnerLog(`preview frame download click: ${frameClick.frameUrl || "-"}${frameClick.debug ? ` | ${frameClick.debug}` : ""}`);
      const frameDownload = await waitForPreviewDownloadAfterClick(attachment, frameStartedAt, options);
      if (frameDownload.ok) {
        return frameDownload;
      }
      appendRunnerLog(`frame semantic button download wait failed: ${frameDownload.summary || "no browser download observed"}`);
    } else if (frameClick?.debug || frameClick?.error) {
      appendRunnerLog(`frame semantic button unavailable: ${frameClick.debug || frameClick.error}`);
    }
    {
      appendRunnerLog(`preview download button missing: ${attachment.fileName || attachment.id}`);
      return { ok: false, summary: "预览界面未识别到下载按钮。" };
    }
  }

  async function waitForPreviewDownloadAfterClick(attachment, startedAt, options = {}) {
    const waited = await waitForRunner(1800, { respectStop: !options.respectStop ? false : true, runToken: options.runToken });
    if (!waited && options.respectStop) {
      return { ok: false, summary: "批量任务已收到停止请求。" };
    }
    const observed = await sendBackgroundMessage({
      type: "wait_for_recent_download",
      payload: {
        sinceMs: startedAt,
        fileNameHint: "",
        timeoutMs: 9000,
        abortOnBatchStop: Boolean(options.respectStop),
      },
    });
    if (observed?.ok && observed.found) {
      if (isHtmlDownloadResult(observed)) {
        appendRunnerLog(`html download rejected: ${observed.filename || observed.url || "-"}`);
        return { ok: false, summary: "点击预览页下载按钮后检测到 HTML/预览页下载，已拒绝保存为简历文件。" };
      }
      appendRunnerLog(`preview download observed: ${observed.filename || observed.url || "-"}`);
      return {
        ok: true,
        downloadTriggered: true,
        observedDownload: observed,
        summary: "已点击预览界面的下载按钮，并检测到浏览器下载任务。",
      };
    }
    return { ok: false, summary: "已点击预览界面的下载按钮，但未检测到浏览器下载任务。" };
  }

  function isHtmlDownloadResult(download) {
    const filename = String(download?.filename || "").toLowerCase();
    const mime = String(download?.mime || "").toLowerCase();
    const url = String(download?.url || download?.finalUrl || "").toLowerCase();
    if (/\.pdf(?:\.crdownload)?(?:$|[?#])/i.test(filename) || mime.includes("application/pdf")) {
      return false;
    }
    if (/\.(html?|xhtml)(?:\.crdownload)?(?:$|[?#])/i.test(filename) || mime.includes("text/html")) {
      return true;
    }
    return /\/wflow\/zpgeek\/download\/preview4boss\/|bzl-office|office\.weizhipin/i.test(url);
  }

  async function triggerPagePdfDownload(url, fileName, options = {}) {
    if (shouldAbortRunner(options)) {
      return { ok: false, error: "批量任务已收到停止请求。" };
    }
    const startedAt = Date.now();
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName.split("/").pop() || "boss_resume.pdf";
      anchor.target = "_blank";
      anchor.rel = "noopener";
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      window.setTimeout(() => anchor.remove(), 200);
    } catch (error) {
      return { ok: false, error: error?.message || String(error) };
    }

    const observed = await sendBackgroundMessage({
      type: "wait_for_recent_download",
      payload: {
        sinceMs: startedAt,
        fileNameHint: fileName.split("/").pop() || "",
        timeoutMs: 5200,
        abortOnBatchStop: Boolean(options.respectStop),
      },
    });
    if (observed?.ok && observed.found) {
      return { ok: true, downloadId: observed.downloadId, filename: observed.filename || "" };
    }
    return { ok: false, error: "已尝试在页面内触发 PDF 下载，但未检测到浏览器下载任务。" };
  }

  async function performRequestResume(settings, options = {}) {
    const normalized = normalizeSettings(settings);
    const result = { ok: true, sentMessage: false, clickedRequestButton: false, clickedConfirm: false, messageOnly: false, logs: [] };
    const messageText = String(normalized.resumeMessage || "").trim();

    if (messageText) {
      if (shouldAbortRunner(options)) {
        return { ok: false, error: "批量任务已收到停止请求。", logs: result.logs };
      }
      const input = findChatInput();
      if (!input) {
        return { ok: false, error: "没有找到聊天输入框。" };
      }
      clearChatInput(input);
      setChatInputValue(input, messageText);
      if (!(await waitForRunner(120, { respectStop: !options.respectStop ? false : true, runToken: options.runToken })) && options.respectStop) {
        return { ok: false, error: "批量任务已收到停止请求。", logs: result.logs };
      }

      const sendButton = findSendButton(input);
      if (sendButton && isElementEnabled(sendButton)) {
        await trustedClickElement(sendButton);
        result.sentMessage = true;
        result.logs.push("已发送自定义话术。");
      } else {
        triggerEnter(input);
        result.sentMessage = true;
        result.logs.push("已通过 Enter 发送自定义话术。");
      }

      if (!(await waitForRunner(450, { respectStop: !options.respectStop ? false : true, runToken: options.runToken })) && options.respectStop) {
        return { ok: false, error: "批量任务已收到停止请求。", logs: result.logs };
      }
    }

    const requestFlow = await triggerRequestResumeFlow({ ...options, allowMessageOnly: result.sentMessage });
    result.clickedRequestButton = requestFlow.clickedRequestButton;
    result.clickedConfirm = requestFlow.clickedConfirm;
    result.messageOnly = Boolean(requestFlow.messageOnly);
    result.logs.push(...requestFlow.logs);

    if (!requestFlow.ok) {
      return {
        ok: false,
        sentMessage: result.sentMessage,
        clickedRequestButton: result.clickedRequestButton,
        clickedConfirm: result.clickedConfirm,
        messageOnly: result.messageOnly,
        logs: result.logs,
        error: requestFlow.error || "未能完成求简历动作。",
      };
    }

    return result;
  }

  async function triggerRequestResumeFlow(options = {}) {
    const logs = [];
    let clickedRequestButton = false;
    let clickedConfirm = false;

    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (shouldAbortRunner(options)) {
        return { ok: false, clickedRequestButton, clickedConfirm, logs, error: "批量任务已收到停止请求。" };
      }
      const requestButton = await waitForRequestResumeButton(options.allowMessageOnly ? 3600 : 1200, options);
      if (!requestButton) {
        if (options.allowMessageOnly) {
          logs.push("没有找到可用的“求简历/附件简历”功能按钮，已发送话术等待候选人发送附件简历。");
          return { ok: true, clickedRequestButton, clickedConfirm, messageOnly: true, logs };
        }
        return { ok: false, clickedRequestButton, clickedConfirm, logs, error: "没有找到“求简历”按钮。" };
      }
      if (!isRequestResumeButtonUsable(requestButton)) {
        const reason = getRequestResumeUnavailableReason(requestButton) || "按钮当前不可用。";
        if (options.allowMessageOnly) {
          logs.push(`求简历按钮当前不可用：${reason} 已发送话术等待候选人发送附件简历。`);
          return { ok: true, clickedRequestButton, clickedConfirm, messageOnly: true, logs };
        }
        return { ok: false, clickedRequestButton, clickedConfirm, logs, error: `求简历按钮当前不可用：${reason}` };
      }

      await trustedClickElement(requestButton);
      clickedRequestButton = true;
      logs.push(`已点击“求简历”按钮（第 ${attempt + 1} 次）。`);

      const confirmButton = await waitForConfirmButton(3600, options);
      if (confirmButton) {
        appendRunnerLog(`request confirm button found: ${describeElement(confirmButton)}`);
        await trustedClickElement(confirmButton);
        clickedConfirm = true;
        logs.push("已自动点击确认按钮。");
        if (!(await waitForRunner(350, { respectStop: !options.respectStop ? false : true, runToken: options.runToken })) && options.respectStop) {
          return { ok: false, clickedRequestButton, clickedConfirm, logs, error: "批量任务已收到停止请求。" };
        }
        const retryConfirmButton = findConfirmButton();
        if (retryConfirmButton && !isSameElement(retryConfirmButton, confirmButton)) {
          appendRunnerLog(`request confirm retry: ${describeElement(retryConfirmButton)}`);
          await trustedClickElement(retryConfirmButton);
          await waitForRunner(250, { respectStop: false });
        } else if (retryConfirmButton) {
          appendRunnerLog(`request confirm still visible, retry same button: ${describeElement(retryConfirmButton)}`);
          await trustedClickElement(retryConfirmButton);
          await waitForRunner(250, { respectStop: false });
        }
        return { ok: true, clickedRequestButton, clickedConfirm, messageOnly: false, logs };
      }

      if (isRequestResumeAlreadySent(requestButton)) {
        logs.push("检测到求简历状态已变更。");
        return { ok: true, clickedRequestButton, clickedConfirm, messageOnly: false, logs };
      }

      if (!(await waitForRunner(450, { respectStop: !options.respectStop ? false : true, runToken: options.runToken })) && options.respectStop) {
        return { ok: false, clickedRequestButton, clickedConfirm, logs, error: "批量任务已收到停止请求。" };
      }
    }

    return {
      ok: false,
      clickedRequestButton,
      clickedConfirm,
      messageOnly: false,
      logs,
      error: "已发送话术，但未成功触发“求简历”按钮的确认或状态变化。",
    };
  }

  async function waitForConfirmButton(timeoutMs, options = {}) {
    const startedAt = Date.now();
    while (Date.now() - startedAt <= timeoutMs) {
      if (shouldAbortRunner(options)) {
        return null;
      }
      const button = findConfirmButton();
      if (button) {
        return button;
      }
      const shouldContinue = await waitForRunner(120, { respectStop: !options.respectStop ? false : true, runToken: options.runToken });
      if (!shouldContinue) {
        return null;
      }
    }
    return null;
  }

  async function waitForRequestResumeButton(timeoutMs, options = {}) {
    const startedAt = Date.now();
    while (Date.now() - startedAt <= timeoutMs) {
      if (shouldAbortRunner(options)) {
        return null;
      }
      const button = findRequestResumeButton();
      if (button) {
        appendRunnerLog(`request resume button found: ${describeElement(button)}`);
        return button;
      }
      const shouldContinue = await waitForRunner(160, {
        respectStop: !options.respectStop ? false : true,
        runToken: options.runToken,
      });
      if (!shouldContinue) {
        return null;
      }
    }
    appendRunnerLog(`request resume button wait timeout: ${timeoutMs}ms`);
    return null;
  }

  function findConfirmButton() {
    const selectors = ["button", "a", "[role='button']", ".btn", ".button", "div", "span"];
    for (const root of queryAllWithFallback(document, SELECTORS.modalRoot)) {
      if (!isElementVisible(root)) {
        continue;
      }
      const button = findButtonByText(root, TEXTS.confirm, { exact: true, preferRightSide: true, selectors });
      if (button) {
        return button;
      }
    }
    const requestConfirm = findRequestResumeConfirmButton();
    if (requestConfirm) {
      return requestConfirm;
    }
    return findButtonByText(document, TEXTS.confirm, { exact: true, preferRightSide: true, selectors });
  }

  function findRequestResumeConfirmButton() {
    const selectors = "button, a, [role='button'], .btn, .button, div, span";
    const candidates = Array.from(document.querySelectorAll(selectors))
      .filter((node) => node instanceof HTMLElement && isElementVisible(node) && isElementEnabled(node))
      .filter((node) => TEXTS.confirm.some((label) => normalizeText(node.innerText || node.textContent || "") === label))
      .filter((node) => isLikelyRequestConfirmButton(node))
      .map((node) => ({
        node,
        rect: node.getBoundingClientRect(),
        score: scoreRequestConfirmButton(node),
      }))
      .sort((left, right) => {
        if (Math.abs(right.score - left.score) > 0.5) {
          return right.score - left.score;
        }
        if (Math.abs(right.rect.left - left.rect.left) > 4) {
          return right.rect.left - left.rect.left;
        }
        return left.rect.top - right.rect.top;
      });
    return candidates[0]?.node || null;
  }

  function isLikelyRequestConfirmButton(node) {
    const rect = node.getBoundingClientRect();
    if (rect.width < 36 || rect.width > 180 || rect.height < 24 || rect.height > 80) {
      return false;
    }
    const context = findDialogLikeAncestorText(node);
    if (/取消|拒绝|关闭/.test(normalizeText(node.innerText || node.textContent || ""))) {
      return false;
    }
    return /请求简历|求简历|回复内容|方便发一份|牛人|确认向/.test(context);
  }

  function scoreRequestConfirmButton(node) {
    const rect = node.getBoundingClientRect();
    const context = findDialogLikeAncestorText(node);
    let score = 0;
    if (/确认向|请求简历|求简历/.test(context)) {
      score += 60;
    }
    if (/回复内容|方便发一份/.test(context)) {
      score += 30;
    }
    if (node.matches("button, a, [role='button']")) {
      score += 12;
    }
    score += Math.min(20, rect.left / Math.max(window.innerWidth, 1) * 20);
    return score;
  }

  function findDialogLikeAncestorText(node) {
    let current = node instanceof HTMLElement ? node : null;
    for (let depth = 0; depth < 7 && current; depth += 1) {
      const rect = current.getBoundingClientRect();
      const text = normalizeText(current.innerText || current.textContent || "");
      if (text && rect.width >= 120 && rect.height >= 40 && text.length <= 500) {
        if (/请求简历|求简历|回复内容|方便发一份|确认向|牛人/.test(text)) {
          return text;
        }
      }
      current = current.parentElement;
    }
    return normalizeText(document.body?.innerText || "").slice(0, 500);
  }

  function findRequestResumeButton() {
    const candidates = Array.from(document.querySelectorAll("button, a, [role='button'], div, span"))
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .map((node) => ({
        node,
        rect: node.getBoundingClientRect(),
        text: normalizeText(node.innerText || node.textContent || ""),
        hint: buildHintText(node),
      }))
      .filter((candidate) => isLikelyRequestResumeAction(candidate))
      .sort((left, right) => {
        const usableDelta = Number(isRequestResumeButtonUsable(right.node)) - Number(isRequestResumeButtonUsable(left.node));
        if (usableDelta !== 0) {
          return usableDelta;
        }
        const scoreDelta = scoreRequestResumeAction(right) - scoreRequestResumeAction(left);
        if (Math.abs(scoreDelta) > 0.5) {
          return scoreDelta;
        }
        if (Math.abs(left.rect.left - right.rect.left) > 4) {
          return left.rect.left - right.rect.left;
        }
        return left.text.length - right.text.length;
      });
    return candidates[0]?.node || null;
  }

  function isLikelyRequestResumeAction(candidate) {
    const node = candidate?.node;
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    const haystack = `${candidate.text || ""} ${candidate.hint || ""}`;
    const hasBottomText = TEXTS.requestResume.some((label) => haystack.includes(label)) || /request.?resume|resume.?request|btn-doc/i.test(haystack);
    const messageContainer = findMessageContainer();
    if (messageContainer?.contains(node)) {
      return false;
    }
    if (hasBottomText && isLikelyBottomActionButton(node)) {
      return true;
    }
    const hasTopAttachmentText = TEXTS.topRequestResume.some((label) => haystack.includes(label));
    return hasTopAttachmentText && isLikelyHeaderResumeActionButton(node);
  }

  function scoreRequestResumeAction(candidate) {
    const haystack = `${candidate.text || ""} ${candidate.hint || ""}`;
    let score = 0;
    if (TEXTS.requestResume.some((label) => haystack.includes(label))) {
      score += 80;
    }
    if (TEXTS.topRequestResume.some((label) => haystack.includes(label))) {
      score += 70;
    }
    if (isLikelyBottomActionButton(candidate.node)) {
      score += 16;
    }
    if (isLikelyHeaderResumeActionButton(candidate.node)) {
      score += 14;
    }
    if (candidate.node?.matches("button, a, [role='button']")) {
      score += 8;
    }
    return score;
  }

  function isLikelyHeaderResumeActionButton(node) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 56 || rect.width > 220 || rect.height < 28 || rect.height > 96) {
      return false;
    }
    if (rect.top > window.innerHeight * 0.34 || rect.left < window.innerWidth * 0.36) {
      return false;
    }
    return rect.right <= window.innerWidth * 0.96;
  }

  function isLikelyFloatingRequestAttachmentButton(node) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 82 || rect.width > 260 || rect.height < 24 || rect.height > 72) {
      return false;
    }
    if (rect.top < window.innerHeight * 0.5 || rect.bottom > window.innerHeight + 12) {
      return false;
    }
    return rect.left <= window.innerWidth * 0.32;
  }

  function isRequestResumeButtonUsable(node) {
    if (!(node instanceof HTMLElement) || !isElementEnabled(node)) {
      return false;
    }
    const style = window.getComputedStyle(node);
    if (style.pointerEvents === "none") {
      return false;
    }
    const haystack = `${normalizeText(node.innerText || node.textContent || "")} ${buildHintText(node)}`;
    return !/disabled|disable|不可用|双方回复后|置灰|禁用/.test(haystack);
  }

  function getRequestResumeUnavailableReason(node) {
    const haystack = `${normalizeText(node?.innerText || node?.textContent || "")} ${buildHintText(node)}`;
    if (/双方回复后/.test(haystack)) {
      return "双方回复后可用";
    }
    if (!isElementEnabled(node)) {
      return "按钮被禁用";
    }
    return "";
  }

  function isLikelyBottomActionButton(node) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 36 || rect.height < 20) {
      return false;
    }
    if (rect.top < window.innerHeight * 0.65) {
      return false;
    }
    return rect.left >= window.innerWidth * 0.2 && rect.right <= window.innerWidth * 0.92;
  }

  function isRequestResumeAlreadySent(requestButton) {
    const buttonText = normalizeText(requestButton?.innerText || requestButton?.textContent || "");
    if (TEXTS.requestSent.some((label) => buttonText.includes(label))) {
      return true;
    }
    const pageText = normalizeText(document.body?.innerText || "");
    return TEXTS.requestSent.some((label) => pageText.includes(label));
  }

  function findChatInput() {
    for (const selector of SELECTORS.composerInput) {
      for (const node of Array.from(document.querySelectorAll(selector))) {
        if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
          continue;
        }
        const rect = node.getBoundingClientRect();
        if (rect.width >= 120 && rect.height >= 18) {
          return node;
        }
      }
    }
    return null;
  }

  function findSendButton(input) {
    const composer = findComposerContainer(input);
    if (composer) {
      const button = findButtonByText(composer, TEXTS.send, {
        exact: false,
        selectors: SELECTORS.sendButton,
        preferRightSide: true,
        preferLower: true,
      });
      if (button) {
        return button;
      }
    }
    return findButtonByText(document, TEXTS.send, { exact: false, selectors: SELECTORS.sendButton, preferRightSide: true, preferLower: true });
  }

  function findComposerContainer(input) {
    let current = input;
    for (let depth = 0; depth < 5 && current; depth += 1) {
      if (!(current instanceof HTMLElement)) {
        break;
      }
      const rect = current.getBoundingClientRect();
      if (rect.width > 320 && rect.height > 40) {
        return current;
      }
      current = current.parentElement;
    }
    return input.parentElement;
  }

  function clearChatInput(input) {
    if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) {
      input.focus();
      setNativeFormControlValue(input, "");
      dispatchFormInputEvents(input);
      return;
    }
    input.focus();
    if (typeof document.execCommand === "function") {
      tryInsertTextIntoEditable(input, "");
    }
    input.textContent = "";
    input.innerHTML = "";
    dispatchEditableInputEvents(input, "deleteContentBackward", "");
  }

  function setChatInputValue(input, value) {
    if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) {
      input.focus();
      setNativeFormControlValue(input, value);
      dispatchFormInputEvents(input);
      return;
    }
    input.focus();
    const inserted = tryInsertTextIntoEditable(input, value);
    if (!inserted) {
      input.textContent = value;
      input.innerHTML = escapeHtml(value).replace(/\n/g, "<br>");
    }
    placeCaretAtEnd(input);
    dispatchEditableInputEvents(input, "insertText", value);
  }

  function triggerEnter(input) {
    const init = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true };
    input.dispatchEvent(new KeyboardEvent("keydown", init));
    input.dispatchEvent(new KeyboardEvent("keypress", init));
    input.dispatchEvent(new KeyboardEvent("keyup", init));
  }

  function hasAttachmentResumeInConversation() {
    return collectResumeAttachments({ downloadableOnly: false, includePending: true }).length > 0;
  }

  function hasSentResumeRequestInConversation(settings = {}) {
    const messageContainer = findMessageContainer();
    if (!messageContainer) {
      return false;
    }
    const fullText = normalizeText(messageContainer.innerText || messageContainer.textContent || "");
    if (!fullText) {
      return false;
    }
    return buildResumeRequestHistoryPatterns(settings).some((pattern) => pattern && fullText.includes(pattern));
  }

  function buildResumeRequestHistoryPatterns(settings = {}) {
    const configuredMessage = normalizeText(settings?.resumeMessage || "");
    return Array.from(new Set([
      ...TEXTS.requestSent,
      configuredMessage,
      "方便发一份你的简历过来吗",
      "方便发一份您的简历过来吗",
      "方便发一份你的简历过来吗？",
      "方便发一份您的简历过来吗？",
      "方便发一份你的附件简历过来吗",
      "方便发一份您的附件简历过来吗",
      "可以把简历发给我吗",
      "可以把您的简历发给我吗",
      "可以发一份简历过来吗",
      "可以发一份附件简历过来吗",
    ].map(normalizeText).filter((pattern) => pattern.length >= 4)));
  }

  function collectResumeAttachments(options = {}) {
    const messageContainer = findMessageContainer();
    if (!messageContainer) {
      return [];
    }
    const candidates = Array.from(messageContainer.querySelectorAll("a, button, div, article, section, li, span")).filter((node) => isAttachmentCardNode(node, messageContainer));
    const attachments = uniqueTopLevelElements(candidates)
      .map((root, index) => {
        const text = normalizeText(root.innerText || root.textContent || "");
        const urls = collectCandidateUrls(root);
        const previewTarget = findPreviewTarget(root);
        const pendingAccept = isPendingAttachmentRequestText(text);
        return {
          id: `attachment-${index + 1}`,
          fileName: inferPdfFileName(root),
          urls,
          text,
          previewTarget,
          pendingAccept,
          downloadable: !pendingAccept && hasDownloadableResumeSignal(text, urls, previewTarget),
          root,
        };
      })
      .sort((left, right) => {
        const leftRect = rectOrNull(left.root);
        const rightRect = rectOrNull(right.root);
        return (leftRect?.top || 0) - (rightRect?.top || 0);
      });
    const filtered = options.includePending ? attachments : attachments.filter((item) => !item.pendingAccept);
    return options.downloadableOnly ? filtered.filter((item) => item.downloadable) : filtered;
  }

  function findMessageContainer() {
    for (const selector of SELECTORS.messageContainer) {
      for (const node of Array.from(document.querySelectorAll(selector))) {
        if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
          continue;
        }
        const rect = node.getBoundingClientRect();
        if (rect.width >= 280 && rect.height >= 200 && rect.left <= window.innerWidth * 0.65) {
          return node;
        }
      }
    }
    return null;
  }

  function isAttachmentCardNode(node, messageContainer) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node) || !messageContainer.contains(node)) {
      return false;
    }
    const text = normalizeText(node.innerText || node.textContent || "");
    if (!text) {
      return false;
    }
    const looksAttachment = TEXTS.attachmentResume.some((label) => text.includes(label)) || /[^\\/:*?"<>|\r\n]+\.pdf/i.test(text);
    if (!looksAttachment) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 80 && rect.height > 20;
  }

  function isPendingAttachmentRequestText(text) {
    const normalizedText = normalizeText(text || "");
    if (!normalizedText.includes("附件简历")) {
      return false;
    }
    return /是否同意|想发送|同意接收|接收附件|发送附件简历/.test(normalizedText);
  }

  function findAttachmentAcceptButton(root) {
    if (!(root instanceof HTMLElement)) {
      return null;
    }
    const byText = findButtonByText(root, TEXTS.acceptAttachment, {
      exact: false,
      selectors: ["button", "a", "[role='button']", "div", "span"],
      preferRightSide: true,
    });
    if (byText && isCompactCardActionButton(byText, root) && isElementEnabled(byText) && !isRejectLikeButton(byText)) {
      return byText;
    }
    const candidates = Array.from(root.querySelectorAll("button, a, [role='button'], div, span"))
      .filter((node) => node instanceof HTMLElement && isElementVisible(node) && isElementEnabled(node))
      .filter((node) => isCompactCardActionButton(node, root))
      .filter((node) => {
        const text = normalizeText(node.innerText || node.textContent || "");
        const hint = buildHintText(node);
        return /agree|accept|confirm|同意|接受|接收|确认/.test(`${text} ${hint}`) && !isRejectLikeButton(node);
      })
      .map((node) => ({ node, rect: node.getBoundingClientRect(), text: normalizeText(node.innerText || node.textContent || "") }))
      .sort((left, right) => {
        if (Math.abs(right.rect.left - left.rect.left) > 4) {
          return right.rect.left - left.rect.left;
        }
        return left.text.length - right.text.length;
      });
    return candidates[0]?.node || null;
  }

  function isCompactCardActionButton(node, root) {
    if (!(node instanceof HTMLElement) || node === root) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    const rootRect = root instanceof HTMLElement ? root.getBoundingClientRect() : null;
    const text = normalizeText(node.innerText || node.textContent || "");
    if (text.length > 18) {
      return false;
    }
    if (rootRect && rect.width * rect.height > rootRect.width * rootRect.height * 0.45) {
      return false;
    }
    return node.matches("button, a, [role='button']") || (rect.width <= 180 && rect.height <= 80);
  }

  function isRejectLikeButton(node) {
    const text = normalizeText(node?.innerText || node?.textContent || "");
    const hint = buildHintText(node);
    return /拒绝|不同意|取消|关闭|reject|decline|cancel|close/.test(`${text} ${hint}`.toLowerCase());
  }

  function hasDownloadableResumeSignal(text, urls, previewTarget) {
    const normalizedText = normalizeText(text || "");
    if (/[^\\/:*?"<>|\r\n]+\.pdf/i.test(normalizedText)) {
      return true;
    }
    if (TEXTS.preview.some((label) => normalizedText.includes(label))) {
      return true;
    }
    if (previewTarget) {
      return true;
    }
    const urlList = Array.isArray(urls) ? urls : [];
    return urlList.some((value) => isPageLocalPdfUrl(value) || isPdfLikeUrl(value, normalizedText) || Boolean(extractNestedPdfUrl(value, normalizedText)));
  }

  function inferPdfFileName(root) {
    const text = normalizeText(root.innerText || root.textContent || "");
    const match = text.match(/[^\\/:*?"<>|\r\n]+\.pdf/gi);
    if (match?.length) {
      return match[match.length - 1];
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
    const attributes = [];
    for (const attrName of node.getAttributeNames()) {
      if (/href|src|url|download|data-url|data-src/i.test(attrName)) {
        attributes.push(node.getAttribute(attrName) || "");
      }
    }
    if (node instanceof HTMLAnchorElement) {
      attributes.push(node.href || "");
    }
    if (node instanceof HTMLImageElement || node instanceof HTMLIFrameElement) {
      attributes.push(node.src || "");
    }
    if (node instanceof HTMLObjectElement) {
      attributes.push(node.data || "");
    }
    for (const value of attributes) {
      const absolute = absolutizeUrl(value);
      if (!absolute) {
        continue;
      }
      urls.add(absolute);
      for (const key of ["src", "file", "url"]) {
        try {
          const nested = new URL(absolute).searchParams.get(key);
          if (nested) {
            urls.add(nested);
          }
        } catch (_error) {
          // Ignore nested parsing failures.
        }
      }
    }
  }

  function chooseDownloadUrl(urls, fileName) {
    const candidates = Array.isArray(urls) ? urls.map((value) => String(value || "").trim()).filter(Boolean) : [];
    const direct = candidates.find((value) => isPdfLikeUrl(value, fileName));
    if (direct) {
      return direct;
    }
    for (const candidate of candidates) {
      const nested = extractNestedPdfUrl(candidate, fileName);
      if (nested) {
        return nested;
      }
    }
    return "";
  }

  function isPdfLikeUrl(url, fileName) {
    const lowerUrl = String(url || "").toLowerCase();
    const lowerName = String(fileName || "").toLowerCase();
    if (isImageUrl(lowerUrl)) {
      return false;
    }
    return /\.pdf(?:$|[?#])/i.test(lowerUrl) || (looksLikeDownloadEndpoint(lowerUrl) && lowerName.endsWith(".pdf"));
  }

  function extractNestedPdfUrl(url, fileName) {
    try {
      const parsed = new URL(String(url || ""), location.href);
      for (const key of ["src", "file", "url"]) {
        const nestedValue = parsed.searchParams.get(key);
        if (!nestedValue) {
          continue;
        }
        const absoluteNested = absolutizeUrl(nestedValue);
        if (absoluteNested && isPdfLikeUrl(absoluteNested, fileName)) {
          return absoluteNested;
        }
      }
    } catch (_error) {
      return "";
    }
    return "";
  }

  function looksLikeDownloadEndpoint(url) {
    return /\/file\/|download|attachment/i.test(String(url || ""));
  }

  function isImageUrl(url) {
    return /\.(png|jpg|jpeg|gif|webp|svg)(?:$|[?#])/i.test(String(url || ""));
  }

  function isPageLocalPdfUrl(url) {
    const text = String(url || "").toLowerCase();
    return text.startsWith("blob:") || text.startsWith("data:application/pdf");
  }

  async function openAttachmentPreview(attachment, options = {}) {
    const targets = findPreviewTargets(attachment.root).slice(0, 4);
    if (targets.length === 0) {
      appendRunnerLog(`preview target missing: ${attachment.fileName || attachment.id}`);
      return { attempted: false, opened: false };
    }
    for (const target of targets) {
      if (shouldAbortRunner(options)) {
        return { attempted: true, opened: false, aborted: true };
      }
      appendRunnerLog(`open preview attempt: ${attachment.fileName || attachment.id} via ${describeElement(target)}`);
      await trustedClickElement(target);
      const previewReady = await waitForPreviewOpened(2600, options);
      appendRunnerLog(`preview attempt ready: ${attachment.fileName || attachment.id} ${previewReady ? "yes" : "no"} via ${describeElement(target)}`);
      if (previewReady) {
        return { attempted: true, opened: true, target };
      }
      await waitForRunner(180, { respectStop: options.respectStop !== false, runToken: options.runToken });
    }
    return { attempted: true, opened: false };
  }

  function findPreviewTarget(root) {
    return findPreviewTargets(root)[0] || null;
  }

  function findPreviewTargets(root) {
    if (!(root instanceof HTMLElement)) {
      return [];
    }
    const rootRect = root.getBoundingClientRect();
    const clickableNodes = [root, ...root.querySelectorAll("a, button, [role='button'], div, span")];
    const candidates = clickableNodes
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .filter((node) => !isPendingAttachmentRequestText(node.innerText || node.textContent || ""))
      .map((node) => {
        const text = normalizeText(node.innerText || node.textContent || "");
        const hint = buildHintText(node);
        const rect = node.getBoundingClientRect();
        let score = 0;
        if (isExplicitPreviewActionText(text, hint)) {
          score += 120;
        } else if (TEXTS.preview.some((label) => text.includes(label))) {
          score += 70;
        }
        if (/\.pdf\b/i.test(text) || /pdf/i.test(hint)) {
          score += 18;
        }
        if (node.matches("button, a, [role='button']")) {
          score += 12;
        }
        if (node !== root) {
          score += 4;
        } else {
          score -= 36;
        }
        if (text.length > 80) {
          score -= 24;
        }
        if (rootRect.width > 0 && rootRect.height > 0 && rect.width * rect.height > rootRect.width * rootRect.height * 0.72) {
          score -= 28;
        }
        score -= Math.min((rect.width * rect.height) / 100000, 12);
        return { node, score };
      })
      .filter((item) => item.score > 0)
      .sort((left, right) => right.score - left.score);
    return uniqueElements(candidates.map((item) => item.node));
  }

  function isExplicitPreviewActionText(text, hint = "") {
    const haystack = `${normalizeText(text || "")} ${String(hint || "").toLowerCase()}`;
    return /点击预览附件简历|预览附件简历|查看附件简历|点击预览|preview/.test(haystack);
  }

  async function waitForPreviewOpened(timeoutMs, options = {}) {
    const startedAt = Date.now();
    while (Date.now() - startedAt <= timeoutMs) {
      if (shouldAbortRunner(options)) {
        return false;
      }
      if (findPreviewRoots().length > 0) {
        return true;
      }
      if (findVisibleDownloadButton({ allowBodyFallback: false }) || findVisibleCloseButton({ allowBodyFallback: false })) {
        return true;
      }
      const shouldContinue = await waitForRunner(150, { respectStop: options.respectStop !== false, runToken: options.runToken });
      if (!shouldContinue) {
        return false;
      }
    }
    return false;
  }

  function findPreviewRoots() {
    const messageContainer = findMessageContainer();
    const selectors = [
      ...SELECTORS.modalRoot,
      "[class*='preview']",
      "[class*='pdf']",
      "[class*='resume']",
      "[class*='attachment']",
      "[class*='file']",
      "[class*='viewer']",
    ];
    const roots = queryAllWithFallback(document, selectors)
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .filter((node) => !(messageContainer && messageContainer.contains(node)))
      .map((node) => ({ node, score: scorePreviewRoot(node), rect: node.getBoundingClientRect() }))
      .filter((item) => item.score > 0)
      .sort((left, right) => {
        if (Math.abs(right.score - left.score) > 0.5) {
          return right.score - left.score;
        }
        return right.rect.width * right.rect.height - left.rect.width * left.rect.height;
      })
      .map((item) => item.node);
    return uniqueTopLevelElements(roots).slice(0, 6);
  }

  function scorePreviewRoot(node) {
    if (!(node instanceof HTMLElement)) {
      return 0;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 220 || rect.height < 120) {
      return 0;
    }
    const text = normalizeText(node.innerText || node.textContent || "");
    const hint = buildHintText(node);
    let score = 0;
    if (/\.pdf\b/i.test(text) || /pdf/i.test(hint)) {
      score += 30;
    }
    if (/preview|viewer|resume|attachment|file|dialog|modal|popup/i.test(hint)) {
      score += 16;
    }
    if (node.querySelector("iframe, embed, object, canvas")) {
      score += 12;
    }
    if (findTopRightIconButton(node, "close", { strict: false })) {
      score += 8;
    }
    if (rect.left > window.innerWidth * 0.2 || rect.width > window.innerWidth * 0.35) {
      score += 4;
    }
    return score;
  }

  function scanVisibleSessions() {
    const resolved = resolveSessionViewport();
    const container = resolved.container;
    const rawItems = resolved.items;
    if (rawItems.length === 0) {
      return {
        ok: true,
        items: [],
        hasContainer: Boolean(container),
        containerScrollTop: 0,
        containerScrollHeight: 0,
        containerClientHeight: 0,
        eligibleUnreadCount: 0,
        rejectedRows: 0,
        scanMessage: container ? "已命中左侧区域，但未识别到真实会话。" : "未识别到左侧会话列表容器。",
        debugSummary: container ? `容器: ${describeElement(container)}` : "容器: 未命中",
      };
    }
    const items = [];
    let rejectedRows = 0;
    rawItems.forEach((node, index) => {
      const descriptor = extractSessionDescriptor(node, index);
      if (descriptor) {
        items.push(descriptor);
      } else {
        rejectedRows += 1;
      }
    });

    const eligibleUnreadCount = items.filter((item) => item.unread).length;
    const containerSummary = describeElement(container);
    const sampleSummary = items.slice(0, 5).map(formatSessionDebugLabel).join(" | ");
    return {
      ok: true,
      items,
      hasContainer: Boolean(container),
      containerScrollTop: Number(container?.scrollTop || 0),
      containerScrollHeight: Number(container?.scrollHeight || 0),
      containerClientHeight: Number(container?.clientHeight || 0),
      eligibleUnreadCount,
      rejectedRows,
      scanMessage:
        items.length === 0
          ? "已命中会话列表容器，但当前可见区域未识别到真实会话。"
          : `已发现 ${items.length} 个可见会话，可确认未读 ${eligibleUnreadCount} 个。`,
      debugSummary: [
        `来源: ${resolved.source}`,
        `容器: ${containerSummary}`,
        `候选行: ${rawItems.length}`,
        `拒绝行: ${rejectedRows}`,
        sampleSummary ? `样本: ${sampleSummary}` : "",
      ]
        .filter(Boolean)
        .join("\n"),
    };
  }

  function resolveSessionViewport() {
    const container = findSessionScrollContainer();
    if (container) {
      return {
        container,
        items: getVisibleSessionItems(container),
        source: "scroll-container",
      };
    }
    const fallbackItems = findSessionRowsFromDocument();
    if (fallbackItems.length === 0) {
      return { container: null, items: [], source: "none" };
    }
    return {
      container: deriveSessionScrollContainerFromRows(fallbackItems),
      items: fallbackItems,
      source: "left-pane-fallback",
    };
  }

  function findSessionScrollContainer() {
    const candidates = [];
    for (const selector of SELECTORS.sessionScrollContainer) {
      candidates.push(...Array.from(document.querySelectorAll(selector)));
    }
    candidates.push(...Array.from(document.querySelectorAll("div, section, aside, ul, ol")));

    const scored = uniqueElements(candidates)
      .map((node) => scoreSessionScrollContainer(node))
      .filter((item) => item && item.score > 0)
      .sort((left, right) => right.score - left.score);
    return scored[0]?.node || null;
  }

  function findSessionRowsFromDocument() {
    const nodes = Array.from(document.querySelectorAll("div, a, li, section, article")).slice(0, 1800);
    const rows = nodes.filter(isLikelySessionRowInDocument);
    return uniqueTopLevelElements(rows).sort(compareElementsByVisualOrder);
  }

  function getVisibleSessionItems(container) {
    const directMatches = queryAllWithFallback(container, SELECTORS.sessionItem).filter((node) => isLikelySessionItem(node, container));
    if (directMatches.length > 0) {
      return uniqueTopLevelElements(directMatches).sort(compareElementsByVisualOrder);
    }
    const fallbackMatches = Array.from(container.querySelectorAll("div, a, li, section, article")).filter((node) => isLikelySessionItem(node, container));
    return uniqueTopLevelElements(fallbackMatches).sort(compareElementsByVisualOrder);
  }

  function isLikelySessionItem(node, container) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
      return false;
    }
    if (!(container instanceof HTMLElement) || node === container) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    if (rect.width < Math.max(150, containerRect.width * 0.55) || rect.width > containerRect.width + 24 || rect.height < 48 || rect.height > 180) {
      return false;
    }
    if (rect.left < containerRect.left - 12 || rect.right > containerRect.right + 24) {
      return false;
    }
    if (rect.top > containerRect.bottom || rect.bottom < containerRect.top) {
      return false;
    }
    const text = normalizeText(node.innerText || node.textContent || "");
    if (text.length < 2 || containsPromoText(text)) {
      return false;
    }
    const lines = splitLines(text);
    if (lines.length > 6) {
      return false;
    }
    const hasAvatar = hasAvatarLikeDescendant(node, rect);
    const time = extractTimeText(node, lines);
    const unread = hasUnreadBadge(node, rect);
    return hasAvatar || Boolean(time) || unread;
  }

  function isLikelySessionRowInDocument(node) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    if (rect.left > window.innerWidth * 0.42 || rect.right > window.innerWidth * 0.55) {
      return false;
    }
    if (rect.width < 180 || rect.width > Math.max(window.innerWidth * 0.42, 620) || rect.height < 48 || rect.height > 180) {
      return false;
    }
    const text = normalizeText(node.innerText || node.textContent || "");
    if (!text || containsPromoText(text)) {
      return false;
    }
    const lines = splitLines(text);
    if (lines.length > 6) {
      return false;
    }
    const hasAvatar = hasAvatarLikeDescendant(node, rect);
    const time = extractTimeText(node, lines);
    const unread = hasUnreadBadge(node, rect);
    return hasAvatar && (Boolean(time) || unread || lines.length >= 2);
  }

  function extractSessionDescriptor(node, index) {
    const wrap = findFirst(node, SELECTORS.sessionItemWrap) || node;
    const rawText = normalizeText(wrap.innerText || wrap.textContent || "");
    const lines = splitLines(rawText);
    const name = firstText(wrap, SELECTORS.sessionName) || extractSessionName(lines);
    const preview = firstText(wrap, SELECTORS.sessionPreview) || extractSessionPreview(lines, name);
    const time = firstText(wrap, SELECTORS.sessionTime) || extractTimeText(wrap, lines);
    const status = firstText(wrap, SELECTORS.sessionStatus) || preview;
    const key = buildSessionKey(wrap, name, preview, time, index);
    if (!key) {
      return null;
    }
    return {
      key,
      name: name || preview || `会话 ${index + 1}`,
      preview,
      time,
      status,
      unread: isUnreadSessionNode(wrap, status, rectOrNull(wrap)),
    };
  }

  function buildSessionKey(node, name, preview, time, index) {
    const attrKey = node.getAttribute("currentuid") || node.getAttribute("data-id") || node.getAttribute("data-session-id") || node.getAttribute("data-user-id") || "";
    if (attrKey) {
      return attrKey;
    }
    const classUid = String(node.className || "").split(/\s+/).find((value) => value.startsWith("uid-"));
    if (classUid) {
      return classUid.slice(4);
    }
    const hrefNode = node.querySelector("a[href]");
    if (hrefNode instanceof HTMLAnchorElement && hrefNode.href) {
      return hrefNode.href;
    }
    const summaryKey = [name, preview, time].map(normalizeText).filter(Boolean).join("|");
    return summaryKey || `row-index-${index}`;
  }

  function isUnreadSessionNode(node, statusText, rect) {
    const status = normalizeText(statusText || "");
    if (status.includes("未读")) {
      return true;
    }
    if (status.startsWith("[") && !status.includes("已读")) {
      return true;
    }
    const rowRect = rect || rectOrNull(node);
    const badges = queryAllWithFallback(node, SELECTORS.unreadBadge);
    if (badges.some((badge) => isUnreadBadge(badge, rowRect))) {
      return true;
    }
    return hasUnreadBadge(node, rowRect);
  }

  function isUnreadBadge(node, rowRect) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    const targetRect = rowRect || rect;
    const text = normalizeText(node.innerText || node.textContent || "");
    const style = window.getComputedStyle(node);
    const smallBadge = rect.width <= 28 && rect.height <= 28;
    const inBadgeZone = rect.left <= targetRect.left + 110 || rect.right >= targetRect.right - 56;
    const redLike = isRedLikeColor(style.backgroundColor) || isRedLikeColor(style.color) || isRedLikeColor(style.borderTopColor);
    if (text && /^(?:\d{1,3}|未读)$/.test(text)) {
      return smallBadge && inBadgeZone;
    }
    return !text && smallBadge && rect.width >= 6 && rect.height >= 6 && inBadgeZone && redLike;
  }

  async function openSession(session, options = {}) {
    const item = findSessionItem(session);
    if (!item) {
      return { ok: false, error: "没有找到目标会话项。" };
    }
    scrollSessionItemIntoView(item);
    const clickTargets = uniqueElements([
      findClickableSessionTarget(item),
      findSessionNameTarget(item),
      item,
    ].filter(Boolean));
    let clickTarget = clickTargets[0] || item;
    let activated = false;
    for (const candidate of clickTargets) {
      if (shouldAbortRunner(options)) {
        return { ok: false, error: "batch stopped before opening session" };
      }
      clickTarget = candidate;
      appendRunnerLog(`open session click: ${session.name || session.key} via ${describeElement(candidate)}`);
      await trustedClickElement(candidate);
      activated = await waitForSessionActivated(session, 1200, options);
      if (activated) {
        break;
      }
    }
    return activated
      ? { ok: true }
      : {
          ok: false,
          error: `会话切换后未能进入激活状态。目标=${session.name || session.key}，点击=${describeElement(clickTarget)}，头部=${extractActiveConversationName() || "-"}`,
        };
  }

  async function waitForSessionActivated(session, timeoutMs, options = {}) {
    const startedAt = Date.now();
    while (Date.now() - startedAt <= timeoutMs) {
      if (shouldAbortRunner(options)) {
        return false;
      }
      const item = findSessionItem(session);
      if ((item && isSessionActive(item, session)) || isChatReadyForSession(session)) {
        return true;
      }
      if (!(await waitForRunner(120, { runToken: options.runToken, respectStop: options.respectStop !== false }))) {
        return false;
      }
    }
    return false;
  }

  function isSessionActive(item, session) {
    if (!(item instanceof HTMLElement)) {
      return false;
    }
    if (SELECTORS.sessionActive.some((selector) => item.matches(selector) || item.querySelector(selector))) {
      return true;
    }
    if (looksVisuallySelected(item)) {
      return true;
    }
    return doesConversationMatchSession(session, item);
  }

  function findSessionItem(session) {
    const resolved = resolveSessionViewport();
    const exact = resolved.items.find((item, index) => {
      const descriptor = extractSessionDescriptor(item, index);
      return descriptor && descriptor.key === session.key;
    });
    if (exact) {
      return exact;
    }
    const sameNameAndTime = resolved.items.find((item, index) => {
      const descriptor = extractSessionDescriptor(item, index);
      return descriptor && descriptor.name === session.name && descriptor.time === session.time;
    });
    if (sameNameAndTime) {
      return sameNameAndTime;
    }
    return resolved.items.find((item, index) => {
      const descriptor = extractSessionDescriptor(item, index);
      if (!descriptor || descriptor.name !== session.name) {
        return false;
      }
      if (session.preview && descriptor.preview) {
        return descriptor.preview.startsWith(session.preview.slice(0, Math.min(session.preview.length, 8)));
      }
      return true;
    }) || null;
  }

  function scrollSessionItemIntoView(item) {
    const container = resolveSessionViewport().container;
    if (!(item instanceof HTMLElement)) {
      return;
    }
    item.scrollIntoView({ block: "nearest" });
    if (container instanceof HTMLElement) {
      const itemRect = item.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      container.scrollTop += itemRect.top - containerRect.top - 40;
    }
  }

  function scrollSessionList(step) {
    const container = resolveSessionViewport().container;
    if (!container || !isElementScrollable(container)) {
      const before = window.scrollY;
      const delta = Math.max(Number(step || 0), Math.max(window.innerHeight * 0.85, 260));
      window.scrollBy(0, delta);
      const after = window.scrollY;
      return {
        moved: after > before + 1,
        atBottom: after + window.innerHeight >= document.documentElement.scrollHeight - 4,
      };
    }
    const delta = Math.max(Number(step || 0), Math.max(container.clientHeight * 0.85, 260));
    const before = container.scrollTop;
    container.scrollTop = Math.min(before + delta, container.scrollHeight);
    const after = container.scrollTop;
    return { moved: after > before + 1, atBottom: after + container.clientHeight >= container.scrollHeight - 4 };
  }

  function findClickableSessionTarget(item) {
    if (!(item instanceof HTMLElement)) {
      return null;
    }
    const itemRect = item.getBoundingClientRect();
    const candidates = [
      ...Array.from(item.querySelectorAll("a[href], button, [role='button']")),
      ...Array.from(item.querySelectorAll("div, span")),
    ]
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .map((node) => ({
        node,
        rect: node.getBoundingClientRect(),
        style: window.getComputedStyle(node),
      }))
      .filter((candidate) => candidate.rect.width >= Math.min(80, itemRect.width * 0.28) && candidate.rect.height >= 18);
    candidates.sort((left, right) => {
      const leftScore = scoreSessionClickTarget(left.node, left.rect, left.style, itemRect);
      const rightScore = scoreSessionClickTarget(right.node, right.rect, right.style, itemRect);
      if (Math.abs(rightScore - leftScore) > 0.5) {
        return rightScore - leftScore;
      }
      if (Math.abs(left.rect.left - right.rect.left) > 4) {
        return left.rect.left - right.rect.left;
      }
      return right.rect.width * right.rect.height - left.rect.width * left.rect.height;
    });
    return candidates[0]?.node || null;
  }

  function findSessionNameTarget(item) {
    if (!(item instanceof HTMLElement)) {
      return null;
    }
    const candidates = Array.from(item.querySelectorAll("span, div, p, a"))
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .map((node) => ({ node, text: normalizeText(node.innerText || node.textContent || ""), rect: node.getBoundingClientRect() }))
      .filter((candidate) => candidate.text && candidate.text.length <= 24 && !TIME_TEXT_REGEX.test(candidate.text))
      .sort((left, right) => {
        if (Math.abs(left.rect.left - right.rect.left) > 4) {
          return left.rect.left - right.rect.left;
        }
        return left.rect.top - right.rect.top;
    });
    return candidates[0]?.node || null;
  }

  function scoreSessionClickTarget(node, rect, style, itemRect) {
    const coverage = Math.min(1, (rect.width * rect.height) / Math.max(1, itemRect.width * itemRect.height));
    const tag = String(node.tagName || "").toLowerCase();
    const clickableBonus =
      (tag === "a" ? 3 : 0) +
      (tag === "button" ? 3 : 0) +
      (node.getAttribute("role") === "button" ? 2.5 : 0) +
      (typeof node.onclick === "function" ? 2 : 0) +
      (node.hasAttribute("href") ? 1.5 : 0) +
      ((style.cursor || "").includes("pointer") ? 1.5 : 0);
    const areaBonus = coverage * 6;
    const leftBias = rect.left <= itemRect.left + 120 ? 0.8 : 0;
    const heightBias = rect.height >= itemRect.height * 0.6 ? 1 : 0;
    return clickableBonus + areaBonus + leftBias + heightBias;
  }

  function scoreSessionScrollContainer(node) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node) || node === document.body || node === document.documentElement) {
      return null;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 220 || rect.width > Math.max(window.innerWidth * 0.48, 640) || rect.height < Math.max(window.innerHeight * 0.35, 320)) {
      return null;
    }
    if (rect.left > window.innerWidth * 0.2 || rect.right > window.innerWidth * 0.55) {
      return null;
    }
    const rowCandidates = estimateSessionRowCount(node);
    if (rowCandidates < 4) {
      return null;
    }
    const scrollable = isElementScrollable(node);
    if (!scrollable && node.scrollHeight <= node.clientHeight + 24) {
      return null;
    }
    const text = normalizeText(node.innerText || node.textContent || "");
    const score =
      rowCandidates * 30 +
      (scrollable ? 40 : 0) +
      Math.max(0, 120 - Math.round(rect.left)) +
      (String(node.className || "").includes("list") ? 12 : 0) +
      (text.includes("未读") ? 8 : 0);
    return { node, score };
  }

  function estimateSessionRowCount(container) {
    const probe = Array.from(container.querySelectorAll("div, a, li, section, article")).slice(0, 180);
    return uniqueTopLevelElements(probe.filter((node) => isLikelySessionItem(node, container))).length;
  }

  function deriveSessionScrollContainerFromRows(rows) {
    if (!Array.isArray(rows) || rows.length === 0) {
      return null;
    }
    for (const ancestor of collectAncestors(rows[0])) {
      if (!(ancestor instanceof HTMLElement)) {
        continue;
      }
      if (!rows.every((row) => ancestor.contains(row))) {
        continue;
      }
      if (isElementScrollable(ancestor)) {
        return ancestor;
      }
    }
    const commonAncestor = findCommonAncestor(rows.slice(0, 8));
    if (commonAncestor instanceof HTMLElement) {
      return commonAncestor;
    }
    return rows[0].parentElement || null;
  }

  function doesConversationMatchSession(session, sessionItem) {
    if (!session || !session.name) {
      return false;
    }
    const headerMatches = findConversationHeaderMatches(session.name);
    if (headerMatches.length === 0) {
      return false;
    }
    const itemRect = rectOrNull(sessionItem);
    const header = headerMatches[0];
    if (!(header instanceof HTMLElement)) {
      return true;
    }
    const headerRect = header.getBoundingClientRect();
    if (itemRect && headerRect.left <= itemRect.right + 40) {
      return false;
    }
    return headerRect.top <= window.innerHeight * 0.35;
  }

  function isChatReadyForSession(session) {
    if (!doesConversationMatchSession(session, null)) {
      return false;
    }
    return Boolean(findChatInput()) || Boolean(findRequestResumeButton()) || Boolean(findMessageContainer());
  }

  function extractActiveConversationName() {
    const candidates = Array.from(document.querySelectorAll("h1, h2, h3, strong, b, span, div, p"))
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .map((node) => ({ node, text: normalizeText(node.innerText || node.textContent || "") }))
      .filter((item) => isLikelyConversationHeaderText(item.text, item.node.getBoundingClientRect()))
      .sort((left, right) => {
        const leftRect = left.node.getBoundingClientRect();
        const rightRect = right.node.getBoundingClientRect();
        if (Math.abs(leftRect.top - rightRect.top) > 4) {
          return leftRect.top - rightRect.top;
        }
        if (Math.abs(leftRect.left - rightRect.left) > 4) {
          return leftRect.left - rightRect.left;
        }
        return cleanedConversationHeaderText(left.text).length - cleanedConversationHeaderText(right.text).length;
      });
    return cleanedConversationHeaderText(candidates[0]?.text || "");
  }

  function findConversationHeaderElement(name) {
    return findConversationHeaderMatches(name)[0] || null;
  }

  function isLikelyConversationHeaderText(text, rect) {
    const cleaned = cleanedConversationHeaderText(text);
    if (!cleaned || cleaned.length < 2 || cleaned.length > 48) {
      return false;
    }
    if (containsPromoText(cleaned) || TIME_TEXT_REGEX.test(cleaned)) {
      return false;
    }
    if (rect.top > window.innerHeight * 0.32 || rect.left < window.innerWidth * 0.28 || rect.width < 20) {
      return false;
    }
    return rect.right <= window.innerWidth * 0.9;
  }

  function findConversationHeaderMatches(name) {
    const normalizedName = normalizePersonName(name);
    if (!normalizedName) {
      return [];
    }
    return Array.from(document.querySelectorAll("h1, h2, h3, strong, b, span, div, p"))
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .filter((node) => {
        const text = normalizeText(node.innerText || node.textContent || "");
        return isLikelyConversationHeaderText(text, node.getBoundingClientRect()) && doesTextContainPersonName(text, normalizedName);
      })
      .sort((left, right) => {
        const leftRect = left.getBoundingClientRect();
        const rightRect = right.getBoundingClientRect();
        if (Math.abs(leftRect.top - rightRect.top) > 4) {
          return leftRect.top - rightRect.top;
        }
        const leftText = cleanedConversationHeaderText(left.innerText || left.textContent || "");
        const rightText = cleanedConversationHeaderText(right.innerText || right.textContent || "");
        return leftText.length - rightText.length;
      });
  }

  function normalizePersonName(value) {
    return normalizeText(value).replace(/[♀♂]/g, "");
  }

  function cleanedConversationHeaderText(text) {
    return normalizeText(String(text || ""))
      .replace(/[♀♂]/g, "")
      .replace(/(在线|离线|刚刚活跃|今日活跃|本周活跃)/g, "")
      .replace(/\d{1,2}岁/g, "")
      .replace(/\d+年/g, "")
      .replace(/(本科|硕士|博士|大专|中专|高中)/g, "")
      .trim();
  }

  function doesTextContainPersonName(text, targetName) {
    const cleaned = cleanedConversationHeaderText(text);
    if (!cleaned || !targetName) {
      return false;
    }
    if (cleaned === targetName) {
      return true;
    }
    if (cleaned.startsWith(targetName)) {
      return true;
    }
    return cleaned.split(/\s+|[|·•,，]/).some((token) => token === targetName);
  }

  function findVisibleDownloadButton(options = {}) {
    const byLayout = findPreviewToolbarDownloadByLayout();
    if (byLayout) {
      appendRunnerLog(`preview toolbar download candidate: ${describeElement(byLayout)}`);
      return byLayout;
    }
    const previewRoots = findPreviewRoots();
    const modalRoots = queryAllWithFallback(document, SELECTORS.modalRoot).filter(isElementVisible);
    const includeBody = options.allowBodyFallback !== false && previewRoots.length === 0;
    const roots = uniqueElements([...previewRoots, ...modalRoots, ...(includeBody ? [document.body] : [])]);
    for (const root of roots) {
      const byText = findButtonByText(root, TEXTS.download, {
        exact: false,
        selectors: ["button", "a", "[role='button']"],
        preferRightSide: true,
      });
      if (byText && !isBadPreviewControlCandidate(byText)) {
        return byText;
      }
      const byAttr = findButtonByHint(root, ["download", "下载", "save", "保存"], { preferTopRight: true });
      if (byAttr && isPreviewActionableControl(byAttr) && !isBadPreviewControlCandidate(byAttr) && isDownloadLikeControl(byAttr)) {
        return byAttr;
      }
      const topRight = findTopRightIconButton(root, "download", { strict: previewRoots.length === 0 });
      if (topRight) {
        return topRight;
      }
    }
    return null;
  }

  function findPreviewToolbarDownloadByLayout() {
    const closeButton = findVisibleCloseButton({ allowBodyFallback: true, skipLayoutDownloadProbe: true });
    const closeRect = closeButton?.getBoundingClientRect?.();
    const topLimit = Math.max(120, window.innerHeight * 0.18);
    const candidates = collectPreviewControlElements(document)
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .map((node) => ({
        node,
        rect: node.getBoundingClientRect(),
        hint: buildHintText(node),
      }))
      .filter((item) => {
        if (item.node === closeButton || isBadPreviewControlCandidate(item.node) || isCloseLikeControl(item.node)) {
          return false;
        }
        const smallEnough = item.rect.width >= 8 && item.rect.height >= 8 && item.rect.width <= 96 && item.rect.height <= 96;
        const inTopBand = item.rect.top >= -4 && item.rect.top <= topLimit;
        const nearClose = closeRect
          ? item.rect.right <= closeRect.left + 8 && item.rect.right >= closeRect.left - 260 && Math.abs(centerY(item.rect) - centerY(closeRect)) <= 52
          : item.rect.right >= window.innerWidth - Math.max(360, window.innerWidth * 0.28);
        return smallEnough && inTopBand && nearClose;
      });
    if (candidates.length === 0) {
      return null;
    }
    candidates.sort((left, right) => {
      const leftDownload = isDownloadLikeControl(left.node) ? 10000 : 0;
      const rightDownload = isDownloadLikeControl(right.node) ? 10000 : 0;
      if (leftDownload !== rightDownload) {
        return rightDownload - leftDownload;
      }
      if (closeRect) {
        return distanceToCloseLeft(left.rect, closeRect) - distanceToCloseLeft(right.rect, closeRect);
      }
      return right.rect.right - left.rect.right;
    });
    appendRunnerLog(`preview toolbar layout candidates: ${candidates.slice(0, 4).map((item) => describeToolbarCandidate(item, closeRect)).join(" | ")}`);
    return candidates[0]?.node || null;
  }

  function distanceToCloseLeft(rect, closeRect) {
    return Math.abs(rect.right - closeRect.left);
  }

  function describeToolbarCandidate(item, closeRect) {
    const distance = closeRect ? ` gap=${Math.round(distanceToCloseLeft(item.rect, closeRect))}` : "";
    const hint = truncateText(item.hint || "", 24);
    return `${describeElement(item.node)}${distance}${hint ? ` hint=${hint}` : ""}`;
  }

  async function closeAttachmentPreview(options = {}) {
    const closeButton = findVisibleCloseButton();
    if (!closeButton) {
      appendRunnerLog("preview close button missing");
      triggerEscape();
      await waitForRunner(250, { respectStop: false });
      return false;
    }
    await trustedClickElement(closeButton);
    appendRunnerLog(`preview close click: ${describeElement(closeButton)}`);
    await waitForRunner(options.force ? 250 : 400, { respectStop: false });
    return true;
  }

  function triggerEscape() {
    const init = { key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true, cancelable: true };
    for (const target of [document.activeElement, document.body, document]) {
      if (!target || typeof target.dispatchEvent !== "function") {
        continue;
      }
      try {
        target.dispatchEvent(new KeyboardEvent("keydown", init));
        target.dispatchEvent(new KeyboardEvent("keyup", init));
      } catch (_error) {}
    }
    appendRunnerLog("preview close fallback: Escape");
  }

  function findVisibleCloseButton(options = {}) {
    const previewRoots = findPreviewRoots();
    const modalRoots = queryAllWithFallback(document, SELECTORS.modalRoot).filter(isElementVisible);
    const bodyFallback = options.allowBodyFallback ? [document.body] : [];
    const roots = uniqueElements([...previewRoots, ...modalRoots, ...bodyFallback]);
    for (const root of roots) {
      const byText = findButtonByText(root, TEXTS.close, {
        exact: false,
        selectors: ["button", "a", "[role='button']", "div", "span"],
        preferRightSide: true,
      });
      if (byText && !isBadPreviewControlCandidate(byText)) {
        return byText;
      }
      const byAttr = findButtonByHint(root, ["close", "关闭", "back", "返回"], { preferTopRight: true });
      if (byAttr && !isBadPreviewControlCandidate(byAttr) && isCloseLikeControl(byAttr)) {
        return byAttr;
      }
      const topRight = findTopRightIconButton(root, "close", { strict: false });
      if (topRight) {
        return topRight;
      }
    }
    return null;
  }

  function collectPreviewControlElements(root) {
    if (!root || typeof root.querySelectorAll !== "function") {
      return [];
    }
    return uniqueElements(
      Array.from(root.querySelectorAll("button, a, [role='button'], [title], [aria-label], [data-title], [name*='download'], i, svg"))
        .map(resolvePreviewControlTarget)
        .filter((node) => node instanceof HTMLElement && isElementVisible(node)),
    );
  }

  function resolvePreviewControlTarget(node) {
    let current = node instanceof Element ? node : null;
    for (let depth = 0; current && depth < 4; depth += 1) {
      if (current instanceof HTMLElement && isPreviewActionableControl(current)) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  function isPreviewActionableControl(node) {
    if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
      return false;
    }
    if (node.matches("button, a, [role='button']")) {
      return true;
    }
    if (typeof node.onclick === "function" || node.hasAttribute("onclick")) {
      return true;
    }
    const tabIndex = Number(node.getAttribute("tabindex"));
    if (Number.isInteger(tabIndex) && tabIndex >= 0) {
      return true;
    }
    return window.getComputedStyle(node).cursor === "pointer";
  }

  function findTopRightIconButton(root, kind, options = {}) {
    if (!(root instanceof HTMLElement) || !isElementVisible(root)) {
      return null;
    }
    const rootRect = root.getBoundingClientRect();
    const strict = options.strict !== false;
    const candidateNodes =
      kind === "download"
        ? collectPreviewControlElements(root)
        : Array.from(root.querySelectorAll("button, a, [role='button'], div, span, i, svg"));
    const candidates = candidateNodes
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .map((node) => ({
        node,
        rect: node.getBoundingClientRect(),
        hint: buildHintText(node),
        text: normalizeText(node.innerText || node.textContent || ""),
      }))
      .filter((item) => {
        if (isBadPreviewControlCandidate(item.node)) {
          return false;
        }
        const smallEnough = item.rect.width <= 96 && item.rect.height <= 96;
        const inTopBand = item.rect.top >= rootRect.top - 12 && item.rect.top <= rootRect.top + Math.max(150, rootRect.height * 0.18);
        const inRightBand = item.rect.right >= rootRect.right - Math.max(280, rootRect.width * 0.25) && item.rect.right <= rootRect.right + 24;
        return smallEnough && inTopBand && inRightBand;
      })
      .filter((item) => {
        if (kind === "download") {
          return isDownloadLikeControl(item.node) || (!strict && !isCloseLikeControl(item.node));
        }
        if (kind === "close") {
          return isCloseLikeControl(item.node) || (!strict && !isDownloadLikeControl(item.node) && item.rect.right >= rootRect.right - 120);
        }
        return false;
      });
    candidates.sort((left, right) => {
      const leftScore = scoreTopRightCandidate(left.rect);
      const rightScore = scoreTopRightCandidate(right.rect);
      return rightScore - leftScore;
    });
    return candidates[0]?.node || null;
  }

  function isDownloadLikeControl(node) {
    const haystack = `${buildHintText(node)} ${normalizeText(node?.innerText || node?.textContent || "")}`.toLowerCase();
    return /download|down|save|export|保存|下载/i.test(haystack);
  }

  function isCloseLikeControl(node) {
    const haystack = `${buildHintText(node)} ${normalizeText(node?.innerText || node?.textContent || "")}`.toLowerCase();
    const text = normalizeText(node?.innerText || node?.textContent || "").toLowerCase();
    return /close|cancel|back|popup__close|modal-close|dialog-close|关闭|返回|取消|×/i.test(haystack) || text === "x";
  }

  function isBadPreviewControlCandidate(node) {
    const haystack = buildHintText(node);
    return /ait-notepad|notepad|ai-assistant|sidebar/i.test(haystack);
  }

  function looksVisuallySelected(item) {
    if (!(item instanceof HTMLElement)) {
      return false;
    }
    const style = window.getComputedStyle(item);
    if (style.backgroundColor && !isTransparentColor(style.backgroundColor)) {
      const selfSelected = !isNearWhite(style.backgroundColor) || style.boxShadow !== "none" || !isTransparentColor(style.borderLeftColor);
      if (selfSelected) {
        return true;
      }
    }
    const childStyles = Array.from(item.children)
      .filter((child) => child instanceof HTMLElement)
      .map((child) => window.getComputedStyle(child));
    return childStyles.some((childStyle) => !isTransparentColor(childStyle.backgroundColor) && !isNearWhite(childStyle.backgroundColor));
  }

  function isNearWhite(colorText) {
    const numbers = String(colorText || "").match(/\d+/g);
    if (!numbers || numbers.length < 3) {
      return false;
    }
    const [red, green, blue] = numbers.slice(0, 3).map((value) => Number(value || 0));
    return red >= 238 && green >= 238 && blue >= 238;
  }

  function isTransparentColor(colorText) {
    const text = String(colorText || "").toLowerCase();
    return !text || text === "transparent" || text === "rgba(0, 0, 0, 0)" || text === "rgba(0,0,0,0)";
  }

  function collectAncestors(node) {
    const ancestors = [];
    let current = node instanceof HTMLElement ? node.parentElement : null;
    while (current && current !== document.body && current !== document.documentElement) {
      ancestors.push(current);
      current = current.parentElement;
    }
    return ancestors;
  }

  function findCommonAncestor(nodes) {
    const list = nodes.filter((node) => node instanceof HTMLElement);
    if (list.length === 0) {
      return null;
    }
    let current = list[0].parentElement;
    while (current) {
      if (list.every((node) => current.contains(node))) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  function hasAvatarLikeDescendant(node, rowRect) {
    return Array.from(node.querySelectorAll("img, svg, [class*='avatar'], [class*='head'], [style*='background-image']")).some((candidate) => {
      if (!(candidate instanceof HTMLElement) || !isElementVisible(candidate)) {
        return false;
      }
      const rect = candidate.getBoundingClientRect();
      return rect.width >= 24 && rect.width <= 72 && rect.height >= 24 && rect.height <= 72 && rect.left <= rowRect.left + 96;
    });
  }

  function hasUnreadBadge(node, rowRect) {
    return Array.from(node.querySelectorAll("span, div, em, i, b, strong")).some((candidate) => isUnreadBadge(candidate, rowRect));
  }

  function extractTimeText(node, lines) {
    const explicitTime = Array.from(node.querySelectorAll("span, p, div, em, i, a"))
      .filter((candidate) => candidate instanceof HTMLElement && isElementVisible(candidate))
      .map((candidate) => normalizeText(candidate.innerText || candidate.textContent || ""))
      .find((text) => TIME_TEXT_REGEX.test(text));
    if (explicitTime) {
      return explicitTime;
    }
    return (lines || []).flatMap((line) => line.split(/\s+/)).map(normalizeText).find((text) => TIME_TEXT_REGEX.test(text)) || "";
  }

  function extractSessionName(lines) {
    const firstLine = normalizeText(lines[0] || "");
    if (!firstLine) {
      return "";
    }
    return stripTimeToken(firstLine);
  }

  function extractSessionPreview(lines, name) {
    const filtered = (lines || []).map(normalizeText).filter(Boolean);
    const withoutName = filtered.filter((line) => line !== name && stripTimeToken(line) !== name);
    return withoutName.find((line) => line.length >= 4 && !TIME_TEXT_REGEX.test(line)) || "";
  }

  function stripTimeToken(text) {
    return normalizeText(String(text || "").replace(/(?:\s+|^)(\d{1,2}:\d{2}|昨天|前天|今天|刚刚|\d{1,2}[/-]\d{1,2}|\d{4}[./-]\d{1,2}[./-]\d{1,2})$/u, ""));
  }

  function splitLines(text) {
    return String(text || "")
      .split(/\r?\n+/)
      .map(normalizeText)
      .filter(Boolean);
  }

  function compareElementsByVisualOrder(left, right) {
    const leftRect = left.getBoundingClientRect();
    const rightRect = right.getBoundingClientRect();
    if (Math.abs(leftRect.top - rightRect.top) > 4) {
      return leftRect.top - rightRect.top;
    }
    return leftRect.left - rightRect.left;
  }

  function rectOrNull(node) {
    return node instanceof HTMLElement ? node.getBoundingClientRect() : null;
  }

  function isElementScrollable(node) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    const style = window.getComputedStyle(node);
    return /(auto|scroll|overlay)/i.test(style.overflowY || "") && node.scrollHeight > node.clientHeight + 24;
  }

  function containsPromoText(text) {
    return ["心仪牛人不回应", "顾问帮您打电话", "VIP专享", "不符合牛人"].some((hint) => String(text || "").includes(hint));
  }

  function isRedLikeColor(colorText) {
    const numbers = String(colorText || "").match(/\d+/g);
    if (!numbers || numbers.length < 3) {
      return false;
    }
    const [red, green, blue] = numbers.slice(0, 3).map((value) => Number(value || 0));
    return red >= 180 && green <= 140 && blue <= 140;
  }

  function describeElement(node) {
    if (!(node instanceof HTMLElement)) {
      return "未命中";
    }
    const rect = node.getBoundingClientRect();
    const classes = String(node.className || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 3)
      .join(".");
    return `${node.tagName.toLowerCase()}${classes ? `.${classes}` : ""} [${Math.round(rect.left)},${Math.round(rect.top)} ${Math.round(rect.width)}x${Math.round(rect.height)}]`;
  }

  function formatSessionDebugLabel(item) {
    const status = item.unread ? "未读" : "非未读";
    const preview = truncateText(item.preview || "", 16);
    const time = item.time ? ` ${item.time}` : "";
    return `${truncateText(item.name || item.key, 12)}(${status})${time}${preview ? ` ${preview}` : ""}`;
  }

  function truncateText(text, maxLength) {
    const normalized = normalizeText(text);
    return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}…` : normalized;
  }

  function applyScanDiagnostics(scan) {
    runnerState.stats.discovered = Math.max(Number(runnerState.stats.discovered || 0), Number(scan.items.length || 0), Number(runnerState.processedKeys.size || 0));
    runnerState.stats.discoveredVisibleSessions = Math.max(Number(runnerState.stats.discoveredVisibleSessions || 0), Number(scan.items.length || 0));
    runnerState.stats.eligibleUnreadSessions = Math.max(Number(runnerState.stats.eligibleUnreadSessions || 0), Number(scan.eligibleUnreadCount || 0));
    runnerState.stats.rejectedRows = Math.max(Number(runnerState.stats.rejectedRows || 0), Number(scan.rejectedRows || 0));
    runnerState.scanMessage = scan.scanMessage || "";
    runnerState.scanDebug = scan.debugSummary || "";
  }

  function buildScanProgressMessage(scan, queueLength) {
    if (!scan.hasContainer) {
      return "未识别到左侧会话列表容器，继续尝试扫描。";
    }
    if (scan.items.length === 0) {
      return "已命中会话列表容器，但当前可见区域未识别到真实会话，继续下滚扫描。";
    }
    if (runnerState.mode === "request_resume" && scan.eligibleUnreadCount === 0) {
      return "已发现会话，但未识别到未读角标，继续下滚扫描。";
    }
    if (queueLength === 0) {
      return runnerState.mode === "download_only" ? "当前可见会话已扫描完，继续下滚查找附件简历。" : "当前可见未读会话已处理完，继续下滚扫描。";
    }
    return runnerState.mode === "download_only"
      ? `已发现 ${scan.items.length} 个可见会话，准备继续扫描附件简历。`
      : `已发现 ${scan.items.length} 个可见会话，可处理未读 ${queueLength} 个。`;
  }

  function buildBatchCompletionMessage(scan) {
    if (!scan.hasContainer) {
      return runnerState.mode === "download_only" ? "批量下载已完成：未识别到左侧会话列表容器。" : "批量求简历已完成：未识别到左侧会话列表容器。";
    }
    if (scan.items.length === 0) {
      return runnerState.mode === "download_only"
        ? "批量下载已完成：命中了滚动容器，但当前可见区域未识别到真实会话。"
        : "批量求简历已完成：命中了滚动容器，但当前可见区域未识别到真实会话。";
    }
    if (runnerState.mode === "request_resume" && scan.eligibleUnreadCount === 0) {
      return "批量求简历已完成：已发现会话，但未识别到未读角标。";
    }
    return runnerState.mode === "download_only" ? "批量下载已完成，当前列表中没有更多可下载会话。" : "批量求简历已完成，当前列表中没有更多可处理未读会话。";
  }

  async function finishBatch(phase, message, error = "", runToken = "") {
    if (runToken && !isRunTokenActive(runToken)) {
      appendRunnerLog(`ignore stale finish for token=${runToken}`);
      return;
    }
    runnerState.running = false;
    runnerState.stopRequested = false;
    runnerState.runToken = "";
    runnerState.lastMessage = message;
    runnerState.error = error;
    await sendBackgroundMessage({
      type: "batch_finished",
      payload: {
        phase,
        mode: runnerState.mode,
        currentSession: runnerState.currentSession,
        message,
        scanMessage: runnerState.scanMessage,
        scanDebug: runnerState.scanDebug,
        error,
        stats: { ...runnerState.stats },
        runnerVersion: CHAT_RUNNER_VERSION,
        runToken,
        runtimeLogs: getRunnerLogs(),
        eventText: message,
      },
    });
  }

  async function reportProgress(extra) {
    runnerState.lastMessage = extra.message || runnerState.lastMessage;
    runnerState.scanMessage = extra.scanMessage ?? runnerState.scanMessage;
    runnerState.scanDebug = extra.scanDebug ?? runnerState.scanDebug;
    if (extra.currentSession) {
      runnerState.currentSession = extra.currentSession;
    }
    if (extra.error) {
      runnerState.error = extra.error;
    }
    await sendBackgroundMessage({
      type: "batch_progress",
      payload: {
        running: runnerState.running,
        stopRequested: runnerState.stopRequested,
        phase: extra.phase || "running",
        mode: extra.mode || runnerState.mode,
        currentSession: runnerState.currentSession,
        message: runnerState.lastMessage,
        scanMessage: runnerState.scanMessage,
        scanDebug: runnerState.scanDebug,
        error: runnerState.error,
        stats: { ...runnerState.stats },
        runnerVersion: CHAT_RUNNER_VERSION,
        runToken: runnerState.runToken,
        runtimeLogs: getRunnerLogs(),
        eventText: extra.eventText || "",
      },
    });
  }

  async function sendBackgroundMessage(message) {
    try {
      return await chrome.runtime.sendMessage(message);
    } catch (error) {
      return { ok: false, error: error?.message || String(error) };
    }
  }

  function findButtonByText(root, labels, options = {}) {
    const selectors = Array.isArray(options.selectors) && options.selectors.length > 0 ? options.selectors : ["button", "a", "[role='button']", ".btn", ".button"];
    const candidates = [];
    for (const selector of selectors) {
      for (const node of Array.from(root.querySelectorAll(selector))) {
        if (!(node instanceof HTMLElement) || !isElementVisible(node)) {
          continue;
        }
        const text = normalizeText(node.innerText || node.textContent || "");
        if (!text) {
          continue;
        }
        const matched = labels.some((label) => (options.exact ? text === label : text.includes(label)));
        if (matched) {
          candidates.push({ node, text, rect: node.getBoundingClientRect() });
        }
      }
    }
    if (candidates.length === 0) {
      return null;
    }
    candidates.sort((left, right) => {
      if (options.preferRightSide && Math.abs(right.rect.left - left.rect.left) > 4) {
        return right.rect.left - left.rect.left;
      }
      if (options.preferLower && Math.abs(right.rect.top - left.rect.top) > 4) {
        return right.rect.top - left.rect.top;
      }
      return left.text.length - right.text.length;
    });
    return candidates[0].node;
  }

  function findButtonByHint(root, hints, options = {}) {
    const candidates = Array.from(root.querySelectorAll("button, a, [role='button'], div, span, i, svg"))
      .filter((node) => node instanceof HTMLElement && isElementVisible(node))
      .map((node) => ({
        node,
        rect: node.getBoundingClientRect(),
        haystack: buildHintText(node),
      }))
      .filter((candidate) => hints.some((hint) => candidate.haystack.includes(String(hint || "").toLowerCase())));
    if (candidates.length === 0) {
      return null;
    }
    candidates.sort((left, right) => {
      if (options.preferTopRight) {
        const leftScore = scoreTopRightCandidate(left.rect);
        const rightScore = scoreTopRightCandidate(right.rect);
        if (Math.abs(rightScore - leftScore) > 0.5) {
          return rightScore - leftScore;
        }
      }
      return right.rect.width * right.rect.height - left.rect.width * left.rect.height;
    });
    return candidates[0].node;
  }

  function buildHintText(node) {
    if (!(node instanceof HTMLElement)) {
      return "";
    }
    const values = [
      node.innerText || node.textContent || "",
      node.getAttribute("title") || "",
      node.getAttribute("aria-label") || "",
      node.getAttribute("data-title") || "",
      node.getAttribute("class") || "",
      node.getAttribute("data-icon") || "",
    ];
    return values.join(" ").toLowerCase();
  }

  function scoreTopRightCandidate(rect) {
    const rightWeight = Math.max(0, window.innerWidth - rect.right);
    const topWeight = Math.max(0, rect.top);
    return 1000 - rightWeight - topWeight;
  }

  function centerY(rect) {
    return (rect.top + rect.bottom) / 2;
  }

  function firstText(root, selectors) {
    const node = findFirst(root, selectors);
    return node ? normalizeText(node.innerText || node.textContent || "") : "";
  }

  function findFirst(root, selectors) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      if (node) {
        return node;
      }
    }
    return null;
  }

  function queryAllWithFallback(root, selectors) {
    const results = [];
    for (const selector of selectors) {
      results.push(...Array.from(root.querySelectorAll(selector)));
    }
    return uniqueElements(results);
  }

  function uniqueTopLevelElements(elements) {
    const unique = uniqueElements(elements);
    return unique.filter((node) => !unique.some((other) => other !== node && other.contains(node)));
  }

  function uniqueElements(elements) {
    return Array.from(new Set(elements));
  }

  function isSameElement(left, right) {
    return left === right;
  }

  function setNativeFormControlValue(input, value) {
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor?.set) {
      descriptor.set.call(input, value);
      return;
    }
    input.value = value;
  }

  function dispatchFormInputEvents(input) {
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function dispatchEditableInputEvents(input, inputType, data) {
    const eventInit = { bubbles: true, cancelable: true, data, inputType };
    try {
      input.dispatchEvent(new InputEvent("beforeinput", eventInit));
    } catch (_error) {}
    try {
      input.dispatchEvent(new InputEvent("input", eventInit));
    } catch (_error) {
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function tryInsertTextIntoEditable(input, value) {
    if (!(input instanceof HTMLElement)) {
      return false;
    }
    placeCaretAtEnd(input);
    try {
      return document.execCommand(value === "" ? "delete" : "insertText", false, value === "" ? undefined : value);
    } catch (_error) {
      return false;
    }
  }

  function placeCaretAtEnd(input) {
    if (!(input instanceof HTMLElement) || typeof window.getSelection !== "function") {
      return;
    }
    const selection = window.getSelection();
    if (!selection) {
      return;
    }
    const range = document.createRange();
    range.selectNodeContents(input);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function clickElement(node) {
    if (!(node instanceof HTMLElement)) {
      return;
    }
    node.scrollIntoView({ block: "center", inline: "nearest" });
    node.focus({ preventScroll: true });
    const rect = node.getBoundingClientRect();
    const mouseInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + Math.max(4, rect.width / 2), clientY: rect.top + Math.max(4, rect.height / 2), button: 0 };
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      try {
        node.dispatchEvent(new MouseEvent(type, mouseInit));
      } catch (_error) {}
    }
    try {
      node.click();
    } catch (_error) {}
  }

  async function trustedClickElement(node) {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    const target = resolveTrustedClickTarget(node);
    target.scrollIntoView({ block: "center", inline: "nearest" });
    await waitForRunner(80, { respectStop: false });
    const point = getTrustedClickPoint(target);
    if (!point) {
      appendRunnerLog(`trusted click target invalid, fallback DOM click: ${describeElement(node)}`);
      clickElement(node);
      return false;
    }
    const result = await sendBackgroundMessage({
      type: "trusted_click",
      payload: { x: point.x, y: point.y },
    });
    if (result?.ok) {
      appendRunnerLog(`trusted click ok: ${describeElement(target)} @${point.x},${point.y}`);
      return true;
    }
    appendRunnerLog(`trusted click failed, fallback DOM click: ${result?.error || "unknown error"}`);
    clickElement(node);
    return false;
  }

  function resolveTrustedClickTarget(node) {
    if (!(node instanceof HTMLElement)) {
      return node;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width > 1 && rect.height > 1) {
      return node;
    }
    const visibleChild = Array.from(node.querySelectorAll("button, a, [role='button'], div, span, i, svg"))
      .find((child) => child instanceof HTMLElement && isElementVisible(child));
    if (visibleChild) {
      return visibleChild;
    }
    const visibleParent = node.closest("button, a, [role='button'], div, span");
    if (visibleParent instanceof HTMLElement && isElementVisible(visibleParent)) {
      return visibleParent;
    }
    return node;
  }

  function getTrustedClickPoint(node) {
    if (!(node instanceof HTMLElement)) {
      return null;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return null;
    }
    const x = Math.round(clamp(rect.left + rect.width / 2, 2, window.innerWidth - 2));
    const y = Math.round(clamp(rect.top + rect.height / 2, 2, window.innerHeight - 2));
    return { x, y };
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
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
    return node.getAttribute("aria-disabled") !== "true";
  }

  function normalizeSettings(settings) {
    return {
      resumeMessage: String(settings.resumeMessage || settings.messageText || "方便发一份你的简历过来吗？").trim(),
      waitSeconds: Math.max(Number(settings.waitSeconds || 45), 5),
      pollIntervalMs: Math.max(Number(settings.pollIntervalMs || 2000), 500),
      batchActionDelayMs: Math.max(Number(settings.batchActionDelayMs || settings.pollIntervalMs || 5000), 1000),
      maxBatchSessions: Math.min(Math.max(Number(settings.maxBatchSessions || 50), 1), 50),
      scrollStep: Math.max(Number(settings.scrollStep || 900), 200),
      scrollWaitMs: Math.max(Number(settings.scrollWaitMs || 1500), 500),
      noNewStopRounds: Math.max(Number(settings.noNewStopRounds || 4), 1),
      downloadFolder: String(settings.downloadFolder || "BossResumes").trim() || "BossResumes",
    };
  }

  function normalizeBatchMode(value) {
    return value === "download_only" ? "download_only" : "request_resume";
  }

  function createEmptyStats() {
    return {
      processed: 0,
      requested: 0,
      skipped: 0,
      skippedNoAttachment: 0,
      failed: 0,
      downloaded: 0,
      discovered: 0,
      discoveredVisibleSessions: 0,
      eligibleUnreadSessions: 0,
      rejectedRows: 0,
    };
  }

  function buildDownloadFileName(fileName, folder) {
    const baseName = sanitizeFileName(fileName || `resume_${timestampToken(new Date())}.pdf`);
    const normalizedBase = /\.pdf$/i.test(baseName) ? baseName : `${baseName}.pdf`;
    const safeFolder = String(folder || "BossResumes").replace(/[\\/:*?"<>|]+/g, "_");
    return `${safeFolder}/${normalizedBase}`;
  }

  function buildAttachmentRunKey(sessionKey, attachment) {
    return [sessionKey, sanitizeFileName(attachment.fileName || ""), normalizeText(attachment.text || ""), chooseDownloadUrl(attachment.urls || [], attachment.fileName || "")].join("|");
  }

  function sanitizeFileName(value) {
    return String(value || "").replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, " ").trim() || "boss_resume.pdf";
  }

  function timestampToken(date) {
    return [date.getFullYear(), pad2(date.getMonth() + 1), pad2(date.getDate()), "_", pad2(date.getHours()), pad2(date.getMinutes()), pad2(date.getSeconds())].join("");
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function formatClock(date) {
    return `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").replace(/\u00a0/g, " ").trim();
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

  function escapeHtml(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function isBossPage() {
    return location.hostname.includes("zhipin.com") || location.hostname.includes("bosszhipin.com");
  }

  function detectAccountVerificationBlock() {
    const visibleText = normalizeText(document.body?.innerText || "");
    if (!visibleText) {
      return "";
    }
    const patterns = [
      "账号登录异常",
      "账号异常",
      "登录异常",
      "安全验证",
      "人机验证",
      "身份验证",
      "请完成验证",
      "拖动滑块",
      "验证码",
      "验证后继续",
      "操作过于频繁",
    ];
    const matched = patterns.find((pattern) => visibleText.includes(pattern));
    if (matched) {
      return matched;
    }
    const regexMatched = visibleText.match(/(?:账号|登录|环境|操作|行为|安全).{0,12}(?:异常|验证|风险|频繁)/);
    return regexMatched?.[0] || "";
  }

  async function waitForRunner(ms, options = {}) {
    const totalMs = Math.max(Number(ms || 0), 0);
    const respectStop = options.respectStop !== false;
    const runToken = String(options.runToken || "");
    let elapsed = 0;
    while (elapsed < totalMs) {
      if (shouldAbortRunner({ respectStop, runToken })) {
        return false;
      }
      const sliceMs = Math.min(100, totalMs - elapsed);
      await delay(sliceMs);
      elapsed += sliceMs;
    }
    return !shouldAbortRunner({ respectStop, runToken });
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }
}
