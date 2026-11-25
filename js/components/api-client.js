/**
 * FinGroww API Client
 * Unified HTTP interface for real-time market data, AI scans, and paper execution.
 */
const FinGrowwAPI = (() => {
  const isLocal = window.location.hostname === "127.0.0.1" || 
                  window.location.hostname === "localhost" || 
                  window.location.protocol === "file:" || 
                  !window.location.hostname;
                  
  const BASE_URLS = [
    isLocal ? "http://127.0.0.1:8787" : "https://api.fingroww.tech",
    "https://api.fingroww.tech",
    "https://fingroww-trading-y3na.onrender.com"
  ].filter(Boolean);

  let activeBase = BASE_URLS[0] || "";

  async function request(endpoint, options = {}) {
    const defaultHeaders = {
      "Accept": "application/json",
      "Content-Type": "application/json"
    };

    const config = {
      ...options,
      headers: { ...defaultHeaders, ...(options.headers || {}) }
    };

    // Try primary base, fallback if unavailable
    for (const base of BASE_URLS) {
      try {
        const fullUrl = `${base}${endpoint}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 6000);
        
        const response = await fetch(fullUrl, {
          ...config,
          signal: controller.signal
        });
        clearTimeout(timeoutId);

        if (response.ok) {
          activeBase = base;
          return await response.json();
        }
      } catch (err) {
        // Try next fallback URL
      }
    }

    return null;
  }

  return {
    getBaseUrl: () => activeBase,
    getMarketStatus: () => request("/api/market-status"),
    getMarketTicker: () => request("/api/market/ticker"),
    getQuote: (symbol) => request(`/api/quote?symbol=${encodeURIComponent(symbol)}`),
    getSignals: () => request("/api/signals"),
    getInstitutional: () => request("/api/skills/institutional"),
    getSessionScan: () => request("/api/paper/session/scan"),
    getSkillsSuite: (symbol) => request(`/api/skills/suite?symbol=${encodeURIComponent(symbol)}`),
    getSwarmStatus: () => request("/api/agents/status"),
    getBrokerStatus: (user = "Akshay") => request(`/api/broker/status?user=${encodeURIComponent(user)}`),
    getLeaderboard: () => request("/api/paper/leaderboard"),
    getAnalytics: (user = "Akshay") => request(`/api/paper/analytics?user=${encodeURIComponent(user)}`),
    executePaperOrder: (orderPayload) => request("/api/paper/order/execute", {
      method: "POST",
      body: JSON.stringify(orderPayload)
    })
  };
})();
