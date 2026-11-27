#!/usr/bin/env python3
"""
FinGroww SaaS Modernisation (Phase 4) — Super Admin Control Centre, RBAC & Support Desk Tests.
"""

import os
import tempfile
import unittest
import uuid

from backend.database import COLLECTION_NAMES, db_manager
from backend.security import auth_rate_limiter
import fingroww_market_server as srv


class TestPhase4AdminRBACAndSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_rate_limiter._hits.clear()
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls._store_file = os.path.join(cls._tmp_dir.name, "test_phase4_store.json")
        db_manager._initialized = False
        db_manager._local_path = cls._store_file
        db_manager._local_store = {name: [] for name in COLLECTION_NAMES}
        db_manager._local_collections = {}
        db_manager.init(force_local=True)

        srv.app.testing = True
        cls.client = srv.app.test_client()

    def setUp(self):
        auth_rate_limiter._hits.clear()

    @classmethod
    def tearDownClass(cls):
        cls._tmp_dir.cleanup()

    def _create_user_with_role(self, prefix: str, role: str = "trader"):
        email = f"{prefix}_{uuid.uuid4().hex[:6]}@fingroww.tech"
        pw = "AdminTest123"
        r = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": pw,
            "full_name": f"{prefix.title()} User",
            "username": f"{prefix}_{uuid.uuid4().hex[:5]}",
        })
        self.assertEqual(r.status_code, 201)
        uid = r.get_json()["user"]["user_id"]
        if role != "trader":
            db_manager.collection("users").update_one({"user_id": uid}, {"$set": {"role": role}})
        # Log in cleanly so JWT carries updated role claim
        login_res = self.client.post("/api/v2/auth/login", json={"email": email, "password": pw}).get_json()
        return uid, email, pw, {"Authorization": f"Bearer {login_res['access_token']}"}

    def test_01_rbac_strictly_blocks_normal_users_and_scopes_roles(self):
        uid_trader, _, _, hdr_trader = self._create_user_with_role("trd", "trader")
        _, _, _, hdr_support = self._create_user_with_role("sup", "support")
        _, _, _, hdr_admin = self._create_user_with_role("adm", "admin")
        _, _, _, hdr_super = self._create_user_with_role("sadm", "super_admin")

        # 1. Unauthenticated -> 401
        self.assertEqual(self.client.get("/api/v2/admin/stats").status_code, 401)

        # 2. Normal trader -> 403 across all admin routes
        for ep in ["/api/v2/admin/stats", "/api/v2/admin/users", "/api/v2/admin/audit-logs", "/api/v2/admin/feature-flags", "/api/v2/admin/tickets"]:
            self.assertEqual(self.client.get(ep, headers=hdr_trader).status_code, 403)

        # 3. Support agent -> allowed users:read & tickets:manage, denied users:suspend & roles:assign
        self.assertEqual(self.client.get("/api/v2/admin/users", headers=hdr_support).status_code, 200)
        self.assertEqual(self.client.get("/api/v2/admin/tickets", headers=hdr_support).status_code, 200)
        self.assertEqual(
            self.client.put(f"/api/v2/admin/users/{uid_trader}/status", headers=hdr_support, json={"account_status": "suspended"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(f"/api/v2/admin/users/{uid_trader}/role", headers=hdr_support, json={"role": "admin"}).status_code,
            403,
        )

        # 4. Admin -> allowed stats, flags, audit, suspend, subscription override; denied roles:assign
        self.assertEqual(self.client.get("/api/v2/admin/stats", headers=hdr_admin).status_code, 200)
        self.assertEqual(self.client.get("/api/v2/admin/audit-logs", headers=hdr_admin).status_code, 200)
        self.assertEqual(
            self.client.put(f"/api/v2/admin/users/{uid_trader}/role", headers=hdr_admin, json={"role": "analyst"}).status_code,
            403,
        )

        # 5. Super Admin -> succeeds on role assignment
        r_role = self.client.put(f"/api/v2/admin/users/{uid_trader}/role", headers=hdr_super, json={"role": "analyst"})
        self.assertEqual(r_role.status_code, 200)
        self.assertEqual(r_role.get_json()["user"]["role"], "analyst")

    def test_02_suspension_immediately_revokes_active_jwt_sessions(self):
        uid, email, pw, hdr_u = self._create_user_with_role("susp_target", "trader")
        _, _, _, hdr_admin = self._create_user_with_role("susp_adm", "admin")

        # User can access /users/me before suspension
        self.assertEqual(self.client.get("/api/v2/users/me", headers=hdr_u).status_code, 200)

        # Admin suspends user
        r_susp = self.client.put(f"/api/v2/admin/users/{uid}/status", headers=hdr_admin, json={
            "account_status": "suspended",
            "reason": "Abuse policy violation test",
        })
        self.assertEqual(r_susp.status_code, 200)
        self.assertEqual(r_susp.get_json()["user"]["account_status"], "suspended")

        # Existing token is immediately rejected (401), new login blocked (403)
        self.assertEqual(self.client.get("/api/v2/users/me", headers=hdr_u).status_code, 401)
        self.assertEqual(self.client.post("/api/v2/auth/login", json={"email": email, "password": pw}).status_code, 403)

        # Admin reinstates user -> login succeeds again
        r_act = self.client.put(f"/api/v2/admin/users/{uid}/status", headers=hdr_admin, json={"account_status": "active"})
        self.assertEqual(r_act.status_code, 200)
        self.assertEqual(self.client.post("/api/v2/auth/login", json={"email": email, "password": pw}).status_code, 200)

    def test_03_subscription_override_feature_flags_and_stats(self):
        uid, _, _, _ = self._create_user_with_role("sub_target", "trader")
        _, _, _, hdr_admin = self._create_user_with_role("sub_adm", "admin")

        r_sub = self.client.put(f"/api/v2/admin/users/{uid}/subscription", headers=hdr_admin, json={
            "plan_code": "pro_algo_swarm",
            "reason": "VIP Promotional Upgrade",
        })
        self.assertEqual(r_sub.status_code, 200)
        self.assertEqual(r_sub.get_json()["user"]["subscription_plan"], "pro_algo_swarm")

        # Record a verified payment & check stats
        db_manager.collection("payments").insert_one({
            "payment_id": "PAY-TEST-001",
            "user_id": uid,
            "amount_inr": 1499.0,
            "status": "SUCCEEDED",
            "paid_at": "2026-11-27T12:00:00+00:00",
        })
        stats = self.client.get("/api/v2/admin/stats", headers=hdr_admin).get_json()
        self.assertGreaterEqual(stats["kpis"]["pro_users"], 1)
        self.assertEqual(stats["kpis"]["total_revenue_inr"], 1499.0)

        # Feature flag toggle + audit check
        r_flag = self.client.put("/api/v2/admin/feature-flags/enable_academy_lms", headers=hdr_admin, json={"enabled": False})
        self.assertEqual(r_flag.status_code, 200)
        self.assertFalse(r_flag.get_json()["flag"]["enabled"])

        logs = self.client.get("/api/v2/admin/audit-logs?action=FEATURE_FLAG_TOGGLE", headers=hdr_admin).get_json()["logs"]
        self.assertGreaterEqual(len(logs), 1)

    def test_04_support_ticket_user_to_admin_resolution_workflow(self):
        _, _, _, hdr_user = self._create_user_with_role("tkt_u", "trader")
        _, _, _, hdr_sup = self._create_user_with_role("tkt_sup", "support")

        r_open = self.client.post("/api/v2/support/tickets", headers=hdr_user, json={
            "subject": "Need help connecting Upstox",
            "message": "Where do I paste the redirect URI?",
            "priority": "urgent",
            "category": "account",
        })
        self.assertEqual(r_open.status_code, 201)
        tid = r_open.get_json()["ticket"]["ticket_id"]

        r_rep = self.client.post(f"/api/v2/admin/tickets/{tid}/reply", headers=hdr_sup, json={
            "reply_message": "Use https://api.fingroww.tech/api/real-algo/upstox/callback.",
            "status": "resolved",
        })
        self.assertEqual(r_rep.status_code, 200)
        self.assertEqual(r_rep.get_json()["ticket"]["status"], "resolved")

        # User sees updated resolved ticket & notification
        u_tickets = self.client.get("/api/v2/support/tickets", headers=hdr_user).get_json()["tickets"]
        self.assertEqual(u_tickets[0]["status"], "resolved")
        self.assertEqual(len(u_tickets[0]["messages"]), 2)

    def test_05_fastapi_openapi_and_admin_html_serving(self):
        from backend.app import app as fastapi_app
        paths = set(fastapi_app.openapi().get("paths", {}).keys())
        self.assertIn("/api/v2/admin/stats", paths)
        self.assertIn("/api/v2/admin/users", paths)
        self.assertIn("/api/v2/admin/audit-logs", paths)
        self.assertIn("/api/v2/support/tickets", paths)

        self.assertEqual(self.client.get("/admin.html").status_code, 200)
        self.assertEqual(self.client.get("/admin").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
