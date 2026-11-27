/**
 * FinGroww Personalised User Dashboard Controller (Phase 2)
 */
const DashboardController = (() => {
  let overviewData = null;
  let activeTab = "overview";

  async function init() {
    if (!FinGrowwAuth.getAccessToken()) {
      window.location.href = "auth.html";
      return;
    }
    await Promise.all([loadProfile(), loadOverview(), loadWatchlists(), loadSavedSignals(), loadNotifications(), loadSupportTickets(), loadAcademy(), loadBilling()]);
  }

  function switchTab(tabId, btnEl) {
    activeTab = tabId;
    document.querySelectorAll(".dash-tab-panel").forEach(p => p.classList.remove("active"));
    const target = document.getElementById("tab-" + tabId);
    if (target) target.classList.add("active");

    document.querySelectorAll(".dash-nav-btn").forEach(b => b.classList.remove("active"));
    if (btnEl) {
      btnEl.classList.add("active");
    } else {
      document.querySelectorAll(`.dash-nav-btn[data-tab="${tabId}"]`).forEach(b => b.classList.add("active"));
    }
  }

  async function loadProfile() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/users/me");
      const u = res.user;
      const prefs = res.preferences || {};
      FinGrowwAuth.saveSession({ user: u });

      const nameEl = document.getElementById("dashUserName");
      const metaEl = document.getElementById("dashUserMeta");
      const planBadge = document.getElementById("dashPlanBadge");
      if (nameEl) nameEl.textContent = `Welcome back, ${u.full_name}`;
      if (metaEl) metaEl.textContent = `@${u.username} • ${u.email} • Role: ${u.role.toUpperCase()}`;
      if (planBadge) {
        const isPro = u.subscription_plan !== "free";
        planBadge.textContent = isPro ? "PRO ALGO SWARM" : "FREE PAPER PLAN";
        planBadge.style.borderColor = isPro ? "var(--accent-green)" : "var(--accent-blue)";
        planBadge.style.color = isPro ? "var(--accent-green)" : "var(--accent-blue)";
      }

      // Populate preferences form
      const setVal = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined && val !== null) el.value = val; };
      setVal("prefExp", u.experience_level);
      setVal("prefStyle", u.trading_style);
      setVal("prefTf", u.preferred_timeframe);
      setVal("prefRisk", u.risk_profile);
      setVal("prefMaxLoss", prefs.daily_loss_limit_pct || 5.0);
    } catch (err) {
      if (String(err.message).toLowerCase().includes("unauthorized") || String(err.message).includes("401")) {
        FinGrowwAuth.clearSession();
        window.location.href = "auth.html";
      }
    }
  }

  async function loadOverview() {
    try {
      const data = await FinGrowwAuth.request("/api/v2/dashboard/overview");
      overviewData = data;
      const s = data.summary || {};

      document.getElementById("kpiVirtualCap").textContent = formatInr(s.virtual_capital);
      document.getElementById("kpiAvailBal").textContent = formatInr(s.available_balance);
      document.getElementById("kpiNetEquity").textContent = `Net Equity: ${formatInr(s.net_equity)}`;

      const totalPnl = (s.realized_pnl || 0) + (s.unrealized_pnl || 0);
      const pnlEl = document.getElementById("kpiTotalPnl");
      pnlEl.textContent = `${totalPnl >= 0 ? "+" : ""}${formatInr(totalPnl)}`;
      pnlEl.className = "dk-val " + (totalPnl >= 0 ? "up" : "down");
      document.getElementById("kpiPnlSub").textContent = `Realized: ${formatInr(s.realized_pnl)} | Unrealized: ${formatInr(s.unrealized_pnl)}`;

      document.getElementById("kpiWinRate").textContent = `${Number(s.win_rate_pct || 0).toFixed(1)}%`;
      document.getElementById("kpiMetricsSub").textContent = `Profit Factor: ${s.profit_factor || 0} • Max DD: ${s.max_drawdown_pct || 0}% (${s.total_trades || 0} trades)`;

      // Update sidebar badges
      const counts = data.counts || {};
      const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      setTxt("badgePosCount", (data.active_positions || []).length);
      setTxt("badgeWlCount", counts.watchlists_items || 0);
      setTxt("badgeSigCount", counts.saved_signals || 0);
      setTxt("badgeNotifCount", counts.unread_notifications || 0);

      renderEquityCurve(data.equity_curve || []);
      renderPositions(data.active_positions || []);
      renderRecentTrades(data.recent_trades || []);
    } catch (err) {
      console.error("Dashboard overview load error:", err);
    }
  }

  function formatInr(val) {
    const num = Number(val || 0);
    const sign = num < 0 ? "-" : "";
    return `${sign}₹${Math.abs(num).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function renderEquityCurve(points) {
    const box = document.getElementById("dashEquityCurveWrap");
    if (!box) return;
    if (!points || points.length <= 1) {
      box.innerHTML = `
        <div class="dash-empty">
          <i class="fa-solid fa-chart-area"></i>
          <div>No closed paper trades recorded yet.</div>
          <div style="margin-top:8px;"><a href="ai-auto-paper-trading.html" class="btn btn-sm btn-launch">Place Your First Paper Trade →</a></div>
        </div>
      `;
      return;
    }

    const w = 620, h = 190, pad = 20;
    const equities = points.map(p => Number(p.equity || 0));
    const minVal = Math.min(...equities);
    const maxVal = Math.max(...equities);
    const range = maxVal - minVal || 1;

    const coords = points.map((p, idx) => {
      const x = pad + (idx / (points.length - 1)) * (w - pad * 2);
      const y = h - pad - ((Number(p.equity) - minVal) / range) * (h - pad * 2);
      return { x: x.toFixed(1), y: y.toFixed(1), ...p };
    });

    const pathD = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x} ${c.y}`).join(" ");
    const areaD = `${pathD} L ${coords[coords.length - 1].x} ${h - pad} L ${coords[0].x} ${h - pad} Z`;
    const isUp = equities[equities.length - 1] >= equities[0];
    const stroke = isUp ? "#10b981" : "#f43f5e";
    const fill = isUp ? "rgba(16,185,129,0.16)" : "rgba(244,63,94,0.16)";

    box.innerHTML = `
      <svg viewBox="0 0 ${w} ${h}" style="width:100%;height:190px;display:block;">
        <path d="${areaD}" fill="${fill}"></path>
        <path d="${pathD}" fill="none" stroke="${stroke}" stroke-width="2.5" stroke-linejoin="round"></path>
        ${coords.map(c => `<circle cx="${c.x}" cy="${c.y}" r="3.5" fill="${stroke}"><title>${c.label}: ${formatInr(c.equity)}</title></circle>`).join("")}
      </svg>
    `;
  }

  function renderPositions(positions) {
    const tbody = document.getElementById("dashPositionsBody");
    if (!tbody) return;
    if (!positions.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-dim);">No open positions in your virtual portfolio.</td></tr>`;
      return;
    }
    tbody.innerHTML = positions.map(p => {
      const pnl = Number(p.unrealized_pnl || 0);
      return `
        <tr>
          <td><strong class="mono">${p.symbol}</strong></td>
          <td class="td-center"><span class="fg-verdict-badge ${p.side === 'BUY' ? 'fg-verdict-buy' : 'fg-verdict-sell'}">${p.side}</span></td>
          <td class="td-right mono">${p.quantity}</td>
          <td class="td-right mono">₹${Number(p.entry_price || 0).toFixed(2)}</td>
          <td class="td-right mono">₹${Number(p.current_price || p.entry_price || 0).toFixed(2)}</td>
          <td class="td-right mono font-bold ${pnl >= 0 ? 'up' : 'down'}">${pnl >= 0 ? '+' : ''}${formatInr(pnl)}</td>
        </tr>
      `;
    }).join("");
  }

  function renderRecentTrades(trades) {
    const list = document.getElementById("dashRecentTradesList");
    if (!list) return;
    if (!trades.length) {
      list.innerHTML = `<div class="dash-empty"><i class="fa-solid fa-receipt"></i><div>No closed trades yet.</div></div>`;
      return;
    }
    list.innerHTML = trades.slice(0, 6).map(t => {
      const pnl = Number(t.net_pnl !== undefined ? t.net_pnl : (t.pnl || 0));
      return `
        <div class="session-item" style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:6px;margin-bottom:8px;">
          <div>
            <strong class="mono" style="color:var(--text-main);font-size:12.5px;">${t.symbol}</strong>
            <div style="font-size:11px;color:var(--text-dim);">${t.side || 'BUY'} • ${t.exit_reason || 'CLOSED'}</div>
          </div>
          <div class="mono font-bold ${pnl >= 0 ? 'up' : 'down'}" style="font-size:13px;">
            ${pnl >= 0 ? '+' : ''}${formatInr(pnl)}
          </div>
        </div>
      `;
    }).join("");
  }

  async function loadWatchlists() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/watchlists");
      const lists = res.watchlists || [];
      const items = lists[0] ? (lists[0].items || []) : [];
      const tbody = document.getElementById("dashWatchlistBody");
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-dim);">Watchlist is empty. Add any NSE stock or index above!</td></tr>`;
        return;
      }
      tbody.innerHTML = items.map(it => {
        const chg = Number(it.pChange || 0);
        return `
          <tr>
            <td><strong class="mono">${it.symbol}</strong></td>
            <td class="td-right mono">${it.ltp ? '₹' + Number(it.ltp).toFixed(2) : '<span style="color:var(--text-dim)">Live on Market</span>'}</td>
            <td class="td-right mono ${chg >= 0 ? 'up' : 'down'}">${it.ltp ? ((chg >= 0 ? '+' : '') + chg.toFixed(2) + '%') : '-'}</td>
            <td class="td-right mono" style="color:var(--accent-gold);">${it.alert_above ? '≥ ₹' + Number(it.alert_above).toFixed(2) : (it.alert_below ? '≤ ₹' + Number(it.alert_below).toFixed(2) : 'None')}</td>
            <td class="td-center">
              <button type="button" class="btn btn-sm btn-outline" style="padding:4px 8px;color:var(--accent-red);border-color:rgba(244,63,94,0.3);" onclick="DashboardController.removeWatchlistSymbol('${it.symbol}')">
                <i class="fa-solid fa-trash"></i>
              </button>
            </td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      console.error("Watchlist error:", err);
    }
  }

  async function addWatchlistSymbol(e) {
    e.preventDefault();
    const sym = document.getElementById("wlSymbolInput").value.trim().toUpperCase();
    const alertAboveRaw = document.getElementById("wlAlertInput").value.trim();
    if (!sym) return;
    try {
      await FinGrowwAuth.request("/api/v2/watchlists/items", {
        method: "POST",
        body: JSON.stringify({
          watchlist_name: "Primary Watchlist",
          symbol: sym,
          alert_above: alertAboveRaw ? Number(alertAboveRaw) : null,
        }),
      });
      document.getElementById("wlSymbolInput").value = "";
      document.getElementById("wlAlertInput").value = "";
      await Promise.all([loadWatchlists(), loadOverview()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function removeWatchlistSymbol(sym) {
    try {
      await FinGrowwAuth.request("/api/v2/watchlists/items", {
        method: "DELETE",
        body: JSON.stringify({ watchlist_name: "Primary Watchlist", symbol: sym }),
      });
      await Promise.all([loadWatchlists(), loadOverview()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadSavedSignals() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/signals/saved");
      const sigs = res.signals || [];
      const container = document.getElementById("dashSavedSignalsBox");
      if (!container) return;
      if (!sigs.length) {
        container.innerHTML = `<div class="dash-empty"><i class="fa-solid fa-bookmark"></i><div>No saved signals yet. Bookmark high-conviction setups from the AI Stock Scanner!</div></div>`;
        return;
      }
      container.innerHTML = sigs.map(s => `
        <div class="dash-panel" style="padding:14px 16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <strong class="mono" style="font-size:14px;">${s.symbol}</strong>
            <span class="fg-verdict-badge ${s.side === 'BUY' ? 'fg-verdict-buy' : 'fg-verdict-sell'}">${s.side}</span>
          </div>
          <div style="font-size:11.5px;color:var(--text-muted);margin-bottom:8px;">${s.strategy}</div>
          <div style="display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:12px;margin-bottom:10px;">
            <span>Entry: <strong>₹${Number(s.entry_price).toFixed(2)}</strong></span>
            <span class="down">SL: ₹${Number(s.stop_loss).toFixed(2)}</span>
            <span class="up">T1: ₹${Number(s.target_1).toFixed(2)}</span>
          </div>
          <button type="button" class="btn btn-sm btn-outline" style="width:100%;font-size:11px;" onclick="DashboardController.deleteSavedSignal('${s.saved_id}')">Remove Signal</button>
        </div>
      `).join("");
    } catch (_) {}
  }

  async function deleteSavedSignal(id) {
    try {
      await FinGrowwAuth.request(`/api/v2/signals/saved/${id}`, { method: "DELETE" });
      await Promise.all([loadSavedSignals(), loadOverview()]);
    } catch (_) {}
  }

  async function loadNotifications() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/notifications");
      const items = res.notifications || [];
      const box = document.getElementById("dashNotificationsList");
      if (!box) return;
      if (!items.length) {
        box.innerHTML = `<div class="dash-empty"><i class="fa-solid fa-bell-slash"></i><div>All caught up! No notifications.</div></div>`;
        return;
      }
      box.innerHTML = items.map(n => `
        <div class="dash-notif-item ${n.is_read ? '' : 'unread'}">
          <div>
            <div style="font-weight:800;font-size:13px;color:var(--text-main);">${n.title}</div>
            <div style="font-size:12px;color:var(--text-muted);margin-top:2px;">${n.message}</div>
            <div style="font-size:10.5px;color:var(--text-dim);margin-top:4px;">${new Date(n.created_at).toLocaleString()}</div>
          </div>
          ${!n.is_read ? `<button type="button" class="btn btn-sm btn-outline" style="font-size:11px;" onclick="DashboardController.markNotificationRead('${n.notification_id}')">Mark Read</button>` : `<span style="font-size:11px;color:var(--text-dim);">Read</span>`}
        </div>
      `).join("");
    } catch (_) {}
  }

  async function markNotificationRead(id, all = false) {
    try {
      await FinGrowwAuth.request("/api/v2/notifications/read", {
        method: "POST",
        body: JSON.stringify({ notification_id: id, mark_all: all }),
      });
      await Promise.all([loadNotifications(), loadOverview()]);
    } catch (_) {}
  }

  async function savePreferences(e) {
    e.preventDefault();
    try {
      await FinGrowwAuth.request("/api/v2/users/me", {
        method: "PUT",
        body: JSON.stringify({
          experience_level: document.getElementById("prefExp").value,
          trading_style: document.getElementById("prefStyle").value,
          preferred_timeframe: document.getElementById("prefTf").value,
          risk_profile: document.getElementById("prefRisk").value,
          preferences: {
            daily_loss_limit_pct: Number(document.getElementById("prefMaxLoss").value || 5.0),
          },
        }),
      });
      const msg = document.getElementById("prefSavedMsg");
      if (msg) {
        msg.style.display = "block";
        setTimeout(() => (msg.style.display = "none"), 2500);
      }
      loadProfile();
    } catch (err) {
      alert(err.message);
    }
  }

  async function signOut() {
    await FinGrowwAuth.logout();
    window.location.href = "index.html";
  }

  async function loadSupportTickets() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/support/tickets");
      const box = document.getElementById("dashTicketsList");
      if (!box) return;
      const tickets = res.tickets || [];
      if (!tickets.length) {
        box.innerHTML = `<div class="dash-empty"><i class="fa-solid fa-headset"></i><div>No support tickets created yet.</div></div>`;
        return;
      }
      box.innerHTML = tickets.map(t => `
        <div class="dash-notif-item">
          <div style="width:100%;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong style="font-size:13px;color:var(--text-main);">${t.subject}</strong>
              <span class="fg-verdict-badge ${t.status === 'resolved' ? 'fg-verdict-buy' : 'fg-verdict-hold'}">${t.status.toUpperCase()}</span>
            </div>
            <div style="font-size:11.5px;color:var(--text-muted);margin-top:6px;">
              ${(t.messages || []).map(m => `<div><strong>${m.sender_role}:</strong> ${m.body}</div>`).join("")}
            </div>
          </div>
        </div>
      `).join("");
    } catch (_) {}
  }

  async function submitSupportTicket(e) {
    e.preventDefault();
    try {
      await FinGrowwAuth.request("/api/v2/support/tickets", {
        method: "POST",
        body: JSON.stringify({
          subject: document.getElementById("tktSubject").value,
          priority: document.getElementById("tktPriority").value,
          message: document.getElementById("tktMessage").value,
        }),
      });
      document.getElementById("tktSubject").value = "";
      document.getElementById("tktMessage").value = "";
      await loadSupportTickets();
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadAcademy() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/academy/courses");
      const badge = document.getElementById("badgeAcademyPct");
      const overall = document.getElementById("academyOverallBadge");
      if (badge) badge.textContent = `${res.overall_progress_pct || 0}%`;
      if (overall) overall.textContent = `${res.completed_lessons_count || 0}/${res.total_lessons_count || 0} Lessons (${res.overall_progress_pct || 0}%)`;

      const box = document.getElementById("academyCoursesBox");
      if (!box) return;
      box.innerHTML = (res.courses || []).map(c => {
        const doneSet = new Set(c.completed_lessons || []);
        return `
          <div class="dash-panel" style="padding:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
              <span class="fg-sec-badge" style="margin-bottom:0;">STAGE ${c.stage} • ${c.level}</span>
              <span class="mono up" style="font-size:12px;font-weight:800;">${c.progress_pct}%</span>
            </div>
            <h4 style="font-size:14.5px;font-weight:800;color:var(--text-main);margin:4px 0 6px;">${c.title}</h4>
            <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px;line-height:1.45;">${c.description}</p>
            <div style="display:flex;flex-direction:column;gap:6px;">
              ${(c.lessons || []).map(ls => {
                const isDone = doneSet.has(ls.lesson_id);
                return `
                  <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:var(--bg-surface);border-radius:6px;border:1px solid var(--border-subtle);font-size:12px;">
                    <span style="color:${isDone ? 'var(--accent-green)' : 'var(--text-main)'};">
                      <i class="fa-solid ${isDone ? 'fa-circle-check' : 'fa-circle-play'}" style="margin-right:6px;"></i>${ls.title}
                    </span>
                    ${!isDone ? `<button type="button" class="btn btn-sm btn-outline" style="padding:2px 8px;font-size:10.5px;" onclick="DashboardController.completeLesson('${c.course_id}', '${ls.lesson_id}')">Complete</button>` : `<span style="font-size:10.5px;color:var(--accent-green);font-weight:700;">Done</span>`}
                  </div>
                `;
              }).join("")}
            </div>
          </div>
        `;
      }).join("");
    } catch (_) {}
  }

  async function completeLesson(courseId, lessonId) {
    try {
      await FinGrowwAuth.request("/api/v2/academy/progress", {
        method: "POST",
        body: JSON.stringify({ course_id: courseId, lesson_id: lessonId }),
      });
      await Promise.all([loadAcademy(), loadNotifications()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadBilling() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/subscriptions/me");
      const plan = res.current_plan || "free";
      const statusEl = document.getElementById("billingPlanStatus");
      const detailsEl = document.getElementById("billingPlanDetails");
      const cancelBtn = document.getElementById("btnCancelSub");
      if (statusEl) statusEl.textContent = plan.toUpperCase();
      if (detailsEl) {
        const pd = res.plan_details || {};
        detailsEl.textContent = `${pd.name || plan} • Max Paper Accounts: ${pd.max_paper_accounts || 1}`;
      }
      if (cancelBtn) cancelBtn.style.display = plan !== "free" ? "inline-flex" : "none";

      const tbody = document.getElementById("billingInvoicesBody");
      if (!tbody) return;
      const invs = res.invoices || [];
      tbody.innerHTML = invs.map(inv => `
        <tr>
          <td class="mono font-bold">${inv.invoice_id}</td>
          <td>${inv.plan_code}</td>
          <td class="td-right mono">₹${Number(inv.base_amount_inr).toFixed(2)}</td>
          <td class="td-right mono">₹${Number(inv.gst_18_inr).toFixed(2)}</td>
          <td class="td-right mono up font-bold">₹${Number(inv.total_amount_inr).toFixed(2)}</td>
          <td class="td-center" style="font-size:11.5px;color:var(--text-dim);">${new Date(inv.issued_at).toLocaleDateString()}</td>
        </tr>
      `).join("") || `<tr><td colspan="6" style="text-align:center;padding:20px;color:var(--text-dim);">No billing invoices yet.</td></tr>`;
    } catch (_) {}
  }

  async function upgradeToPro() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/subscriptions/checkout", {
        method: "POST",
        body: JSON.stringify({ plan_code: "pro_algo_swarm", billing_cycle: "monthly" }),
      });
      if (res.dev_webhook_sample) {
        if (confirm("Sandbox Checkout Order Ready (" + res.checkout.payment_id + "). Simulate verified payment capture now?")) {
          const wh = res.dev_webhook_sample;
          await fetch("/api/v2/subscriptions/webhook", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-FinGroww-Signature": wh.signature },
            body: wh.raw_body_str || JSON.stringify(wh.payload),
          });
          await Promise.all([loadBilling(), loadProfile(), loadNotifications()]);
        }
      } else {
        alert("Checkout initialized: " + res.checkout.payment_id);
      }
    } catch (err) {
      alert(err.message);
    }
  }

  async function cancelSubscription() {
    if (!confirm("Cancel your paid subscription and revert to the Free AI Paper plan?")) return;
    try {
      await FinGrowwAuth.request("/api/v2/subscriptions/cancel", { method: "POST" });
      await Promise.all([loadBilling(), loadProfile()]);
    } catch (err) {
      alert(err.message);
    }
  }

  return {
    init,
    switchTab,
    addWatchlistSymbol,
    removeWatchlistSymbol,
    deleteSavedSignal,
    markNotificationRead,
    savePreferences,
    submitSupportTicket,
    completeLesson,
    upgradeToPro,
    cancelSubscription,
    signOut,
  };
})();

document.addEventListener("DOMContentLoaded", DashboardController.init);
