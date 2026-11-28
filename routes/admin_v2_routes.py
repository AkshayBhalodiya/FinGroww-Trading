"""
FinGroww SaaS Platform — Flask Parity Blueprint for Phase 4 Admin Control Centre & Support Desk.
"""

from functools import wraps
from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from backend.schemas import (
    AdminCreateUserRequest,
    AdminSubscriptionUpdateRequest,
    AdminUserRoleUpdateRequest,
    AdminUserStatusUpdateRequest,
    AdminUserUpdateRequest,
    FeatureFlagUpdateRequest,
    SupportTicketCreateRequest,
    SupportTicketReplyRequest,
)
from backend.security import has_permission
from backend.services import admin_service
from routes.auth_v2_routes import _client_ip, _validation_error_response, require_jwt_auth

admin_v2_bp = Blueprint("admin_v2_api", __name__)


def require_perm(perm: str):
    def decorator(fn):
        @wraps(fn)
        @require_jwt_auth
        def wrapper(user, *args, **kwargs):
            if not has_permission(user.get("role", "trader"), perm):
                return jsonify({"ok": False, "error": f"Insufficient permissions: {perm} required"}), 403
            return fn(user, *args, **kwargs)
        return wrapper
    return decorator


def require_any_role(*allowed_roles: str):
    allowed = {r.lower() for r in allowed_roles}

    def decorator(fn):
        @wraps(fn)
        @require_jwt_auth
        def wrapper(user, *args, **kwargs):
            role = (user.get("role") or "trader").lower()
            if role != "super_admin" and role not in allowed:
                return jsonify({"ok": False, "error": "Administrative access required"}), 403
            return fn(user, *args, **kwargs)
        return wrapper
    return decorator


@admin_v2_bp.get("/api/v2/admin/stats")
@require_any_role("super_admin", "admin", "analyst")
def v2_admin_stats(user):
    return jsonify(admin_service.get_platform_stats())


@admin_v2_bp.get("/api/v2/admin/users")
@require_perm("users:read")
def v2_admin_list_users(user):
    return jsonify(
        admin_service.list_users_directory(
            search=request.args.get("search", ""),
            role=request.args.get("role", ""),
            status=request.args.get("status", ""),
            page=max(1, int(request.args.get("page", 1))),
            page_size=min(100, max(1, int(request.args.get("page_size", 20)))),
        )
    )


@admin_v2_bp.get("/api/v2/admin/users/<target_user_id>")
@require_perm("users:read")
def v2_admin_get_user(user, target_user_id):
    try:
        return jsonify(admin_service.get_user_detail(target_user_id))
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.post("/api/v2/admin/users")
@require_perm("users:write")
def v2_admin_create_user(user):
    try:
        payload = AdminCreateUserRequest.model_validate(request.get_json(silent=True) or {})
        res = admin_service.admin_create_user(user, payload.model_dump(), _client_ip())
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.put("/api/v2/admin/users/<target_user_id>")
@require_perm("users:write")
def v2_admin_update_user(user, target_user_id):
    try:
        payload = AdminUserUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            admin_service.admin_update_user(
                user, target_user_id, payload.model_dump(exclude_none=True), _client_ip()
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.delete("/api/v2/admin/users/<target_user_id>")
@require_perm("users:delete")
def v2_admin_delete_user(user, target_user_id):
    try:
        return jsonify(admin_service.admin_delete_user(user, target_user_id, _client_ip()))
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.get("/api/v2/admin/sessions")
@require_perm("users:read")
def v2_admin_list_sessions(user):
    return jsonify(admin_service.list_active_sessions())


@admin_v2_bp.delete("/api/v2/admin/sessions/<session_id>")
@require_perm("users:suspend")
def v2_admin_revoke_session(user, session_id):
    try:
        return jsonify(admin_service.revoke_session_by_id(user, session_id, _client_ip()))
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.put("/api/v2/admin/users/<target_user_id>/status")
@require_perm("users:suspend")
def v2_admin_update_status(user, target_user_id):
    try:
        payload = AdminUserStatusUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            admin_service.update_user_status(
                user, target_user_id, payload.account_status, payload.reason, _client_ip()
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.put("/api/v2/admin/users/<target_user_id>/role")
@require_perm("roles:assign")
def v2_admin_update_role(user, target_user_id):
    try:
        payload = AdminUserRoleUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(admin_service.update_user_role(user, target_user_id, payload.role, _client_ip()))
    except ValidationError as exc:
        return _validation_error_response(exc)
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.put("/api/v2/admin/users/<target_user_id>/subscription")
@require_perm("users:write")
def v2_admin_override_sub(user, target_user_id):
    try:
        payload = AdminSubscriptionUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            admin_service.admin_update_subscription(
                user, target_user_id, payload.plan_code, payload.reason, _client_ip()
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.get("/api/v2/admin/audit-logs")
@require_perm("audit:read")
def v2_admin_audit_logs(user):
    logs = admin_service.list_audit_logs(
        action_filter=request.args.get("action", ""),
        limit=min(200, int(request.args.get("limit", 50))),
    )
    return jsonify({"ok": True, "count": len(logs), "logs": logs})


@admin_v2_bp.get("/api/v2/admin/feature-flags")
@require_any_role("super_admin", "admin")
def v2_admin_get_flags(user):
    return jsonify({"ok": True, "flags": admin_service.get_feature_flags()})


@admin_v2_bp.put("/api/v2/admin/feature-flags/<key>")
@require_any_role("super_admin", "admin")
def v2_admin_toggle_flag(user, key):
    try:
        payload = FeatureFlagUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(admin_service.toggle_feature_flag(user, key, payload.enabled, _client_ip()))
    except ValidationError as exc:
        return _validation_error_response(exc)
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.get("/api/v2/admin/tickets")
@require_perm("tickets:manage")
def v2_admin_list_tickets(user):
    tickets = admin_service.admin_list_tickets(status_filter=request.args.get("status", ""))
    return jsonify({"ok": True, "count": len(tickets), "tickets": tickets})


@admin_v2_bp.post("/api/v2/admin/tickets/<ticket_id>/reply")
@require_perm("tickets:manage")
def v2_admin_reply_ticket(user, ticket_id):
    try:
        payload = SupportTicketReplyRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            admin_service.admin_reply_ticket(user, ticket_id, payload.reply_message, payload.status, _client_ip())
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except admin_service.AdminServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@admin_v2_bp.get("/api/v2/support/tickets")
@require_jwt_auth
def v2_user_list_tickets(user):
    items = admin_service.list_user_tickets(user["user_id"])
    return jsonify({"ok": True, "count": len(items), "tickets": items})


@admin_v2_bp.post("/api/v2/support/tickets")
@require_jwt_auth
def v2_user_create_ticket(user):
    try:
        payload = SupportTicketCreateRequest.model_validate(request.get_json(silent=True) or {})
        res = admin_service.create_support_ticket(
            user, payload.subject, payload.message, payload.priority, payload.category
        )
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)
