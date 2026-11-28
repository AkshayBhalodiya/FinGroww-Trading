"""
FinGroww SaaS Platform — Administrative Control Centre & Support Ticket Service (Phase 4).
Provides verifiable platform KPIs, user directory, moderation, RBAC role assignments,
subscription administration, audit logging, feature flags, and support desk operations.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.database import db_manager
from backend.security import hash_password
from backend.services import auth_service
from backend.services.auth_service import (
    _resolve_unique_trading_name,
    _sanitize_user,
    ensure_paper_and_broker_user,
    record_audit_log,
)


class AdminServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# -------------------------------------------------------------------------
# PLATFORM ANALYTICS & HEALTH
# -------------------------------------------------------------------------
def get_platform_stats() -> Dict[str, Any]:
    now = _now_utc()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    users = list(db_manager.collection("users").find({"account_status": {"$ne": "deleted"}}, {"_id": 0, "password_hash": 0}))
    total_users = len(users)
    free_users = 0
    pro_users = 0
    new_24h = 0
    new_7d = 0
    dau_24h = 0
    mau_30d = 0

    for u in users:
        plan = u.get("subscription_plan", "free")
        if plan == "free":
            free_users += 1
        else:
            pro_users += 1

        reg_dt = _parse_iso(u.get("registered_at") or u.get("created_at"))
        if reg_dt:
            if reg_dt >= cutoff_24h:
                new_24h += 1
            if reg_dt >= cutoff_7d:
                new_7d += 1

        login_dt = _parse_iso(u.get("last_login_at"))
        if login_dt:
            if login_dt >= cutoff_24h:
                dau_24h += 1
            if login_dt >= cutoff_30d:
                mau_30d += 1

    # Verified revenue strictly from completed payments
    payments = list(db_manager.collection("payments").find({"status": "SUCCEEDED"}, {"_id": 0}))
    total_revenue = round(sum(float(p.get("amount_inr", 0.0)) for p in payments), 2)
    monthly_revenue = 0.0
    for p in payments:
        p_dt = _parse_iso(p.get("paid_at") or p.get("created_at"))
        if p_dt and p_dt >= cutoff_30d:
            monthly_revenue += float(p.get("amount_inr", 0.0))
    monthly_revenue = round(monthly_revenue, 2)

    # Conversion & Churn strictly computed from subscriptions
    subs = list(db_manager.collection("subscriptions").find({}, {"_id": 0}))
    cancelled_subs = sum(1 for s in subs if s.get("status") == "cancelled")
    paid_subs_total = sum(1 for s in subs if s.get("plan_code") != "free")
    conversion_rate_pct = round((pro_users / total_users) * 100.0, 2) if total_users > 0 else 0.0
    churn_rate_pct = round((cancelled_subs / paid_subs_total) * 100.0, 2) if paid_subs_total > 0 else 0.0

    open_tickets = db_manager.collection("support_tickets").count_documents({"status": {"$in": ["open", "investigating"]}})
    total_trades = db_manager.collection("paper_trades").count_documents({})
    active_sessions = db_manager.collection("sessions").count_documents({"is_revoked": False})

    return {
        "ok": True,
        "kpis": {
            "total_users": total_users,
            "dau_24h": dau_24h,
            "mau_30d": mau_30d,
            "new_registrations_24h": new_24h,
            "new_registrations_7d": new_7d,
            "free_users": free_users,
            "pro_users": pro_users,
            "conversion_rate_pct": conversion_rate_pct,
            "churn_rate_pct": churn_rate_pct,
            "total_revenue_inr": total_revenue,
            "monthly_revenue_inr": monthly_revenue,
            "open_support_tickets": open_tickets,
            "total_paper_trades": total_trades,
            "active_sessions": active_sessions,
        },
        "platform_health": {
            "status": "healthy",
            "db_mode": db_manager.mode,
            "timestamp": _now_iso(),
        },
    }


# -------------------------------------------------------------------------
# USER DIRECTORY & MODERATION
# -------------------------------------------------------------------------
def list_users_directory(
    search: str = "",
    role: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    users = list(db_manager.collection("users").find({}, {"_id": 0, "password_hash": 0}).sort("registered_at", -1))
    active_sessions = list(db_manager.collection("sessions").find({"is_revoked": False}, {"_id": 0, "user_id": 1, "last_used_at": 1}))
    sessions_by_uid: Dict[str, int] = {}
    for s in active_sessions:
        uid = s.get("user_id")
        if uid:
            sessions_by_uid[uid] = sessions_by_uid.get(uid, 0) + 1

    paper_accs = list(db_manager.collection("paper_accounts").find({}, {"_id": 0, "user_id": 1, "virtual_capital": 1, "available_balance": 1, "is_default": 1}))
    paper_by_uid: Dict[str, Dict[str, Any]] = {}
    for pa in paper_accs:
        uid = pa.get("user_id")
        if uid and (uid not in paper_by_uid or pa.get("is_default")):
            paper_by_uid[uid] = pa

    q = search.strip().lower()
    filtered = []
    for u in users:
        st_val = (u.get("account_status") or "active").lower()
        if not status and st_val == "deleted":
            continue
        if role and (u.get("role") or "").lower() != role.lower():
            continue
        if status and st_val != status.lower():
            continue
        if q:
            haystack = " ".join([
                str(u.get("user_id") or ""),
                str(u.get("email") or ""),
                str(u.get("username") or ""),
                str(u.get("full_name") or ""),
                str(u.get("trading_profile_name") or ""),
            ]).lower()
            if q not in haystack:
                continue
        clean = _sanitize_user(u)
        uid = clean.get("user_id", "")
        ses_cnt = sessions_by_uid.get(uid, 0)
        pa = paper_by_uid.get(uid, {})
        clean["active_sessions_count"] = ses_cnt
        clean["is_online"] = ses_cnt > 0
        clean["paper_capital"] = float(pa.get("virtual_capital", 100000.0))
        clean["paper_balance"] = float(pa.get("available_balance", 100000.0))
        filtered.append(clean)

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "users": filtered[start:end],
    }


def get_user_detail(target_user_id: str) -> Dict[str, Any]:
    user_doc = db_manager.collection("users").find_one({"user_id": target_user_id}, {"_id": 0, "password_hash": 0})
    if not user_doc:
        raise AdminServiceError("Target user not found", 404)

    accounts = list(db_manager.collection("paper_accounts").find({"user_id": target_user_id}, {"_id": 0}))
    sessions = list(db_manager.collection("sessions").find({"user_id": target_user_id, "is_revoked": False}, {"_id": 0, "refresh_token_hash": 0}))
    history = list(db_manager.collection("login_history").find({"user_id": target_user_id}, {"_id": 0}).sort("logged_in_at", -1).limit(10))
    tickets = list(db_manager.collection("support_tickets").find({"user_id": target_user_id}, {"_id": 0}).sort("created_at", -1))

    return {
        "ok": True,
        "user": _sanitize_user(user_doc),
        "paper_accounts": accounts,
        "active_sessions": len(sessions),
        "login_history": history,
        "support_tickets": tickets,
    }


def update_user_status(actor: Dict[str, Any], target_user_id: str, new_status: str, reason: str, ip: str = "unknown") -> Dict[str, Any]:
    if actor["user_id"] == target_user_id and new_status != "active":
        raise AdminServiceError("Administrators cannot suspend or ban their own account", 400)

    col = db_manager.collection("users")
    target = col.find_one({"user_id": target_user_id})
    if not target:
        raise AdminServiceError("Target user not found", 404)

    if target.get("role") == "super_admin" and actor.get("role") != "super_admin":
        raise AdminServiceError("Only a Super Admin can modify another Super Admin's status", 403)

    col.update_one(
        {"user_id": target_user_id},
        {"$set": {"account_status": new_status, "status_reason": reason, "status_updated_at": _now_iso()}},
    )

    if new_status in ("suspended", "banned"):
        # Immediately invalidate all JWT refresh/access sessions
        db_manager.collection("sessions").update_many(
            {"user_id": target_user_id},
            {"$set": {"is_revoked": True, "revoked_at": _now_iso()}},
        )

    record_audit_log(
        actor["user_id"],
        actor.get("role", "admin"),
        f"ADMIN_USER_STATUS_{new_status.upper()}",
        f"users/{target_user_id}",
        ip,
        {"reason": reason},
    )
    updated = col.find_one({"user_id": target_user_id}, {"_id": 0, "password_hash": 0})
    return {"ok": True, "user": _sanitize_user(updated)}


def update_user_role(actor: Dict[str, Any], target_user_id: str, new_role: str, ip: str = "unknown") -> Dict[str, Any]:
    col = db_manager.collection("users")
    target = col.find_one({"user_id": target_user_id})
    if not target:
        raise AdminServiceError("Target user not found", 404)

    old_role = target.get("role", "trader")
    col.update_one({"user_id": target_user_id}, {"$set": {"role": new_role, "role_updated_at": _now_iso()}})

    record_audit_log(
        actor["user_id"],
        actor.get("role", "super_admin"),
        "ADMIN_ROLE_ASSIGN",
        f"users/{target_user_id}",
        ip,
        {"old_role": old_role, "new_role": new_role},
    )
    updated = col.find_one({"user_id": target_user_id}, {"_id": 0, "password_hash": 0})
    return {"ok": True, "user": _sanitize_user(updated)}


def admin_update_subscription(actor: Dict[str, Any], target_user_id: str, plan_code: str, reason: str, ip: str = "unknown") -> Dict[str, Any]:
    col = db_manager.collection("users")
    target = col.find_one({"user_id": target_user_id})
    if not target:
        raise AdminServiceError("Target user not found", 404)

    now_iso = _now_iso()
    col.update_one({"user_id": target_user_id}, {"$set": {"subscription_plan": plan_code, "plan_updated_at": now_iso}})
    db_manager.collection("subscriptions").update_many(
        {"user_id": target_user_id, "status": "active"},
        {"$set": {"status": "replaced", "ended_at": now_iso}},
    )
    db_manager.collection("subscriptions").insert_one({
        "subscription_id": f"SUB-{uuid.uuid4().hex[:8].upper()}",
        "user_id": target_user_id,
        "plan_code": plan_code,
        "status": "active",
        "granted_by_admin": actor["user_id"],
        "reason": reason,
        "started_at": now_iso,
    })

    record_audit_log(
        actor["user_id"],
        actor.get("role", "admin"),
        "ADMIN_SUBSCRIPTION_OVERRIDE",
        f"users/{target_user_id}",
        ip,
        {"plan_code": plan_code, "reason": reason},
    )
    updated = col.find_one({"user_id": target_user_id}, {"_id": 0, "password_hash": 0})
    return {"ok": True, "user": _sanitize_user(updated)}


# -------------------------------------------------------------------------
# AUDIT LOGS & FEATURE FLAGS
# -------------------------------------------------------------------------
def list_audit_logs(action_filter: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    filt: Dict[str, Any] = {}
    if action_filter.strip():
        filt["action"] = action_filter.strip().upper()
    return list(
        db_manager.collection("audit_logs")
        .find(filt, {"_id": 0})
        .sort("timestamp", -1)
        .limit(min(limit, 200))
    )


def get_feature_flags() -> List[Dict[str, Any]]:
    return list(db_manager.collection("feature_flags").find({}, {"_id": 0}))


def toggle_feature_flag(actor: Dict[str, Any], key: str, enabled: bool, ip: str = "unknown") -> Dict[str, Any]:
    col = db_manager.collection("feature_flags")
    existing = col.find_one({"key": key})
    if not existing:
        raise AdminServiceError(f"Feature flag '{key}' not found", 404)

    col.update_one({"key": key}, {"$set": {"enabled": enabled, "updated_at": _now_iso(), "updated_by": actor["user_id"]}})
    record_audit_log(actor["user_id"], actor.get("role", "admin"), "FEATURE_FLAG_TOGGLE", f"feature_flags/{key}", ip, {"enabled": enabled})
    return {"ok": True, "flag": col.find_one({"key": key}, {"_id": 0})}


# -------------------------------------------------------------------------
# SUPPORT TICKETS (USER & ADMIN DESK)
# -------------------------------------------------------------------------
def create_support_ticket(user: Dict[str, Any], subject: str, message: str, priority: str = "medium", category: str = "other") -> Dict[str, Any]:
    now_iso = _now_iso()
    ticket = {
        "ticket_id": f"TKT-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user["user_id"],
        "user_email": user.get("email"),
        "subject": subject.strip(),
        "priority": priority,
        "category": category,
        "status": "open",
        "messages": [
            {
                "sender_id": user["user_id"],
                "sender_role": user.get("role", "trader"),
                "body": message.strip(),
                "sent_at": now_iso,
            }
        ],
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    db_manager.collection("support_tickets").insert_one(ticket)
    ticket.pop("_id", None)
    return {"ok": True, "ticket": ticket}


def list_user_tickets(user_id: str) -> List[Dict[str, Any]]:
    return list(db_manager.collection("support_tickets").find({"user_id": user_id}, {"_id": 0}).sort("updated_at", -1))


def admin_list_tickets(status_filter: str = "") -> List[Dict[str, Any]]:
    filt: Dict[str, Any] = {}
    if status_filter.strip():
        filt["status"] = status_filter.strip().lower()
    return list(db_manager.collection("support_tickets").find(filt, {"_id": 0}).sort("updated_at", -1))


def admin_reply_ticket(actor: Dict[str, Any], ticket_id: str, reply_message: str, new_status: Optional[str] = None, ip: str = "unknown") -> Dict[str, Any]:
    col = db_manager.collection("support_tickets")
    ticket = col.find_one({"ticket_id": ticket_id})
    if not ticket:
        raise AdminServiceError("Support ticket not found", 404)

    now_iso = _now_iso()
    msg_obj = {
        "sender_id": actor["user_id"],
        "sender_role": actor.get("role", "support"),
        "body": reply_message.strip(),
        "sent_at": now_iso,
    }
    update_doc: Dict[str, Any] = {
        "$push": {"messages": msg_obj},
        "$set": {"updated_at": now_iso, "status": new_status or ticket.get("status", "investigating")},
    }
    col.update_one({"ticket_id": ticket_id}, update_doc)

    # Notify ticket owner
    db_manager.collection("notifications").insert_one({
        "notification_id": f"NTF-{uuid.uuid4().hex[:8].upper()}",
        "user_id": ticket["user_id"],
        "title": f"Support Update ({ticket_id})",
        "message": f"FinGroww Support replied to '{ticket['subject']}'. Status: {new_status or ticket.get('status')}",
        "category": "support",
        "is_read": False,
        "created_at": now_iso,
    })

    record_audit_log(actor["user_id"], actor.get("role", "support"), "TICKET_REPLY", f"support_tickets/{ticket_id}", ip, {"status": new_status})
    return {"ok": True, "ticket": col.find_one({"ticket_id": ticket_id}, {"_id": 0})}


# -------------------------------------------------------------------------
# COMPLETE SUPER ADMIN USER & SESSION CRUD MANAGEMENT
# -------------------------------------------------------------------------
def admin_create_user(actor: Dict[str, Any], data: Dict[str, Any], ip: str = "unknown") -> Dict[str, Any]:
    """Creates a new Trader or Admin user directly from the Super Admin / Admin Control Centre."""
    target_role = (data.get("role") or "trader").lower()
    actor_role = (actor.get("role") or "trader").lower()
    if target_role in ("super_admin", "admin") and actor_role != "super_admin":
        raise AdminServiceError("Only Super Admin can create Admin or Super Admin accounts", 403)

    try:
        reg_res = auth_service.register_user(
            email=data["email"],
            password=data["password"],
            full_name=data["full_name"],
            username=data.get("username"),
            mobile_number=data.get("mobile_number"),
            role=target_role,
            ip_address=f"admin_create:{actor['user_id']}",
            user_agent="FinGroww Admin Console",
        )
    except auth_service.AuthError as exc:
        raise AdminServiceError(exc.message, exc.status_code)

    created = reg_res["user"]
    uid = created["user_id"]
    now_iso = _now_iso()
    plan_code = (data.get("subscription_plan") or "free").lower()
    is_verified = bool(data.get("is_email_verified", True))
    req_trading_name = (data.get("trading_profile_name") or "").strip()

    updates: Dict[str, Any] = {
        "is_email_verified": is_verified,
        "subscription_plan": plan_code,
        "updated_at": now_iso,
    }
    if req_trading_name:
        updates["trading_profile_name"] = _resolve_unique_trading_name(req_trading_name, created["username"], uid)

    db_manager.collection("users").update_one({"user_id": uid}, {"$set": updates})

    cap = float(data.get("virtual_capital") or 100000.0)
    db_manager.collection("paper_accounts").update_many(
        {"user_id": uid, "is_default": True},
        {"$set": {"virtual_capital": cap, "available_balance": cap}},
    )
    if plan_code != "free":
        db_manager.collection("subscriptions").update_many(
            {"user_id": uid, "status": "active"},
            {"$set": {"status": "replaced", "ended_at": now_iso}},
        )
        db_manager.collection("subscriptions").insert_one({
            "subscription_id": f"SUB-{uuid.uuid4().hex[:8].upper()}",
            "user_id": uid,
            "plan_code": plan_code,
            "status": "active",
            "granted_by_admin": actor["user_id"],
            "reason": "Created via Admin Control Centre",
            "started_at": now_iso,
        })

    # Clean up the initial admin-creation synthetic session so user sessions reflect real logins
    db_manager.collection("sessions").delete_many({"user_id": uid})

    user_doc = db_manager.collection("users").find_one({"user_id": uid}, {"_id": 0, "password_hash": 0})
    ensure_paper_and_broker_user(user_doc)
    record_audit_log(
        actor["user_id"],
        actor_role,
        "ADMIN_USER_CREATE",
        f"users/{uid}",
        ip,
        {"email": user_doc.get("email"), "role": target_role, "plan": plan_code},
    )
    return {"ok": True, "user": _sanitize_user(user_doc)}


def admin_update_user(actor: Dict[str, Any], target_user_id: str, data: Dict[str, Any], ip: str = "unknown") -> Dict[str, Any]:
    """Updates user details, trading profile, role, status, plan, or password."""
    col = db_manager.collection("users")
    target = col.find_one({"user_id": target_user_id})
    if not target:
        raise AdminServiceError("Target user not found", 404)

    actor_role = (actor.get("role") or "trader").lower()
    target_current_role = (target.get("role") or "trader").lower()
    if target_current_role == "super_admin" and actor_role != "super_admin":
        raise AdminServiceError("Only a Super Admin can modify a Super Admin account", 403)

    updates: Dict[str, Any] = {}
    if data.get("role") is not None:
        new_role = str(data["role"]).lower()
        if new_role != target_current_role:
            if new_role in ("super_admin", "admin") and actor_role != "super_admin":
                raise AdminServiceError("Only Super Admin can assign Admin or Super Admin role", 403)
            if actor["user_id"] == target_user_id and actor_role == "super_admin" and new_role != "super_admin":
                raise AdminServiceError("Super Admin cannot demote their own active account", 400)
            updates["role"] = new_role

    if data.get("account_status") is not None:
        new_status = str(data["account_status"]).lower()
        if actor["user_id"] == target_user_id and new_status != "active":
            raise AdminServiceError("Administrators cannot suspend or ban their own account", 400)
        updates["account_status"] = new_status
        if new_status in ("suspended", "banned"):
            db_manager.collection("sessions").update_many(
                {"user_id": target_user_id},
                {"$set": {"is_revoked": True, "revoked_at": _now_iso()}},
            )

    if data.get("full_name"):
        updates["full_name"] = str(data["full_name"]).strip()
        updates["name"] = updates["full_name"]

    if data.get("username"):
        uname = str(data["username"]).strip().lower()
        clash = col.find_one({"username": uname})
        if clash and clash.get("user_id") != target_user_id:
            raise AdminServiceError("Username is already taken", 409)
        updates["username"] = uname

    if data.get("trading_profile_name"):
        updates["trading_profile_name"] = _resolve_unique_trading_name(
            str(data["trading_profile_name"]).strip(),
            updates.get("username", target.get("username", "trader")),
            target_user_id,
        )

    if data.get("mobile_number") is not None:
        updates["mobile_number"] = data["mobile_number"]

    if data.get("is_email_verified") is not None:
        updates["is_email_verified"] = bool(data["is_email_verified"])

    if data.get("new_password"):
        updates["password_hash"] = hash_password(str(data["new_password"]))

    if data.get("subscription_plan") is not None:
        new_plan = str(data["subscription_plan"]).lower()
        if new_plan != target.get("subscription_plan"):
            now_iso = _now_iso()
            updates["subscription_plan"] = new_plan
            db_manager.collection("subscriptions").update_many(
                {"user_id": target_user_id, "status": "active"},
                {"$set": {"status": "replaced", "ended_at": now_iso}},
            )
            db_manager.collection("subscriptions").insert_one({
                "subscription_id": f"SUB-{uuid.uuid4().hex[:8].upper()}",
                "user_id": target_user_id,
                "plan_code": new_plan,
                "status": "active",
                "granted_by_admin": actor["user_id"],
                "reason": "Updated via Admin Edit Modal",
                "started_at": now_iso,
            })

    if updates:
        updates["updated_at"] = _now_iso()
        col.update_one({"user_id": target_user_id}, {"$set": updates})

    updated_doc = col.find_one({"user_id": target_user_id}, {"_id": 0, "password_hash": 0})
    ensure_paper_and_broker_user(updated_doc)
    record_audit_log(
        actor["user_id"],
        actor_role,
        "ADMIN_USER_UPDATE",
        f"users/{target_user_id}",
        ip,
        {"fields": sorted([k for k in updates.keys() if k != "password_hash"])},
    )
    return {"ok": True, "user": _sanitize_user(updated_doc)}


def admin_delete_user(actor: Dict[str, Any], target_user_id: str, ip: str = "unknown") -> Dict[str, Any]:
    """Deletes a user account and cleans up sessions/data safely."""
    if actor["user_id"] == target_user_id:
        raise AdminServiceError("Administrators cannot delete their own account", 400)

    col = db_manager.collection("users")
    target = col.find_one({"user_id": target_user_id})
    if not target:
        raise AdminServiceError("Target user not found", 404)

    actor_role = (actor.get("role") or "trader").lower()
    if (target.get("role") or "").lower() in ("super_admin", "admin") and actor_role != "super_admin":
        raise AdminServiceError("Only Super Admin can delete Admin or Super Admin accounts", 403)

    if (target.get("role") or "").lower() == "super_admin":
        active_supers = col.count_documents({"role": "super_admin", "account_status": {"$ne": "deleted"}})
        if active_supers <= 1:
            raise AdminServiceError("Cannot delete the last remaining Super Admin account", 400)

    db_manager.collection("sessions").delete_many({"user_id": target_user_id})
    db_manager.collection("preferences").delete_many({"user_id": target_user_id})
    db_manager.collection("watchlists").delete_many({"user_id": target_user_id})
    db_manager.collection("saved_signals").delete_many({"user_id": target_user_id})
    db_manager.collection("notifications").delete_many({"user_id": target_user_id})
    db_manager.collection("paper_accounts").delete_many({"user_id": target_user_id})
    db_manager.collection("trading_journals").delete_many({"user_id": target_user_id})
    col.delete_one({"user_id": target_user_id})

    record_audit_log(
        actor["user_id"],
        actor_role,
        "ADMIN_USER_DELETE",
        f"users/{target_user_id}",
        ip,
        {"deleted_email": target.get("email"), "deleted_role": target.get("role")},
    )
    return {"ok": True, "deleted_user_id": target_user_id, "message": f"User {target.get('email')} deleted."}


def list_active_sessions() -> Dict[str, Any]:
    """Returns all currently logged-in users & active non-revoked JWT sessions."""
    sessions = list(
        db_manager.collection("sessions")
        .find({"is_revoked": False}, {"_id": 0, "refresh_token_hash": 0, "refresh_jti": 0})
        .sort("last_used_at", -1)
    )
    users_col = db_manager.collection("users")
    all_users = {u.get("user_id"): _sanitize_user(u) for u in users_col.find({}, {"_id": 0, "password_hash": 0})}

    enriched = []
    unique_online_users: Dict[str, Dict[str, Any]] = {}
    for s in sessions:
        uid = s.get("user_id", "")
        u = all_users.get(uid, {})
        row = {
            "session_id": s.get("session_id"),
            "user_id": uid,
            "email": u.get("email", "—"),
            "full_name": u.get("full_name", "Unknown User"),
            "username": u.get("username", ""),
            "trading_profile_name": u.get("trading_profile_name", ""),
            "role": u.get("role", "trader"),
            "subscription_plan": u.get("subscription_plan", "free"),
            "ip_address": s.get("ip_address", "unknown"),
            "user_agent": s.get("user_agent", "unknown"),
            "created_at": s.get("created_at"),
            "last_used_at": s.get("last_used_at"),
        }
        enriched.append(row)
        if uid and uid not in unique_online_users:
            unique_online_users[uid] = row

    return {
        "ok": True,
        "active_sessions_count": len(enriched),
        "logged_in_users_count": len(unique_online_users),
        "logged_in_users": list(unique_online_users.values()),
        "sessions": enriched,
    }


def revoke_session_by_id(actor: Dict[str, Any], session_id: str, ip: str = "unknown") -> Dict[str, Any]:
    col = db_manager.collection("sessions")
    target = col.find_one({"session_id": session_id, "is_revoked": False})
    if not target:
        raise AdminServiceError("Active session not found", 404)

    col.update_one(
        {"session_id": session_id},
        {"$set": {"is_revoked": True, "revoked_at": _now_iso(), "revoked_by": actor["user_id"]}},
    )
    record_audit_log(
        actor["user_id"],
        actor.get("role", "admin"),
        "ADMIN_SESSION_REVOKE",
        f"sessions/{session_id}",
        ip,
        {"target_user_id": target.get("user_id")},
    )
    return {"ok": True, "revoked_session_id": session_id}
