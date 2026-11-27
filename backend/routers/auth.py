"""
FinGroww SaaS Platform — FastAPI v2 Authentication Router (/api/v2/auth/*).
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.dependencies import get_client_ip, get_current_user
from backend.schemas import (
    DeleteAccountRequest,
    EmailVerifyRequest,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    RefreshTokenRequest,
    ResendVerifyRequest,
    ResetPasswordRequest,
    UserLoginRequest,
    UserRegisterRequest,
)
from backend.services import auth_service

router = APIRouter(prefix="/api/v2/auth", tags=["Authentication v2"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: UserRegisterRequest, request: Request) -> Dict[str, Any]:
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "unknown")
    try:
        return auth_service.register_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            username=payload.username,
            mobile_number=payload.mobile_number,
            experience_level=payload.experience_level,
            trading_style=payload.trading_style,
            ip_address=ip,
            user_agent=ua,
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/verify-email")
def verify_email(payload: EmailVerifyRequest, request: Request) -> Dict[str, Any]:
    try:
        return auth_service.verify_email(payload.email, payload.otp_or_token, get_client_ip(request))
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/resend-verification")
def resend_verification(payload: ResendVerifyRequest) -> Dict[str, Any]:
    try:
        return auth_service.resend_verification(payload.email)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/login")
def login(payload: UserLoginRequest, request: Request) -> Dict[str, Any]:
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "unknown")
    try:
        return auth_service.login_user(
            email=payload.email,
            password=payload.password,
            ip_address=ip,
            user_agent=ua,
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/google")
def google_login(payload: GoogleAuthRequest, request: Request) -> Dict[str, Any]:
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "unknown")
    try:
        return auth_service.google_auth(id_token=payload.id_token, ip_address=ip, user_agent=ua)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/refresh")
def refresh(payload: RefreshTokenRequest, request: Request) -> Dict[str, Any]:
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "unknown")
    try:
        return auth_service.refresh_tokens(payload.refresh_token, ip_address=ip, user_agent=ua)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/logout")
def logout(request: Request, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return auth_service.logout_user(
        session_id=user.get("session_id", ""),
        user_id=user["user_id"],
        ip_address=get_client_ip(request),
    )


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request) -> Dict[str, Any]:
    try:
        return auth_service.forgot_password(payload.email, get_client_ip(request))
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request) -> Dict[str, Any]:
    try:
        return auth_service.reset_password(payload.token, payload.new_password, get_client_ip(request))
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.delete("/account")
def delete_account(
    payload: DeleteAccountRequest,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return auth_service.delete_account(
            user_id=user["user_id"],
            password=payload.password,
            confirmation_text=payload.confirmation_text,
            ip_address=get_client_ip(request),
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
