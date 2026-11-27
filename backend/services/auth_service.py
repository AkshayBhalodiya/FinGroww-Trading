"""
FinGroww SaaS Platform — Authentication, Session, Profile & Audit Service.
Shared by FastAPI (/api/v2/*) routers and legacy Flask (/api/*) routes.
"""

import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from backend.config import settings
from backend.database import db_manager
from backend.security import (
    auth_rate_limiter,
    create_access_token,
    create_action_token,
    create_refresh_token,
    decode_jwt,
    get_role_permissions,
    hash_password,
    hash_token_identifier,
    verify_password,
)

logger = logging.getLogger("FinGroww.Services.Auth")


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_user(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    if not user_doc:
        return {}
    role = user_doc.get("role", "trader")
    full_name = user_doc.get("full_name") or user_doc.get("name") or user_doc.get("username")
    trading_name = user_doc.get("trading_profile_name") or full_name or user_doc.get("username")
    return {
        "user_id": user_doc.get("user_id"),
        "email": user_doc.get("email"),
        "username": user_doc.get("username"),
        "full_name": full_name,
        "trading_profile_name": trading_name,
        "mobile_number": user_doc.get("mobile_number"),
        "profile_image": user_doc.get("profile_image"),
        "role": role,
        "permissions": sorted(list(get_role_permissions(role))),
        "account_status": user_doc.get("account_status", "active"),
        "is_email_verified": bool(user_doc.get("is_email_verified", False)),
        "experience_level": user_doc.get("experience_level", "beginner"),
        "trading_style": user_doc.get("trading_style", "intraday_momentum"),
        "preferred_timeframe": user_doc.get("preferred_timeframe", "15m"),
        "risk_profile": user_doc.get("risk_profile", "moderate"),
        "subscription_plan": user_doc.get("subscription_plan", "free"),
        "registered_at": user_doc.get("registered_at") or user_doc.get("created_at") or _now_iso(),
        "last_login_at": user_doc.get("last_login_at"),
    }


def record_audit_log(
    actor_user_id: str,
    actor_role: str,
    action: str,
    resource: str,
    ip_address: str = "unknown",
    details: Optional[Dict[str, Any]] = None,
):
    try:
        db_manager.collection("audit_logs").insert_one({
            "audit_id": f"AUD-{uuid.uuid4().hex[:10].upper()}",
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "action": action,
            "resource": resource,
            "ip_address": ip_address,
            "details": details or {},
            "timestamp": _now_iso(),
        })
    except Exception as exc:
        logger.debug("Audit log write failed: %s", exc)


def _generate_unique_username(email: str, requested_username: Optional[str] = None) -> str:
    users_col = db_manager.collection("users")
    base = (requested_username or email.split("@")[0]).strip().lower()
    base = "".join(c for c in base if c.isalnum() or c == "_")[:24] or "trader"
    candidate = base
    for i in range(10):
        if not users_col.find_one({"username": candidate}):
            return candidate
        candidate = f"{base}_{secrets.token_hex(2)}"
    return f"usr_{uuid.uuid4().hex[:8]}"


def _resolve_unique_trading_name(full_name: str, username: str, user_id: str) -> str:
    """Uses the user's exact sign-up/display name as their Paper Algo & Real Broker profile name without cross-user collisions."""
    base_name = (full_name or username or "Trader").strip()
    users_col = db_manager.collection("users")
    all_users = list(users_col.find({"trading_profile_name": {"$ne": None}}, {"_id": 0, "user_id": 1, "trading_profile_name": 1}))
    taken = any(
        (u.get("trading_profile_name") or "").strip().casefold() == base_name.casefold()
        and u.get("user_id") != user_id
        for u in all_users
    )
    if not taken:
        return base_name
    return f"{base_name} ({username})"


def ensure_paper_and_broker_user(user_doc: Dict[str, Any]) -> str:
    """
    Auto-provisions both a Paper Algo portfolio session and an isolated Real Broker user slot
    using the user's authenticated trading_profile_name (e.g. their sign-in/display name).
    """
    trader_name = (
        user_doc.get("trading_profile_name")
        or user_doc.get("full_name")
        or user_doc.get("name")
        or user_doc.get("username")
        or "Trader"
    ).strip()

    # 1. Provision Paper Algo Engine session & profile under trader_name
    try:
        import fingroww_market_server as srv
        if hasattr(srv, "paper_manager") and srv.paper_manager:
            u_sess, _ = srv.paper_manager.get_session(trader_name)
            u_sess.user_id = user_doc.get("user_id", u_sess.user_id)
    except Exception as exc:
        logger.debug("Paper profile auto-provision deferred: %s", exc)

    # 2. Provision Real Broker isolated slot under trader_name
    try:
        from brokers import broker_manager
        if broker_manager:
            if trader_name not in broker_manager._user_modes:
                broker_manager._user_modes[trader_name] = "PAPER"
            broker_manager.get_status(trader_name)
    except Exception as exc:
        logger.debug("Broker slot auto-provision deferred: %s", exc)

    return trader_name


def _create_session_and_tokens(
    user_doc: Dict[str, Any],
    ip_address: str = "unknown",
    user_agent: str = "unknown",
) -> Tuple[str, str, str]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session_id = f"SES-{uuid.uuid4().hex[:12].upper()}"

    user_id = user_doc["user_id"]
    email = user_doc["email"]
    username = user_doc["username"]
    role = user_doc.get("role", "trader")

    access_token = create_access_token(user_id=user_id, email=email, role=role, session_id=session_id, username=username)
    refresh_token, refresh_jti = create_refresh_token(user_id=user_id, session_id=session_id)

    db_manager.collection("sessions").insert_one({
        "session_id": session_id,
        "user_id": user_id,
        "refresh_token_hash": hash_token_identifier(refresh_token),
        "refresh_jti": refresh_jti,
        "ip_address": ip_address,
        "user_agent": user_agent[:250],
        "created_at": now.isoformat(),
        "last_used_at": now.isoformat(),
        "expires_at": expires_at,
        "is_revoked": False,
    })

    db_manager.collection("login_history").insert_one({
        "event_id": f"LGN-{uuid.uuid4().hex[:10].upper()}",
        "user_id": user_id,
        "session_id": session_id,
        "ip_address": ip_address,
        "user_agent": user_agent[:250],
        "status": "SUCCESS",
        "logged_in_at": now.isoformat(),
    })

    return access_token, refresh_token, session_id


def check_rate_limit(identifier: str, action: str = "auth"):
    allowed, retry_after = auth_rate_limiter.check(
        f"{action}:{identifier}",
        max_requests=settings.RATE_LIMIT_AUTH_PER_MIN,
        window_seconds=60,
    )
    if not allowed:
        raise AuthError(f"Too many requests. Please try again in {retry_after} seconds.", status_code=429)


def register_user(
    email: str,
    password: str,
    full_name: str,
    username: Optional[str] = None,
    mobile_number: Optional[str] = None,
    experience_level: str = "beginner",
    trading_style: str = "intraday_momentum",
    ip_address: str = "unknown",
    user_agent: str = "unknown",
    role: str = "trader",
) -> Dict[str, Any]:
    check_rate_limit(ip_address, "register")

    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        raise AuthError("Valid email address is required", 400)

    users_col = db_manager.collection("users")
    if users_col.find_one({"email": email_norm}):
        raise AuthError("An account with this email already exists", 409)

    if username:
        uname_clean = username.strip().lower()
        if users_col.find_one({"username": uname_clean}):
            raise AuthError("Username is already taken", 409)
        final_username = uname_clean
    else:
        final_username = _generate_unique_username(email_norm)

    user_id = f"USR-{uuid.uuid4().hex[:10].upper()}"
    now_iso = _now_iso()
    verify_otp = f"{secrets.randbelow(900000) + 100000}"
    clean_full_name = (full_name or final_username).strip()
    trading_name = _resolve_unique_trading_name(clean_full_name, final_username, user_id)

    user_doc = {
        "user_id": user_id,
        "email": email_norm,
        "username": final_username,
        "full_name": clean_full_name,
        "name": clean_full_name,
        "trading_profile_name": trading_name,
        "mobile_number": mobile_number,
        "profile_image": None,
        "password_hash": hash_password(password),
        "role": role,
        "account_status": "active",
        "is_email_verified": False,
        "email_verify_otp_hash": hash_token_identifier(verify_otp),
        "email_verify_expires_at": time.time() + (settings.EMAIL_VERIFY_EXPIRE_HOURS * 3600),
        "experience_level": experience_level,
        "trading_style": trading_style,
        "preferred_timeframe": "15m",
        "risk_profile": "moderate",
        "subscription_plan": "free",
        "registered_at": now_iso,
        "created_at": now_iso,
        "last_login_at": now_iso,
    }

    users_col.insert_one(user_doc)

    # Create default user preferences
    db_manager.collection("preferences").update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "theme": "dark",
                "default_chart_interval": "15m",
                "sound_alerts": True,
                "email_notifications": True,
                "telegram_notifications": False,
                "daily_loss_limit_pct": 5.0,
                "updated_at": now_iso,
            }
        },
        upsert=True,
    )

    # Provision default isolated Paper Trading account (₹1,00,000)
    db_manager.collection("paper_accounts").insert_one({
        "account_id": f"ACC-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "name": "Primary AI Paper Account",
        "virtual_capital": 100000.0,
        "available_balance": 100000.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_trades": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "max_drawdown_pct": 0.0,
        "is_default": True,
        "circuit_breaker_triggered": False,
        "created_at": now_iso,
    })

    # Provision free subscription record
    db_manager.collection("subscriptions").insert_one({
        "subscription_id": f"SUB-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "plan_code": "free",
        "status": "active",
        "started_at": now_iso,
        "expires_at": None,
    })

    # Send welcome notification
    db_manager.collection("notifications").insert_one({
        "notification_id": f"NTF-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "title": "Welcome to FinGroww AI Terminal!",
        "message": "Your ₹1,00,000 virtual paper trading account is active. Verify your email to unlock full account security.",
        "category": "system",
        "is_read": False,
        "created_at": now_iso,
    })

    ensure_paper_and_broker_user(user_doc)
    access_token, refresh_token, _ = _create_session_and_tokens(user_doc, ip_address, user_agent)
    record_audit_log(user_id, role, "USER_REGISTER", f"users/{user_id}", ip_address)

    resp = {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": _sanitize_user(user_doc),
    }
    # In local/dev environment expose verification OTP for easy testing when SMTP isn't configured
    if not settings.SMTP_HOST:
        resp["verification_otp_dev"] = verify_otp
    return resp


