"""
FinGroww SaaS Platform — Subscription Centre, Payment Webhooks & Invoice Generator (Phase 5).
Implements HMAC-SHA256 webhook signature verification, idempotent payment capture,
plan upgrades, GST invoices, and cancellation tracking.
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.database import db_manager
from backend.services.auth_service import record_audit_log


class BillingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def sign_webhook_payload(raw_body: bytes) -> str:
    """Computes HMAC-SHA256 signature for payment webhook verification."""
    secret = settings.PAYMENT_WEBHOOK_SECRET.encode("utf-8")
    return hmac.new(secret, raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, provided_sig: str) -> bool:
    if not provided_sig:
        return False
    expected = sign_webhook_payload(raw_body)
    return hmac.compare_digest(expected, provided_sig.strip().lower())


def list_plans() -> List[Dict[str, Any]]:
    return list(db_manager.collection("plans").find({}, {"_id": 0}))


def get_my_billing_overview(user_id: str) -> Dict[str, Any]:
    user_doc = db_manager.collection("users").find_one({"user_id": user_id}, {"_id": 0, "password_hash": 0}) or {}
    sub = db_manager.collection("subscriptions").find_one({"user_id": user_id, "status": "active"}, {"_id": 0})
    payments = list(db_manager.collection("payments").find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1))
    invoices = list(db_manager.collection("invoices").find({"user_id": user_id}, {"_id": 0}).sort("issued_at", -1))
    plan_code = user_doc.get("subscription_plan", "free")
    plan_doc = db_manager.collection("plans").find_one({"plan_code": plan_code}, {"_id": 0})

    return {
        "ok": True,
        "current_plan": plan_code,
        "plan_details": plan_doc,
        "active_subscription": sub,
        "payments": payments,
        "invoices": invoices,
    }


def create_checkout_order(user: Dict[str, Any], plan_code: str, billing_cycle: str = "monthly") -> Dict[str, Any]:
    plan_doc = db_manager.collection("plans").find_one({"plan_code": plan_code}, {"_id": 0})
    base_price = float(plan_doc.get("price_inr", 1499.0)) if plan_doc else 1499.0
    if plan_code == "enterprise" and not plan_doc:
        base_price = 4999.0
    amount = base_price if billing_cycle == "monthly" else round(base_price * 10.0, 2)  # 2 months free on annual

    now_iso = _now_iso()
    payment_id = f"PAY-{uuid.uuid4().hex[:10].upper()}"
    order = {
        "payment_id": payment_id,
        "user_id": user["user_id"],
        "plan_code": plan_code,
        "billing_cycle": billing_cycle,
        "amount_inr": amount,
        "currency": "INR",
        "status": "PENDING",
        "created_at": now_iso,
    }
    db_manager.collection("payments").insert_one(order)
    order.pop("_id", None)

    resp: Dict[str, Any] = {
        "ok": True,
        "checkout": order,
        "message": "Checkout order initialized. Complete payment via FinGroww gateway.",
    }
    if settings.ENVIRONMENT != "production":
        sample_payload = {
            "event": "payment.captured",
            "payment_id": payment_id,
            "user_id": user["user_id"],
            "plan_code": plan_code,
            "amount_inr": amount,
            "gateway_ref": f"GW-SANDBOX-{payment_id[-6:]}",
        }
        raw = json.dumps(sample_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        resp["dev_webhook_sample"] = {
            "payload": sample_payload,
            "raw_body_str": raw.decode("utf-8"),
            "signature": sign_webhook_payload(raw),
        }
    return resp


def process_payment_webhook(raw_body: bytes, signature: str, payload: Dict[str, Any], ip: str = "unknown") -> Dict[str, Any]:
    if not verify_webhook_signature(raw_body, signature):
        raise BillingError("Invalid payment webhook HMAC signature", 401)

    payment_id = payload["payment_id"]
    user_id = payload["user_id"]
    event = payload["event"]
    plan_code = payload["plan_code"]
    amount_inr = float(payload["amount_inr"])
    now = _now_utc()
    now_iso = now.isoformat()

    pay_col = db_manager.collection("payments")
    existing = pay_col.find_one({"payment_id": payment_id})

    # Idempotency guard: if already captured, return OK without duplicating invoice/subscription
    if existing and existing.get("status") == "SUCCEEDED" and event == "payment.captured":
        return {"ok": True, "idempotent": True, "message": "Webhook already processed"}

    if event == "payment.failed":
        pay_col.update_one(
            {"payment_id": payment_id},
            {"$set": {"status": "FAILED", "failed_at": now_iso, "user_id": user_id, "plan_code": plan_code, "amount_inr": amount_inr}},
            upsert=True,
        )
        record_audit_log(user_id, "system", "PAYMENT_FAILED", f"payments/{payment_id}", ip, {"amount_inr": amount_inr})
        return {"ok": True, "status": "FAILED"}

    # payment.captured -> Upgrade subscription & generate GST invoice
    pay_col.update_one(
        {"payment_id": payment_id},
        {
            "$set": {
                "payment_id": payment_id,
                "user_id": user_id,
                "plan_code": plan_code,
                "amount_inr": amount_inr,
                "status": "SUCCEEDED",
                "gateway_ref": payload.get("gateway_ref"),
                "paid_at": now_iso,
            }
        },
        upsert=True,
    )

    # Upgrade user's plan and role (only promote 'trader' -> 'pro_trader', preserve admin roles)
    users_col = db_manager.collection("users")
    u_doc = users_col.find_one({"user_id": user_id})
    if u_doc:
        upd: Dict[str, Any] = {"subscription_plan": plan_code, "plan_updated_at": now_iso}
        if (u_doc.get("role") or "trader").lower() == "trader":
            upd["role"] = "pro_trader"
        users_col.update_one({"user_id": user_id}, {"$set": upd})

    # Replace previous active subscription
    subs_col = db_manager.collection("subscriptions")
    subs_col.update_many({"user_id": user_id, "status": "active"}, {"$set": {"status": "replaced", "ended_at": now_iso}})
    sub_id = f"SUB-{uuid.uuid4().hex[:8].upper()}"
    subs_col.insert_one({
        "subscription_id": sub_id,
        "user_id": user_id,
        "plan_code": plan_code,
        "payment_id": payment_id,
        "status": "active",
        "started_at": now_iso,
        "expires_at": (now + timedelta(days=30)).isoformat(),
    })

    # Generate GST Invoice (18% inclusive breakdown)
    base_amt = round(amount_inr / 1.18, 2)
    gst_amt = round(amount_inr - base_amt, 2)
    inv_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
    invoice = {
        "invoice_id": inv_id,
        "user_id": user_id,
        "payment_id": payment_id,
        "subscription_id": sub_id,
        "plan_code": plan_code,
        "base_amount_inr": base_amt,
        "gst_18_inr": gst_amt,
        "total_amount_inr": amount_inr,
        "currency": "INR",
        "issued_at": now_iso,
    }
    db_manager.collection("invoices").insert_one(invoice)
    invoice.pop("_id", None)

    db_manager.collection("notifications").insert_one({
        "notification_id": f"NTF-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "title": "Pro Algo Swarm Plan Activated!",
        "message": f"Payment ₹{amount_inr:,.2f} verified ({inv_id}). Multiple paper accounts & Pro Algo features unlocked.",
        "category": "billing",
        "is_read": False,
        "created_at": now_iso,
    })

    record_audit_log(user_id, "system", "SUBSCRIPTION_ACTIVATED", f"subscriptions/{sub_id}", ip, {"plan_code": plan_code, "invoice_id": inv_id})
    return {"ok": True, "subscription_id": sub_id, "invoice": invoice}


def cancel_my_subscription(user_id: str, ip: str = "unknown") -> Dict[str, Any]:
    now_iso = _now_iso()
    subs_col = db_manager.collection("subscriptions")
    active = subs_col.find_one({"user_id": user_id, "status": "active"})
    if not active or active.get("plan_code") == "free":
        raise BillingError("No active paid subscription found to cancel", 400)

    subs_col.update_one({"subscription_id": active["subscription_id"]}, {"$set": {"status": "cancelled", "cancelled_at": now_iso}})
    users_col = db_manager.collection("users")
    u_doc = users_col.find_one({"user_id": user_id}) or {}
    upd: Dict[str, Any] = {"subscription_plan": "free", "plan_updated_at": now_iso}
    if (u_doc.get("role") or "").lower() == "pro_trader":
        upd["role"] = "trader"
    users_col.update_one({"user_id": user_id}, {"$set": upd})

    record_audit_log(user_id, u_doc.get("role", "trader"), "SUBSCRIPTION_CANCELLED", f"subscriptions/{active['subscription_id']}", ip)
    return {"ok": True, "message": "Subscription cancelled and reverted to Free AI Paper plan"}


def get_invoice(user_id: str, invoice_id: str) -> Dict[str, Any]:
    inv = db_manager.collection("invoices").find_one({"user_id": user_id, "invoice_id": invoice_id}, {"_id": 0})
    if not inv:
        raise BillingError("Invoice not found or unauthorized", 404)
    return {"ok": True, "invoice": inv}
