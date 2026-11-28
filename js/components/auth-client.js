/**
 * FinGroww SaaS Auth Client (v2.0)
 * Manages JWT access/refresh tokens, authenticated fetch calls, header state sync,
 * and automatic token refresh.
 */
const FinGrowwAuth = (() => {
  const ACCESS_KEY = "fg_access_token";
  const REFRESH_KEY = "fg_refresh_token";
  const USER_KEY = "fg_auth_user";

  function getApiBase() {
    if (typeof FinGrowwAPI !== "undefined" && typeof FinGrowwAPI.getBaseUrl === "function") {
      return FinGrowwAPI.getBaseUrl();
    }
    const host = window.location.hostname;
    const port = window.location.port;
    if ((host === "127.0.0.1" || host === "localhost") && port === "8787") return "";
    if (host === "127.0.0.1" || host === "localhost" || !host) return "http://127.0.0.1:8787";
    return "https://api.fingroww.tech";
  }

  function getAccessToken() {
    try { return localStorage.getItem(ACCESS_KEY) || ""; } catch (_) { return ""; }
  }

  function getRefreshToken() {
    try { return localStorage.getItem(REFRESH_KEY) || ""; } catch (_) { return ""; }
  }

  function getUser() {
    try {
      const raw = localStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function saveSession(data) {
    try {
      if (data.access_token) localStorage.setItem(ACCESS_KEY, data.access_token);
      if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token);
      if (data.user) {
        localStorage.setItem(USER_KEY, JSON.stringify(data.user));
        const traderName = data.user.trading_profile_name || data.user.full_name || data.user.username;
        if (traderName) localStorage.setItem("fingroww_paper_user", traderName);
      }
    } catch (_) {}
    syncHeaderUI();
  }

  function clearSession() {
    try {
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem("fingroww_paper_user");
    } catch (_) {}
    syncHeaderUI();
  }

  async function request(path, options = {}) {
    const base = getApiBase();
    const token = getAccessToken();
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    let res = await fetch(base + path, { ...options, headers });

    // Auto-refresh access token on 401 if refresh token exists
    if (res.status === 401 && getRefreshToken() && !path.includes("/auth/refresh") && !path.includes("/auth/login")) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${getAccessToken()}`;
        res = await fetch(base + path, { ...options, headers });
      }
    }

    const json = await res.json().catch(() => ({ ok: false, error: "Invalid server response" }));
    if (!res.ok) {
      const msg = json.detail || json.error || `Request failed (${res.status})`;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return json;
  }

  async function tryRefresh() {
    const rt = getRefreshToken();
    if (!rt) return false;
    try {
      const res = await fetch(getApiBase() + "/api/v2/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) {
        clearSession();
        return false;
      }
      const data = await res.json();
      saveSession(data);
      return true;
    } catch (_) {
      return false;
    }
  }

  async function logout() {
    try {
      if (getAccessToken()) {
        await request("/api/v2/auth/logout", { method: "POST" });
      }
    } catch (_) {}
    clearSession();
  }

  function syncHeaderUI() {
    if (typeof window.syncFinGrowwAuthHeader === "function") {
      window.syncFinGrowwAuthHeader();
      return;
    }
    const btn = document.getElementById("headerAuthBtn");
    if (!btn) return;
    const user = getUser();
    const existingAdm = document.getElementById("headerAdminLinkBtn");
    if (user && getAccessToken()) {
      const displayName = (user.full_name || user.trading_profile_name || user.username || "Trader").split(" ")[0];
      const isAdm = ["super_admin", "admin", "support", "analyst", "content_manager"].includes((user.role || "").toLowerCase());
      btn.href = "auth.html";
      btn.innerHTML = `<i class="fa-solid fa-user-pen" style="color:var(--accent-green);"></i> <span>${displayName}</span>`;
      btn.title = `Account & Profile (${user.email})`;

      if (isAdm && btn.parentElement) {
        if (!existingAdm) {
          const adm = document.createElement("a");
          adm.id = "headerAdminLinkBtn";
          adm.href = "admin.html";
          adm.className = "btn btn-sm btn-primary";
          adm.innerHTML = `<i class="fa-solid fa-shield-halved"></i> <span>${user.role === "super_admin" ? "Super Admin" : "Admin"}</span>`;
          btn.parentElement.insertBefore(adm, btn);
        }
      } else if (existingAdm) {
        existingAdm.remove();
      }
    } else {
      btn.href = "auth.html";
      btn.innerHTML = `<i class="fa-solid fa-right-to-bracket"></i> <span>Sign In</span>`;
      btn.title = "Sign In or Create FinGroww Account";
      if (existingAdm) existingAdm.remove();
    }
  }

  document.addEventListener("DOMContentLoaded", syncHeaderUI);

  return {
    getAccessToken,
    getRefreshToken,
    getUser,
    saveSession,
    clearSession,
    request,
    logout,
    syncHeaderUI,
  };
})();
