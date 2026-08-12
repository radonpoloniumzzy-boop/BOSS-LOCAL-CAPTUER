(function initializeBossLocalPairing(global) {
  function parsePairingCode(value) {
    const raw = String(value || "").trim();
    if (/^[A-F0-9]{6}-[A-F0-9]{6}$/i.test(raw)) {
      return {
        pairingCode: raw.toUpperCase(),
        apiBase: "http://127.0.0.1:17864",
        connectionMode: "web",
      };
    }
    let pairingUrl;
    try {
      pairingUrl = new URL(raw);
    } catch (_error) {
      throw new Error("连接码格式无效，请从网页工作台设置页重新生成。");
    }
    if (pairingUrl.protocol === "boss-local:" && pairingUrl.hostname === "web-pair") {
      if (pairingUrl.username || pairingUrl.password || pairingUrl.hash || (pairingUrl.pathname && pairingUrl.pathname !== "/")) {
        throw new Error("网页连接码格式无效。");
      }
      const keys = [...pairingUrl.searchParams.keys()];
      if (
        keys.length !== 2
        || !keys.includes("apiBase")
        || !keys.includes("pairingCode")
        || pairingUrl.searchParams.getAll("apiBase").length !== 1
        || pairingUrl.searchParams.getAll("pairingCode").length !== 1
      ) {
        throw new Error("网页连接码只能包含本机地址和一次性连接码。");
      }
      const pairingCode = String(pairingUrl.searchParams.get("pairingCode") || "").trim().toUpperCase();
      if (!/^[A-F0-9]{6}-[A-F0-9]{6}$/.test(pairingCode)) {
        throw new Error("网页一次性连接码无效。");
      }
      let webApiUrl;
      try {
        webApiUrl = new URL(String(pairingUrl.searchParams.get("apiBase") || "").trim());
      } catch (_error) {
        throw new Error("网页连接码中的本机地址无效。");
      }
      const port = Number(webApiUrl.port);
      if (
        webApiUrl.protocol !== "http:"
        || webApiUrl.hostname !== "127.0.0.1"
        || webApiUrl.username
        || webApiUrl.password
        || webApiUrl.hash
        || webApiUrl.search
        || (webApiUrl.pathname && webApiUrl.pathname !== "/")
        || !Number.isInteger(port)
        || port < 1024
        || port > 65535
      ) {
        throw new Error("网页连接码中的地址必须是 127.0.0.1 本机 HTTP 端口。");
      }
      return { pairingCode, apiBase: webApiUrl.origin, connectionMode: "web" };
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
      connectionMode: "desktop",
    };
  }

  global.BossLocalPairing = { parsePairingCode };
})(globalThis);
