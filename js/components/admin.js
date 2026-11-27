/**
 * FinGroww Super Admin Control Centre Controller (Phase 4)
 */
const AdminController = (() => {
  let currentActor = null;
  let currentPage = 1;

  async function init() {
    if (!FinGrowwAuth.getAccessToken()) {
      showAccessDenied("Please sign in with an administrative account to access /admin.");
      return;
    }

    try {
      const me = await FinGrowwAuth.request("/api/v2/users/me");
      currentActor = me.user;
      const role = (currentActor.role || "trader").toLowerCase();
      const allowed = ["super_admin", "admin", "support", "analyst", "content_manager"];
      if (!allowed.includes(role)) {
        showAccessDenied(`Access Denied: Your role '${role}' does not have administrative permissions.`);
        return;
      }

      document.getElementById("adminDeniedCard").style.display = "none";
      document.getElementById("adminWorkspace").style.display = "grid";
      document.getElementById("adminActorBadge").textContent = `${currentActor.full_name} (${role.toUpperCase()})`;

      await Promise.all([loadStats(), loadFeatureFlags(), loadUsers(), loadTickets(), loadAuditLogs()]);
    } catch (err) {
      showAccessDenied(err.message || "Authentication verification failed.");
    }
  }

  function showAccessDenied(msg) {
    document.getElementById("adminWorkspace").style.display = "none";
    const card = document.getElementById("adminDeniedCard");
    card.style.display = "block";
    document.getElementById("adminDeniedMsg").textContent = msg;
  }

  function switchTab(tabId, btnEl) {
    document.querySelectorAll(".dash-tab-panel").forEach(p => p.classList.remove("active"));
    const target = document.getElementById("tab-" + tabId);
    if (target) target.classList.add("active");
    document.querySelectorAll(".dash-nav-btn").forEach(b => b.classList.remove("active"));
    if (btnEl) btnEl.classList.add("active");
  }

  async function loadStats() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/admin/stats");
      const k = res.kpis || {};
      const h = res.platform_health || {};
      const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };

      setTxt("admTotalUsers", k.total_users ?? 0);
      setTxt("admNewReg7d", `New (7d): ${k.new_registrations_7d ?? 0} • 24h: ${k.new_registrations_24h ?? 0}`);
      setTxt("admDauMau", `${k.dau_24h ?? 0} / ${k.mau_30d ?? 0}`);
      setTxt("admActiveSessions", `Active JWT Sessions: ${k.active_sessions ?? 0}`);
      setTxt("admFreePro", `${k.free_users ?? 0} / ${k.pro_users ?? 0}`);
      setTxt("admConvChurn", `Conv: ${k.conversion_rate_pct ?? 0}% • Churn: ${k.churn_rate_pct ?? 0}%`);
      setTxt("admRevenue", `₹${Number(k.total_revenue_inr || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`);
      setTxt("admTicketsCount", `Open Support Tickets: ${k.open_support_tickets ?? 0}`);
      setTxt("admHealthMeta", `Status: ${(h.status || "healthy").toUpperCase()} • DB: ${h.db_mode || "local"}`);
    } catch (_) {}
  }

  async function loadFeatureFlags() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/admin/feature-flags");
      const box = document.getElementById("admFlagsList");
      if (!box) return;
      box.innerHTML = (res.flags || []).map(f => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:6px;margin-bottom:8px;">
          <div>
            <strong class="mono" style="font-size:12.5px;color:var(--text-main);">${f.key}</strong>
            <div style="font-size:11px;color:var(--text-dim);">${f.description || ''}</div>
          </div>
          <button type="button" class="btn btn-sm ${f.enabled ? 'btn-launch' : 'btn-outline'}" style="padding:4px 12px;font-size:11px;" onclick="AdminController.toggleFlag('${f.key}', ${!f.enabled})">
            ${f.enabled ? 'ENABLED' : 'DISABLED'}
          </button>
        </div>
      `).join("");
    } catch (_) {}
  }

  async function toggleFlag(key, enabled) {
    try {
      await FinGrowwAuth.request(`/api/v2/admin/feature-flags/${key}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      await Promise.all([loadFeatureFlags(), loadAuditLogs()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadUsers(page = 1) {
    currentPage = page;
    const search = encodeURIComponent(document.getElementById("admUserSearch")?.value || "");
    const role = encodeURIComponent(document.getElementById("admRoleFilter")?.value || "");
    const status = encodeURIComponent(document.getElementById("admStatusFilter")?.value || "");
    try {
      const res = await FinGrowwAuth.request(`/api/v2/admin/users?search=${search}&role=${role}&status=${status}&page=${page}&page_size=15`);
      const tbody = document.getElementById("admUsersTableBody");
      if (!tbody) return;
      const users = res.users || [];
      if (!users.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-dim);">No users match your filters.</td></tr>`;
        return;
      }

      const isSuperAdmin = (currentActor?.role || "").toLowerCase() === "super_admin";
      tbody.innerHTML = users.map(u => {
        const isSusp = u.account_status === "suspended" || u.account_status === "banned";
        return `
          <tr>
            <td>
              <strong style="color:var(--text-main);">${u.full_name}</strong>
              <div style="font-size:11px;color:var(--text-dim);">${u.email} (${u.user_id})</div>
            </td>
            <td class="td-center"><span class="fg-sec-badge" style="margin-bottom:0;">${u.role}</span></td>
            <td class="td-center mono" style="font-size:12px;">${u.subscription_plan}</td>
            <td class="td-center"><span class="fg-verdict-badge ${isSusp ? 'fg-verdict-sell' : 'fg-verdict-buy'}">${u.account_status}</span></td>
            <td class="td-center" style="font-size:11.5px;color:var(--text-dim);">${u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : '-'}</td>
            <td class="td-center" style="display:flex;gap:6px;justify-content:center;">
              <button type="button" class="btn btn-sm btn-outline" style="padding:4px 8px;font-size:11px;" onclick="AdminController.inspectUser('${u.user_id}')">Inspect</button>
              <button type="button" class="btn btn-sm btn-outline" style="padding:4px 8px;font-size:11px;color:${isSusp ? 'var(--accent-green)' : 'var(--accent-red)'};" onclick="AdminController.setStatus('${u.user_id}', '${isSusp ? 'active' : 'suspended'}')">
                ${isSusp ? 'Activate' : 'Suspend'}
              </button>
              <button type="button" class="btn btn-sm btn-outline" style="padding:4px 8px;font-size:11px;color:var(--accent-gold);" onclick="AdminController.grantPro('${u.user_id}', '${u.subscription_plan === 'free' ? 'pro_algo_swarm' : 'free'}')">
                ${u.subscription_plan === 'free' ? 'Grant Pro' : 'Set Free'}
              </button>
              ${isSuperAdmin ? `<button type="button" class="btn btn-sm btn-outline" style="padding:4px 8px;font-size:11px;" onclick="AdminController.promptRole('${u.user_id}', '${u.role}')">Role</button>` : ''}
            </td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      console.error("Admin users error:", err);
    }
  }

  async function inspectUser(uid) {
    try {
      const res = await FinGrowwAuth.request(`/api/v2/admin/users/${uid}`);
      const u = res.user;
      alert(`User Detail:\nID: ${u.user_id}\nName: ${u.full_name} (@${u.username})\nEmail: ${u.email}\nRole: ${u.role}\nPlan: ${u.subscription_plan}\nPaper Accounts: ${(res.paper_accounts || []).length}\nActive Sessions: ${res.active_sessions}`);
    } catch (err) {
      alert(err.message);
    }
  }

  async function setStatus(uid, newStatus) {
    if (!confirm(`Change user ${uid} status to ${newStatus.toUpperCase()}?`)) return;
    try {
      await FinGrowwAuth.request(`/api/v2/admin/users/${uid}/status`, {
        method: "PUT",
        body: JSON.stringify({ account_status: newStatus, reason: "Updated via /admin" }),
      });
      await Promise.all([loadUsers(currentPage), loadStats(), loadAuditLogs()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function grantPro(uid, planCode) {
    try {
      await FinGrowwAuth.request(`/api/v2/admin/users/${uid}/subscription`, {
        method: "PUT",
        body: JSON.stringify({ plan_code: planCode, reason: "Updated via /admin" }),
      });
      await Promise.all([loadUsers(currentPage), loadStats(), loadAuditLogs()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function promptRole(uid, currentRole) {
    const newRole = prompt(`Enter new role for ${uid} (super_admin, admin, support, analyst, content_manager, pro_trader, trader):`, currentRole);
    if (!newRole || newRole === currentRole) return;
    try {
      await FinGrowwAuth.request(`/api/v2/admin/users/${uid}/role`, {
        method: "PUT",
        body: JSON.stringify({ role: newRole.trim().toLowerCase() }),
      });
      await Promise.all([loadUsers(currentPage), loadAuditLogs()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadTickets() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/admin/tickets");
      const box = document.getElementById("admTicketsList");
      if (!box) return;
      const tickets = res.tickets || [];
      if (!tickets.length) {
        box.innerHTML = `<div class="dash-empty"><i class="fa-solid fa-headset"></i><div>No support tickets submitted yet.</div></div>`;
        return;
      }
      box.innerHTML = tickets.map(t => `
        <div class="dash-panel" style="padding:14px 16px;margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <div>
              <strong style="color:var(--text-main);">${t.subject}</strong>
              <span style="font-size:11px;color:var(--text-dim);margin-left:8px;">${t.ticket_id} • ${t.user_email} • Priority: ${t.priority.toUpperCase()}</span>
            </div>
            <span class="fg-verdict-badge ${t.status === 'resolved' ? 'fg-verdict-buy' : 'fg-verdict-hold'}">${t.status.toUpperCase()}</span>
          </div>
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;">
            ${(t.messages || []).map(m => `<div style="margin-bottom:4px;"><strong>${m.sender_role}:</strong> ${m.body}</div>`).join("")}
          </div>
          <div style="display:flex;gap:8px;">
            <input type="text" id="reply_${t.ticket_id}" placeholder="Type admin reply..." style="flex:1;padding:6px 10px;background:var(--bg-surface);border:1px solid var(--border-card);color:var(--text-main);border-radius:6px;font-size:12px;">
            <button type="button" class="btn btn-sm btn-launch" onclick="AdminController.replyTicket('${t.ticket_id}', 'resolved')">Reply & Resolve</button>
          </div>
        </div>
      `).join("");
    } catch (_) {}
  }

  async function replyTicket(tid, status) {
    const inp = document.getElementById(`reply_${tid}`);
    const msg = inp ? inp.value.trim() : "";
    if (!msg) return alert("Enter a reply message.");
    try {
      await FinGrowwAuth.request(`/api/v2/admin/tickets/${tid}/reply`, {
        method: "POST",
        body: JSON.stringify({ reply_message: msg, status }),
      });
      await Promise.all([loadTickets(), loadStats(), loadAuditLogs()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadAuditLogs() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/admin/audit-logs?limit=40");
      const tbody = document.getElementById("admAuditBody");
      if (!tbody) return;
      const logs = res.logs || [];
      tbody.innerHTML = logs.map(l => `
        <tr>
          <td class="mono" style="font-size:11px;color:var(--text-dim);">${new Date(l.timestamp).toLocaleString()}</td>
          <td class="mono" style="font-size:11.5px;">${l.actor_user_id} (${l.actor_role})</td>
          <td><span class="fg-sec-badge" style="margin-bottom:0;">${l.action}</span></td>
          <td class="mono" style="font-size:11.5px;color:var(--text-muted);">${l.resource}</td>
          <td class="mono" style="font-size:11px;color:var(--text-dim);">${l.ip_address}</td>
        </tr>
      `).join("") || `<tr><td colspan="5" style="text-align:center;padding:20px;color:var(--text-dim);">No audit entries yet.</td></tr>`;
    } catch (_) {}
  }

  return {
    init,
    switchTab,
    loadUsers,
    toggleFlag,
    inspectUser,
    setStatus,
    grantPro,
    promptRole,
    replyTicket,
  };
})();

document.addEventListener("DOMContentLoaded", AdminController.init);
