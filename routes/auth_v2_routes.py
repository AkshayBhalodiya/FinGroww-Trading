"""
FinGroww Trading Intelligence — Flask Parity Blueprint for v2 Auth & User Management.
Allows existing Flask runtime (python fingroww_market_server.py / Gunicorn) to expose
all /api/v2/auth/* and /api/v2/users/* endpoints using the shared Pydantic + AuthService layer.
"""

from functools import wraps
from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from backend.database import db_manager
from backend.schemas import (
    DeleteAccountRequest,
    EmailVerifyRequest,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    RefreshTokenRequest,
    ResendVerifyRequest,
    ResetPasswordRequest,
    UserLoginRequest,
    UserProfileUpdateRequest,
    UserRegisterRequest,
)
from backend.security import has_permission
from backend.services import auth_service

auth_v2_bp = Blueprint("auth_v2_api", __name__)


def _client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _validation_error_response(exc: ValidationError):
    errs = exc.errors(include_context=False, include_url=False)
    msg = errs[0].get("msg", "Invalid input") if errs else "Validation error"
    return jsonify({"ok": False, "error": msg, "detail": errs}), 422


def require_jwt_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"ok": False, "error": "Missing or invalid Authorization Bearer token"}), 401
        token = auth_header.split(" ", 1)[1].strip()
        user = auth_service.get_user_from_access_token(token)
        if not user:
            return jsonify({"ok": False, "error": "Invalid, expired, or revoked access token"}), 401
        return fn(user, *args, **kwargs)
    return wrapper


@auth_v2_bp.get("/api/v2/health")
def v2_health_flask():
    db_manager.init()
    return jsonify({
        "ok": True,
        "engine": "Flask-FastAPI Hybrid Bridge",
        "db_mode": db_manager.mode,
    })


@auth_v2_bp.post("/api/v2/auth/register")
def v2_register():
    try:
        payload = UserRegisterRequest.model_validate(request.get_json(silent=True) or {})
        res = auth_service.register_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            username=payload.username,
            mobile_number=payload.mobile_number,
            experience_level=payload.experience_level,
            trading_style=payload.trading_style,
            ip_address=_client_ip(),
            user_agent=request.headers.get("User-Agent", "unknown"),
        )
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.post("/api/v2/auth/verify-email")
def v2_verify_email():
    try:
        payload = EmailVerifyRequest.model_validate(request.get_json(silent=True) or {})
        res = auth_service.verify_email(payload.email, payload.otp_or_token, _client_ip())
        return jsonify(res)
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.post("/api/v2/auth/resend-verification")
def v2_resend_verification():
    try:
        payload = ResendVerifyRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(auth_service.resend_verification(payload.email))
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.post("/api/v2/auth/login")
def v2_login():
    try:
        payload = UserLoginRequest.model_validate(request.get_json(silent=True) or {})
        res = auth_service.login_user(
            email=payload.email,
            password=payload.password,
            ip_address=_client_ip(),
            user_agent=request.headers.get("User-Agent", "unknown"),
        )
        return jsonify(res)
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.post("/api/v2/auth/google")
def v2_google_login():
    try:
        payload = GoogleAuthRequest.model_validate(request.get_json(silent=True) or {})
        res = auth_service.google_auth(
            id_token=payload.id_token,
            ip_address=_client_ip(),
            user_agent=request.headers.get("User-Agent", "unknown"),
        )
        return jsonify(res)
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.post("/api/v2/auth/refresh")
def v2_refresh():
    try:
        payload = RefreshTokenRequest.model_validate(request.get_json(silent=True) or {})
        res = auth_service.refresh_tokens(
            payload.refresh_token,
            ip_address=_client_ip(),
            user_agent=request.headers.get("User-Agent", "unknown"),
        )
        return jsonify(res)
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.post("/api/v2/auth/logout")
@require_jwt_auth
def v2_logout(user):
    res = auth_service.logout_user(user.get("session_id", ""), user["user_id"], _client_ip())
    return jsonify(res)


@auth_v2_bp.post("/api/v2/auth/forgot-password")
def v2_forgot_password():
    try:
        payload = ForgotPasswordRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(auth_service.forgot_password(payload.email, _client_ip()))
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.post("/api/v2/auth/reset-password")
def v2_reset_password():
    try:
        payload = ResetPasswordRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(auth_service.reset_password(payload.token, payload.new_password, _client_ip()))
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.delete("/api/v2/auth/account")
@require_jwt_auth
def v2_delete_account(user):
    try:
        payload = DeleteAccountRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            auth_service.delete_account(
                user["user_id"],
                payload.password,
                payload.confirmation_text,
                _client_ip(),
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.get("/api/v2/users/me")
@require_jwt_auth
def v2_get_me(user):
    prefs = auth_service.get_user_preferences(user["user_id"])
    return jsonify({"ok": True, "user": user, "preferences": prefs})


@auth_v2_bp.put("/api/v2/users/me")
@require_jwt_auth
def v2_update_me(user):
    try:
        payload = UserProfileUpdateRequest.model_validate(request.get_json(silent=True) or {})
        updates = payload.model_dump(exclude_none=True)
        res = auth_service.update_user_profile(user["user_id"], updates, _client_ip())
        res["preferences"] = auth_service.get_user_preferences(user["user_id"])
        return jsonify(res)
    except ValidationError as exc:
        return _validation_error_response(exc)
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.get("/api/v2/users/me/sessions")
@require_jwt_auth
def v2_get_sessions(user):
    sessions = auth_service.list_active_sessions(user["user_id"], user.get("session_id"))
    return jsonify({"ok": True, "count": len(sessions), "sessions": sessions})


@auth_v2_bp.delete("/api/v2/users/me/sessions/<session_id>")
@require_jwt_auth
def v2_revoke_session(user, session_id):
    try:
        return jsonify(auth_service.revoke_session(user["user_id"], session_id, _client_ip()))
    except auth_service.AuthError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@auth_v2_bp.get("/api/v2/users/me/login-history")
@require_jwt_auth
def v2_login_history(user):
    history = auth_service.get_login_history(user["user_id"])
    return jsonify({"ok": True, "count": len(history), "history": history})
