/**
 * FinGroww Market Overview & Outlook Controller
 * Powers Section 3 (Live Market Overview) and Section 4 (Today's Market Outlook)
 */
const MarketOverviewController = (() => {
  // Reliable default spot reference for off-market or initial load
  const DEFAULT_INDICES = [
    { symbol: "NIFTY 50", name: "NIFTY 50", ltp: 25350.00, change: 172.50, changePct: 0.68, high: 25410.00, low: 25280.00, expiry: "Weekly Tue" },
    { symbol: "BANK NIFTY", name: "BANK NIFTY", ltp: 62585.35, change: 695.10, changePct: 1.12, high: 62790.00, low: 62140.00, expiry: "Monthly Tue" },
    { symbol: "SENSEX", name: "SENSEX", ltp: 82450.00, change: 442.20, changePct: 0.54, high: 82600.00, low: 82180.00, expiry: "Weekly Thu" },
    { symbol: "FINNIFTY", name: "FINNIFTY", ltp: 28150.00, change: 235.40, changePct: 0.84, high: 28240.00, low: 28010.00, expiry: "Monthly Tue" },
    { symbol: "MIDCPNIFTY", name: "MIDCPNIFTY", ltp: 13800.00, change: 184.20, changePct: 1.35, high: 13860.00, low: 13690.00, expiry: "Monthly Tue" }
  ];

  async function init() {
    renderIndexCards(DEFAULT_INDICES);
    await syncLiveMarketData();
    setInterval(syncLiveMarketData, 20000); // 20s live polling
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

  async function syncLiveMarketData() {
    try {
      const tickerData = await FinGrowwAPI.getMarketTicker();
      if (tickerData && Array.isArray(tickerData.rows) && tickerData.rows.length > 0) {
        const updated = DEFAULT_INDICES.map(def => {
          const matched = tickerData.rows.find(r => r.symbol === def.symbol || r.name === def.name);
          if (matched && matched.lastPrice) {
            const ltp = Number(matched.lastPrice);
            const pChange = Number(matched.pChange || matched.changePct || def.changePct);
            return {
              ...def,
              ltp: ltp,
              changePct: pChange,
              high: Number(matched.dayHigh || matched.high || def.high),
              low: Number(matched.dayLow || matched.low || def.low)
            };
          }
          return def;
        });
        renderIndexCards(updated);
      }
    } catch (e) {
      // Retain graceful fallback
    }
  }

  return { init, syncLiveMarketData };
})();
