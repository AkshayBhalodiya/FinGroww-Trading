/**
 * FinGroww 4-Agent Algo Swarm Controller
 * Powers Section 7 (AI Algo Trading - 4 Agents) & Broker Status Badges
 */
const AlgoSwarmController = (() => {
  const AGENTS = [
    {
      id: "agent-1",
      name: "Agent 1: Trend Hunter",
      role: "Macro Confluence & Golden Zone",
      desc: "Scans 15m and 1h charts for 0.618 Fibonacci pullbacks, institutional VWAP accumulation, and Supertrend alignment to validate multi-timeframe direction.",
      status: "ONLINE",
      badge: "High-Probability Filter",
      color: "var(--accent-green)",
      icon: "fa-compass"
    },
    {
      id: "agent-2",
      name: "Agent 2: Momentum Scalper",
      role: "Volume Surges & Breakouts",
      desc: "Monitors real-time Open Interest (OI) unwinding, 3x volume spikes, and options volatility to capture high-velocity 1-3 minute intraday scalps.",
      status: "ACTIVE",
      badge: "Sub-Second Sniper",
      color: "var(--accent-gold)",
      icon: "fa-bolt"
    },
    {
      id: "agent-3",
      name: "Agent 3: Execution Sniper",
      role: "Order Routing & Position Sizing",
      desc: "Computes mathematically balanced lot sizes and routes orders across Zerodha, Angel One, Upstox, and Dhan gateways with slippage protection.",
      status: "ARMED",
      badge: "Multi-Broker Gateway",
      color: "var(--accent-blue)",
      icon: "fa-crosshairs"
    },
    {
      id: "agent-4",
      name: "Agent 4: Risk Sentinel",
      role: "Capital Preservation Guard",
      desc: "Enforces continuous trailing stop-loss management and an automated 5% daily drawdown circuit breaker to eliminate emotional revenge trading.",
      status: "GUARDING",
      badge: "5% Circuit Breaker",
      color: "var(--accent-purple)",
      icon: "fa-shield-halved"
    }
  ];

  async function init() {
    renderAgentCards();
    await checkSwarmTelemetry();
  }

  function renderAgentCards() {
    const container = document.getElementById("algoSwarmCardsContainer");
    if (!container) return;

    container.innerHTML = AGENTS.map(agent => `
      <div class="fg-agent-card" id="${agent.id}">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
          <div class="fg-agent-avatar" style="background:${agent.color}22;color:${agent.color};">
            <i class="fa-solid ${agent.icon}"></i>
          </div>
          <span style="font-size:10px;padding:2px 8px;border-radius:4px;background:rgba(16,185,129,0.15);color:var(--accent-green);font-weight:800;">
            <i class="fa-solid fa-circle-dot"></i> ${agent.status}
          </span>
        </div>
        <div class="fg-agent-name">${agent.name}</div>
        <div class="fg-agent-role">${agent.role}</div>
        <p class="fg-agent-desc">${agent.desc}</p>
        <div style="padding-top:12px;border-top:1px solid var(--border-subtle);display:flex;align-items:center;justify-content:space-between;">
          <span style="font-size:11px;font-weight:700;color:${agent.color};">${agent.badge}</span>
          <span style="font-size:11px;color:var(--text-dim);font-family:var(--font-mono);">0.04s latency</span>
        </div>
      </div>
    `).join("");
  }

  async function checkSwarmTelemetry() {
    try {
      const swarmStatus = await FinGrowwAPI.getSwarmStatus();
      if (swarmStatus && swarmStatus.ok) {
        const badgeEl = document.getElementById("swarmTelemetryBadge");
        if (badgeEl) {
          badgeEl.textContent = `All 4 Agents Operational • ${swarmStatus.active_positions || 0} Open Swarm Positions`;
        }
      }
    } catch (e) {}
  }

  return { init, checkSwarmTelemetry };
})();
