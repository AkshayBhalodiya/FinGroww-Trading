"""
FinGroww SaaS Platform — Flask Parity Blueprint for Phase 5 (Subscriptions, Billing Webhooks & Academy LMS).
"""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from backend.schemas import (
    AcademyProgressUpdateRequest,
    PaymentWebhookPayload,
    SubscriptionCheckoutRequest,
)
from backend.services import academy_service, billing_service
from backend.services.auth_service import get_user_from_access_token
from routes.auth_v2_routes import _client_ip, _validation_error_response, require_jwt_auth

phase5_v2_bp = Blueprint("phase5_v2_api", __name__)


@phase5_v2_bp.get("/api/v2/subscriptions/plans")
def v2_list_plans():
    return jsonify({"ok": True, "plans": billing_service.list_plans()})


@phase5_v2_bp.get("/api/v2/subscriptions/me")
@require_jwt_auth
def v2_get_my_billing(user):
    return jsonify(billing_service.get_my_billing_overview(user["user_id"]))


@phase5_v2_bp.post("/api/v2/subscriptions/checkout")
@require_jwt_auth
def v2_create_checkout(user):
    try:
        payload = SubscriptionCheckoutRequest.model_validate(request.get_json(silent=True) or {})
        res = billing_service.create_checkout_order(user, payload.plan_code, payload.billing_cycle)
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)


@phase5_v2_bp.post("/api/v2/subscriptions/webhook")
def v2_payment_webhook():
    raw_body = request.get_data() or b""
    sig = request.headers.get("X-FinGroww-Signature", "")
    try:
        payload = PaymentWebhookPayload.model_validate_json(raw_body)
        return jsonify(
            billing_service.process_payment_webhook(
                raw_body=raw_body,
                signature=sig,
                payload=payload.model_dump(),
                ip=_client_ip(),
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except billing_service.BillingError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase5_v2_bp.post("/api/v2/subscriptions/cancel")
@require_jwt_auth
def v2_cancel_subscription(user):
    try:
        return jsonify(billing_service.cancel_my_subscription(user["user_id"], _client_ip()))
    except billing_service.BillingError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase5_v2_bp.get("/api/v2/subscriptions/invoices/<invoice_id>")
@require_jwt_auth
def v2_get_invoice(user, invoice_id):
    try:
        return jsonify(billing_service.get_invoice(user["user_id"], invoice_id))
    except billing_service.BillingError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase5_v2_bp.get("/api/v2/academy/courses")
def v2_academy_courses():
    user_id = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        u = get_user_from_access_token(auth_header.split(" ", 1)[1].strip())
        if u:
            user_id = u["user_id"]
    return jsonify(academy_service.list_courses_with_progress(user_id=user_id))


@phase5_v2_bp.post("/api/v2/academy/progress")
@require_jwt_auth
def v2_academy_progress(user):
    try:
        payload = AcademyProgressUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            academy_service.mark_lesson_complete(
                user_id=user["user_id"],
                course_id=payload.course_id,
                lesson_id=payload.lesson_id,
                quiz_score_pct=payload.quiz_score_pct,
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except academy_service.AcademyError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code