def verify_email(email: str, otp_or_token: str, ip_address: str = "unknown") -> Dict[str, Any]:
    email_norm = (email or "").strip().lower()
    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"email": email_norm})
    if not user_doc:
        raise AuthError("User account not found", 404)

    if user_doc.get("is_email_verified"):
        return {"ok": True, "message": "Email is already verified"}

    # Check either signed JWT action token or 6-digit OTP
    valid = False
    decoded = decode_jwt(otp_or_token, expected_type="action")
    if decoded and decoded.get("action") == "verify_email" and decoded.get("email") == email_norm:
        valid = True
    else:
        exp_ts = user_doc.get("email_verify_expires_at") or 0
        stored_otp_hash = user_doc.get("email_verify_otp_hash")
        if stored_otp_hash and time.time() <= exp_ts:
            if hash_token_identifier(otp_or_token.strip()) == stored_otp_hash:
                valid = True

    if not valid:
        raise AuthError("Invalid or expired verification code", 400)

    users_col.update_one(
        {"user_id": user_doc["user_id"]},
        {"$set": {"is_email_verified": True, "email_verify_otp_hash": None}},
    )
    record_audit_log(user_doc["user_id"], user_doc.get("role", "trader"), "EMAIL_VERIFIED", f"users/{user_doc['user_id']}", ip_address)
    return {"ok": True, "message": "Email verified successfully"}


