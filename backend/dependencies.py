"""
FinGroww SaaS Platform — FastAPI Authentication & RBAC Dependencies.
"""

from typing import Any, Dict, Optional
from fastapi import Depends, Header, HTTPException, Request, status

from backend.security import has_permission
from backend.services.auth_service import get_user_from_access_token


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def get_current_user(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    user = get_user_from_access_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed_roles: str):
    """Dependency enforcing that the authenticated user belongs to one of allowed_roles."""
    allowed_set = {r.lower() for r in allowed_roles}

    def _checker(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        role = (user.get("role") or "trader").lower()
        if role == "super_admin" or role in allowed_set:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient role privileges. Required: {', '.join(allowed_roles)}",
        )

    return _checker


def require_permission(perm: str):
    """Dependency enforcing granular RBAC permission."""

    def _checker(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        role = (user.get("role") or "trader").lower()
        if has_permission(role, perm):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {perm}",
        )

    return _checker
