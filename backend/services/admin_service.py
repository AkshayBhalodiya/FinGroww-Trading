"""
FinGroww SaaS Platform — Administrative Control Centre & Support Ticket Service (Phase 4).
Provides verifiable platform KPIs, user directory, moderation, RBAC role assignments,
subscription administration, audit logging, feature flags, and support desk operations.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.database import db_manager
from backend.services.auth_service import _sanitize_user, record_audit_log


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

    q = search.strip().lower()
    filtered = []
    for u in users:
        if role and (u.get("role") or "").lower() != role.lower():
            continue
        if status and (u.get("account_status") or "").lower() != status.lower():
            continue
        if q:
            haystack = " ".join([
                str(u.get("user_id") or ""),
                str(u.get("email") or ""),
                str(u.get("username") or ""),
                str(u.get("full_name") or ""),
            ]).lower()
            if q not in haystack:
                continue
        filtered.append(_sanitize_user(u))

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
