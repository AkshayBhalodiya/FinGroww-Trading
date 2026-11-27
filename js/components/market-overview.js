/**
 * FinGroww Market Overview & Outlook Controller
 * Powers Section 3 (Live Market Overview), Section 4 (Today's Market Outlook),
 * and the Top Global Live Ticker Ribbon.
 */
const MarketOverviewController = (() => {
  // Current institutional spot reference baseline
  const DEFAULT_INDICES = [
    { symbol: "NIFTY 50", name: "NIFTY 50", ltp: 25819.25, change: 468.75, changePct: 1.85, high: 25865.00, low: 25350.00, expiry: "Weekly Tue" },
    { symbol: "BANK NIFTY", name: "BANK NIFTY", ltp: 63703.25, change: 1118.00, changePct: 1.79, high: 63850.00, low: 62580.00, expiry: "Monthly Tue" },
    { symbol: "SENSEX", name: "SENSEX", ltp: 83938.28, change: 1488.28, changePct: 1.82, high: 84100.00, low: 82450.00, expiry: "Weekly Thu" },
    { symbol: "FINNIFTY", name: "FINNIFTY", ltp: 28764.95, change: 614.95, changePct: 2.17, high: 28850.00, low: 28150.00, expiry: "Monthly Tue" },
    { symbol: "MIDCPNIFTY", name: "MIDCPNIFTY", ltp: 13800.00, change: 184.20, changePct: 1.35, high: 13860.00, low: 13690.00, expiry: "Monthly Tue" }
  ];

  async function init() {
    renderIndexCards(DEFAULT_INDICES);
    await syncLiveMarketData();
    await syncInstitutionalOutlook();
    
    // Live interval: 15s refresh
    setInterval(async () => {
      await syncLiveMarketData();
      await syncInstitutionalOutlook();
    }, 15000);
    
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        syncLiveMarketData();
        syncInstitutionalOutlook();
      }
    });
  }

  function renderIndexCards(indices) {
    const container = document.getElementById("marketOverviewContainer");
    if (!container) return;

    container.innerHTML = indices.map(idx => {
      const isUp = (idx.changePct >= 0);
      const sign = isUp ? "+" : "";
      const colorClass = isUp ? "up" : "down";
      const icon = isUp ? "fa-arrow-trend-up" : "fa-arrow-trend-down";
      
      const rangeSpan = Math.max(1, idx.high - idx.low);
      const posPct = Math.min(100, Math.max(0, ((idx.ltp - idx.low) / rangeSpan) * 100));

      return `
        <div class="fg-index-card" data-symbol="${idx.symbol}">
          <div class="fg-ic-header">
            <span class="fg-ic-name">${idx.name}</span>
            <span class="fg-ic-change ${colorClass}">
              <i class="fa-solid ${icon}"></i> ${sign}${Number(idx.changePct).toFixed(2)}%
            </span>
          </div>
          <div class="fg-ic-ltp">₹${Number(idx.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          <div class="fg-ic-range-bar">
            <div class="fg-ic-range-fill" style="width:${posPct.toFixed(1)}%;background:${isUp ? 'var(--accent-green)' : 'var(--accent-red)'}"></div>
          </div>
          <div class="fg-ic-meta">
            <span>L: ₹${Number(idx.low).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
            <span style="color:var(--text-muted);">${idx.expiry}</span>
            <span>H: ₹${Number(idx.high).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
          </div>
        </div>
      `;
    }).join("");
  }

  function updateGlobalTickerTrack(rows) {
    const track = document.getElementById("globalTickerTrack");
    if (!track || !Array.isArray(rows) || rows.length === 0) return;

    const itemsHtml = rows.map(r => {
      const sym = r.symbol || r.name;
      const ltp = Number(r.lastPrice || r.ltp || 0);
      const pchg = Number(r.pChange ?? r.changePct ?? 0);
      const isUp = pchg >= 0;
      const sign = isUp ? "+" : "";
      const colorClass = isUp ? "up" : "down";
      const icon = isUp ? "▲" : "▼";
      const prefix = (sym.includes("NIFTY") || sym.includes("SENSEX")) ? "" : "₹";

      return `
        <div class="t-item">
          <span class="t-val">${sym}</span> 
          ${prefix}${ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 
          <span class="${colorClass}">${icon} ${sign}${pchg.toFixed(2)}%</span>
        </div>
      `;
    }).join("");

    const specialItems = `
      <div class="t-item"><span class="t-val"><i class="fa-solid fa-robot" style="color:var(--accent-green)"></i> AI PAPER TRADING</span> FREE ₹1,00,000 CREDITS ACTIVE</div>
      <div class="t-item"><span class="t-val"><i class="fa-solid fa-bolt" style="color:var(--accent-gold)"></i> 15M GOLDEN ZONE</span> NIFTY 25,800 CE (ACTIVE)</div>
    `;

    // Duplicate track for seamless infinite scroll
    track.innerHTML = itemsHtml + specialItems + itemsHtml + specialItems;
  }

  async function syncLiveMarketData() {
    if (!localStorage.getItem("fg_access_token")) {
      return;
    }
    try {
      const tickerData = await FinGrowwAPI.getMarketTicker();
      let rows = tickerData?.rows || tickerData?.data || [];
      
      if (Array.isArray(rows) && rows.length > 0) {
        // If SENSEX is not in rows (some cloud instances), fetch it separately
        const hasSensex = rows.some(r => (r.symbol || r.name || "").includes("SENSEX"));
        if (!hasSensex) {
          try {
            const sensexQuote = await FinGrowwAPI.getQuote("SENSEX");
            if (sensexQuote && (sensexQuote.lastPrice || sensexQuote.ltp)) {
              rows.push({
                symbol: "SENSEX",
                name: "SENSEX",
                lastPrice: Number(sensexQuote.lastPrice || sensexQuote.ltp),
                ltp: Number(sensexQuote.lastPrice || sensexQuote.ltp),
                pChange: Number(sensexQuote.pChange || 0),
                changePct: Number(sensexQuote.pChange || 0),
                dayHigh: Number(sensexQuote.dayHigh || (sensexQuote.lastPrice * 1.006)),
                dayLow: Number(sensexQuote.dayLow || (sensexQuote.lastPrice * 0.994))
              });
            }
          } catch(e) {}
        }

        const updated = DEFAULT_INDICES.map(def => {
          const defClean = def.symbol.replace(/\s+/g, "").toUpperCase();
          const matched = rows.find(r => {
            const sym = (r.symbol || r.name || "").replace(/\s+/g, "").toUpperCase();
            return sym === defClean || sym.includes(defClean) || defClean.includes(sym);
          });
          if (matched && (matched.lastPrice || matched.ltp)) {
            const ltp = Number(matched.lastPrice || matched.ltp);
            const pChange = Number(matched.pChange ?? matched.changePct ?? def.changePct);
            const high = Number(matched.dayHigh || matched.high || (ltp * 1.006));
            const low = Number(matched.dayLow || matched.low || (ltp * 0.994));
            return {
              ...def,
              ltp: ltp,
              changePct: pChange,
              high: high,
              low: low
            };
          }
          return def;
        });

        renderIndexCards(updated);
        updateGlobalTickerTrack(rows);
        updateSectorHeatmap(rows);
      }
    } catch (e) {
      // Retain baseline cards gracefully
    }
  }

  async function syncInstitutionalOutlook() {
    if (!localStorage.getItem("fg_access_token")) {
      return;
    }
    try {
      const inst = await FinGrowwAPI.getInstitutional();
      if (!inst) return;

      const fiiEl = document.getElementById("outlookFiiNet");
      const diiEl = document.getElementById("outlookDiiNet");
      const biasEl = document.getElementById("outlookSentimentBias");
      const noteEl = document.getElementById("outlookSentimentNote");

      if (fiiEl && inst.fii_net_cash_inr_crores != null) {
        const val = Number(inst.fii_net_cash_inr_crores);
        fiiEl.textContent = `${val >= 0 ? '+' : ''}₹${Math.abs(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`;
        fiiEl.style.color = val >= 0 ? "var(--accent-green)" : "var(--accent-red)";
      }

      if (diiEl && inst.dii_net_cash_inr_crores != null) {
        const val = Number(inst.dii_net_cash_inr_crores);
        diiEl.textContent = `${val >= 0 ? '+' : ''}₹${Math.abs(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`;
        diiEl.style.color = val >= 0 ? "var(--accent-green)" : "var(--accent-red)";
      }

      if (biasEl && inst.sentiment) {
        biasEl.innerHTML = `<i class="fa-solid fa-arrow-trend-up"></i> ${inst.sentiment}`;
      }

      if (noteEl && inst.fii_index_futures_oi_long_pct) {
        noteEl.textContent = `Institutional accumulation: FII Index Futures Long OI at ${inst.fii_index_futures_oi_long_pct} with steady call writing absorption.`;
      }
    } catch (e) {}
  }

  function updateSectorHeatmap(rows) {
    const list = document.getElementById("outlookSectorList");
    if (!list || !Array.isArray(rows) || rows.length === 0) return;

    // Map representative stocks or indices to sectors
    const bankRow = rows.find(r => (r.symbol || "").includes("BANK NIFTY")) || rows.find(r => (r.symbol || "").includes("HDFCBANK"));
    const itRow = rows.find(r => (r.symbol || "").includes("TCS")) || rows.find(r => (r.symbol || "").includes("INFY"));
    const autoRow = rows.find(r => (r.symbol || "").includes("TATAMOTORS"));
    const energyRow = rows.find(r => (r.symbol || "").includes("RELIANCE"));
    const finRow = rows.find(r => (r.symbol || "").includes("FINNIFTY"));

    const sectors = [
      { name: "Nifty Bank", item: bankRow, fallback: 1.79 },
      { name: "Nifty IT", item: itRow, fallback: 2.37 },
      { name: "Nifty Energy", item: energyRow, fallback: 1.70 },
      { name: "Nifty Financials", item: finRow, fallback: 2.17 },
      { name: "Nifty Auto", item: autoRow, fallback: 1.45 }
    ];

    list.innerHTML = sectors.map(sec => {
      const pchg = sec.item ? Number(sec.item.pChange ?? sec.item.changePct ?? sec.fallback) : sec.fallback;
      const isUp = pchg >= 0;
      const colorClass = isUp ? "up font-bold" : "down font-bold";
      const icon = isUp ? "▲" : "▼";
      const sign = isUp ? "+" : "";

      return `
        <div class="fg-sector-row">
          <span style="font-weight:700;color:var(--text-main);">${sec.name}</span>
          <span class="${colorClass}">${sign}${pchg.toFixed(2)}% ${icon}</span>
        </div>
      `;
    }).join("");
  }

  return { init, syncLiveMarketData, syncInstitutionalOutlook };
})();
