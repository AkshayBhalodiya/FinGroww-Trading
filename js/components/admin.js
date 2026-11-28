/**
 * FinGroww Super Admin & Admin Control Centre Controller
 * Complete User CRUD, Role Assignment (Admin/Super Admin), & Live Logged-In Sessions.
 */
const AdminController = (() => {
  let currentActor = null;
  let currentPage = 1;
  let cachedUsers = [];

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function init() {
    if (!FinGrowwAuth.getAccessToken()) {
      showAccessDenied("Please sign in with your Super Admin or Admin account to access /admin.html.");
      return;
    }

    try {
      const me = await FinGrowwAuth.request("/api/v2/users/me");
      currentActor = me.user;
      FinGrowwAuth.saveSession({ user: currentActor });
      const role = (currentActor.role || "trader").toLowerCase();
      const allowed = ["super_admin", "admin", "support", "analyst", "content_manager"];
      if (!allowed.includes(role)) {
        showAccessDenied(`Access Denied: Your role '${role}' does not have administrative permissions.`);
        return;
      }

      document.getElementById("adminDeniedCard").style.display = "none";
      document.getElementById("adminWorkspace").style.display = "grid";
      const mobBar = document.getElementById("adminMobileBar");
      if (mobBar && window.innerWidth <= 820) mobBar.style.display = "flex";
      document.getElementById("adminActorBadge").textContent =
        `${currentActor.full_name} (${role.toUpperCase()})`;

      // Lock super-only role options when actor isn't super_admin
      const isSuper = role === "super_admin";
      document.querySelectorAll('#admInpRole option[data-super-only="1"]').forEach(opt => {
        opt.disabled = !isSuper;
      });

      await Promise.all([
        loadStats(),
        loadFeatureFlags(),
        loadUsers(),
        loadSessions(),
        loadTickets(),
        loadAuditLogs(),
      ]);
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
    if (btnEl) {
      btnEl.classList.add("active");
    } else {
      const sideBtn = document.querySelector(`.dash-sidebar .dash-nav-btn[data-tab="${tabId}"]`);
      if (sideBtn) sideBtn.classList.add("active");
    }
    if (tabId === "sessions") loadSessions();
    if (tabId === "users") loadUsers(currentPage);
  }

  async function signOut() {
    await FinGrowwAuth.logout();
    window.location.href = "auth.html";
  }

  async function loadStats() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/admin/stats");
      const k = res.kpis || {};
      const h = res.platform_health || {};
      const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };

      setTxt("admTotalUsers", k.total_users ?? 0);
      setTxt("admBadgeUsers", k.total_users ?? 0);
      setTxt("admNewReg7d", `New (7d): ${k.new_registrations_7d ?? 0} • 24h: ${k.new_registrations_24h ?? 0}`);
      setTxt("admDauMau", `${k.dau_24h ?? 0} / ${k.active_sessions ?? 0}`);
      setTxt("admActiveSessions", `MAU (30d): ${k.mau_30d ?? 0} • Live JWT Sessions: ${k.active_sessions ?? 0}`);
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
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:8px;margin-bottom:8px;">
          <div>
            <strong class="mono" style="font-size:12.5px;color:var(--text-main);">${esc(f.key)}</strong>
            <div style="font-size:11px;color:var(--text-dim);">${esc(f.description || '')}</div>
          </div>
          <button type="button" class="btn btn-sm ${f.enabled ? 'btn-launch' : 'btn-outline'}" style="padding:4px 12px;font-size:11px;" onclick="AdminController.toggleFlag('${esc(f.key)}', ${!f.enabled})">
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
      if (window.showToast) window.showToast(`Flag '${key}' updated!`);
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
      const res = await FinGrowwAuth.request(`/api/v2/admin/users?search=${search}&role=${role}&status=${status}&page=${page}&page_size=50`);
      const tbody = document.getElementById("admUsersTableBody");
      if (!tbody) return;
      cachedUsers = res.users || [];
      const badgeEl = document.getElementById("admBadgeUsers");
      if (badgeEl && !search && !role && !status) badgeEl.textContent = res.total ?? cachedUsers.length;

      if (!cachedUsers.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-dim);">No users match your filters.</td></tr>`;
        return;
      }

      const isSuperAdmin = (currentActor?.role || "").toLowerCase() === "super_admin";
      tbody.innerHTML = cachedUsers.map(u => {
        const isSusp = u.account_status === "suspended" || u.account_status === "banned";
        const isSelf = currentActor && u.user_id === currentActor.user_id;
        const canDelete = !isSelf && (isSuperAdmin || !["super_admin", "admin"].includes((u.role || "").toLowerCase()));
        const canEdit = isSuperAdmin || (u.role || "").toLowerCase() !== "super_admin";

        const roleBg =
          u.role === "super_admin"
            ? "background:rgba(168,85,247,0.16);border-color:rgba(168,85,247,0.45);color:var(--accent-purple);"
            : u.role === "admin"
              ? "background:rgba(245,158,11,0.16);border-color:rgba(245,158,11,0.45);color:var(--accent-gold);"
              : "";

        return `
          <tr>
            <td>
              <strong style="color:var(--text-main);">${esc(u.full_name)}</strong>
              ${isSelf ? '<span style="font-size:10px;color:var(--accent-blue);font-weight:800;margin-left:6px;">(YOU)</span>' : ''}
              <div style="font-size:11px;color:var(--text-dim);">${esc(u.email)} • <span class="mono">${esc(u.user_id)}</span></div>
              <div style="font-size:11px;color:var(--accent-blue);margin-top:2px;">
                <i class="fa-solid fa-id-badge"></i> Trading Profile (Paper &amp; Real): <strong>${esc(u.trading_profile_name || u.full_name)}</strong>
              </div>
            </td>
            <td class="td-center">
              <span class="fg-sec-badge" style="margin-bottom:0;${roleBg}">${esc(u.role)}</span>
            </td>
            <td class="td-center">
              ${
                u.is_online
                  ? `<span class="adm-online-pill"><span class="fg-live-dot"></span> ONLINE (${u.active_sessions_count || 1})</span>`
                  : `<span class="adm-offline-pill">OFFLINE</span>`
              }
            </td>
            <td class="td-center mono" style="font-size:11.5px;">
              <div>${esc(u.subscription_plan)}</div>
              <div style="color:var(--accent-green);">₹${Number(u.paper_balance ?? 100000).toLocaleString("en-IN")}</div>
            </td>
            <td class="td-center">
              <span class="fg-verdict-badge ${isSusp ? 'fg-verdict-sell' : 'fg-verdict-buy'}">${esc(u.account_status)}</span>
            </td>
            <td class="td-center">
              <div class="adm-action-row">
                <button type="button" class="btn btn-sm btn-outline" style="padding:4px 9px;font-size:11px;" onclick="AdminController.inspectUser('${esc(u.user_id)}')" title="Inspect details">
                  <i class="fa-solid fa-eye"></i>
                </button>
                ${canEdit ? `<button type="button" class="btn btn-sm btn-outline" style="padding:4px 9px;font-size:11px;color:var(--accent-blue);" onclick="AdminController.openEditModal('${esc(u.user_id)}')" title="Edit user">
                  <i class="fa-solid fa-pen"></i> Edit
                </button>` : ''}
                ${!isSelf ? `<button type="button" class="btn btn-sm btn-outline" style="padding:4px 9px;font-size:11px;color:${isSusp ? 'var(--accent-green)' : 'var(--accent-gold)'};" onclick="AdminController.setStatus('${esc(u.user_id)}', '${isSusp ? 'active' : 'suspended'}')">
                  ${isSusp ? 'Activate' : 'Suspend'}
                </button>` : ''}
                ${canDelete ? `<button type="button" class="btn btn-sm btn-outline" style="padding:4px 9px;font-size:11px;color:var(--accent-red);border-color:rgba(244,63,94,0.35);" onclick="AdminController.deleteUser('${esc(u.user_id)}', '${esc(u.email)}')" title="Delete user">
                  <i class="fa-solid fa-trash"></i>
                </button>` : ''}
              </div>
            </td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      console.error("Admin users error:", err);
    }
  }

  async function loadSessions() {
    try {
      const res = await FinGrowwAuth.request("/api/v2/admin/sessions");
      const sessions = res.sessions || [];
      const badge = document.getElementById("admBadgeOnline");
      if (badge) badge.textContent = res.logged_in_users_count ?? sessions.length;

      const summaryEl = document.getElementById("admSessionsSummary");
      if (summaryEl) {
        summaryEl.textContent = `${res.logged_in_users_count || 0} logged-in user(s) across ${res.active_sessions_count || 0} active JWT session(s).`;
      }

      const tbody = document.getElementById("admSessionsTableBody");
      if (!tbody) return;
      if (!sessions.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-dim);">No active logged-in sessions found.</td></tr>`;
        return;
      }

      tbody.innerHTML = sessions.map(s => {
        const isCurrent = currentActor && s.user_id === currentActor.user_id;
        return `
          <tr>
            <td>
              <strong style="color:var(--text-main);">${esc(s.full_name)}</strong>
              ${isCurrent ? '<span style="font-size:10px;color:var(--accent-green);font-weight:800;margin-left:4px;">(CURRENT ADMIN)</span>' : ''}
              <div style="font-size:11px;color:var(--text-dim);">${esc(s.email)} • <span class="mono">${esc(s.session_id)}</span></div>
            </td>
            <td class="td-center mono" style="font-size:12px;color:var(--accent-blue);">${esc(s.trading_profile_name || s.username)}</td>
            <td class="td-center"><span class="fg-sec-badge" style="margin-bottom:0;">${esc(s.role)} · ${esc(s.subscription_plan)}</span></td>
            <td class="td-center mono" style="font-size:11.5px;">${esc(s.ip_address)}</td>
            <td class="td-center" style="font-size:11px;color:var(--text-dim);">${s.last_used_at ? new Date(s.last_used_at).toLocaleString() : '-'}</td>
            <td class="td-center">
              <button type="button" class="btn btn-sm btn-outline" style="padding:4px 10px;font-size:11px;color:var(--accent-red);" onclick="AdminController.revokeSession('${esc(s.session_id)}')">
                Force Logout
              </button>
            </td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      console.error("Load sessions error:", err);
    }
  }

  async function revokeSession(sid) {
    if (!confirm(`Revoke active JWT session ${sid}? That user will be logged out immediately.`)) return;
    try {
      await FinGrowwAuth.request(`/api/v2/admin/sessions/${encodeURIComponent(sid)}`, { method: "DELETE" });
      if (window.showToast) window.showToast(`Session ${sid} revoked.`);
      await Promise.all([loadSessions(), loadUsers(currentPage), loadStats(), loadAuditLogs()]);
    } catch (err) {
      alert(err.message);
    }
  }

  function openCreateModal() {
    document.getElementById("admModalTitle").textContent = "Create New User / Admin";
    document.getElementById("admEditUserId").value = "";
    document.getElementById("admInpFullName").value = "";
    document.getElementById("admInpEmail").value = "";
    document.getElementById("admInpEmail").disabled = false;
    document.getElementById("admInpUsername").value = "";
    document.getElementById("admInpTradingProfile").value = "";
    document.getElementById("admInpPassword").value = "";
    document.getElementById("admInpPassword").required = true;
    document.getElementById("admLblPassword").textContent = "Password (min 8 chars, letters + numbers) *";
    document.getElementById("admInpRole").value = "trader";
    document.getElementById("admInpPlan").value = "free";
    document.getElementById("admStatusWrap").style.display = "none";
    document.getElementById("admCapitalWrap").style.display = "block";
    document.getElementById("admInpCapital").value = "100000";
    document.getElementById("admFormError").style.display = "none";
    document.getElementById("admSubmitBtn").textContent = "Create User Account";
    document.getElementById("admUserModal").classList.add("open");
  }

  function openEditModal(uid) {
    const u = cachedUsers.find(x => x.user_id === uid);
    if (!u) return;
    document.getElementById("admModalTitle").textContent = `Edit User: ${u.full_name}`;
    document.getElementById("admEditUserId").value = u.user_id;
    document.getElementById("admInpFullName").value = u.full_name || "";
    document.getElementById("admInpEmail").value = u.email || "";
    document.getElementById("admInpEmail").disabled = true;
    document.getElementById("admInpUsername").value = u.username || "";
    document.getElementById("admInpTradingProfile").value = u.trading_profile_name || u.full_name || "";
    document.getElementById("admInpPassword").value = "";
    document.getElementById("admInpPassword").required = false;
    document.getElementById("admLblPassword").textContent = "Reset Password (leave blank to keep unchanged)";
    document.getElementById("admInpRole").value = u.role || "trader";
    document.getElementById("admInpPlan").value = u.subscription_plan || "free";
    document.getElementById("admStatusWrap").style.display = "block";
    document.getElementById("admInpStatus").value = u.account_status || "active";
    document.getElementById("admCapitalWrap").style.display = "none";
    document.getElementById("admFormError").style.display = "none";
    document.getElementById("admSubmitBtn").textContent = "Save Changes";
    document.getElementById("admUserModal").classList.add("open");
  }

  function closeUserModal() {
    document.getElementById("admUserModal").classList.remove("open");
  }

  async function submitUserForm(e) {
    e.preventDefault();
    const errBox = document.getElementById("admFormError");
    errBox.style.display = "none";

    const editId = document.getElementById("admEditUserId").value.trim();
    const fullName = document.getElementById("admInpFullName").value.trim();
    const email = document.getElementById("admInpEmail").value.trim();
    const username = document.getElementById("admInpUsername").value.trim();
    const tradingProfile = document.getElementById("admInpTradingProfile").value.trim();
    const pw = document.getElementById("admInpPassword").value;
    const role = document.getElementById("admInpRole").value;
    const plan = document.getElementById("admInpPlan").value;

    try {
      if (!editId) {
        const payload = {
          full_name: fullName,
          email,
          password: pw,
          role,
          subscription_plan: plan,
          virtual_capital: Number(document.getElementById("admInpCapital").value || 100000),
          is_email_verified: true,
        };
        if (username) payload.username = username;
        if (tradingProfile) payload.trading_profile_name = tradingProfile;
        await FinGrowwAuth.request("/api/v2/admin/users", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (window.showToast) window.showToast(`Created user ${email} (${role})!`);
      } else {
        const payload = {
          full_name: fullName,
          role,
          subscription_plan: plan,
          account_status: document.getElementById("admInpStatus").value,
        };
        if (username) payload.username = username;
        if (tradingProfile) payload.trading_profile_name = tradingProfile;
        if (pw.trim()) payload.new_password = pw;
        await FinGrowwAuth.request(`/api/v2/admin/users/${encodeURIComponent(editId)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        if (window.showToast) window.showToast(`Updated user ${fullName}!`);
      }
      closeUserModal();
      await Promise.all([loadUsers(currentPage), loadSessions(), loadStats(), loadAuditLogs()]);
    } catch (err) {
      errBox.textContent = err.message || "Operation failed.";
      errBox.style.display = "block";
    }
  }

  async function deleteUser(uid, email) {
    if (!confirm(`PERMANENTLY DELETE user ${email} (${uid}) and all associated paper accounts & sessions? This cannot be undone.`)) return;
    try {
      await FinGrowwAuth.request(`/api/v2/admin/users/${encodeURIComponent(uid)}`, { method: "DELETE" });
      if (window.showToast) window.showToast(`Deleted user ${email}.`);
      await Promise.all([loadUsers(currentPage), loadSessions(), loadStats(), loadAuditLogs()]);
    } catch (err) {
      alert(err.message);
    }
  }

  async function inspectUser(uid) {
    const modal = document.getElementById("admInspectModal");
    const body = document.getElementById("admInspectBody");
    modal.classList.add("open");
    body.innerHTML = `<div style="padding:20px;text-align:center;">Loading user portfolio &amp; session telemetry...</div>`;
    try {
      const res = await FinGrowwAuth.request(`/api/v2/admin/users/${encodeURIComponent(uid)}`);
      const u = res.user;
      const pas = res.paper_accounts || [];
      const hist = res.login_history || [];
      body.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:10px;padding:14px;margin-bottom:14px;">
          <div><strong>Full Name:</strong> ${esc(u.full_name)}</div>
          <div><strong>User ID:</strong> <span class="mono">${esc(u.user_id)}</span></div>
          <div><strong>Email:</strong> ${esc(u.email)}</div>
          <div><strong>Username:</strong> @${esc(u.username)}</div>
          <div><strong>Role:</strong> <span class="fg-sec-badge" style="margin:0;">${esc(u.role)}</span></div>
          <div><strong>Plan:</strong> ${esc(u.subscription_plan)}</div>
          <div><strong>Paper &amp; Real Profile:</strong> <strong style="color:var(--accent-blue);">${esc(u.trading_profile_name)}</strong></div>
          <div><strong>Active Sessions:</strong> ${res.active_sessions ?? 0}</div>
        </div>
        <h4 style="color:var(--text-main);font-size:13px;margin:10px 0 6px;">Paper Trading Accounts (${pas.length})</h4>
        ${pas.map(pa => `
          <div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:8px;margin-bottom:6px;">
            <span><strong>${esc(pa.name)}</strong> (${esc(pa.account_id)})</span>
            <span class="mono" style="color:var(--accent-green);">Avail: ₹${Number(pa.available_balance || 0).toLocaleString("en-IN")} / Cap: ₹${Number(pa.virtual_capital || 0).toLocaleString("en-IN")}</span>
          </div>
        `).join("") || '<div style="color:var(--text-dim);">None provisioned yet.</div>'}
        <h4 style="color:var(--text-main);font-size:13px;margin:12px 0 6px;">Recent Login Events</h4>
        ${hist.slice(0, 5).map(h => `
          <div style="display:flex;justify-content:space-between;padding:6px 10px;background:var(--bg-surface);border-radius:6px;margin-bottom:4px;font-size:11.5px;">
            <span class="${h.status === 'SUCCESS' ? 'up' : 'down'}">${esc(h.status)}</span>
            <span class="mono">${esc(h.ip_address)}</span>
            <span>${h.logged_in_at ? new Date(h.logged_in_at).toLocaleString() : '-'}</span>
          </div>
        `).join("") || '<div style="color:var(--text-dim);">No login history yet.</div>'}
      `;
    } catch (err) {
      body.innerHTML = `<div style="color:var(--accent-red);padding:12px;">${esc(err.message)}</div>`;
    }
  }

  function closeInspectModal() {
    document.getElementById("admInspectModal").classList.remove("open");
  }

  async function setStatus(uid, newStatus) {
    if (!confirm(`Change user ${uid} status to ${newStatus.toUpperCase()}?`)) return;
    try {
      await FinGrowwAuth.request(`/api/v2/admin/users/${uid}/status`, {
        method: "PUT",
        body: JSON.stringify({ account_status: newStatus, reason: "Updated via /admin" }),
      });
      await Promise.all([loadUsers(currentPage), loadSessions(), loadStats(), loadAuditLogs()]);
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
              <strong style="color:var(--text-main);">${esc(t.subject)}</strong>
              <span style="font-size:11px;color:var(--text-dim);margin-left:8px;">${esc(t.ticket_id)} • ${esc(t.user_email)} • Priority: ${esc(t.priority.toUpperCase())}</span>
            </div>
            <span class="fg-verdict-badge ${t.status === 'resolved' ? 'fg-verdict-buy' : 'fg-verdict-hold'}">${esc(t.status.toUpperCase())}</span>
          </div>
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;">
            ${(t.messages || []).map(m => `<div style="margin-bottom:4px;"><strong>${esc(m.sender_role)}:</strong> ${esc(m.body)}</div>`).join("")}
          </div>
          <div style="display:flex;gap:8px;">
            <input type="text" id="reply_${esc(t.ticket_id)}" placeholder="Type admin reply..." style="flex:1;padding:6px 10px;background:var(--bg-surface);border:1px solid var(--border-card);color:var(--text-main);border-radius:6px;font-size:12px;">
            <button type="button" class="btn btn-sm btn-launch" onclick="AdminController.replyTicket('${esc(t.ticket_id)}', 'resolved')">Reply &amp; Resolve</button>
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
          <td class="mono" style="font-size:11.5px;">${esc(l.actor_user_id)} (${esc(l.actor_role)})</td>
          <td><span class="fg-sec-badge" style="margin-bottom:0;">${esc(l.action)}</span></td>
          <td class="mono" style="font-size:11.5px;color:var(--text-muted);">${esc(l.resource)}</td>
          <td class="mono" style="font-size:11px;color:var(--text-dim);">${esc(l.ip_address)}</td>
        </tr>
      `).join("") || `<tr><td colspan="5" style="text-align:center;padding:20px;color:var(--text-dim);">No audit entries yet.</td></tr>`;
    } catch (_) {}
  }

  return {
    init,
    switchTab,
    signOut,
    loadUsers,
    loadSessions,
    revokeSession,
    toggleFlag,
    openCreateModal,
    openEditModal,
    closeUserModal,
    submitUserForm,
    deleteUser,
    inspectUser,
    closeInspectModal,
    setStatus,
    replyTicket,
  };
})();

document.addEventListener("DOMContentLoaded", AdminController.init);
