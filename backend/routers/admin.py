"""
FinGroww SaaS Platform — FastAPI v2 Admin Control Centre & Support Centre Router.
Strict RBAC enforcement on every endpoint.
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.dependencies import get_client_ip, get_current_user, require_permission, require_roles
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
from backend.services import admin_service

router = APIRouter(prefix="/api/v2", tags=["Admin & Support v2"])


# -------------------------------------------------------------------------
# ADMIN CONTROL CENTRE ENDPOINTS (/api/v2/admin/*)
# -------------------------------------------------------------------------
@router.get("/admin/stats")
def get_admin_stats(
    user: Dict[str, Any] = Depends(require_roles("super_admin", "admin", "analyst")),
) -> Dict[str, Any]:
    return admin_service.get_platform_stats()


@router.get("/admin/users")
def admin_list_users(
    search: str = Query(default=""),
    role: str = Query(default=""),
    status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: Dict[str, Any] = Depends(require_permission("users:read")),
) -> Dict[str, Any]:
    return admin_service.list_users_directory(search=search, role=role, status=status, page=page, page_size=page_size)


@router.post("/admin/users", status_code=201)
def admin_create_user(
    payload: AdminCreateUserRequest,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("users:write")),
) -> Dict[str, Any]:
    try:
        return admin_service.admin_create_user(actor, payload.model_dump(), get_client_ip(request))
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/admin/users/{target_user_id}")
def admin_get_user_detail(
    target_user_id: str,
    user: Dict[str, Any] = Depends(require_permission("users:read")),
) -> Dict[str, Any]:
    try:
        return admin_service.get_user_detail(target_user_id)
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.put("/admin/users/{target_user_id}")
def admin_update_user(
    target_user_id: str,
    payload: AdminUserUpdateRequest,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("users:write")),
) -> Dict[str, Any]:
    try:
        return admin_service.admin_update_user(
            actor, target_user_id, payload.model_dump(exclude_unset=True), get_client_ip(request)
        )
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.delete("/admin/users/{target_user_id}")
def admin_delete_user(
    target_user_id: str,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("users:delete")),
) -> Dict[str, Any]:
    try:
        return admin_service.admin_delete_user(actor, target_user_id, get_client_ip(request))
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/admin/sessions")
def admin_list_sessions(
    actor: Dict[str, Any] = Depends(require_permission("users:read")),
) -> Dict[str, Any]:
    return admin_service.list_active_sessions()


@router.delete("/admin/sessions/{session_id}")
def admin_revoke_session(
    session_id: str,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("users:suspend")),
) -> Dict[str, Any]:
    try:
        return admin_service.revoke_session_by_id(actor, session_id, get_client_ip(request))
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.put("/admin/users/{target_user_id}/status")
def admin_update_user_status(
    target_user_id: str,
    payload: AdminUserStatusUpdateRequest,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("users:suspend")),
) -> Dict[str, Any]:
    try:
        return admin_service.update_user_status(
            actor, target_user_id, payload.account_status, payload.reason, get_client_ip(request)
        )
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.put("/admin/users/{target_user_id}/role")
def admin_update_user_role(
    target_user_id: str,
    payload: AdminUserRoleUpdateRequest,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("roles:assign")),
) -> Dict[str, Any]:
    try:
        return admin_service.update_user_role(actor, target_user_id, payload.role, get_client_ip(request))
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.put("/admin/users/{target_user_id}/subscription")
def admin_override_subscription(
    target_user_id: str,
    payload: AdminSubscriptionUpdateRequest,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("users:write")),
) -> Dict[str, Any]:
    try:
        return admin_service.admin_update_subscription(
            actor, target_user_id, payload.plan_code, payload.reason, get_client_ip(request)
        )
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/admin/audit-logs")
def admin_get_audit_logs(
    action: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    actor: Dict[str, Any] = Depends(require_permission("audit:read")),
) -> Dict[str, Any]:
    logs = admin_service.list_audit_logs(action_filter=action, limit=limit)
    return {"ok": True, "count": len(logs), "logs": logs}


@router.get("/admin/feature-flags")
def admin_get_feature_flags(
    actor: Dict[str, Any] = Depends(require_roles("super_admin", "admin")),
) -> Dict[str, Any]:
    flags = admin_service.get_feature_flags()
    return {"ok": True, "flags": flags}


@router.put("/admin/feature-flags/{key}")
def admin_toggle_feature_flag(
    key: str,
    payload: FeatureFlagUpdateRequest,
    request: Request,
    actor: Dict[str, Any] = Depends(require_roles("super_admin", "admin")),
) -> Dict[str, Any]:
    try:
        return admin_service.toggle_feature_flag(actor, key, payload.enabled, get_client_ip(request))
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/admin/tickets")
def admin_list_support_tickets(
    status: str = Query(default=""),
    actor: Dict[str, Any] = Depends(require_permission("tickets:manage")),
) -> Dict[str, Any]:
    tickets = admin_service.admin_list_tickets(status_filter=status)
    return {"ok": True, "count": len(tickets), "tickets": tickets}


@router.post("/admin/tickets/{ticket_id}/reply")
def admin_reply_support_ticket(
    ticket_id: str,
    payload: SupportTicketReplyRequest,
    request: Request,
    actor: Dict[str, Any] = Depends(require_permission("tickets:manage")),
) -> Dict[str, Any]:
    try:
        return admin_service.admin_reply_ticket(
            actor, ticket_id, payload.reply_message, payload.status, get_client_ip(request)
        )
    except admin_service.AdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


# -------------------------------------------------------------------------
# USER SUPPORT CENTRE ENDPOINTS (/api/v2/support/*)
# -------------------------------------------------------------------------
@router.get("/support/tickets")
def list_my_tickets(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    items = admin_service.list_user_tickets(user["user_id"])
    return {"ok": True, "count": len(items), "tickets": items}


@router.post("/support/tickets", status_code=201)
def create_my_ticket(
    payload: SupportTicketCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return admin_service.create_support_ticket(
        user, payload.subject, payload.message, payload.priority, payload.category
    )
