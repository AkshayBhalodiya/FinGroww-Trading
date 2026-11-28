#!/usr/bin/env python3
"""
FinGroww Complete SaaS Platform — Full End-to-End Authentication & Flow Verification Suite.
Enforces strict global authentication (zero anonymous access) and verifies every module
across Phases 1-5 + Legacy Engines in sequence.
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


class TestFullPlatformE2EAuthFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_rate_limiter._hits.clear()
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls._store_file = os.path.join(cls._tmp_dir.name, "test_full_e2e_store.json")
        db_manager._initialized = False
        db_manager._local_path = cls._store_file
        db_manager._local_store = {name: [] for name in COLLECTION_NAMES}
        db_manager._local_collections = {}
        db_manager.init(force_local=True)

        srv.app.testing = True
        srv.app.config["ENFORCE_STRICT_AUTH_IN_TESTS"] = True
        cls.client = srv.app.test_client()

    @classmethod
    def tearDownClass(cls):
        srv.app.config["ENFORCE_STRICT_AUTH_IN_TESTS"] = False
        cls._tmp_dir.cleanup()

    def setUp(self):
        auth_rate_limiter._hits.clear()

    def test_01_without_login_every_protected_api_returns_401(self):
        protected_gets = [
            "/api/market/ticker",
            "/api/quote?symbol=RELIANCE",
            "/api/option-chain?symbol=NIFTY%2050",
            "/api/symbols",
            "/api/paper/session/state",
            "/api/paper/session/scan",
            "/api/paper/stream",
            "/api/agents/status",
            "/api/broker/status",
            "/api/skills/suite",
            "/api/v2/users/me",
            "/api/v2/dashboard/overview",
            "/api/v2/watchlists",
            "/api/v2/paper/accounts",
            "/api/v2/journal",
            "/api/v2/coach/insights",
            "/api/v2/intelligence/confluence?symbol=NIFTY%2050",
            "/api/v2/admin/stats",
            "/api/v2/support/tickets",
        ]
        for ep in protected_gets:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 401, f"Expected 401 for unauthenticated GET {ep}, got {res.status_code}")

        protected_posts = [
            ("/api/paper/session/start", {}),
            ("/api/paper/manual-order", {"symbol": "RELIANCE"}),
            ("/api/agents/control", {"is_active": False}),
            ("/api/broker/connect", {"broker": "ZERODHA_KITE"}),
        ]
        for ep, payload in protected_posts:
            res = self.client.post(ep, json=payload)
            self.assertEqual(res.status_code, 401, f"Expected 401 for unauthenticated POST {ep}, got {res.status_code}")

        # Public discovery & health endpoints stay accessible
        for pub in ["/api/health", "/api/v2/health", "/api/v2/subscriptions/plans", "/api/v2/academy/courses"]:
            self.assertEqual(self.client.get(pub).status_code, 200)

    def test_02_frontend_theme_auth_gate_protects_all_app_pages(self):
        with open("theme.js", "r", encoding="utf-8") as f:
            theme_js = f.read()
        self.assertIn("isProtectedPage", theme_js)
        self.assertIn("redirectToLogin", theme_js)
        self.assertIn("window.fetch =", theme_js)
        self.assertIn("window.EventSource =", theme_js)

    def test_03_complete_authenticated_user_and_admin_lifecycle(self):
        # 1. Register & verify email
        email = f"e2e_full_{uuid.uuid4().hex[:6]}@fingroww.tech"
        pw = "E2ESecurePass123"
        r_reg = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": pw,
            "full_name": "Full Flow Trader",
            "username": f"fullflow_{uuid.uuid4().hex[:5]}",
            "experience_level": "intermediate",
            "trading_style": "swing_trader",
        })
        self.assertEqual(r_reg.status_code, 201)
        reg_data = r_reg.get_json()
        uid = reg_data["user"]["user_id"]
        uname = reg_data["user"]["username"]
        trading_name = reg_data["user"]["trading_profile_name"]
        self.assertEqual(trading_name, "Full Flow Trader")
        otp = reg_data["verification_otp_dev"]

        self.assertEqual(
            self.client.post("/api/v2/auth/verify-email", json={"email": email, "otp_or_token": otp}).status_code,
            200,
        )

        # 2. Login cleanly -> get JWT pair
        r_login = self.client.post("/api/v2/auth/login", json={"email": email, "password": pw})
        self.assertEqual(r_login.status_code, 200)
        access_tok = r_login.get_json()["access_token"]
        hdr = {"Authorization": f"Bearer {access_tok}"}

        # 3. Verify Paper Algo AND Real Broker auto-created under exact sign-up name + user isolation
        r_state = self.client.get("/api/paper/session/state?user=AttackerSpoof", headers=hdr)
        self.assertEqual(r_state.status_code, 200)
        self.assertEqual(r_state.get_json()["user_name"], trading_name)

        r_profs = self.client.get("/api/paper/profiles", headers=hdr)
        self.assertEqual(r_profs.status_code, 200)
        prof_names = [p["user_name"] for p in r_profs.get_json()["profiles"]]
        self.assertEqual(prof_names, [trading_name])

        r_agent = self.client.get("/api/agents/status", headers=hdr)
        self.assertEqual(r_agent.status_code, 200)

        r_brk = self.client.get("/api/broker/status", headers=hdr)
        self.assertEqual(r_brk.status_code, 200)
        self.assertEqual(r_brk.get_json()["user_name"], trading_name)

        # 3b. Second user registering with the SAME full name gets distinct trading_profile_name without collision
        r_dup_name = self.client.post("/api/v2/auth/register", json={
            "email": f"dupname_{uuid.uuid4().hex[:5]}@fingroww.tech",
            "password": "DupUserPass123",
            "full_name": "Full Flow Trader",
        })
        self.assertEqual(r_dup_name.status_code, 201)
        dup_tname = r_dup_name.get_json()["user"]["trading_profile_name"]
        self.assertNotEqual(dup_tname, trading_name)
        self.assertTrue(dup_tname.startswith("Full Flow Trader"))

        # 4. Trader cannot hit Admin APIs (403)
        self.assertEqual(self.client.get("/api/v2/admin/stats", headers=hdr).status_code, 403)

        # 5. Dashboard, Watchlist, Notifications & Academy LMS
        self.assertEqual(self.client.get("/api/v2/dashboard/overview", headers=hdr).status_code, 200)
        self.assertEqual(
            self.client.post("/api/v2/watchlists/items", headers=hdr, json={"symbol": "TCS", "alert_above": 4200.0}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post("/api/v2/academy/progress", headers=hdr, json={"course_id": "COURSE-01", "lesson_id": "L1-1"}).status_code,
            200,
        )

        # 6. Upgrade to Pro via HMAC-verified payment webhook -> create 2nd Paper Account -> trade -> journal
        chk = self.client.post("/api/v2/subscriptions/checkout", headers=hdr, json={"plan_code": "pro_algo_swarm"}).get_json()
        pay_id = chk["checkout"]["payment_id"]
        wh_payload = {
            "event": "payment.captured",
            "payment_id": pay_id,
            "user_id": uid,
            "plan_code": "pro_algo_swarm",
            "amount_inr": 1499.0,
        }
        raw = json.dumps(wh_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = sign_webhook_payload(raw)
        self.assertEqual(
            self.client.post("/api/v2/subscriptions/webhook", data=raw, content_type="application/json", headers={"X-FinGroww-Signature": sig}).status_code,
            200,
        )

        r_acc2 = self.client.post("/api/v2/paper/accounts", headers=hdr, json={"name": "Pro Lab", "virtual_capital": 300000.0})
        self.assertEqual(r_acc2.status_code, 201)
        acc_id = r_acc2.get_json()["account"]["account_id"]

        r_ord = self.client.post(f"/api/v2/paper/accounts/{acc_id}/orders", headers=hdr, json={
            "symbol": "INFY", "side": "BUY", "quantity": 50, "entry_price": 1800.0, "stop_loss": 1750.0, "target_1": 1900.0
        })
        self.assertEqual(r_ord.status_code, 201)
        pos_id = r_ord.get_json()["position"]["position_id"]

        r_cls = self.client.post(f"/api/v2/paper/accounts/{acc_id}/close", headers=hdr, json={
            "position_id": pos_id, "exit_price": 1880.0
        })
        self.assertEqual(r_cls.status_code, 200)
        net_pnl = r_cls.get_json()["trade"]["net_pnl"]
        self.assertGreater(net_pnl, 3500.0)

        self.assertEqual(
            self.client.post("/api/v2/journal", headers=hdr, json={
                "account_id": acc_id, "symbol": "INFY", "side": "BUY", "net_pnl": net_pnl, "mood": "disciplined", "rules_followed": True
            }).status_code,
            201,
        )
        coach = self.client.get("/api/v2/coach/insights", headers=hdr).get_json()
        self.assertTrue(coach["has_sufficient_data"])

        # 7. Support ticket -> Admin login -> Resolve ticket
        tkt_res = self.client.post("/api/v2/support/tickets", headers=hdr, json={
            "subject": "Verify Pro Features", "message": "Checking ticket flow"
        })
        self.assertEqual(tkt_res.status_code, 201)
        tid = tkt_res.get_json()["ticket"]["ticket_id"]

        # Create Super Admin & log in
        adm_email = f"adm_{uuid.uuid4().hex[:5]}@fingroww.tech"
        self.client.post("/api/v2/auth/register", json={"email": adm_email, "password": "SuperPass123", "full_name": "Admin"})
        db_manager.collection("users").update_one({"email": adm_email}, {"$set": {"role": "super_admin"}})
        adm_tok = self.client.post("/api/v2/auth/login", json={"email": adm_email, "password": "SuperPass123"}).get_json()["access_token"]
        adm_hdr = {"Authorization": f"Bearer {adm_tok}"}

        self.assertEqual(
            self.client.post(f"/api/v2/admin/tickets/{tid}/reply", headers=adm_hdr, json={"reply_message": "All verified!", "status": "resolved"}).status_code,
            200,
        )
        adm_stats = self.client.get("/api/v2/admin/stats", headers=adm_hdr).get_json()
        self.assertGreaterEqual(adm_stats["kpis"]["total_revenue_inr"], 1499.0)

        # 8. Logout invalidates user session -> subsequent API call returns 401
        self.assertEqual(self.client.post("/api/v2/auth/logout", headers=hdr).status_code, 200)
        self.assertEqual(self.client.get("/api/paper/session/state", headers=hdr).status_code, 401)
        self.assertEqual(self.client.get("/api/v2/dashboard/overview", headers=hdr).status_code, 401)

    def test_super_admin_user_management_crud_and_sessions(self):
        # 1. Public registration cannot elevate role even if payload passes role="super_admin"
        pub_email = f"pub_{uuid.uuid4().hex[:6]}@fingroww.tech"
        r_pub = self.client.post("/api/v2/auth/register", json={
            "email": pub_email,
            "password": "UserPass123",
            "full_name": "Public Normal User",
            "role": "super_admin",
        })
        self.assertEqual(r_pub.status_code, 201)
        pub_body = r_pub.get_json()
        self.assertEqual(pub_body["user"]["role"], "trader")
        pub_tok = pub_body["access_token"]
        pub_hdr = {"Authorization": f"Bearer {pub_tok}"}
        pub_tname = pub_body["user"]["trading_profile_name"]

        # Unified Paper & Real Broker identity for logged-in user (normal user CANNOT switch even with ?user=SpoofTarget)
        self.assertEqual(self.client.get("/api/paper/session/state?user=CRUD%20Trader%20Desk", headers=pub_hdr).get_json()["user_name"], pub_tname)
        self.assertEqual(self.client.get("/api/broker/status?user=CRUD%20Trader%20Desk", headers=pub_hdr).get_json()["user_name"], pub_tname)
        self.assertEqual(
            self.client.post("/api/paper/profiles/create", headers=pub_hdr, json={"user_name": "UnauthorizedSwitch"}).status_code,
            403,
        )

        # 2. Bootstrap Super Admin (admin@fingroww.tech) & login
        from backend.create_admin import bootstrap_super_admin
        bootstrap_super_admin("admin@fingroww.tech", "FinGroww@Admin2026", "Akshay Super Admin")
        sa_login = self.client.post("/api/v2/auth/login", json={
            "email": "admin@fingroww.tech",
            "password": "FinGroww@Admin2026",
        })
        self.assertEqual(sa_login.status_code, 200)
        sa_body = sa_login.get_json()
        self.assertEqual(sa_body["user"]["role"], "super_admin")
        sa_hdr = {"Authorization": f"Bearer {sa_body['access_token']}"}

        # 3. Super Admin creates a normal trader AND an admin via CRUD endpoint
        cr_trader_email = f"crud_tr_{uuid.uuid4().hex[:5]}@fingroww.tech"
        r_cr_tr = self.client.post("/api/v2/admin/users", headers=sa_hdr, json={
            "email": cr_trader_email,
            "password": "TraderPass123",
            "full_name": "CRUD Trader",
            "trading_profile_name": "CRUD Trader Desk",
            "role": "trader",
            "subscription_plan": "pro_algo_swarm",
            "virtual_capital": 750000,
            "is_email_verified": True,
        })
        self.assertEqual(r_cr_tr.status_code, 201)
        cr_tr_uid = r_cr_tr.get_json()["user"]["user_id"]
        self.assertEqual(r_cr_tr.get_json()["user"]["role"], "trader")

        cr_admin_email = f"crud_adm_{uuid.uuid4().hex[:5]}@fingroww.tech"
        r_cr_adm = self.client.post("/api/v2/admin/users", headers=sa_hdr, json={
            "email": cr_admin_email,
            "password": "AdminPass123",
            "full_name": "Ops Admin",
            "role": "admin",
        })
        self.assertEqual(r_cr_adm.status_code, 201)
        cr_adm_uid = r_cr_adm.get_json()["user"]["user_id"]
        self.assertEqual(r_cr_adm.get_json()["user"]["role"], "admin")

        # 4. Users directory shows online count & paper_balance
        r_dir = self.client.get(f"/api/v2/admin/users?search={pub_email}", headers=sa_hdr)
        self.assertEqual(r_dir.status_code, 200)
        dir_users = r_dir.get_json()["users"]
        self.assertEqual(len(dir_users), 1)
        self.assertTrue(dir_users[0]["is_online"])
        self.assertGreaterEqual(dir_users[0]["active_sessions_count"], 1)
        self.assertIn("paper_balance", dir_users[0])

        # 5. Live logged-in sessions endpoint lists active users + sessions
        r_sess = self.client.get("/api/v2/admin/sessions", headers=sa_hdr)
        self.assertEqual(r_sess.status_code, 200)
        sess_data = r_sess.get_json()
        self.assertGreaterEqual(sess_data["logged_in_users_count"], 2)
        self.assertGreaterEqual(sess_data["active_sessions_count"], 2)
        pub_sessions = [s for s in sess_data["sessions"] if s["email"] == pub_email]
        self.assertGreaterEqual(len(pub_sessions), 1)
        pub_sid = pub_sessions[0]["session_id"]

        # 6. Super Admin updates trader profile, role, and trading_profile_name
        r_upd = self.client.put(f"/api/v2/admin/users/{cr_tr_uid}", headers=sa_hdr, json={
            "full_name": "CRUD Trader Updated",
            "trading_profile_name": "CRUD Updated Desk",
            "subscription_plan": "enterprise",
            "role": "trader",
        })
        self.assertEqual(r_upd.status_code, 200)
        self.assertEqual(r_upd.get_json()["user"]["full_name"], "CRUD Trader Updated")
        self.assertEqual(r_upd.get_json()["user"]["trading_profile_name"], "CRUD Updated Desk")

        # 7. Normal Admin cannot create admins, promote to admin, or delete users (403)
        adm_login = self.client.post("/api/v2/auth/login", json={
            "email": cr_admin_email,
            "password": "AdminPass123",
        })
        self.assertEqual(adm_login.status_code, 200)
        ops_hdr = {"Authorization": f"Bearer {adm_login.get_json()['access_token']}"}
        self.assertEqual(
            self.client.post("/api/v2/admin/users", headers=ops_hdr, json={
                "email": f"fail_{uuid.uuid4().hex[:5]}@fingroww.tech",
                "password": "FailPass123",
                "full_name": "Should Fail",
                "role": "admin",
            }).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(f"/api/v2/admin/users/{cr_tr_uid}", headers=ops_hdr, json={"role": "admin"}).status_code,
            403,
        )
        self.assertEqual(self.client.delete(f"/api/v2/admin/users/{cr_tr_uid}", headers=ops_hdr).status_code, 403)

        # 7b. Only Super Admin and Admin CAN switch into another user's Paper & Broker workspace
        self.assertEqual(
            self.client.get("/api/paper/session/state?user=CRUD%20Updated%20Desk", headers=sa_hdr).get_json()["user_name"],
            "CRUD Updated Desk",
        )
        self.assertEqual(
            self.client.get("/api/broker/status?user=CRUD%20Updated%20Desk", headers=ops_hdr).get_json()["user_name"],
            "CRUD Updated Desk",
        )

        # 8. Super Admin revokes public user's live session -> user token becomes 401
        r_rev = self.client.delete(f"/api/v2/admin/sessions/{pub_sid}", headers=sa_hdr)
        self.assertEqual(r_rev.status_code, 200)
        self.assertEqual(self.client.get("/api/paper/session/state", headers=pub_hdr).status_code, 401)

        # 9. Super Admin deletes created test users -> removed cleanly
        self.assertEqual(self.client.delete(f"/api/v2/admin/users/{cr_tr_uid}", headers=sa_hdr).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v2/admin/users/{cr_adm_uid}", headers=sa_hdr).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v2/admin/users/{cr_tr_uid}", headers=sa_hdr).status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
