#!/usr/bin/env python3
"""
FinGroww SaaS Modernisation (Phase 5) — Subscription Centre, HMAC Payment Webhooks,
GST Invoices & 4-Stage Academy LMS Test Suite.
"""

import json
import os
import tempfile
import unittest
import uuid

from backend.database import COLLECTION_NAMES, db_manager
from backend.security import auth_rate_limiter
from backend.services.billing_service import sign_webhook_payload
import fingroww_market_server as srv


class TestPhase5BillingAndAcademy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_rate_limiter._hits.clear()
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls._store_file = os.path.join(cls._tmp_dir.name, "test_phase5_store.json")
        db_manager._initialized = False
        db_manager._local_path = cls._store_file
        db_manager._local_store = {name: [] for name in COLLECTION_NAMES}
        db_manager._local_collections = {}
        db_manager.init(force_local=True)

        srv.app.testing = True
        cls.client = srv.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls._tmp_dir.cleanup()

    def setUp(self):
        auth_rate_limiter._hits.clear()

    def _register_user(self, prefix: str):
        email = f"{prefix}_{uuid.uuid4().hex[:6]}@fingroww.tech"
        r = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "Phase5User123",
            "full_name": f"{prefix.title()} Trader",
            "username": f"{prefix}_{uuid.uuid4().hex[:5]}",
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        return data["user"]["user_id"], {"Authorization": f"Bearer {data['access_token']}"}

    def test_01_checkout_webhook_hmac_verification_invoice_and_cancel(self):
        uid_a, hdr_a = self._register_user("bill_a")
        _, hdr_b = self._register_user("bill_b")

        # 1. Public plans list
        r_plans = self.client.get("/api/v2/subscriptions/plans")
        self.assertEqual(r_plans.status_code, 200)
        self.assertGreaterEqual(len(r_plans.get_json()["plans"]), 2)

        # 2. Checkout initialization
        r_chk = self.client.post("/api/v2/subscriptions/checkout", headers=hdr_a, json={
            "plan_code": "pro_algo_swarm",
            "billing_cycle": "monthly",
        })
        self.assertEqual(r_chk.status_code, 201)
        chk = r_chk.get_json()
        pay_id = chk["checkout"]["payment_id"]

        payload = {
            "event": "payment.captured",
            "payment_id": pay_id,
            "user_id": uid_a,
            "plan_code": "pro_algo_swarm",
            "amount_inr": 1499.0,
            "gateway_ref": "GW-LIVE-999",
        }
        raw_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        valid_sig = sign_webhook_payload(raw_bytes)

        # 3. Tampered / invalid signature rejected with 401
        r_bad = self.client.post(
            "/api/v2/subscriptions/webhook",
            data=raw_bytes,
            content_type="application/json",
            headers={"X-FinGroww-Signature": "0000deadbeef"},
        )
        self.assertEqual(r_bad.status_code, 401)
        self.assertEqual(self.client.get("/api/v2/subscriptions/me", headers=hdr_a).get_json()["current_plan"], "free")

        # 4. Valid HMAC signature upgrades user & issues GST invoice
        r_good = self.client.post(
            "/api/v2/subscriptions/webhook",
            data=raw_bytes,
            content_type="application/json",
            headers={"X-FinGroww-Signature": valid_sig},
        )
        self.assertEqual(r_good.status_code, 200)
        inv = r_good.get_json()["invoice"]
        inv_id = inv["invoice_id"]
        self.assertAlmostEqual(inv["base_amount_inr"] + inv["gst_18_inr"], 1499.0, places=2)

        # 5. Idempotent replay does not generate a second invoice
        r_dup = self.client.post(
            "/api/v2/subscriptions/webhook",
            data=raw_bytes,
            content_type="application/json",
            headers={"X-FinGroww-Signature": valid_sig},
        )
        self.assertEqual(r_dup.status_code, 200)
        self.assertTrue(r_dup.get_json().get("idempotent"))

        # 6. Verify upgraded plan & cross-user invoice isolation
        me_bill = self.client.get("/api/v2/subscriptions/me", headers=hdr_a).get_json()
        self.assertEqual(me_bill["current_plan"], "pro_algo_swarm")
        self.assertEqual(len(me_bill["invoices"]), 1)

        self.assertEqual(self.client.get(f"/api/v2/subscriptions/invoices/{inv_id}", headers=hdr_a).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v2/subscriptions/invoices/{inv_id}", headers=hdr_b).status_code, 404)

        # 7. Cancel subscription reverts to free
        r_cancel = self.client.post("/api/v2/subscriptions/cancel", headers=hdr_a)
        self.assertEqual(r_cancel.status_code, 200)
        self.assertEqual(self.client.get("/api/v2/subscriptions/me", headers=hdr_a).get_json()["current_plan"], "free")

    def test_02_academy_lms_courses_and_progress_tracking(self):
        _, hdr = self._register_user("acad_u")

        # Unauthenticated progress update blocked
        self.assertEqual(
            self.client.post("/api/v2/academy/progress", json={"course_id": "COURSE-01", "lesson_id": "L1-1"}).status_code,
            401,
        )

        # List 4 seeded courses
        r_courses = self.client.get("/api/v2/academy/courses", headers=hdr)
        self.assertEqual(r_courses.status_code, 200)
        c_data = r_courses.get_json()
        self.assertEqual(len(c_data["courses"]), 4)
        self.assertEqual(c_data["overall_progress_pct"], 0.0)

        # Complete all 4 lessons in COURSE-01
        for lid in ["L1-1", "L1-2", "L1-3", "L1-4"]:
            r_prog = self.client.post("/api/v2/academy/progress", headers=hdr, json={
                "course_id": "COURSE-01",
                "lesson_id": lid,
                "quiz_score_pct": 95.0,
            })
            self.assertEqual(r_prog.status_code, 200)

        final = r_prog.get_json()
        c1 = next(c for c in final["courses"] if c["course_id"] == "COURSE-01")
        self.assertTrue(c1["completed"])
        self.assertEqual(c1["progress_pct"], 100.0)
        self.assertGreater(final["overall_progress_pct"], 0.0)

    def test_03_fastapi_openapi_includes_phase5_routes(self):
        from backend.app import app as fastapi_app
        paths = set(fastapi_app.openapi().get("paths", {}).keys())
        self.assertIn("/api/v2/subscriptions/plans", paths)
        self.assertIn("/api/v2/subscriptions/checkout", paths)
        self.assertIn("/api/v2/subscriptions/webhook", paths)
        self.assertIn("/api/v2/academy/courses", paths)
        self.assertIn("/api/v2/academy/progress", paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
