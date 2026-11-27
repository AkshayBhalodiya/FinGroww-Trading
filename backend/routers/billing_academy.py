"""
FinGroww SaaS Platform — FastAPI v2 Subscriptions, Payment Webhooks & Academy LMS Router (Phase 5).
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from backend.dependencies import get_client_ip, get_current_user
from backend.schemas import (
    AcademyProgressUpdateRequest,
    PaymentWebhookPayload,
    SubscriptionCheckoutRequest,
)
from backend.services import academy_service, billing_service
from backend.services.auth_service import get_user_from_access_token

router = APIRouter(prefix="/api/v2", tags=["Subscriptions, Billing & Academy LMS v2"])


@router.get("/subscriptions/plans")
def get_plans() -> Dict[str, Any]:
    return {"ok": True, "plans": billing_service.list_plans()}


@router.get("/subscriptions/me")
def get_my_billing(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return billing_service.get_my_billing_overview(user["user_id"])


@router.post("/subscriptions/checkout", status_code=201)
def create_checkout(
    payload: SubscriptionCheckoutRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return billing_service.create_checkout_order(user, payload.plan_code, payload.billing_cycle)


@router.post("/subscriptions/webhook")
async def payment_webhook(
    request: Request,
    x_fingroww_signature: str = Header(default=""),
) -> Dict[str, Any]:
    raw_body = await request.body()
    try:
        payload = PaymentWebhookPayload.model_validate_json(raw_body)
        return billing_service.process_payment_webhook(
            raw_body=raw_body,
            signature=x_fingroww_signature,
            payload=payload.model_dump(),
            ip=get_client_ip(request),
        )
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/subscriptions/cancel")
def cancel_subscription(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return billing_service.cancel_my_subscription(user["user_id"], get_client_ip(request))
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/subscriptions/invoices/{invoice_id}")
def get_invoice(
    invoice_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return billing_service.get_invoice(user["user_id"], invoice_id)
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


# -------------------------------------------------------------------------
# ACADEMY LMS ENDPOINTS
# -------------------------------------------------------------------------
@router.get("/academy/courses")
def get_academy_courses(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    user_id = None
    if authorization and authorization.startswith("Bearer "):
        u = get_user_from_access_token(authorization.split(" ", 1)[1].strip())
        if u:
            user_id = u["user_id"]
    return academy_service.list_courses_with_progress(user_id=user_id)


@router.post("/academy/progress")
def update_academy_progress(
    payload: AcademyProgressUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return academy_service.mark_lesson_complete(
            user_id=user["user_id"],
            course_id=payload.course_id,
            lesson_id=payload.lesson_id,
            quiz_score_pct=payload.quiz_score_pct,
        )
    except academy_service.AcademyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
