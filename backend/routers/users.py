"""
FinGroww SaaS Platform — FastAPI v2 User Profile, Preferences & Session Router (/api/v2/users/*).
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request

from backend.dependencies import get_client_ip, get_current_user
from backend.schemas import UserProfileUpdateRequest
from backend.services import auth_service

router = APIRouter(prefix="/api/v2/users", tags=["User Management v2"])


@router.get("/me")
def get_my_profile(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    prefs = auth_service.get_user_preferences(user["user_id"])
    return {"ok": True, "user": user, "preferences": prefs}


@router.put("/me")
def update_my_profile(
    payload: UserProfileUpdateRequest,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        updates = payload.model_dump(exclude_none=True)
        res = auth_service.update_user_profile(user["user_id"], updates, get_client_ip(request))
        res["preferences"] = auth_service.get_user_preferences(user["user_id"])
        return res
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/me/sessions")
def get_my_sessions(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    sessions = auth_service.list_active_sessions(user["user_id"], user.get("session_id"))
    return {"ok": True, "count": len(sessions), "sessions": sessions}


@router.delete("/me/sessions/{session_id}")
def revoke_my_session(
    session_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return auth_service.revoke_session(user["user_id"], session_id, get_client_ip(request))
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/me/login-history")
def get_my_login_history(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    history = auth_service.get_login_history(user["user_id"])
    return {"ok": True, "count": len(history), "history": history}
