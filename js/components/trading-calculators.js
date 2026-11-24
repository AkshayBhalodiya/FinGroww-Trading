/**
 * FinGroww Trading Calculators Controller
 * Powers Section 9 (Trading Tools & Calculators)
 */
const TradingCalculatorsController = (() => {
  let riskPct = 2.0;

  function init() {
    bindEvents();
    recalculateCompounding();
  }

  function bindEvents() {
    const slider = document.getElementById("calcCapInput");
    if (slider) {
      slider.addEventListener("input", recalculateCompounding);
    }
  }

  function setRiskPercentage(pct, btnEl) {
    riskPct = Number(pct);
    document.querySelectorAll(".fg-risk-btn").forEach(b => b.classList.remove("active"));
    if (btnEl) btnEl.classList.add("active");
    recalculateCompounding();
  }

  function recalculateCompounding() {
    const slider = document.getElementById("calcCapInput");
    const capValEl = document.getElementById("calcCapVal");
    const profitEl = document.getElementById("calcOutProfit");
    const subEl = document.getElementById("calcOutSub");

    const cap = parseFloat(slider ? slider.value : 100000) || 100000;
    if (capValEl) capValEl.textContent = "₹" + cap.toLocaleString("en-IN");

    const riskAmt = (cap * riskPct) / 100;
    const winAmt = riskAmt * 3.2; // 1:3.2 Risk Reward

    // 20 trades model (16 wins, 4 losses => 80% disciplined win-rate)
    const totalProfit = Math.round((16 * winAmt) - (4 * riskAmt));

    if (profitEl) profitEl.textContent = "+₹" + totalProfit.toLocaleString("en-IN");
    if (subEl) subEl.textContent = `Max Risk / Trade: ₹${Math.round(riskAmt).toLocaleString("en-IN")} (${riskPct}%) | 1:3.2 Risk-to-Reward Ratio`;

    renderSvgEquityCurve(cap, riskAmt, winAmt);
  }

  function renderSvgEquityCurve(startCap, riskAmt, winAmt) {
    const svg = document.getElementById("dynamicEquityCurve");
    if (!svg) return;

    const outcomes = [1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1];
    let currentBalance = startCap;
    const points = [[0, startCap]];

    outcomes.forEach((win, idx) => {
      if (win) {
        currentBalance += winAmt;
      } else {
        currentBalance -= riskAmt;
      }
      points.push([idx + 1, currentBalance]);
    });

    const minBal = startCap * 0.95;
    const maxBal = currentBalance * 1.05;
    const width = 300;
    const height = 80;

    const polyPoints = points.map(([x, y]) => {
      const px = (x / 20) * (width - 20) + 10;
      const py = height - 10 - ((y - minBal) / (maxBal - minBal)) * (height - 20);
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    }).join(" ");

    const firstPx = 10;
    const lastPx = width - 10;
    const areaPoints = `${firstPx},${height - 6} ${polyPoints} ${lastPx},${height - 6}`;

    svg.innerHTML = `
      <defs>
        <linearGradient id="fgEqGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#10b981" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="#10b981" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <polygon points="${areaPoints}" fill="url(#fgEqGrad)" />
      <polyline points="${polyPoints}" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="${lastPx}" cy="${(height - 10 - ((points[points.length-1][1] - minBal) / (maxBal - minBal)) * (height - 20)).toFixed(1)}" r="4" fill="#38bdf8" />
      <text x="12" y="18" fill="#94a3b8" font-size="9" font-family="monospace">Start: ₹${Math.round(startCap/1000)}k</text>
      <text x="${width - 70}" y="18" fill="#10b981" font-weight="700" font-size="9" font-family="monospace">End: ₹${Math.round(currentBalance/1000)}k</text>
    `;
  }

  return { init, setRiskPercentage, recalculateCompounding };
})();
