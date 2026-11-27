/**
 * FinGroww Trading Journal, AI Trading Coach & Multi-Account Paper Manager (Phase 3)
 */
const JournalController = (() => {
  async function init() {
    if (!FinGrowwAuth.getAccessToken()) {
      window.location.href = "auth.html";
      return;
    }
    await Promise.all([loadCoachInsights(), loadJournals(), loadPaperAccounts()]);
    runConfluenceCheck();
  }

  function switchTab(tabId, btnEl) {
    document.querySelectorAll(".dash-tab-panel").forEach(p => p.classList.remove("active"));
    const target = document.getElementById("tab-" + tabId);
    if (target) target.classList.add("active");

    document.querySelectorAll(".dash-nav-btn").forEach(b => b.classList.remove("active"));
    if (btnEl) btnEl.classList.add("active");
  }

  async function loadCoachInsights() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/coach/insights");
      const scoreEl = document.getElementById("coachDisciplineScore");
      const statsEl = document.getElementById("coachStatsLine");
      const recsBox = document.getElementById("coachRecsList");
      const leakEl = document.getElementById("coachEmotionalLeak");

      if (scoreEl) {
        scoreEl.textContent = res.discipline_score !== null && res.discipline_score !== undefined
          ? `${res.discipline_score}/100`
          : "N/A";
      }
      if (statsEl) {
        const st = res.stats || {};
        statsEl.textContent = `Journal Entries: ${st.journal_entries || 0} • Rule Compliance: ${st.rule_compliance_pct !== null && st.rule_compliance_pct !== undefined ? st.rule_compliance_pct + '%' : 'N/A'} • Closed Trades: ${st.closed_trades || 0}`;
      }
      if (leakEl) {
        const leak = Number(res.emotional_leakage_inr || 0);
        leakEl.textContent = `${leak >= 0 ? '+' : '-'}₹${Math.abs(leak).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
        leakEl.className = leak < 0 ? "down mono font-bold" : "up mono font-bold";
      }
      if (recsBox) {
        recsBox.innerHTML = (res.recommendations || []).map(r => `
          <div style="display:flex;align-items:flex-start;gap:8px;padding:8px 10px;background:var(--bg-surface);border-left:3px solid var(--accent-purple);border-radius:0 6px 6px 0;font-size:12.5px;color:var(--text-muted);margin-bottom:8px;">
            <i class="fa-solid fa-robot" style="color:var(--accent-purple);margin-top:3px;"></i>
            <span>${r}</span>
          </div>
        `).join("");
      }
    } catch (err) {
      console.error("Coach insights error:", err);
    }
  }

  async function loadJournals() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/journal");
      const entries = res.entries || [];
      const container = document.getElementById("journalEntriesList");
      if (!container) return;

      if (!entries.length) {
        container.innerHTML = `<div class="dash-empty"><i class="fa-solid fa-book-open"></i><div>No journal entries logged yet. Record your first trade reflection on the left!</div></div>`;
        return;
      }

      container.innerHTML = entries.map(e => {
        const pnl = e.net_pnl !== null && e.net_pnl !== undefined ? Number(e.net_pnl) : null;
        const pnlBadge = pnl !== null
          ? `<span class="mono font-bold ${pnl >= 0 ? 'up' : 'down'}">${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)}</span>`
          : `<span style="color:var(--text-dim);font-size:11px;">Log Only</span>`;
        const tagsHtml = (e.mistake_tags || []).map(t => `<span class="fg-verdict-badge fg-verdict-sell" style="margin-right:4px;">${t}</span>`).join("");

        return `
          <div class="dash-panel" style="padding:14px 16px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:8px;">
              <div>
                <strong class="mono" style="font-size:14px;color:var(--text-main);">${e.symbol}</strong>
                <span class="fg-verdict-badge ${e.side === 'BUY' ? 'fg-verdict-buy' : 'fg-verdict-sell'}" style="margin-left:6px;">${e.side}</span>
                <span style="font-size:11px;color:var(--text-dim);margin-left:8px;">${e.timeframe} • ${e.setup_tag}</span>
              </div>
              <div style="display:flex;align-items:center;gap:10px;">
                ${pnlBadge}
                <button type="button" class="btn btn-sm btn-outline" style="padding:3px 8px;color:var(--accent-red);border-color:rgba(244,63,94,0.3);" onclick="JournalController.deleteEntry('${e.journal_id}')">
                  <i class="fa-solid fa-trash"></i>
                </button>
              </div>
            </div>
            <div style="font-size:11.5px;color:var(--text-muted);margin-bottom:6px;">
              Mood: <strong style="color:var(--text-main);text-transform:uppercase;">${e.mood}</strong> •
              Rules Followed: <strong class="${e.rules_followed ? 'up' : 'down'}">${e.rules_followed ? 'YES' : 'NO'}</strong>
            </div>
            ${tagsHtml ? `<div style="margin-bottom:8px;">${tagsHtml}</div>` : ''}
            ${e.notes ? `<p style="font-size:12.5px;color:var(--text-muted);margin:0 0 8px;line-height:1.5;">${e.notes}</p>` : ''}
            <div style="background:var(--bg-surface);border-left:3px solid var(--accent-blue);padding:8px 10px;border-radius:0 4px 4px 0;font-size:12px;color:var(--text-muted);">
              <strong style="color:var(--accent-blue);">AI Coach Feedback:</strong> ${e.ai_feedback}
            </div>
          </div>
        `;
      }).join("");
    } catch (err) {
      console.error("Journal load error:", err);
    }
  }

  async function submitJournal(e) {
    e.preventDefault();
    const checkedTags = Array.from(document.querySelectorAll("input[name='mistakeTag']:checked")).map(cb => cb.value);
    const pnlRaw = document.getElementById("jPnl").value.trim();

    try {
      await FinGrowwAuth.request("/api/v2/journal", {
        method: "POST",
        body: JSON.stringify({
          symbol: document.getElementById("jSymbol").value,
          side: document.getElementById("jSide").value,
          net_pnl: pnlRaw !== "" ? Number(pnlRaw) : null,
          timeframe: document.getElementById("jTimeframe").value,
          setup_tag: document.getElementById("jSetup").value,
          mood: document.getElementById("jMood").value,
          rules_followed: document.getElementById("jRules").checked,
          mistake_tags: checkedTags,
          notes: document.getElementById("jNotes").value,
        }),
      });
      document.getElementById("journalForm").reset();
      document.getElementById("jRules").checked = true;
      await Promise.all([loadJournals(), loadCoachInsights()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function deleteEntry(id) {
    try {
      await FinGrowwAuth.request(`/api/v2/journal/${id}`, { method: "DELETE" });
      await Promise.all([loadJournals(), loadCoachInsights()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadPaperAccounts() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/paper/accounts");
      const accounts = res.accounts || [];
      const grid = document.getElementById("paperAccountsGrid");
      if (!grid) return;

      grid.innerHTML = accounts.map(a => `
        <div class="dash-panel" style="padding:18px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <strong style="font-size:14.5px;color:var(--text-main);">${a.name}</strong>
            ${a.is_default ? '<span class="fg-sec-badge" style="margin-bottom:0;">PRIMARY</span>' : '<span style="font-size:11px;color:var(--text-dim);">SUB-ACCOUNT</span>'}
          </div>
          <div style="font-size:11.5px;color:var(--text-dim);margin-bottom:12px;">ID: ${a.account_id} • Style: ${a.trading_style}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;background:var(--bg-surface);padding:10px;border-radius:6px;margin-bottom:12px;">
            <div>
              <div style="font-size:10px;color:var(--text-dim);">Virtual Capital</div>
              <div class="mono font-bold" style="font-size:13.5px;">₹${Number(a.virtual_capital).toLocaleString("en-IN")}</div>
            </div>
            <div>
              <div style="font-size:10px;color:var(--text-dim);">Available Balance</div>
              <div class="mono font-bold up" style="font-size:13.5px;">₹${Number(a.available_balance).toLocaleString("en-IN")}</div>
            </div>
            <div>
              <div style="font-size:10px;color:var(--text-dim);">Realized P&L</div>
              <div class="mono font-bold ${Number(a.realized_pnl) >= 0 ? 'up' : 'down'}" style="font-size:13px;">₹${Number(a.realized_pnl || 0).toFixed(2)}</div>
            </div>
            <div>
              <div style="font-size:10px;color:var(--text-dim);">Closed Trades</div>
              <div class="mono font-bold" style="font-size:13px;">${a.total_trades || 0}</div>
            </div>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button type="button" class="btn btn-sm btn-outline" style="flex:1;font-size:11.5px;" onclick="JournalController.resetAccount('${a.account_id}')">
              <i class="fa-solid fa-rotate"></i> Reset
            </button>
            <button type="button" class="btn btn-sm btn-outline" style="flex:1;font-size:11.5px;" onclick="JournalController.downloadCsv('${a.account_id}')">
              <i class="fa-solid fa-download"></i> CSV
            </button>
            ${!a.is_default ? `<button type="button" class="btn btn-sm btn-outline" style="font-size:11.5px;color:var(--accent-red);border-color:rgba(244,63,94,0.3);" onclick="JournalController.archiveAccount('${a.account_id}')">Archive</button>` : ''}
          </div>
        </div>
      `).join("");
    } catch (err) {
      console.error("Accounts error:", err);
    }
  }

  async function createAccount(e) {
    e.preventDefault();
    const errBox = document.getElementById("accErrorBox");
    if (errBox) errBox.style.display = "none";
    try {
      await FinGrowwAuth.request("/api/v2/paper/accounts", {
        method: "POST",
        body: JSON.stringify({
          name: document.getElementById("accNameInput").value,
          virtual_capital: Number(document.getElementById("accCapInput").value),
          trading_style: document.getElementById("accStyleInput").value,
        }),
      });
      document.getElementById("accNameInput").value = "";
      await loadPaperAccounts();
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message;
        errBox.style.display = "block";
      } else {
        alert(err.message);
      }
    }
  }

  async function resetAccount(id) {
    if (!confirm("Reset this paper account? Open positions and trade ledger for this account will be cleared.")) return;
    try {
      await FinGrowwAuth.request(`/api/v2/paper/accounts/${id}/reset`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await loadPaperAccounts();
    } catch (err) {
      alert(err.message);
    }
  }

  async function archiveAccount(id) {
    try {
      await FinGrowwAuth.request(`/api/v2/paper/accounts/${id}/archive`, { method: "POST" });
      await loadPaperAccounts();
    } catch (err) {
      alert(err.message);
    }
  }

  async function downloadCsv(id) {
    try {
      const token = FinGrowwAuth.getAccessToken();
      const res = await fetch(`/api/v2/paper/accounts/${id}/export.csv`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `fingroww_${id}_trades.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err.message);
    }
  }

  async function runConfluenceCheck(e) {
    if (e) e.preventDefault();
    const sym = (document.getElementById("confSymInput")?.value || "NIFTY 50").trim();
    const outBox = document.getElementById("confluenceResultsBox");
    if (!outBox) return;
    outBox.innerHTML = `<div style="padding:20px;color:var(--text-muted);text-align:center;">Evaluating 1H Trend, 15M Primary & 5M Entry candles for ${sym}...</div>`;

    try {
      const res = await FinGrowwAuth.request(`/api/v2/intelligence/confluence?symbol=${encodeURIComponent(sym)}`);
      const tfs = res.timeframes || {};
      const cards = [tfs["1h"], tfs["15m"], tfs["5m"]].filter(Boolean);

      outBox.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:10px;background:var(--bg-surface);padding:12px 16px;border-radius:8px;border:1px solid var(--border-card);">
          <div>
            <strong class="mono" style="font-size:15px;">${res.symbol}</strong>
            <span style="font-size:12px;color:var(--text-dim);margin-left:10px;">Data Verified: ${res.data_verified ? 'YES' : 'INSUFFICIENT'}</span>
          </div>
          <div>
            <span class="fg-sec-badge" style="margin-bottom:0;">Verdict: ${res.verdict} (${res.alignment_score})</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">
          ${cards.map(c => `
            <div class="dash-panel" style="padding:14px;">
              <div style="font-size:10.5px;color:var(--text-dim);font-weight:800;">${c.timeframe}</div>
              <div class="${c.bias === 'BULLISH' ? 'up' : (c.bias === 'BEARISH' ? 'down' : '')}" style="font-size:1.15rem;font-weight:900;margin:4px 0;">${c.bias}</div>
              <div style="font-size:12px;color:var(--text-muted);font-family:var(--font-mono);">
                EMA9: ${c.ema9 ?? 'N/A'} • EMA21: ${c.ema21 ?? 'N/A'}<br>
                Close: ${c.last_close ?? 'N/A'} (${c.candle_count} candles)
              </div>
            </div>
          `).join("")}
        </div>
      `;
    } catch (err) {
      outBox.innerHTML = `<div class="dash-empty">${err.message}</div>`;
    }
  }

  return {
    init,
    switchTab,
    submitJournal,
    deleteEntry,
    createAccount,
    resetAccount,
    archiveAccount,
    downloadCsv,
    runConfluenceCheck,
  };
})();

document.addEventListener("DOMContentLoaded", JournalController.init);
