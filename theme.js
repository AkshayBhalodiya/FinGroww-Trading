// FinGroww Global Theme, Auth Gate & Interactive Controller
(function() {
  const THEME_KEY = 'fingroww_theme';
  const ACCESS_TOKEN_KEY = 'fg_access_token';
  const REFRESH_TOKEN_KEY = 'fg_refresh_token';

  // Pages accessible without signing in (Public Landing, Auth, Info & Compliance)
  const PUBLIC_PAGES = new Set([
    '',
    'index.html',
    'auth.html',
    'login',
    'register',
    'account',
    'about.html',
    'contact.html',
    'disclaimer.html',
    'pricing.html',
  ]);

  function getCurrentRouteSlug() {
    const path = (window.location.pathname || '').replace(/\/+$/, '');
    const seg = path.split('/').pop() || '';
    return seg.toLowerCase();
  }

  function isProtectedPage() {
    return !PUBLIC_PAGES.has(getCurrentRouteSlug());
  }

  function redirectToLogin() {
    const nextUrl = window.location.pathname + window.location.search + window.location.hash;
    window.location.replace('auth.html?next=' + encodeURIComponent(nextUrl || 'auth.html'));
  }

  // Enforce strict login gate immediately on protected application pages
  if (isProtectedPage()) {
    try {
      const tok = localStorage.getItem(ACCESS_TOKEN_KEY);
      if (!tok || !tok.trim()) {
        redirectToLogin();
        return;
      }
    } catch (_) {
      redirectToLogin();
      return;
    }
  }

  // Global fetch() JWT Bearer injector + auto-refresh + 401 redirect guard
  if (typeof window.fetch === 'function' && !window.__fgFetchPatched) {
    const nativeFetch = window.fetch.bind(window);
    window.__fgFetchPatched = true;

    window.fetch = async function(input, init) {
      const urlStr = typeof input === 'string' ? input : (input && input.url ? input.url : '');
      const isApiCall = urlStr.includes('/api/');
      const isAuthEndpoint = urlStr.includes('/api/v2/auth/login') || urlStr.includes('/api/v2/auth/register') || urlStr.includes('/api/v2/auth/refresh') || urlStr.includes('/api/auth/login') || urlStr.includes('/api/auth/register');

      const nextInit = init ? { ...init } : {};
      if (isApiCall && !isAuthEndpoint) {
        const token = localStorage.getItem(ACCESS_TOKEN_KEY);
        if (token) {
          const headers = new Headers(nextInit.headers || (input instanceof Request ? input.headers : undefined) || {});
          if (!headers.has('Authorization')) {
            headers.set('Authorization', 'Bearer ' + token);
          }
          nextInit.headers = headers;
        }
      }

      let response = await nativeFetch(input, nextInit);

      if (response.status === 401 && isApiCall && !isAuthEndpoint) {
        const rt = localStorage.getItem(REFRESH_TOKEN_KEY);
        if (rt) {
          try {
            const refRes = await nativeFetch('/api/v2/auth/refresh', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ refresh_token: rt }),
            });
            if (refRes.ok) {
              const refJson = await refRes.json();
              if (refJson.access_token) localStorage.setItem(ACCESS_TOKEN_KEY, refJson.access_token);
              if (refJson.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, refJson.refresh_token);
              if (refJson.user) localStorage.setItem('fg_auth_user', JSON.stringify(refJson.user));
              const retryHeaders = new Headers(nextInit.headers || {});
              retryHeaders.set('Authorization', 'Bearer ' + refJson.access_token);
              nextInit.headers = retryHeaders;
              response = await nativeFetch(input, nextInit);
            }
          } catch (_) {}
        }

        if (response.status === 401 && isProtectedPage()) {
          localStorage.removeItem(ACCESS_TOKEN_KEY);
          localStorage.removeItem(REFRESH_TOKEN_KEY);
          localStorage.removeItem('fg_auth_user');
          redirectToLogin();
        }
      }

      return response;
    };
  }

  // Global EventSource SSE JWT query injector
  if (typeof window.EventSource === 'function' && !window.__fgSSEPatched) {
    const NativeES = window.EventSource;
    window.__fgSSEPatched = true;
    window.EventSource = function(url, config) {
      let targetUrl = url;
      try {
        const token = localStorage.getItem(ACCESS_TOKEN_KEY);
        if (token && typeof targetUrl === 'string' && targetUrl.includes('/api/') && !targetUrl.includes('token=')) {
          targetUrl += (targetUrl.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token);
        }
      } catch (_) {}
      return new NativeES(targetUrl, config);
    };
    window.EventSource.prototype = NativeES.prototype;
  }
  
  // Initialize theme from storage or system preference
  function getPreferredTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved) return saved;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
    
    // Update theme toggle buttons across the page
    document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      const icon = btn.querySelector('.theme-icon');
      if (icon) {
        icon.innerHTML = theme === 'dark'
          ? '<i class="fa-solid fa-sun" aria-hidden="true"></i>'
          : '<i class="fa-solid fa-moon" aria-hidden="true"></i>';
      }
      const label = btn.querySelector('.theme-label');
      if (label) {
        label.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
      }
    });
  }

  window.toggleTheme = function() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
  };

  // Run immediately before DOM load to avoid flash
  const initialTheme = getPreferredTheme();
  applyTheme(initialTheme);

  // Setup DOM elements once ready
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(getPreferredTheme());

    // Accessibility Skip Link & main landmark hook
    const mainLandmark = document.querySelector('main') || document.querySelector('.container');
    if (mainLandmark && !mainLandmark.id) {
      mainLandmark.id = 'main-content';
    }
    if (mainLandmark && !document.querySelector('.fg-skip-link')) {
      const skip = document.createElement('a');
      skip.href = '#' + mainLandmark.id;
      skip.className = 'fg-skip-link';
      skip.textContent = 'Skip to main content';
      document.body.insertBefore(skip, document.body.firstChild);
    }

    // Header elevation on scroll + active link + Account / Super Admin sync
    try {
      if ('caches' in window) {
        caches.keys().then(keys => keys.forEach(k => { if (k.startsWith('fingroww-') && k !== 'fingroww-v2.0') caches.delete(k); })).catch(() => {});
      }
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistrations().then(regs => regs.forEach(r => r.update())).catch(() => {});
      }
    } catch (_) {}

    const currentSlug = getCurrentRouteSlug() || 'index.html';
    document.querySelectorAll('header.site-header .nav-links li, #mobileDrawer a').forEach(el => {
      const link = el.tagName === 'A' ? el : el.querySelector('a');
      const href = ((link && link.getAttribute('href')) || '').split('#')[0].split('?')[0].toLowerCase();
      if (href === 'backtest.html') {
        el.remove();
      }
    });
    document.querySelectorAll('header.site-header .nav-links a, #mobileDrawer a').forEach(a => {
      const href = (a.getAttribute('href') || '').split('#')[0].split('?')[0].toLowerCase();
      if (!href) return;
      if (href === currentSlug) {
        a.classList.add('active');
      } else {
        a.classList.remove('active');
      }
    });

    // Canonical Before-Login / After-Login Header & Mobile Drawer Auth Sync
    window.fgGlobalSignOut = async function() {
      const tok = localStorage.getItem(ACCESS_TOKEN_KEY);
      if (tok) {
        try {
          await fetch('/api/v2/auth/logout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tok },
          });
        } catch (_) {}
      }
      try {
        localStorage.removeItem(ACCESS_TOKEN_KEY);
        localStorage.removeItem(REFRESH_TOKEN_KEY);
        localStorage.removeItem('fg_auth_user');
        localStorage.removeItem('fingroww_paper_user');
      } catch (_) {}
      if (typeof window.syncFinGrowwAuthHeader === 'function') {
        window.syncFinGrowwAuthHeader();
      }
      window.location.href = 'auth.html';
    };

    window.syncFinGrowwAuthHeader = function() {
      const siteHdr = document.querySelector('header.site-header');
      const mobileDrawerEl = document.getElementById('mobileDrawer');
      let u = null;
      let tok = '';
      try {
        tok = localStorage.getItem(ACCESS_TOKEN_KEY) || '';
        const rawUser = localStorage.getItem('fg_auth_user');
        u = rawUser ? JSON.parse(rawUser) : null;
      } catch (_) {
        u = null;
      }
      const isLoggedIn = Boolean(u && tok);
      const role = isLoggedIn ? String(u.role || 'trader').toLowerCase() : '';
      const isAdm = isLoggedIn && ['super_admin', 'admin', 'support', 'analyst', 'content_manager'].includes(role);
      const firstName = isLoggedIn
        ? String(u.full_name || u.trading_profile_name || u.username || 'Trader').trim().split(/\s+/)[0]
        : '';

      if (siteHdr) {
        const navActs = siteHdr.querySelector('.nav-actions');
        const hasMainLinks = Boolean(siteHdr.querySelector('.nav-links'));
        if (navActs && hasMainLinks) {
          let authLink = document.getElementById('headerAuthBtn');
          if (!authLink) {
            authLink = document.createElement('a');
            authLink.id = 'headerAuthBtn';
            authLink.href = 'auth.html';
            authLink.className = 'btn btn-sm btn-outline';
            navActs.insertBefore(authLink, navActs.querySelector('.btn-launch') || navActs.querySelector('.mobile-toggle'));
          }

          let existingAdm = document.getElementById('headerAdminLinkBtn');
          if (isAdm) {
            if (!existingAdm) {
              existingAdm = document.createElement('a');
              existingAdm.id = 'headerAdminLinkBtn';
              existingAdm.href = 'admin.html';
              existingAdm.className = 'btn btn-sm btn-primary';
              navActs.insertBefore(existingAdm, authLink);
            }
            existingAdm.innerHTML = `<i class="fa-solid fa-shield-halved"></i> <span>${role === 'super_admin' ? 'Super Admin' : 'Admin'}</span>`;
            existingAdm.title = 'Open Admin Control Centre';
          } else if (existingAdm) {
            existingAdm.remove();
          }

          if (isLoggedIn) {
            authLink.href = 'auth.html';
            authLink.innerHTML = `<i class="fa-solid fa-user-pen" style="color:var(--accent-green);"></i> <span></span>`;
            authLink.querySelector('span').textContent = firstName;
            authLink.title = `Account & Profile (${u.email || ''})`;
          } else {
            authLink.href = 'auth.html';
            authLink.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> <span>Sign In</span>';
            authLink.title = 'Sign In or Create FinGroww Account';
          }
        }
      }

      if (mobileDrawerEl) {
        const drawerList = mobileDrawerEl.querySelector('.mobile-nav-list');
        const drawerActs = mobileDrawerEl.querySelector('.mobile-drawer-actions');
        const drawerAuth = document.getElementById('drawerAuthBtn');

        // Hide dashboard.html link for guest & normal traders; keep visible for Admins
        const dashDrawerLink = drawerList ? drawerList.querySelector('a[href="dashboard.html"]') : null;
        if (dashDrawerLink) {
          dashDrawerLink.style.display = isAdm ? '' : 'none';
        }

        let drawerAdmLink = document.getElementById('drawerAdminLink');
        if (isAdm && drawerList) {
          if (!drawerAdmLink) {
            drawerAdmLink = document.createElement('a');
            drawerAdmLink.id = 'drawerAdminLink';
            drawerAdmLink.href = 'admin.html';
            drawerAdmLink.style.cssText = 'color:var(--accent-blue);font-weight:800;';
            drawerList.insertBefore(drawerAdmLink, drawerList.firstChild);
          }
          drawerAdmLink.innerHTML = `<i class="fa-solid fa-shield-halved"></i> ${role === 'super_admin' ? 'Super Admin Console' : 'Admin Console'}`;
        } else if (drawerAdmLink) {
          drawerAdmLink.remove();
        }

        if (drawerAuth) {
          if (isLoggedIn) {
            drawerAuth.href = 'auth.html';
            drawerAuth.innerHTML = '<i class="fa-solid fa-user-pen" style="color:var(--accent-green);"></i> <span></span>';
            drawerAuth.querySelector('span').textContent = firstName;
          } else {
            drawerAuth.href = 'auth.html';
            drawerAuth.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> <span>Sign In</span>';
          }
        }

        let drawerSignOut = document.getElementById('drawerSignOutBtn');
        if (isLoggedIn && drawerActs) {
          if (!drawerSignOut) {
            drawerSignOut = document.createElement('button');
            drawerSignOut.type = 'button';
            drawerSignOut.id = 'drawerSignOutBtn';
            drawerSignOut.className = 'btn btn-sm btn-outline mobile-drawer-signout';
            drawerSignOut.innerHTML = '<i class="fa-solid fa-right-from-bracket"></i> Sign Out';
            drawerSignOut.addEventListener('click', window.fgGlobalSignOut);
            drawerActs.appendChild(drawerSignOut);
          }
        } else if (drawerSignOut) {
          drawerSignOut.remove();
        }
      }
    };

    const siteHdr = document.querySelector('header.site-header');
    if (siteHdr) {
      const onScroll = () => siteHdr.classList.toggle('is-scrolled', window.scrollY > 12);
      window.addEventListener('scroll', onScroll, { passive: true });
      onScroll();
    }
    window.syncFinGrowwAuthHeader();
    window.addEventListener('storage', (ev) => {
      if (!ev.key || ev.key === ACCESS_TOKEN_KEY || ev.key === 'fg_auth_user') {
        window.syncFinGrowwAuthHeader();
      }
    });

    // Mobile menu drawer toggle
    const mobileBtn = document.getElementById('mobileMenuBtn');
    const mobileDrawer = document.getElementById('mobileDrawer');
    if (mobileBtn && mobileDrawer) {
      const closeDrawer = () => {
        mobileDrawer.classList.remove('open');
        mobileDrawer.setAttribute('aria-hidden', 'true');
        mobileBtn.setAttribute('aria-expanded', 'false');
        mobileBtn.innerHTML = '<i class="fa-solid fa-bars"></i>';
      };
      mobileBtn.addEventListener('click', () => {
        const isOpen = mobileDrawer.classList.contains('open');
        if (isOpen) {
          closeDrawer();
        } else {
          mobileDrawer.classList.add('open');
          mobileDrawer.setAttribute('aria-hidden', 'false');
          mobileBtn.setAttribute('aria-expanded', 'true');
          mobileBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        }
      });
      mobileDrawer.querySelectorAll('a').forEach(a => a.addEventListener('click', closeDrawer));
      window.addEventListener('keydown', e => {
        if (e.key === 'Escape' && mobileDrawer.classList.contains('open')) closeDrawer();
      });
      window.addEventListener('resize', () => {
        if (window.innerWidth > 1120 && mobileDrawer.classList.contains('open')) closeDrawer();
      });
    }

    // FAQ accordions
    document.querySelectorAll('.faq-item').forEach(item => {
      const q = item.querySelector('.faq-q') || item.querySelector('.faq-question');
      if (q) {
        q.addEventListener('click', () => {
          const wasActive = item.classList.contains('active');
          document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('active'));
          if (!wasActive) item.classList.add('active');
        });
      }
    });
  });

  // Global Toast Notification Helper
  window.showToast = function(msg, duration = 4000) {
    let toast = document.getElementById('fingrowwToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'fingrowwToast';
      toast.className = 'global-toast';
      document.body.appendChild(toast);
    }
    toast.innerHTML = `<span class="toast-check">✔</span> <span>${msg}</span>`;
    toast.classList.add('show');
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, duration);
  };

  // ==========================================================================
  // FinGroww Multi-Instrument Live Signal Alert & Web Push Notification Engine
  // ==========================================================================
  const ALERT_STORAGE_KEY = 'fingroww_alerts_config';
  const DEFAULT_CONFIG = {
    soundEnabled: true,
    browserNotify: true,
    minConfluence: 60,
    symbols: ['ALL'], // 'ALL' or specific symbols: 'NIFTY 50', 'BANK NIFTY', etc.
    onlyAplus: false
  };

  function loadAlertConfig() {
    try {
      const raw = localStorage.getItem(ALERT_STORAGE_KEY);
      return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_CONFIG };
    } catch(e) {
      return { ...DEFAULT_CONFIG };
    }
  }

  function saveAlertConfig(cfg) {
    localStorage.setItem(ALERT_STORAGE_KEY, JSON.stringify(cfg));
  }

  // Web Audio Synthesizer (Generates studio chimes with zero external audio assets)
  let audioCtx = null;
  function getAudioContext() {
    if (!audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) audioCtx = new AudioContext();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    return audioCtx;
  }

  function playChime(type = 'BUY') {
    try {
      const ctx = getAudioContext();
      if (!ctx) return;
      const now = ctx.currentTime;

      if (type === 'BUY') {
        // High ascending major triad (C5, E5, G5)
        const notes = [523.25, 659.25, 783.99];
        notes.forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(freq, now + idx * 0.1);
          gain.gain.setValueAtTime(0, now + idx * 0.1);
          gain.gain.linearRampToValueAtTime(0.22, now + idx * 0.1 + 0.03);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.1 + 0.45);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.1);
          osc.stop(now + idx * 0.1 + 0.45);
        });
      } else if (type === 'SELL') {
        // Warning descending chord (F5, D5, Bb4)
        const notes = [698.46, 587.33, 466.16];
        notes.forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'triangle';
          osc.frequency.setValueAtTime(freq, now + idx * 0.11);
          gain.gain.setValueAtTime(0, now + idx * 0.11);
          gain.gain.linearRampToValueAtTime(0.24, now + idx * 0.11 + 0.03);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.11 + 0.48);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.11);
          osc.stop(now + idx * 0.11 + 0.48);
        });
      } else {
        // High double alert ping
        const notes = [783.99, 1046.50];
        notes.forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(freq, now + idx * 0.12);
          gain.gain.setValueAtTime(0.18, now + idx * 0.12);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.12 + 0.35);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.12);
          osc.stop(now + idx * 0.12 + 0.35);
        });
      }
    } catch(e) {
      console.warn("Audio chime note error:", e);
    }
  }

  // Deduplication cache: stores symbol+signal to prevent duplicate alerts within 3 minutes
  const recentAlerts = new Map();

  // Floating On-Screen Banner Alert
  function showFloatingSignalBanner(data) {
    let container = document.getElementById('signalAlertContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'signalAlertContainer';
      container.className = 'signal-alert-container';
      document.body.appendChild(container);
    }

    const banner = document.createElement('div');
    const isBuy = data.sig === 'BUY';
    banner.className = `signal-alert-banner ${isBuy ? 'sab-buy' : 'sab-sell'}`;

    const formattedPrice = typeof data.price === 'number' ? `₹${data.price.toFixed(2)}` : data.price;
    const formattedSl = typeof data.sl === 'number' ? `₹${data.sl.toFixed(2)}` : data.sl;
    const formattedT1 = typeof data.t1 === 'number' ? `₹${data.t1.toFixed(2)}` : data.t1;
    const formattedT2 = typeof data.t2 === 'number' ? `₹${data.t2.toFixed(2)}` : data.t2;

    const timeStr = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    banner.innerHTML = `
      <div class="sab-top">
        <div class="sab-sym">
          <i class="fa-solid fa-bolt" style="color:${isBuy ? 'var(--accent-green)' : 'var(--accent-red)'}"></i>
          <span>${data.symbol}</span>
          <span class="sab-badge ${isBuy ? 'badge-buy' : 'badge-sell'}">${data.sig} • ${data.quality || 'A+'}</span>
        </div>
        <button class="sab-close" title="Dismiss">&times;</button>
      </div>

      <div class="sab-levels">
        <div>
          <div class="sab-lvl-lbl">Entry (LTP)</div>
          <div class="sab-lvl-val">${formattedPrice}</div>
        </div>
        <div>
          <div class="sab-lvl-lbl">Stop Loss</div>
          <div class="sab-lvl-val" style="color:var(--accent-red)">${formattedSl}</div>
        </div>
        <div>
          <div class="sab-lvl-lbl">Target 1</div>
          <div class="sab-lvl-val" style="color:var(--accent-green)">${formattedT1}</div>
        </div>
      </div>

      <div class="sab-footer">
        <div class="sab-time">
          <i class="fa-regular fa-clock"></i> ${timeStr} • ${data.score || 95}% Confluence
        </div>
        <a href="fingroww_trading_intelligence_NSE.html" class="sab-action-btn">
          View Setup &rarr;
        </a>
      </div>
    `;

    container.appendChild(banner);

    // Slide in
    requestAnimationFrame(() => {
      banner.classList.add('show');
    });

    const closeBtn = banner.querySelector('.sab-close');
    const dismiss = () => {
      banner.classList.remove('show');
      setTimeout(() => banner.remove(), 400);
    };

    if (closeBtn) closeBtn.addEventListener('click', dismiss);
    setTimeout(dismiss, 9000);
  }

  // Browser System Web Notification (Works across tabs & when browser is minimized)
  function sendSystemNotification(data) {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;

    try {
      const isBuy = data.sig === 'BUY';
      const title = `⚡ FinGroww 95% ${data.sig} Signal: ${data.symbol}`;
      const body = `Price: ₹${data.price} | T1: ₹${data.t1} | SL: ₹${data.sl} (${data.score || 95}% Confluence)`;
      
      const notif = new Notification(title, {
        body: body,
        icon: 'https://cdn-icons-png.flaticon.com/512/2953/2953363.png',
        badge: 'https://cdn-icons-png.flaticon.com/512/2953/2953363.png',
        tag: `fingroww-${data.symbol}-${data.sig}`,
        renotify: true
      });

      notif.onclick = function() {
        window.focus();
        window.location.href = 'fingroww_trading_intelligence_NSE.html';
        this.close();
      };
    } catch(e) {
      console.warn("Browser notification dispatch error:", e);
    }
  }

  // FinGroww Alert Settings Modal UI
  const POPULAR_SYMBOLS = ['NIFTY 50', 'BANK NIFTY', 'FINNIFTY', 'RELIANCE', 'HDFCBANK', 'TATA MOTORS', 'SBIN', 'INFY', 'TCS', 'ICICIBANK'];

  function createSettingsModal() {
    let overlay = document.getElementById('fingrowwAlertModal');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'fingrowwAlertModal';
    overlay.className = 'alert-modal-overlay';

    overlay.innerHTML = `
      <div class="alert-modal-card">
        <div class="alert-modal-head">
          <div class="alert-modal-title">
            <i class="fa-solid fa-bell" style="color:var(--accent-gold)"></i>
            <span>Live Signal Notification Settings</span>
          </div>
          <button type="button" class="sab-close" id="closeAlertModalBtn" style="font-size:18px;">&times;</button>
        </div>

        <!-- Sound Chimes -->
        <div class="alert-row">
          <div class="alert-row-text">
            <h5>Audio Sound Chimes</h5>
            <p>Play instant professional tone when a BUY or SELL signal generates.</p>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <button type="button" class="btn btn-outline btn-sm" id="testSoundBtn" style="padding:4px 8px;font-size:11px;">
              <i class="fa-solid fa-play"></i> Test Sound
            </button>
            <div class="switch-ui active" id="swSound"><div class="switch-handle"></div></div>
          </div>
        </div>

        <!-- Browser System Notification -->
        <div class="alert-row">
          <div class="alert-row-text">
            <h5>Browser Push Notifications</h5>
            <p>Receive notifications on your device even if you are on another tab.</p>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <button type="button" class="btn btn-primary btn-sm" id="requestPermBtn" style="padding:4px 8px;font-size:11px;">
              Enable Permission
            </button>
            <div class="switch-ui active" id="swPush"><div class="switch-handle"></div></div>
          </div>
        </div>

        <!-- Minimum Confluence Threshold -->
        <div class="alert-row">
          <div class="alert-row-text">
            <h5>Minimum Confluence Filter</h5>
            <p>Only alert on high-probability institutional grade setups.</p>
          </div>
          <select id="selConfluence" class="form-control" style="width:130px;padding:6px 10px;font-size:12px;font-weight:700;">
            <option value="58">58%+ (Standard)</option>
            <option value="70">70%+ (High Confidence)</option>
            <option value="80">80%+ (Tier A+ Sniper Only)</option>
          </select>
        </div>

        <!-- Instrument Selection -->
        <div>
          <div style="font-size:13px;font-weight:800;color:var(--text-main);margin-bottom:6px;">
            Select Instruments to Alert On:
          </div>
          <div class="watchlist-chips-grid" id="wlChipsGrid">
            <button type="button" class="wl-chip active" data-sym="ALL">✔ All Scanned Instruments</button>
            ${POPULAR_SYMBOLS.map(sym => `<button type="button" class="wl-chip" data-sym="${sym}">${sym}</button>`).join('')}
          </div>
        </div>

        <!-- Modal Footer Actions -->
        <div style="display:flex;justify-content:space-between;align-items:center;padding-top:10px;border-top:1px solid var(--border-subtle)">
          <button type="button" class="btn btn-outline btn-sm" id="testLiveAlertBtn">
            <i class="fa-solid fa-bolt"></i> Test Trigger Alert
          </button>
          <button type="button" class="btn btn-primary btn-sm" id="saveAlertModalBtn">
            Save Alert Preferences
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // Event handlers for modal
    const closeBtn = overlay.querySelector('#closeAlertModalBtn');
    const saveBtn = overlay.querySelector('#saveAlertModalBtn');
    const testSoundBtn = overlay.querySelector('#testSoundBtn');
    const requestPermBtn = overlay.querySelector('#requestPermBtn');
    const testLiveAlertBtn = overlay.querySelector('#testLiveAlertBtn');

    const swSound = overlay.querySelector('#swSound');
    const swPush = overlay.querySelector('#swPush');
    const selConfluence = overlay.querySelector('#selConfluence');
    const wlChipsGrid = overlay.querySelector('#wlChipsGrid');

    // Load initial values
    let cfg = loadAlertConfig();
    if (!cfg.soundEnabled) swSound.classList.remove('active');
    if (!cfg.browserNotify) swPush.classList.remove('active');
    selConfluence.value = String(cfg.minConfluence || 60);

    if ('Notification' in window && Notification.permission === 'granted') {
      requestPermBtn.textContent = 'Permission Granted ✔';
      requestPermBtn.style.background = 'var(--accent-green)';
    }

    const updateChipActive = () => {
      wlChipsGrid.querySelectorAll('.wl-chip').forEach(chip => {
        const sym = chip.dataset.sym;
        if (cfg.symbols.includes(sym)) {
          chip.classList.add('active');
        } else {
          chip.classList.remove('active');
        }
      });
    };
    updateChipActive();

    // Toggle sound
    swSound.addEventListener('click', () => {
      swSound.classList.toggle('active');
      cfg.soundEnabled = swSound.classList.contains('active');
      saveAlertConfig(cfg);
    });

    // Toggle push
    swPush.addEventListener('click', () => {
      swPush.classList.toggle('active');
      cfg.browserNotify = swPush.classList.contains('active');
      saveAlertConfig(cfg);
    });

    // Test sound
    testSoundBtn.addEventListener('click', () => {
      playChime('BUY');
    });

    // Request browser permission
    requestPermBtn.addEventListener('click', async () => {
      if ('Notification' in window) {
        const perm = await Notification.requestPermission();
        if (perm === 'granted') {
          showToast("Browser push notification permission GRANTED! ✔");
          requestPermBtn.textContent = 'Permission Granted ✔';
          requestPermBtn.style.background = 'var(--accent-green)';
        } else {
          showToast("Browser notification permission denied or dismissed.");
        }
      } else {
        alert("Your browser does not support HTML5 desktop notifications.");
      }
    });

    // Watchlist chip clicks
    wlChipsGrid.querySelectorAll('.wl-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const sym = chip.dataset.sym;
        if (sym === 'ALL') {
          cfg.symbols = ['ALL'];
        } else {
          cfg.symbols = cfg.symbols.filter(s => s !== 'ALL');
          if (cfg.symbols.includes(sym)) {
            cfg.symbols = cfg.symbols.filter(s => s !== sym);
            if (cfg.symbols.length === 0) cfg.symbols = ['ALL'];
          } else {
            cfg.symbols.push(sym);
          }
        }
        updateChipActive();
      });
    });

    // Test Live Alert
    testLiveAlertBtn.addEventListener('click', () => {
      window.FinGrowwAlerts.triggerSignal({
        symbol: 'NIFTY 50',
        sig: 'BUY',
        quality: 'A+ Sniper',
        price: 24682.40,
        sl: 24610.00,
        t1: 24765.00,
        t2: 24820.00,
        score: 95
      }, true);
    });

    // Save & Close
    const closeModal = () => overlay.classList.remove('open');
    closeBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });

    saveBtn.addEventListener('click', () => {
      cfg.minConfluence = parseInt(selConfluence.value, 10);
      saveAlertConfig(cfg);
      showToast("Alert preferences saved successfully! ✔");
      closeModal();
    });

    return overlay;
  }

  // Public Interface for FinGrowwAlerts
  window.FinGrowwAlerts = {
    playChime: playChime,
    openSettings: function() {
      const modal = createSettingsModal();
      modal.classList.add('open');
    },
    triggerSignal: function(data, force = false) {
      if (!data || !data.symbol || !data.sig) return;
      if (data.sig === 'WAIT') return;

      const cfg = loadAlertConfig();

      // Check symbol filter
      if (!force && !cfg.symbols.includes('ALL') && !cfg.symbols.includes(data.symbol)) {
        return;
      }

      // Check confluence filter
      if (!force && (data.score || 0) < cfg.minConfluence) {
        return;
      }

      // Check deduplication (throttle same signal on same symbol within 3 mins)
      const key = `${data.symbol}_${data.sig}`;
      const now = Date.now();
      if (!force && recentAlerts.has(key)) {
        const lastTime = recentAlerts.get(key);
        if (now - lastTime < 180000) return; // 3 minutes
      }
      recentAlerts.set(key, now);

      // Play audio chime
      if (cfg.soundEnabled) {
        playChime(data.sig);
      }

      // Show on-screen animated banner
      showFloatingSignalBanner(data);

      // Show system desktop/mobile push notification
      if (cfg.browserNotify) {
        sendSystemNotification(data);
      }
    }
  };

  // Automatically inject Alert Button into header navigation actions
  function injectAlertNavBtn() {
    const target = document.querySelector('.nav-actions') || document.querySelector('.status-hud');
    if (target && !document.getElementById('navAlertSettingsBtn')) {
      const alertBtn = document.createElement('button');
      alertBtn.type = 'button';
      alertBtn.id = 'navAlertSettingsBtn';
      alertBtn.className = 'nav-alert-btn active-pulse';
      alertBtn.title = 'Live Signal Notification Alerts (Sound & Push)';
      alertBtn.setAttribute('aria-label', 'Live Signal Notification Alerts');
      alertBtn.innerHTML = '<i class="fa-solid fa-bell" aria-hidden="true"></i>';
      alertBtn.addEventListener('click', (e) => {
        e.preventDefault();
        window.FinGrowwAlerts.openSettings();
      });

      if (target.classList.contains('status-hud')) {
        alertBtn.style.width = '32px';
        alertBtn.style.height = '32px';
        alertBtn.style.borderRadius = '999px';
        alertBtn.style.fontSize = '14px';
        alertBtn.style.marginLeft = '4px';
        target.appendChild(alertBtn);
      } else {
        target.insertBefore(alertBtn, target.firstChild);
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectAlertNavBtn);
  } else {
    injectAlertNavBtn();
  }

})();

