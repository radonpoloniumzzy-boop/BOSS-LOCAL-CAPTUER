(function initBatchExport(global) {
  function normalizeConnectionMode(value) {
    const mode = String(value || "").trim().toLowerCase();
    return mode === "web" || mode === "desktop" ? mode : "";
  }

  function normalizeApiBase(value) {
    return String(value || "http://127.0.0.1:17863").trim().replace(/\/+$/, "");
  }

  function filenameFromDisposition(disposition, batchId) {
    const value = String(disposition || "");
    const encoded = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (encoded) {
      try {
        return decodeURIComponent(encoded[1]);
      } catch (_error) {}
    }
    const quoted = value.match(/filename="([^"]+)"/i);
    return quoted?.[1] || `batch_${batchId}.csv`;
  }

  function batchBelongsToConnection(batchConnection, currentConnection) {
    if (!batchConnection || !currentConnection) {
      return false;
    }
    const batchMode = normalizeConnectionMode(batchConnection.connectionMode);
    const currentMode = normalizeConnectionMode(currentConnection.connectionMode);
    if (!batchMode || !currentMode) {
      return false;
    }
    return (
      batchMode === currentMode
      && normalizeApiBase(batchConnection.apiBase) === normalizeApiBase(currentConnection.apiBase)
      && String(batchConnection.apiToken || "") === String(currentConnection.apiToken || "")
    );
  }

  async function downloadBatchCsv({
    apiBase,
    apiToken,
    batchId,
    fetchImpl = global.fetch,
    downloadsApi = global.chrome?.downloads,
    urlApi = global.URL,
  }) {
    const resolvedBatchId = Number(batchId);
    if (!Number.isInteger(resolvedBatchId) || resolvedBatchId <= 0) {
      throw new Error("当前没有可下载的采集批次。");
    }
    const response = await fetchImpl(
      `${normalizeApiBase(apiBase)}/api/export/batches/${resolvedBatchId}.csv`,
      { headers: { "X-Boss-Local-Token": String(apiToken || "") } },
    );
    if (!response.ok) {
      let message = `本地接口返回状态码 ${response.status || "-"}`;
      try {
        const payload = await response.json();
        message = payload?.error || message;
      } catch (_error) {}
      throw new Error(message);
    }
    if (!downloadsApi?.download) {
      throw new Error("Chrome 下载功能不可用，请重新加载扩展。");
    }
    const blob = await response.blob();
    const objectUrl = urlApi.createObjectURL(blob);
    try {
      const filename = filenameFromDisposition(
        response.headers?.get?.("Content-Disposition"),
        resolvedBatchId,
      );
      const downloadId = await downloadsApi.download({
        url: objectUrl,
        filename,
        saveAs: false,
      });
      return { downloadId, filename, batchId: resolvedBatchId };
    } finally {
      urlApi.revokeObjectURL(objectUrl);
    }
  }

  async function downloadBatchMarkdown({
    apiBase,
    apiToken,
    batchId,
    fetchImpl = global.fetch,
    downloadsApi = global.chrome?.downloads,
    urlApi = global.URL,
  }) {
    const resolvedBatchId = Number(batchId);
    if (!Number.isInteger(resolvedBatchId) || resolvedBatchId <= 0) {
      const error = new Error("当前没有可导出的 Web 批次。");
      error.code = "batch_not_available";
      throw error;
    }
    let response;
    try {
      response = await fetchImpl(
        `${normalizeApiBase(apiBase)}/api/capture-batches/${resolvedBatchId}/export.md`,
        { headers: { "X-Boss-Local-Token": String(apiToken || "") } },
      );
    } catch (_error) {
      const error = new Error("网页工作台尚未启动，请先运行‘启动网页工作台’。");
      error.code = "workbench_not_running";
      throw error;
    }
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch (_error) {}
      const serverCode = String(payload?.error?.code || "");
      const code = response.status === 401
        ? "auth_failed"
        : response.status === 404
          ? "batch_not_found"
          : "export_failed";
      const messages = {
        auth_failed: "网页工作台连接已失效，请重新配对。",
        batch_not_found: "该采集批次不存在，可能属于其他人才库。",
        export_failed: "Markdown 文件生成失败，请稍后重试。",
      };
      const error = new Error(messages[code]);
      error.code = serverCode || code;
      throw error;
    }
    if (!downloadsApi?.download) {
      throw new Error("Chrome 下载功能不可用，请重新加载扩展。");
    }
    const blob = await response.blob();
    const objectUrl = urlApi.createObjectURL(blob);
    try {
      const filename = filenameFromDisposition(response.headers?.get?.("Content-Disposition"), resolvedBatchId)
        .replace(/\.csv$/i, ".md");
      const downloadId = await downloadsApi.download({ url: objectUrl, filename, saveAs: false });
      return { downloadId, filename, batchId: resolvedBatchId };
    } finally {
      urlApi.revokeObjectURL(objectUrl);
    }
  }

  global.BossLocalBatchExport = { batchBelongsToConnection, downloadBatchCsv, downloadBatchMarkdown };
})(globalThis);
