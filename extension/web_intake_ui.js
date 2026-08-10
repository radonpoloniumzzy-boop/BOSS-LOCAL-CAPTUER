(function (globalThis) {
  const { sameConnectionIdentity, connectionIdentity, isWebWorkbenchMode } = globalThis.BossLocalWebIntakeIdentity;

  function modeLabel(settings) {
    return isWebWorkbenchMode(settings) ? "Web 工作台模式" : "旧桌面兼容模式";
  }

  async function formatStatus(record, settings) {
    const currentIdentity = await connectionIdentity(settings);
    const belongsToCurrentConnection = sameConnectionIdentity(record?.connection, currentIdentity);
    const result = record?.webResult || {};
    const title = record?.statusLabel || "等待发送";
    const lines = [
      `当前模式：${modeLabel(settings)}`,
      record?.message || "采集完成后会自动尝试发送到网页工作台。",
      result.batch_id ? `Web 批次 ID: ${result.batch_id}` : "",
      Number.isFinite(result.received_count) ? `接收数: ${result.received_count || 0}` : "",
      Number.isFinite(result.inserted_candidates) ? `新增数: ${result.inserted_candidates || 0}` : "",
      Number.isFinite(result.updated_candidates) ? `更新数: ${result.updated_candidates || 0}` : "",
      Number.isFinite(result.skipped_candidates) ? `跳过数: ${result.skipped_candidates || 0}` : "",
      Number.isFinite(result.failed_candidates) ? `失败数: ${result.failed_candidates || 0}` : "",
      !belongsToCurrentConnection && record ? "该批次属于旧连接，当前模式不会误投到新的工作台。" : "",
    ].filter(Boolean);
    return {
      title,
      message: lines.join("\n"),
      canRetry: belongsToCurrentConnection && ["waiting_retry", "failed"].includes(String(record?.status || "")),
      mode: modeLabel(settings),
    };
  }

  function classifySuccessfulStatus(result) {
    const status = String(result?.status || "").trim();
    if (status === "failed") {
      return {
        status: "failed",
        statusLabel: "发送失败",
        message: result?.batch_id
          ? `网页工作台返回失败结果，批次 #${result.batch_id} 未成功入库。`
          : "网页工作台返回失败结果，本次未成功入库。",
      };
    }
    if (status === "partial") {
      return {
        status: "partial",
        statusLabel: "部分成功",
        message: `网页工作台已接收批次 #${result?.batch_id || "-"}，但其中存在部分失败。`,
      };
    }
    if (status === "reused" || result?.reused) {
      return {
        status: "reused",
        statusLabel: "已复用原批次",
        message: `网页工作台已复用批次 #${result?.batch_id || "-"}`,
      };
    }
    return {
      status: "completed",
      statusLabel: "入库成功",
      message: `网页工作台已接收批次 #${result?.batch_id || "-"}`,
    };
  }

  globalThis.BossLocalWebIntakeUi = {
    modeLabel,
    formatStatus,
    classifySuccessfulStatus,
  };
})(globalThis);
