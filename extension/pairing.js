(function initializeBossLocalPairing(global) {
  function parsePairingCode(value) {
    let pairingUrl;
    try {
      pairingUrl = new URL(String(value || "").trim());
    } catch (_error) {
      throw new Error("连接码格式无效，请从桌面端设置页重新复制。");
    }
    if (pairingUrl.protocol !== "boss-local:" || pairingUrl.hostname !== "pair") {
      throw new Error("连接码格式无效，请从桌面端设置页重新复制。");
    }

    const apiToken = String(pairingUrl.searchParams.get("apiToken") || "").trim();
    const rawApiBase = String(pairingUrl.searchParams.get("apiBase") || "").trim();
    let apiUrl;
    try {
      apiUrl = new URL(rawApiBase);
    } catch (_error) {
      throw new Error("连接码中的接口地址无效。");
    }
    const hostname = apiUrl.hostname.toLowerCase();
    if (apiUrl.protocol !== "http:" || !["127.0.0.1", "localhost", "::1", "[::1]"].includes(hostname)) {
      throw new Error("连接码中的接口地址不是本机地址。");
    }
    if (!apiToken) {
      throw new Error("连接码中缺少 Token，请从桌面端重新复制。");
    }
    if (hostname !== "127.0.0.1") {
      apiUrl.hostname = "127.0.0.1";
    }
    return {
      apiBase: apiUrl.toString().replace(/\/+$/, ""),
      apiToken,
    };
  }

  global.BossLocalPairing = { parsePairingCode };
})(globalThis);