def resend_verification(email: str) -> Dict[str, Any]:
    email_norm = (email or "").strip().lower()
    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"email": email_norm})
    if not user_doc:
        raise AuthError("User account not found", 404)

    verify_otp = f"{secrets.randbelow(900000) + 100000}"
    users_col.update_one(
        {"user_id": user_doc["user_id"]},
        {
            "$set": {
                "email_verify_otp_hash": hash_token_identifier(verify_otp),
                "email_verify_expires_at": time.time() + (settings.EMAIL_VERIFY_EXPIRE_HOURS * 3600),
            }
        },
    )
    out: Dict[str, Any] = {"ok": True, "message": "Verification code regenerated"}
    if not settings.SMTP_HOST:
        out["verification_otp_dev"] = verify_otp
    return out


def login_user(
    email: str,
    password: str,
    ip_address: str = "unknown",
    user_agent: str = "unknown",
) -> Dict[str, Any]:
    check_rate_limit(ip_address, "login")

    email_norm = (email or "").strip().lower()
    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"email": email_norm})

    if not user_doc:
        raise AuthError("Invalid email or password", 401)

    status = user_doc.get("account_status", "active")
    if status in ("suspended", "banned", "deleted"):
        raise AuthError(f"Account is {status}. Please contact FinGroww support.", 403)

    is_valid, needs_rehash = verify_password(password, user_doc.get("password_hash", ""))
    if not is_valid:
        db_manager.collection("login_history").insert_one({
            "event_id": f"LGN-{uuid.uuid4().hex[:10].upper()}",
            "user_id": user_doc["user_id"],
            "ip_address": ip_address,
            "user_agent": user_agent[:250],
            "status": "FAILED_INVALID_PASSWORD",
            "logged_in_at": _now_iso(),
        })
        raise AuthError("Invalid email or password", 401)

    now_iso = _now_iso()
    update_fields: Dict[str, Any] = {"last_login_at": now_iso}
    if needs_rehash:
        # Transparent cryptographic upgrade from legacy SHA-256 to salted scrypt!
        update_fields["password_hash"] = hash_password(password)
        logger.info("Upgraded legacy password hash to scrypt for user %s", user_doc["user_id"])

    # Ensure profile completeness for migrated legacy users
    if not user_doc.get("username"):
        update_fields["username"] = _generate_unique_username(email_norm)
        user_doc["username"] = update_fields["username"]
    if not user_doc.get("full_name"):
        update_fields["full_name"] = user_doc.get("name") or user_doc["username"]
        user_doc["full_name"] = update_fields["full_name"]
    if not user_doc.get("trading_profile_name"):
        update_fields["trading_profile_name"] = _resolve_unique_trading_name(
            user_doc["full_name"], user_doc["username"], user_doc["user_id"]
        )
        user_doc["trading_profile_name"] = update_fields["trading_profile_name"]

    users_col.update_one({"user_id": user_doc["user_id"]}, {"$set": update_fields})
    user_doc.update(update_fields)

    ensure_paper_and_broker_user(user_doc)
    access_token, refresh_token, _ = _create_session_and_tokens(user_doc, ip_address, user_agent)
    record_audit_log(user_doc["user_id"], user_doc.get("role", "trader"), "USER_LOGIN", f"users/{user_doc['user_id']}", ip_address)

    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": _sanitize_user(user_doc),
    }


