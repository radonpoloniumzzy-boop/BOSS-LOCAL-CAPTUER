(function initBatchExport(global) {
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
    return (
      normalizeApiBase(batchConnection.apiBase) === normalizeApiBase(currentConnection.apiBase)
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

  global.BossLocalBatchExport = { batchBelongsToConnection, downloadBatchCsv };
})(globalThis);
