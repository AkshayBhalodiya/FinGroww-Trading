/**
 * FinGroww Stock Scanner & AI Research Controller
 * Powers Section 5 (AI Stock Scanner) & Section 6 (AI Buy/Sell/Hold Research)
 */
const StockScannerController = (() => {
  let allSignals = [
    {
      symbol: "NIFTY 50 25,350 CE",
      base_symbol: "NIFTY 50",
      instrument_type: "OPTION",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 98,
      entry_price: 192.50,
      stop_loss: 154.00,
      target_1: 248.00,
      target_2: 285.00,
      strategy: "15m 0.618 Fib Golden Zone Rebound",
      rationale: "Bullish rejection at 0.618 Golden Zone (₹25,300 support) + Supertrend green + 3.8x volume expansion.",
      category: "options buy"
    },
    {
      symbol: "BANK NIFTY 62,600 CE",
      base_symbol: "BANK NIFTY",
      instrument_type: "OPTION",
      side: "BUY",
      verdict: "STRONG BUY",
      confidence: 96,
      entry_price: 285.00,
      stop_loss: 233.70,
      target_1: 377.34,
      target_2: 448.00,
      strategy: "Monthly Tuesday High Beta Scalp",
      rationale: "CPR breakout with heavy put writing at 62,500 PE + Institutional banking sector momentum.",
      category: "options buy"
    },
    {
      symbol: "RELIANCE",
      base_symbol: "RELIANCE",
      instrument_type: "EQUITY",
      side: "BUY",
      verdict: "ACCUMULATE",
      confidence: 94,
      entry_price: 1350.00,
      stop_loss: 1330.00,
      target_1: 1386.00,
      target_2: 1420.00,
      strategy: "1h Horizontal Range Breakout",
      rationale: "Multi-day resistance breakout with 2.4x institutional delivery volume and RSI bullish divergence.",
      category: "buy equities"
    },
    {
      symbol: "TCS",
      base_symbol: "TCS",
      instrument_type: "EQUITY",
      side: "HOLD",
      verdict: "HOLD",
      confidence: 88,
      entry_price: 4150.00,
      stop_loss: 4120.00,
      target_1: 4195.00,
      target_2: 4240.00,
      strategy: "50 EMA Consolidation Range",
      rationale: "Stock is compressing between 50 EMA and 200 EMA. Avoid fresh entries until ₹4,195 is breached with volume.",
      category: "hold equities"
    },
    {
      symbol: "AXISBANK",
      base_symbol: "AXISBANK",
      instrument_type: "EQUITY",
      side: "SELL",
      verdict: "SELL / SHORT",
      confidence: 98,
      entry_price: 1388.60,
      stop_loss: 1395.25,
      target_1: 1376.60,
      target_2: 1365.00,
      strategy: "9/21 EMA + VWAP Breakdown",
      rationale: "Confirmed 15m trend rejection at session VWAP + breakdown below ₹1,390 support. Downside target ₹1,376.",
      category: "sell equities"
    },
    {
      symbol: "INFY",
      base_symbol: "INFY",
      instrument_type: "EQUITY",
      side: "HOLD",
      verdict: "HOLD",
      confidence: 86,
      entry_price: 1880.00,
      stop_loss: 1850.00,
      target_1: 1910.00,
      target_2: 1945.00,
      strategy: "Demand Zone Retest",
      rationale: "Consolidating near horizontal demand base. Existing longs hold with trailing stop-loss at ₹1,850.",
      category: "hold equities"
    }
  ];

  let currentCategory = "all";
  let searchQuery = "";

  async function init() {
    renderResearchCards();
    renderScannerTable();
    await fetchLiveScans();
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
    renderResearchCards();
    renderScannerTable();
  }

  function getFilteredSignals() {
    return allSignals.filter(s => {
      const matchesCat = (currentCategory === "all") || (s.category && s.category.includes(currentCategory));
      const matchesSearch = !searchQuery || 
        s.symbol.toLowerCase().includes(searchQuery) || 
        s.base_symbol.toLowerCase().includes(searchQuery) ||
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
          <div>No active signals matching "${searchQuery || currentCategory}".</div>
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

      return `
        <div class="fg-signal-card" data-cat="${sig.category}">
          <div class="fg-sc-top">
            <div>
              <div class="fg-sc-sym">${sig.symbol}</div>
              <div class="fg-sc-sub">${sig.strategy}</div>
            </div>
            <span class="fg-verdict-badge ${badgeClass}"><i class="fa-solid ${icon}"></i> ${sig.verdict}</span>
          </div>

          <div style="display:flex;justify-content:space-between;align-items:center;margin:6px 0;font-size:11px;font-weight:700;">
            <span style="color:var(--text-dim);">AI Confidence:</span>
            <span class="${isBuy ? 'up' : (isHold ? '' : 'down')}" style="font-weight:800;color:${isHold ? 'var(--accent-gold)' : ''}">
              <i class="fa-solid fa-shield-check"></i> ${sig.confidence}% Score
            </span>
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
            <strong>Institutional Thesis:</strong> ${sig.rationale}
          </div>

          ${isHold ? `
            <button type="button" class="btn btn-sm btn-outline" style="width:100%;font-weight:700;" onclick="StockScannerController.showWatchlistToast('${sig.symbol}')">
              <i class="fa-solid fa-eye"></i> Add to Active Watchlist
            </button>
          ` : `
            <button type="button" class="opp-btn-action" onclick="StockScannerController.executeQuickTrade('${sig.symbol}', '${sig.side}', ${sig.entry_price}, ${sig.stop_loss}, ${sig.target_1})">
              <i class="fa-solid fa-bolt"></i> 1-Click Paper Trade
            </button>
          `}
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
      const colorClass = isBuy ? "up" : (isHold ? "text-muted" : "down");
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

  async function fetchLiveScans() {
    try {
      const data = await FinGrowwAPI.getSessionScan();
      if (data && Array.isArray(data.scanned_signals) && data.scanned_signals.length > 0) {
        const liveItems = data.scanned_signals.slice(0, 10).map(s => {
          const side = (s.side || "BUY").toUpperCase();
          const isBuy = side === "BUY";
          return {
            symbol: s.symbol,
            base_symbol: s.base_symbol || s.symbol,
            instrument_type: s.instrument_type || "EQUITY",
            side: side,
            verdict: isBuy ? "STRONG BUY" : "SELL / SHORT",
            confidence: s.confidence_score || 95,
            entry_price: Number(s.entry_price) || 100,
            stop_loss: Number(s.stop_loss) || 95,
            target_1: Number(s.target_price || (s.entry_price * 1.05)),
            target_2: Number(s.target_price ? s.target_price * 1.03 : (s.entry_price * 1.09)),
            strategy: s.strategy || "Smart Money Confluence",
            rationale: s.rationale || "Algorithmic momentum and VWAP breakout alignment.",
            category: isBuy ? "buy equities" : "sell equities"
          };
        });

        // Merge keeping options on top
        allSignals = [...allSignals.slice(0, 2), ...liveItems];
        renderResearchCards();
        renderScannerTable();
      }
    } catch(e) {}
  }

  async function executeQuickTrade(sym, side, entry, sl, t1) {
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
      const res = await FinGrowwAPI.executePaperOrder({
        symbol: sym,
        signal_type: side,
        entry_price: entry,
        stop_loss: sl,
        target_1: t1,
        user_name: "Akshay"
      });
      if (descEl && res && res.ok) {
        descEl.innerHTML = `<strong>Live Server Synced!</strong> 1 Lot of ${sym} executed in your active AI Paper Trading account.`;
      }
    } catch (e) {}

    if (modal) modal.classList.add("active");
  }

  function showWatchlistToast(sym) {
    if (typeof showToast === "function") {
      showToast(sym, "HOLD ALERT: Added to active watchlist", 0);
    }
  }

  return {
    init,
    filterCategory,
    onSearchInput,
    executeQuickTrade,
    showWatchlistToast
  };
})();