def google_auth(
    id_token: str,
    ip_address: str = "unknown",
    user_agent: str = "unknown",
    verified_google_claims: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Authenticates via Google OAuth2 ID Token (verifying against Google tokeninfo endpoint)."""
    claims = verified_google_claims
    if not claims:
        try:
            r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token}, timeout=6)
            if r.status_code != 200:
                raise AuthError("Invalid Google authentication token", 401)
            claims = r.json()
            if settings.GOOGLE_CLIENT_ID and claims.get("aud") != settings.GOOGLE_CLIENT_ID:
                raise AuthError("Google Client ID mismatch", 401)
        except AuthError:
            raise
        except Exception:
            raise AuthError("Failed to verify Google authentication token", 401)

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise AuthError("Google profile did not provide an email address", 400)

    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"email": email})
    now_iso = _now_iso()

    if not user_doc:
        # Auto-provision account for Google user
        full_name = claims.get("name") or email.split("@")[0]
        user_id = f"USR-{uuid.uuid4().hex[:10].upper()}"
        uname = _generate_unique_username(email)
        tname = _resolve_unique_trading_name(full_name, uname, user_id)
        user_doc = {
            "user_id": user_id,
            "email": email,
            "username": uname,
            "full_name": full_name,
            "name": full_name,
            "trading_profile_name": tname,
            "profile_image": claims.get("picture"),
            "password_hash": hash_password(secrets.token_urlsafe(24)),
            "auth_provider": "google",
            "role": "trader",
            "account_status": "active",
            "is_email_verified": True,
            "experience_level": "beginner",
            "trading_style": "intraday_momentum",
            "preferred_timeframe": "15m",
            "risk_profile": "moderate",
            "subscription_plan": "free",
            "registered_at": now_iso,
            "created_at": now_iso,
            "last_login_at": now_iso,
        }
        users_col.insert_one(user_doc)
        db_manager.collection("paper_accounts").insert_one({
            "account_id": f"ACC-{uuid.uuid4().hex[:8].upper()}",
            "user_id": user_id,
            "name": "Primary AI Paper Account",
            "virtual_capital": 100000.0,
            "available_balance": 100000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "max_drawdown_pct": 0.0,
            "is_default": True,
            "circuit_breaker_triggered": False,
            "created_at": now_iso,
        })
    else:
        if user_doc.get("account_status") in ("suspended", "banned", "deleted"):
            raise AuthError(f"Account is {user_doc.get('account_status')}", 403)
        users_col.update_one(
            {"user_id": user_doc["user_id"]},
            {"$set": {"last_login_at": now_iso, "is_email_verified": True}},
        )

    ensure_paper_and_broker_user(user_doc)
    access_token, refresh_token, _ = _create_session_and_tokens(user_doc, ip_address, user_agent)
    record_audit_log(user_doc["user_id"], user_doc.get("role", "trader"), "GOOGLE_LOGIN", f"users/{user_doc['user_id']}", ip_address)
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": _sanitize_user(user_doc),
    }


def refresh_tokens(refresh_token: str, ip_address: str = "unknown", user_agent: str = "unknown") -> Dict[str, Any]:
    decoded = decode_jwt(refresh_token, expected_type="refresh")
    if not decoded:
        raise AuthError("Invalid or expired refresh token", 401)

    session_id = decoded.get("sid")
    user_id = decoded.get("sub")
    sessions_col = db_manager.collection("sessions")
    session_doc = sessions_col.find_one({"session_id": session_id, "user_id": user_id})

    if not session_doc or session_doc.get("is_revoked"):
        raise AuthError("Session has been revoked", 401)

    if session_doc.get("refresh_token_hash") != hash_token_identifier(refresh_token):
        # Token reuse detected: revoke session immediately for safety
        sessions_col.update_one({"session_id": session_id}, {"$set": {"is_revoked": True}})
        raise AuthError("Refresh token mismatch — session revoked", 401)

    user_doc = db_manager.collection("users").find_one({"user_id": user_id})
    if not user_doc or user_doc.get("account_status") in ("suspended", "banned", "deleted"):
        raise AuthError("User account inactive", 403)

    new_access = create_access_token(
        user_id=user_id,
        email=user_doc["email"],
        role=user_doc.get("role", "trader"),
        session_id=session_id,
        username=user_doc["username"],
    )
    new_refresh, new_jti = create_refresh_token(user_id=user_id, session_id=session_id)

    sessions_col.update_one(
        {"session_id": session_id},
        {
            "$set": {
                "refresh_token_hash": hash_token_identifier(new_refresh),
                "refresh_jti": new_jti,
                "last_used_at": _now_iso(),
                "ip_address": ip_address,
            }
        },
    )

    return {
        "ok": True,
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": _sanitize_user(user_doc),
    }


def logout_user(session_id: str, user_id: str, ip_address: str = "unknown") -> Dict[str, Any]:
    db_manager.collection("sessions").update_one(
        {"session_id": session_id, "user_id": user_id},
        {"$set": {"is_revoked": True, "revoked_at": _now_iso()}},
    )
    record_audit_log(user_id, "trader", "USER_LOGOUT", f"sessions/{session_id}", ip_address)
    return {"ok": True, "message": "Logged out successfully"}


def forgot_password(email: str, ip_address: str = "unknown") -> Dict[str, Any]:
    check_rate_limit(ip_address, "forgot_pw")
    email_norm = (email or "").strip().lower()
    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"email": email_norm})

    # Always return generic message to avoid user enumeration
    if not user_doc:
        return {"ok": True, "message": "If an account exists for this email, a reset link has been generated."}

    reset_token = create_action_token(
        user_id=user_doc["user_id"],
        email=email_norm,
        action="password_reset",
        expires_seconds=settings.PASSWORD_RESET_EXPIRE_MINUTES * 60,
    )
    users_col.update_one(
        {"user_id": user_doc["user_id"]},
        {"$set": {"password_reset_token_hash": hash_token_identifier(reset_token)}},
    )
    record_audit_log(user_doc["user_id"], user_doc.get("role", "trader"), "FORGOT_PASSWORD_REQUEST", f"users/{user_doc['user_id']}", ip_address)

    resp: Dict[str, Any] = {"ok": True, "message": "If an account exists for this email, a reset link has been generated."}
    if not settings.SMTP_HOST:
        resp["reset_token_dev"] = reset_token
    return resp


def reset_password(token: str, new_password: str, ip_address: str = "unknown") -> Dict[str, Any]:
    decoded = decode_jwt(token, expected_type="action")
    if not decoded or decoded.get("action") != "password_reset":
        raise AuthError("Invalid or expired password reset token", 400)

    user_id = decoded.get("sub")
    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"user_id": user_id})
    if not user_doc:
        raise AuthError("User account not found", 404)

    if user_doc.get("password_reset_token_hash") != hash_token_identifier(token):
        raise AuthError("Reset token already used or invalidated", 400)

    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "password_hash": hash_password(new_password),
                "password_reset_token_hash": None,
            }
        },
    )
    # Revoke all existing sessions for security
    db_manager.collection("sessions").update_many(
        {"user_id": user_id},
        {"$set": {"is_revoked": True, "revoked_at": _now_iso()}},
    )
    record_audit_log(user_id, user_doc.get("role", "trader"), "PASSWORD_RESET_COMPLETE", f"users/{user_id}", ip_address)
    return {"ok": True, "message": "Password reset successfully. Please log in with your new password."}


def get_user_from_access_token(token: str) -> Optional[Dict[str, Any]]:
    decoded = decode_jwt(token, expected_type="access")
    if not decoded:
        return None
    user_id = decoded.get("sub")
    session_id = decoded.get("sid")
    if not user_id:
        return None

    # Check active session not revoked
    if session_id:
        ses = db_manager.collection("sessions").find_one({"session_id": session_id, "user_id": user_id})
        if not ses or ses.get("is_revoked"):
            return None

    user_doc = db_manager.collection("users").find_one({"user_id": user_id})
    if not user_doc or user_doc.get("account_status") in ("suspended", "banned", "deleted"):
        return None

    sanitized = _sanitize_user(user_doc)
    sanitized["session_id"] = session_id
    return sanitized


def update_user_profile(user_id: str, updates: Dict[str, Any], ip_address: str = "unknown") -> Dict[str, Any]:
    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"user_id": user_id})
    if not user_doc:
        raise AuthError("User not found", 404)

    allowed_fields = {
        "full_name", "username", "mobile_number", "profile_image",
        "experience_level", "trading_style", "preferred_timeframe", "risk_profile",
    }
    clean_updates: Dict[str, Any] = {}
    for k, v in updates.items():
        if k in allowed_fields and v is not None:
            if k == "username":
                uname = str(v).strip().lower()
                existing = users_col.find_one({"username": uname})
                if existing and existing.get("user_id") != user_id:
                    raise AuthError("Username is already taken", 409)
                clean_updates["username"] = uname
            else:
                clean_updates[k] = v

    if "full_name" in clean_updates:
        clean_updates["name"] = clean_updates["full_name"]

    if clean_updates:
        clean_updates["updated_at"] = _now_iso()
        users_col.update_one({"user_id": user_id}, {"$set": clean_updates})

    prefs = updates.get("preferences")
    if isinstance(prefs, dict):
        prefs_data = {**prefs, "user_id": user_id, "updated_at": _now_iso()}
        db_manager.collection("preferences").update_one(
            {"user_id": user_id}, {"$set": prefs_data}, upsert=True
        )

    updated_doc = users_col.find_one({"user_id": user_id})
    record_audit_log(user_id, updated_doc.get("role", "trader"), "PROFILE_UPDATE", f"users/{user_id}", ip_address)
    return {"ok": True, "user": _sanitize_user(updated_doc)}


def get_user_preferences(user_id: str) -> Dict[str, Any]:
    pref = db_manager.collection("preferences").find_one({"user_id": user_id}, {"_id": 0})
    return pref or {
        "user_id": user_id,
        "theme": "dark",
        "default_chart_interval": "15m",
        "sound_alerts": True,
        "email_notifications": True,
        "telegram_notifications": False,
        "daily_loss_limit_pct": 5.0,
    }


def list_active_sessions(user_id: str, current_session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = list(db_manager.collection("sessions").find({"user_id": user_id, "is_revoked": False}, {"_id": 0, "refresh_token_hash": 0, "refresh_jti": 0}).sort("last_used_at", -1))
    for r in rows:
        r["is_current"] = (r.get("session_id") == current_session_id)
    return rows


def revoke_session(user_id: str, target_session_id: str, ip_address: str = "unknown") -> Dict[str, Any]:
    res = db_manager.collection("sessions").update_one(
        {"session_id": target_session_id, "user_id": user_id},
        {"$set": {"is_revoked": True, "revoked_at": _now_iso()}},
    )
    if res.matched_count == 0:
        raise AuthError("Session not found or unauthorized", 404)
    record_audit_log(user_id, "trader", "SESSION_REVOKED", f"sessions/{target_session_id}", ip_address)
    return {"ok": True, "message": "Session revoked"}


def get_login_history(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    return list(
        db_manager.collection("login_history")
        .find({"user_id": user_id}, {"_id": 0})
        .sort("logged_in_at", -1)
        .limit(min(limit, 100))
    )


def delete_account(user_id: str, password: str, confirmation_text: str, ip_address: str = "unknown") -> Dict[str, Any]:
    if confirmation_text.strip() != "DELETE":
        raise AuthError("Confirmation text must be exactly 'DELETE'", 400)

    users_col = db_manager.collection("users")
    user_doc = users_col.find_one({"user_id": user_id})
    if not user_doc:
        raise AuthError("User not found", 404)

    is_valid, _ = verify_password(password, user_doc.get("password_hash", ""))
    if not is_valid:
        raise AuthError("Incorrect password confirmation", 401)

    # Anonymize user & revoke sessions while preserving anonymized audit log
    anonymized_email = f"deleted_{user_id.lower()}@deleted.fingroww.local"
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "email": anonymized_email,
                "username": f"deleted_{user_id.lower()}",
                "full_name": "Deleted User",
                "mobile_number": None,
                "profile_image": None,
                "password_hash": hash_password(secrets.token_urlsafe(32)),
                "account_status": "deleted",
                "deleted_at": _now_iso(),
            }
        },
    )
    db_manager.collection("sessions").update_many(
        {"user_id": user_id},
        {"$set": {"is_revoked": True, "revoked_at": _now_iso()}},
    )
    record_audit_log(user_id, user_doc.get("role", "trader"), "ACCOUNT_DELETED", f"users/{user_id}", ip_address)
    return {"ok": True, "message": "Account permanently deleted and all sessions revoked"}
