#!/usr/bin/env python3
"""
FinGroww SaaS Modernisation (Phase 2) — User Dashboard, Watchlists, Signals & Notifications Tests.
Verifies verified quantitative metrics, cross-user data isolation, FastAPI OpenAPI registration,
and dashboard page serving.
"""

import os
import tempfile
import unittest
import uuid

from backend.database import COLLECTION_NAMES, db_manager
from backend.services.dashboard_service import _compute_verified_metrics
import fingroww_market_server as srv


class TestPhase2DashboardAndIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls._store_file = os.path.join(cls._tmp_dir.name, "test_phase2_store.json")
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

    def _register_user(self, prefix: str):
        email = f"{prefix}_{uuid.uuid4().hex[:6]}@fingroww.tech"
        r = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "DashUser123",
            "full_name": f"{prefix.title()} Trader",
            "username": f"{prefix}_{uuid.uuid4().hex[:5]}",
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        return data["user"]["user_id"], {"Authorization": f"Bearer {data['access_token']}"}

    def test_01_unauthenticated_access_blocked(self):
        for ep in ["/api/v2/dashboard/overview", "/api/v2/watchlists", "/api/v2/signals/saved", "/api/v2/notifications"]:
            self.assertEqual(self.client.get(ep).status_code, 401)

    def test_02_verified_metrics_math_without_fabrication(self):
        # Zero trades -> 0 win rate, 0 profit factor, 1 point equity curve
        empty = _compute_verified_metrics(100000.0, [])
        self.assertEqual(empty["total_trades"], 0)
        self.assertEqual(empty["win_rate_pct"], 0.0)
        self.assertEqual(len(empty["equity_curve"]), 1)

        # Known sequence: +5000, -2000, +3000 -> net +6000, 2/3 wins (66.67%), PF=8000/2000=4.0
        # Peak after T1=105000, after T2=103000 -> DD=(2000/105000)*100 = 1.90%
        trades = [
            {"symbol": "RELIANCE", "net_pnl": 5000.0, "closed_at": "2026-11-01T10:00:00"},
            {"symbol": "INFY", "net_pnl": -2000.0, "closed_at": "2026-11-02T10:00:00"},
            {"symbol": "TCS", "net_pnl": 3000.0, "closed_at": "2026-11-03T10:00:00"},
        ]
        m = _compute_verified_metrics(100000.0, trades)
        self.assertEqual(m["total_trades"], 3)
        self.assertEqual(m["win_rate_pct"], 66.67)
        self.assertEqual(m["profit_factor"], 4.0)
        self.assertEqual(m["realized_pnl"], 6000.0)
        self.assertEqual(m["max_drawdown_pct"], 1.9)
        self.assertEqual(len(m["equity_curve"]), 4)
        self.assertEqual(m["equity_curve"][-1]["equity"], 106000.0)

    def test_03_watchlist_crud_and_cross_user_isolation(self):
        uid_a, hdr_a = self._register_user("wl_a")
        uid_b, hdr_b = self._register_user("wl_b")

        # User A adds RELIANCE with target alert
        r_add = self.client.post("/api/v2/watchlists/items", headers=hdr_a, json={
            "watchlist_name": "Primary Watchlist",
            "symbol": "reliance",
            "alert_above": 1450.5,
        })
        self.assertEqual(r_add.status_code, 200)
        items_a = r_add.get_json()["watchlists"][0]["items"]
        self.assertEqual(len(items_a), 1)
        self.assertEqual(items_a[0]["symbol"], "RELIANCE")

        # User B's watchlist must be isolated (empty)
        r_b = self.client.get("/api/v2/watchlists?live=false", headers=hdr_b)
        self.assertEqual(r_b.status_code, 200)
        items_b = r_b.get_json()["watchlists"][0]["items"]
        self.assertEqual(len(items_b), 0)

        # User A deletes RELIANCE
        r_del = self.client.delete("/api/v2/watchlists/items", headers=hdr_a, json={
            "watchlist_name": "Primary Watchlist",
            "symbol": "RELIANCE",
        })
        self.assertEqual(r_del.status_code, 200)
        self.assertEqual(len(r_del.get_json()["watchlists"][0]["items"]), 0)

    def test_04_saved_signals_and_isolation(self):
        _, hdr_a = self._register_user("sig_a")
        _, hdr_b = self._register_user("sig_b")

        r_save = self.client.post("/api/v2/signals/saved", headers=hdr_a, json={
            "symbol": "NIFTY 50 25,800 CE",
            "side": "BUY",
            "strategy": "15m Fib Golden Zone",
            "entry_price": 195.0,
            "stop_loss": 160.0,
            "target_1": 265.0,
        })
        self.assertEqual(r_save.status_code, 201)
        saved_id = r_save.get_json()["signal"]["saved_id"]

        # User B cannot see or delete User A's saved signal
        r_list_b = self.client.get("/api/v2/signals/saved", headers=hdr_b)
        self.assertEqual(r_list_b.get_json()["count"], 0)
        r_del_b = self.client.delete(f"/api/v2/signals/saved/{saved_id}", headers=hdr_b)
        self.assertEqual(r_del_b.status_code, 404)

        # User A can list and delete
        r_list_a = self.client.get("/api/v2/signals/saved", headers=hdr_a)
        self.assertEqual(r_list_a.get_json()["count"], 1)
        self.assertEqual(self.client.delete(f"/api/v2/signals/saved/{saved_id}", headers=hdr_a).status_code, 200)

    def test_05_notifications_and_mark_read(self):
        _, hdr = self._register_user("notif_u")
        r_list = self.client.get("/api/v2/notifications", headers=hdr)
        self.assertEqual(r_list.status_code, 200)
        data = r_list.get_json()
        self.assertGreaterEqual(data["unread_count"], 1)  # Welcome notification created on register

        r_read = self.client.post("/api/v2/notifications/read", headers=hdr, json={"mark_all": True})
        self.assertEqual(r_read.status_code, 200)
        self.assertEqual(r_read.get_json()["unread_count"], 0)

    def test_06_dashboard_overview_and_html_routes(self):
        uid, hdr = self._register_user("dash_full")
        db_manager.collection("paper_trades").insert_one({
            "trade_id": "TRD-TEST-1",
            "user_id": uid,
            "symbol": "TCS",
            "side": "BUY",
            "net_pnl": 4200.0,
            "closed_at": "2026-11-27T11:00:00",
        })

        r_ov = self.client.get("/api/v2/dashboard/overview", headers=hdr)
        self.assertEqual(r_ov.status_code, 200)
        ov = r_ov.get_json()
        self.assertTrue(ov["ok"])
        self.assertEqual(ov["summary"]["realized_pnl"], 4200.0)
        self.assertEqual(ov["summary"]["win_rate_pct"], 100.0)
        self.assertEqual(ov["summary"]["total_trades"], 1)

        # Static Dashboard HTML serving
        self.assertEqual(self.client.get("/dashboard.html").status_code, 200)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_07_fastapi_openapi_includes_phase2_routes(self):
        from backend.app import app as fastapi_app
        paths = set(fastapi_app.openapi().get("paths", {}).keys())
        self.assertIn("/api/v2/dashboard/overview", paths)
        self.assertIn("/api/v2/watchlists", paths)
        self.assertIn("/api/v2/signals/saved", paths)
        self.assertIn("/api/v2/notifications", paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
