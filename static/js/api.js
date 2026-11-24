/**
 * FinGroww Trading Intelligence — Unified Universal API Client (v1.0.0)
 * Centralized multi-host router, failover resilience, automatic cache sanitizer,
 * and high-availability HTTP bridge for both local dev and production Render backend.
 */
(function(window) {
  'use strict';

  // Master Endpoint Registry
  const PRIMARY_RENDER_URL = "https://fingroww-trading-y3na.onrender.com";
  const CUSTOM_DOMAIN_API = "https://api.fingroww.tech";
  const LOCAL_DEV_API = "http://127.0.0.1:8787";
  const CACHE_STORAGE_KEY = "fingroww_active_api_host";

  // Prohibited / suspended legacy domains
  const DEAD_HOST_FRAGMENTS = [
    "fingroww-trading.onrender.com" // Suspended Render service (returns 503 without CORS)
  ];

  function isHostDead(host) {
    if (!host) return false;
    for (const dead of DEAD_HOST_FRAGMENTS) {
      if (host.includes(dead) && !host.includes("fingroww-trading-y3na.onrender.com")) {
        return true;
      }
    }
    return false;
  }

  // Active host cache sanitizer
  let activeWorkingHost = (function() {
    try {
      const cached = sessionStorage.getItem(CACHE_STORAGE_KEY);
      if (cached && (cached.startsWith("http://") || cached.startsWith("https://"))) {
        if (isHostDead(cached)) {
          sessionStorage.removeItem(CACHE_STORAGE_KEY);
          return null;
        }
        return cached;
      }
    } catch (_) {}
    return null;
  })();

  function getCandidateHosts() {
    const hostname = window.location.hostname || "";
    const port = window.location.port || "";
    const protocol = window.location.protocol || "";

    const isLocalBackendServed = (hostname === "127.0.0.1" || hostname === "localhost") && port === "8787";
    const isRenderServed = hostname.includes("onrender.com") || hostname.includes("api.fingroww.tech");
    const isLocalDev = hostname === "127.0.0.1" || hostname === "localhost" || protocol === "file:" || !hostname;

    let hosts = [PRIMARY_RENDER_URL];
    if (isLocalBackendServed) {
      hosts = ["", LOCAL_DEV_API, PRIMARY_RENDER_URL, CUSTOM_DOMAIN_API];
    } else if (isRenderServed) {
      hosts = ["", PRIMARY_RENDER_URL, CUSTOM_DOMAIN_API];
    } else if (isLocalDev) {
      hosts = [LOCAL_DEV_API, PRIMARY_RENDER_URL, CUSTOM_DOMAIN_API];
    } else {
      // Live production static domain (e.g., fingroww.tech)
      hosts = [PRIMARY_RENDER_URL, CUSTOM_DOMAIN_API];
    }

    // Filter out any dead host
    hosts = hosts.filter(h => !isHostDead(h));

    // Place warm active host first if valid
    if (activeWorkingHost && hosts.includes(activeWorkingHost)) {
      hosts = [activeWorkingHost, ...hosts.filter(h => h !== activeWorkingHost)];
    }
    return hosts;
  }

  async function requestApi(path, options = {}) {
    const candidateHosts = getCandidateHosts();

    // Smart adaptive timeout: heavy scans/backtests get 60s, normal calls get 20s
    let timeoutMs = 20000;
    if (typeof options.timeout === "number") {
      timeoutMs = options.timeout;
    } else if (path.includes("/scan") || path.includes("/backtest")) {
      timeoutMs = 60000;
    }

    for (const host of candidateHosts) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const url = host ? (host + path) : path;
        const fetchOptions = {
          ...options,
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            ...(options.headers || {})
          }
        };

        const res = await fetch(url, fetchOptions);
        clearTimeout(timer);

        if (res && (res.ok || (res.status >= 400 && res.status < 500 && res.status !== 404))) {
          if (host && !isHostDead(host)) {
            activeWorkingHost = host;
            try { sessionStorage.setItem(CACHE_STORAGE_KEY, host); } catch (_) {}
          }
          // Try parsing JSON; fallback to raw response if not JSON
          try {
            return await res.json();
          } catch (_) {
            return res;
          }
        }
      } catch (err) {
        clearTimeout(timer);
        // Continue to next candidate host
      }
    }

    return null;
  }

  // Unified FinGroww API Object
  const FinGrowwApi = {
    PRIMARY_RENDER_URL,
    CUSTOM_DOMAIN_API,
    API_URL: CUSTOM_DOMAIN_API,
    LOCAL_DEV_API,
    fetch: requestApi,
    get: (path, opts = {}) => requestApi(path, { ...opts, method: "GET" }),
    post: (path, body, opts = {}) => requestApi(path, {
      ...opts,
      method: "POST",
      body: typeof body === "string" ? body : JSON.stringify(body || {})
    }),
    getActiveHost: () => activeWorkingHost || PRIMARY_RENDER_URL,
    buildUrl: (path) => {
      const host = activeWorkingHost || PRIMARY_RENDER_URL;
      if (!path) return host;
      if (!path.startsWith("/")) path = "/" + path;
      return host ? (host + path) : path;
    },
    clearActiveHost: () => {
      activeWorkingHost = null;
      try { sessionStorage.removeItem(CACHE_STORAGE_KEY); } catch (_) {}
    }
  };

  // Backward compatibility global exports
  window.FinGrowwApi = FinGrowwApi;
  window.PRIMARY_RENDER_URL = PRIMARY_RENDER_URL;
  window.API_URL = CUSTOM_DOMAIN_API;
  window.PRIMARY_RENDER_API = PRIMARY_RENDER_URL;
  window.CLOUD_API = CUSTOM_DOMAIN_API;
  window.LOCAL_API = LOCAL_DEV_API;

  window.fetchPaperApi = function(path, options = {}) {
    return requestApi(path, options);
  };

  window.fetchApi = function(path, options = {}) {
    return requestApi(path, options);
  };

  window.agentFetch = async function(path, options = {}) {
    const candidateHosts = getCandidateHosts();
    for (const host of candidateHosts) {
      try {
        const url = host ? (host + path) : path;
        const res = await fetch(url, options);
        if (res && (res.ok || (res.status >= 400 && res.status < 500 && res.status !== 404))) {
          if (host && !isHostDead(host)) {
            activeWorkingHost = host;
            try { sessionStorage.setItem(CACHE_STORAGE_KEY, host); } catch (_) {}
          }
          return res;
        }
      } catch (_) {}
    }
    return null;
  };

})(window);
