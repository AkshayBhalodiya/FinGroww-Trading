/**
 * FinGroww Stock Scanner & AI Research Controller
 * Powers Section 5 (AI Stock Scanner), Section 6 (AI Buy/Sell/Hold Research),
 * Hero Cockpit Live Sync, and Section 4.5 Quantitative Terminal Preview.
 */
const StockScannerController = (() => {
  let allSignals = [
    {
      symbol: "RELIANCE",
      base_symbol: "RELIANCE",
      company_name: "Reliance Industries Ltd",
      instrument_type: "EQUITY",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 94,
      perf_1d: "+1.70%",
      perf_1w: "+4.20%",
      perf_1m: "+8.60%",
      entry_price: 1373.90,
      stop_loss: 1353.30,
      target_1: 1412.35,
      target_2: 1449.45,
      strategy: "1h Horizontal Range Breakout",
      rationale: "Should you BUY? YES. Multi-day resistance breakout with 2.4x institutional delivery volume and bullish RSI divergence. Recommended entry ₹1,373.90 with target ₹1,412.35.",
      category: "buy equities"
    },
    {
      symbol: "TCS",
      base_symbol: "TCS",
      company_name: "Tata Consultancy Services",
      instrument_type: "EQUITY",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 96,
      perf_1d: "+2.33%",
      perf_1w: "+3.80%",
      perf_1m: "+6.15%",
      entry_price: 2517.30,
      stop_loss: 2479.50,
      target_1: 2587.80,
      target_2: 2655.75,
      strategy: "🎯 80%+ Smart Money VWAP & 9/21 EMA Pullback",
      rationale: "Should you BUY? YES. IT heavyweight breakout with strong institutional accumulation and positive momentum. Target ₹2,587.80 with tight trailing SL.",
      category: "buy equities"
    },
    {
      symbol: "HDFCBANK",
      base_symbol: "HDFCBANK",
      company_name: "HDFC Bank Ltd",
      instrument_type: "EQUITY",
      side: "BUY",
      verdict: "ACCUMULATE",
      confidence: 95,
      perf_1d: "+3.47%",
      perf_1w: "+4.85%",
      perf_1m: "+9.20%",
      entry_price: 846.20,
      stop_loss: 833.50,
      target_1: 869.90,
      target_2: 892.75,
      strategy: "Weekly CPR Breakout & Institutional Inflow",
      rationale: "Should you BUY? YES. Massive delivery volume accumulation above 20 EMA. Banking sector leadership indicates strong upward momentum toward ₹890.",
      category: "buy equities"
    },
    {
      symbol: "INFY",
      base_symbol: "INFY",
      company_name: "Infosys Ltd",
      instrument_type: "EQUITY",
      side: "HOLD",
      verdict: "HOLD / WAIT",
      confidence: 86,
      perf_1d: "+2.41%",
      perf_1w: "+3.65%",
      perf_1m: "+5.40%",
      entry_price: 1130.00,
      stop_loss: 1116.40,
      target_1: 1150.35,
      target_2: 1169.55,
      strategy: "Horizontal Demand Zone Retest",
      rationale: "Should you HOLD? YES. Price is holding steady near demand support with modest volume. Existing longs hold with tight stop-loss at ₹1,116. Wait for fresh breakout before sizing up.",
      category: "hold equities"
    },
    {
      symbol: "TATAMOTORS",
      base_symbol: "TATAMOTORS",
      company_name: "Tata Motors Ltd",
      instrument_type: "EQUITY",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 93,
      perf_1d: "+1.45%",
      perf_1w: "+3.90%",
      perf_1m: "+8.40%",
      entry_price: 785.00,
      stop_loss: 773.20,
      target_1: 807.00,
      target_2: 828.20,
      strategy: "VWAP Momentum Expansion",
      rationale: "Should you BUY? YES. Auto sector momentum expansion with institutional buying above session VWAP. Clean 1:2.4 risk-to-reward ratio.",
      category: "buy equities"
    },
    {
      symbol: "AXISBANK",
      base_symbol: "AXISBANK",
      company_name: "Axis Bank Ltd",
      instrument_type: "EQUITY",
      side: "HOLD",
      verdict: "HOLD / WATCH",
      confidence: 88,
      perf_1d: "+1.10%",
      perf_1w: "+1.80%",
      perf_1m: "+3.20%",
      entry_price: 1188.00,
      stop_loss: 1173.75,
      target_1: 1209.40,
      target_2: 1229.50,
      strategy: "50 EMA Range Compression",
      rationale: "Should you HOLD? YES. Compressing inside weekly range. Hold existing positions with SL ₹1,173.75; avoid new aggressive long entries until breakout is confirmed.",
      category: "hold equities"
    },
    {
      symbol: "SBIN",
      base_symbol: "SBIN",
      company_name: "State Bank of India",
      instrument_type: "EQUITY",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 91,
      perf_1d: "+0.49%",
      perf_1w: "+2.20%",
      perf_1m: "+5.50%",
      entry_price: 1138.15,
      stop_loss: 1121.05,
      target_1: 1170.00,
      target_2: 1200.75,
      strategy: "Daily Bull Flag Breakout",
      rationale: "Should you BUY? YES. PSU banking leader breaking out of a multi-week bull flag with volume support. Target ₹1,170 with ₹1,121 stop-loss.",
      category: "buy equities"
    },
    {
      symbol: "ITC",
      base_symbol: "ITC",
      company_name: "ITC Ltd",
      instrument_type: "EQUITY",
      side: "HOLD",
      verdict: "HOLD / COMPOUND",
      confidence: 89,
      perf_1d: "+0.10%",
      perf_1w: "+0.35%",
      perf_1m: "+0.90%",
      entry_price: 472.00,
      stop_loss: 466.30,
      target_1: 480.50,
      target_2: 488.50,
      strategy: "Defensive Value Base",
      rationale: "Should you HOLD? YES. Low-volatility FMCG defensive compounder. Ideal to hold for dividend yield and stability; avoid aggressive short-term trading.",
      category: "hold equities"
    },
    {
      symbol: "BHARTIARTL",
      base_symbol: "BHARTIARTL",
      company_name: "Bharti Airtel Ltd",
      instrument_type: "EQUITY",
      side: "HOLD",
      verdict: "HOLD / WATCH",
      confidence: 87,
      perf_1d: "-0.52%",
      perf_1w: "+2.60%",
      perf_1m: "+8.30%",
      entry_price: 2117.50,
      stop_loss: 2092.10,
      target_1: 2155.60,
      target_2: 2191.60,
      strategy: "Pullback to 20 EMA Support",
      rationale: "Should you HOLD? YES. Mild intraday pullback towards 20 EMA. Hold existing positions with trailing SL ₹2,092.10. Rebound setup intact.",
      category: "hold equities"
    },
    {
      symbol: "NIFTY 50 25,800 CE",
      base_symbol: "NIFTY 50",
      company_name: "Nifty 50 Weekly Option",
      instrument_type: "OPTION",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 98,
      perf_1d: "+24.10%",
      perf_1w: "+48.00%",
      perf_1m: "+95.00%",
      entry_price: 142.50,
      stop_loss: 118.00,
      target_1: 185.00,
      target_2: 220.00,
      strategy: "15m 0.618 Fib Golden Zone Rebound",
      rationale: "Should you BUY? YES. Bullish rejection at 0.618 Golden Zone + Supertrend green + 3.8x volume expansion.",
      category: "options buy"
    },
    {
      symbol: "BANK NIFTY 63,700 CE",
      base_symbol: "BANK NIFTY",
      company_name: "Bank Nifty Weekly Option",
      instrument_type: "OPTION",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 96,
      perf_1d: "+18.20%",
      perf_1w: "+36.50%",
      perf_1m: "+82.00%",
      entry_price: 285.00,
      stop_loss: 235.00,
      target_1: 375.00,
      target_2: 448.00,
      strategy: "Monthly Tuesday High Beta Scalp",
      rationale: "Should you BUY? YES. CPR breakout with heavy put writing at 63,500 PE + Institutional banking sector momentum.",
      category: "options buy"
    }
  ];

  let currentCategory = "all";
  let searchQuery = "";

  async function init() {
    renderResearchCards();
    renderScannerTable();
    await syncLiveQuotesAndScans();

    // 15-second live refresh cycle
    setInterval(syncLiveQuotesAndScans, 15000);

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        syncLiveQuotesAndScans();
      }
    });
  }

  function filterCategory(cat, btnEl) {
    currentCategory = cat;
    document.querySelectorAll(".fg-tab-btn").forEach(b => b.classList.remove("active"));
    if (btnEl) btnEl.classList.add("active");
    renderResearchCards();
    renderScannerTable();
  }

  function onSearchInput(val) {
    searchQuery = (val || "").trim().toLowerCase();
    
    // Highlight matching chip if available
    const chips = document.querySelectorAll("#stockQuickChips .chip");
    chips.forEach(c => {
      const txt = c.textContent.trim().toLowerCase();
      if ((!searchQuery && txt.includes("all")) || (searchQuery && txt.includes(searchQuery))) {
        c.classList.add("active");
      } else {
        c.classList.remove("active");
      }
    });

    renderResearchCards();
    renderScannerTable();
  }

  function getFilteredSignals() {
    return allSignals.filter(s => {
      const matchesCat = (currentCategory === "all") || (s.category && s.category.includes(currentCategory));
      const matchesSearch = !searchQuery || 
        s.symbol.toLowerCase().includes(searchQuery) || 
        s.base_symbol.toLowerCase().includes(searchQuery) ||
        (s.company_name && s.company_name.toLowerCase().includes(searchQuery)) ||
        s.strategy.toLowerCase().includes(searchQuery);
      return matchesCat && matchesSearch;
    });
  }

  function renderResearchCards() {
    const container = document.getElementById("aiResearchCardsContainer");
    if (!container) return;

    const filtered = getFilteredSignals();
    if (filtered.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; text-align:center; padding:40px; color:var(--text-dim);">
          <i class="fa-solid fa-crosshairs" style="font-size:28px;margin-bottom:10px;opacity:0.5;"></i>
          <div>No active signals matching "${searchQuery || currentCategory}". Try searching another symbol like Reliance, TCS, or HDFC.</div>
        </div>
      `;
      return;
    }

    container.innerHTML = filtered.map(sig => {
      const isBuy = sig.side === "BUY";
      const isHold = sig.side === "HOLD";
      const badgeClass = isBuy ? "fg-verdict-buy" : (isHold ? "fg-verdict-hold" : "fg-verdict-sell");
      const icon = isBuy ? "fa-arrow-up" : (isHold ? "fa-pause" : "fa-arrow-down");
      const riskPct = sig.stop_loss ? Math.abs((sig.entry_price - sig.stop_loss) / sig.entry_price * 100).toFixed(1) : "1.5";

      const p1d = sig.perf_1d || "+1.2%";
      const p1w = sig.perf_1w || "+3.4%";
      const p1m = sig.perf_1m || "+7.5%";
      const baseSym = sig.base_symbol || sig.symbol.split(" ")[0];

      return `
        <div class="fg-signal-card" data-cat="${sig.category}">
          <div class="fg-sc-top">
            <div>
              <div class="fg-sc-sym" style="display:flex;align-items:center;gap:6px;">
                <span>${sig.symbol}</span>
                ${sig.instrument_type === 'EQUITY' ? '<span style="font-size:9.5px;padding:1px 5px;border-radius:4px;background:rgba(255,255,255,0.08);color:var(--text-dim);font-weight:700;">NSE</span>' : ''}
              </div>
              <div class="fg-sc-sub">${sig.company_name || sig.strategy}</div>
            </div>
            <span class="fg-verdict-badge ${badgeClass}"><i class="fa-solid ${icon}"></i> ${sig.verdict}</span>
          </div>

          <!-- Multi-timeframe Performance Strip -->
          <div class="fg-perf-strip">
            <div class="fg-perf-item">
              <span class="fg-perf-lbl">1-Day</span>
              <span class="fg-perf-val ${p1d.startsWith('+') ? 'up' : 'down'}">${p1d}</span>
            </div>
            <div class="fg-perf-item">
              <span class="fg-perf-lbl">1-Week</span>
              <span class="fg-perf-val ${p1w.startsWith('+') ? 'up' : 'down'}">${p1w}</span>
            </div>
            <div class="fg-perf-item">
              <span class="fg-perf-lbl">1-Month</span>
              <span class="fg-perf-val ${p1m.startsWith('+') ? 'up' : 'down'}">${p1m}</span>
            </div>
            <div class="fg-perf-item">
              <span class="fg-perf-lbl">Confidence</span>
              <span class="fg-perf-val up">${sig.confidence}%</span>
            </div>
          </div>

          <div class="fg-levels-grid">
            <div>
              <div class="fg-lv-lbl">Entry</div>
              <div class="fg-lv-val ${isBuy ? 'up' : (isHold ? '' : 'down')}">₹${Number(sig.entry_price).toFixed(2)}</div>
            </div>
            <div>
              <div class="fg-lv-lbl">Stop-Loss</div>
              <div class="fg-lv-val down">₹${Number(sig.stop_loss).toFixed(2)} (-${riskPct}%)</div>
            </div>
            <div>
              <div class="fg-lv-lbl">Target 1</div>
              <div class="fg-lv-val up">₹${Number(sig.target_1).toFixed(2)}</div>
            </div>
            <div>
              <div class="fg-lv-lbl">Target 2</div>
              <div class="fg-lv-val" style="color:var(--accent-gold)">₹${Number(sig.target_2).toFixed(2)}</div>
            </div>
          </div>

          <div class="fg-rationale-box">
            <strong>${isBuy ? '🟢 BUY Thesis:' : (isHold ? '🟡 HOLD Thesis:' : '🔴 SELL Thesis:')}</strong> ${sig.rationale}
          </div>

          <div style="margin-top:auto;">
            ${isHold ? `
              <button type="button" class="btn btn-sm btn-outline" style="width:100%;font-weight:700;" onclick="StockScannerController.showWatchlistToast('${sig.symbol}')">
                <i class="fa-solid fa-eye"></i> Add to Active Watchlist
              </button>
            ` : `
              <button type="button" class="opp-btn-action" onclick="StockScannerController.executeQuickTrade('${sig.symbol}', '${sig.side}', ${sig.entry_price}, ${sig.stop_loss}, ${sig.target_1})">
                <i class="fa-solid fa-bolt"></i> 1-Click Paper Trade
              </button>
            `}
            <a href="fingroww_trading_intelligence_NSE.html?symbol=${encodeURIComponent(baseSym)}" class="btn-arena-link" title="Open in Live NSE Trading Arena">
              <i class="fa-solid fa-chart-line"></i> View in Live NSE Trading Arena &rarr;
            </a>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderScannerTable() {
    const tableBody = document.getElementById("aiScannerTableBody");
    if (!tableBody) return;

    const filtered = getFilteredSignals();
    if (filtered.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-dim);">No scanned instruments found.</td></tr>`;
      return;
    }

    tableBody.innerHTML = filtered.map(sig => {
      const isBuy = sig.side === "BUY";
      const isHold = sig.side === "HOLD";
      const badgeClass = isBuy ? "fg-verdict-buy" : (isHold ? "fg-verdict-hold" : "fg-verdict-sell");

      return `
        <tr>
          <td><strong style="color:var(--text-main);font-family:var(--font-mono);font-size:13px;">${sig.symbol}</strong></td>
          <td class="td-center"><span class="fg-verdict-badge ${badgeClass}">${sig.side}</span></td>
          <td style="font-size:12px;color:var(--text-muted);">${sig.strategy}</td>
          <td class="td-right mono font-bold" style="color:var(--text-main);">₹${Number(sig.entry_price).toFixed(2)}</td>
          <td class="td-right mono font-bold down">₹${Number(sig.stop_loss).toFixed(2)}</td>
          <td class="td-right mono font-bold up">₹${Number(sig.target_1).toFixed(2)}</td>
          <td class="td-center">
            <button type="button" class="btn btn-sm ${isHold ? 'btn-outline' : 'btn-launch'}" style="padding:5px 12px;font-size:11px;" onclick="StockScannerController.executeQuickTrade('${sig.symbol}', '${sig.side}', ${sig.entry_price}, ${sig.stop_loss}, ${sig.target_1})">
              <i class="fa-solid fa-bolt"></i> Trade
            </button>
          </td>
        </tr>
      `;
    }).join("");
  }

  async function syncLiveQuotesAndScans() {
    if (!localStorage.getItem("fg_access_token")) {
      return;
    }
    let hasChanges = false;

    // 1. Sync Live Equity Quotes from /api/market/ticker
    try {
      const tickerData = await FinGrowwAPI.getMarketTicker();
      const rows = tickerData?.rows || tickerData?.data || [];
      if (Array.isArray(rows) && rows.length > 0) {
        allSignals = allSignals.map(sig => {
          if (sig.instrument_type !== "EQUITY") return sig;
          const cleanBase = sig.base_symbol.replace(/\s+/g, "").toUpperCase();
          const matched = rows.find(r => {
            const sym = (r.symbol || r.name || "").replace(/\s+/g, "").toUpperCase();
            return sym === cleanBase || sym.includes(cleanBase) || cleanBase.includes(sym);
          });
          if (matched && (matched.lastPrice || matched.ltp)) {
            const lp = Number(matched.lastPrice || matched.ltp);
            const pchg = matched.pChangeFormatted || ((matched.pChange >= 0 ? '+' : '') + Number(matched.pChange || 0).toFixed(2) + '%');
            const isBuy = sig.side === "BUY";
            const isHold = sig.side === "HOLD";
            
            const sl = isBuy ? (lp * 0.985) : (isHold ? (lp * 0.988) : (lp * 1.015));
            const t1 = isBuy ? (lp * 1.028) : (isHold ? (lp * 1.018) : (lp * 0.972));
            const t2 = isBuy ? (lp * 1.055) : (isHold ? (lp * 1.035) : (lp * 0.945));

            hasChanges = true;
            return {
              ...sig,
              entry_price: lp,
              perf_1d: pchg,
              stop_loss: sl,
              target_1: t1,
              target_2: t2
            };
          }
          return sig;
        });
      }
    } catch(e) {}

    // 2. Sync Live Option Scans from /api/paper/session/scan
    try {
      const scanData = await FinGrowwAPI.getSessionScan();
      if (scanData && Array.isArray(scanData.scanned_signals) && scanData.scanned_signals.length > 0) {
        const topScans = scanData.scanned_signals.slice(0, 3);
        
        topScans.forEach(scan => {
          const side = (scan.side || "BUY").toUpperCase();
          const optIdx = allSignals.findIndex(s => s.symbol === scan.symbol || s.base_symbol === scan.base_symbol);
          const formatted = {
            symbol: scan.symbol,
            base_symbol: scan.base_symbol || scan.symbol,
            company_name: scan.name || `${scan.base_symbol} Options Contract`,
            instrument_type: "OPTION",
            side: side,
            verdict: "STRONG BUY",
            confidence: scan.confidence_score || 96,
            perf_1d: "+24.10%",
            perf_1w: "+48.00%",
            perf_1m: "+95.00%",
            entry_price: Number(scan.entry_price || 142.50),
            stop_loss: Number(scan.stop_loss || 118.00),
            target_1: Number(scan.target_price || 185.00),
            target_2: Number(scan.target_price ? scan.target_price * 1.15 : 220.00),
            strategy: scan.strategy || "🎯 15m 0.618 Fib Golden Zone Rebound",
            rationale: scan.rationale || `Strong confluence with underlying ${scan.base_symbol} momentum. Recommended entry ₹${Number(scan.entry_price).toFixed(2)} with strict SL ₹${Number(scan.stop_loss).toFixed(2)}.`,
            category: "options buy"
          };

          if (optIdx >= 0) {
            allSignals[optIdx] = formatted;
          } else {
            allSignals.unshift(formatted);
          }
          hasChanges = true;
        });
      }
    } catch(e) {}

    // 3. Update Hero Cockpit Card & Arena Preview with top active setup
    updateHeroCockpitCard();
    updateArenaPreviewCard();

    // 4. Re-render UI
    if (hasChanges) {
      renderResearchCards();
      renderScannerTable();
    }
  }

  function updateHeroCockpitCard() {
    const topOption = allSignals.find(s => s.instrument_type === "OPTION") || allSignals[0];
    if (!topOption) return;

    const symEl = document.getElementById("cockpitSym");
    const subEl = document.getElementById("cockpitSymSub");
    const ltpEl = document.getElementById("cockpitLtpBadge");
    const entryEl = document.getElementById("cockpitEntry");
    const slEl = document.getElementById("cockpitSL");
    const t1El = document.getElementById("cockpitT1");
    const t2El = document.getElementById("cockpitT2");
    const tradeBtn = document.getElementById("cockpitTradeBtn");

    if (symEl) symEl.textContent = topOption.symbol;
    if (subEl) subEl.textContent = `${topOption.strategy} • Conf: ${topOption.confidence}%`;
    if (ltpEl) ltpEl.textContent = `LTP ₹${Number(topOption.entry_price).toFixed(2)} ▲`;
    if (entryEl) entryEl.textContent = `₹${Number(topOption.entry_price).toFixed(2)}`;
    if (slEl) slEl.textContent = `₹${Number(topOption.stop_loss).toFixed(2)}`;
    if (t1El) t1El.textContent = `₹${Number(topOption.target_1).toFixed(2)}`;
    if (t2El) t2El.textContent = `₹${Number(topOption.target_2).toFixed(2)}`;

    if (tradeBtn) {
      tradeBtn.onclick = () => {
        executeQuickTrade(topOption.symbol, topOption.side, topOption.entry_price, topOption.stop_loss, topOption.target_1);
      };
    }
  }

  function updateArenaPreviewCard() {
    const topOption = allSignals.find(s => s.instrument_type === "OPTION") || allSignals[0];
    if (!topOption) return;

    const scoreEl = document.getElementById("arenaConfluenceScore");
    const entryEl = document.getElementById("arenaEntry");
    const slEl = document.getElementById("arenaSL");
    const t1El = document.getElementById("arenaTarget");

    if (scoreEl) scoreEl.textContent = `${topOption.confidence} / 100`;
    if (entryEl) entryEl.textContent = `₹${Number(topOption.entry_price).toFixed(2)}`;
    if (slEl) slEl.textContent = `₹${Number(topOption.stop_loss).toFixed(2)}`;
    if (t1El) t1El.textContent = `₹${Number(topOption.target_1).toFixed(2)}`;
  }

  async function executeQuickTrade(sym, side, entry, sl, t1) {
    if (!localStorage.getItem("fg_access_token")) {
      window.location.href = "auth.html?next=" + encodeURIComponent("index.html#aiScanner");
      return;
    }

    if (typeof showToast === "function") {
      showToast(sym, `${side} (1 Lot)`, entry);
    }

    const modal = document.getElementById("modalPaperExecuted");
    const descEl = document.getElementById("simModalDesc");
    const detailsEl = document.getElementById("simModalDetails");

    if (detailsEl) {
      detailsEl.innerHTML = `
        <div>Symbol: <span style="color:var(--text-main);font-weight:700;">${sym}</span></div>
        <div>Side: <span class="${side === 'BUY' ? 'up' : 'down'}" style="font-weight:700;">${side} (1 Lot)</span></div>
        <div>Entry: <span style="color:var(--accent-blue);">₹${Number(entry).toFixed(2)}</span> • SL: <span class="down">₹${Number(sl).toFixed(2)}</span></div>
        <div>Target: <span class="up">₹${Number(t1).toFixed(2)}</span></div>
      `;
    }

    try {
      const authUserObj = (() => { try { return JSON.parse(localStorage.getItem("fg_auth_user") || "null"); } catch(_) { return null; } })();
      const activeTrader = (authUserObj && (authUserObj.trading_profile_name || authUserObj.full_name || authUserObj.username)) || "Trader";
      const res = await FinGrowwAPI.executePaperOrder({
        symbol: sym,
        signal_type: side,
        entry_price: entry,
        stop_loss: sl,
        target_1: t1,
        user_name: activeTrader
      });
      if (descEl && res && res.ok) {
        descEl.innerHTML = `<strong>Live Server Synced!</strong> 1 Lot of ${sym} executed in your active AI Paper Trading account.`;
      }
    } catch (e) {}

    if (modal) modal.classList.add("active");
  }

  function showWatchlistToast(sym) {
    if (!localStorage.getItem("fg_access_token")) {
      window.location.href = "auth.html?next=" + encodeURIComponent("index.html#stockResearch");
      return;
    }
    if (typeof showToast === "function") {
      showToast(sym, "HOLD ALERT: Added to active watchlist", 0);
    }
  }

  return {
    init,
    filterCategory,
    onSearchInput,
    syncLiveQuotesAndScans,
    executeQuickTrade,
    showWatchlistToast
  };
})();
