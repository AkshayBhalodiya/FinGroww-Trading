#!/usr/bin/env python3
"""
FinGroww SaaS Modernisation (Phase 3) — Multi-Account Paper Trading, Trading Journal,
AI Trading Coach & 3-Timeframe Confluence Intelligence Test Suite.
"""

import os
import tempfile
import unittest
import uuid

from backend.database import COLLECTION_NAMES, db_manager
from backend.services.intelligence_service import evaluate_three_timeframe_confluence
import fingroww_market_server as srv


class TestPhase3AccountsJournalAndIntelligence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls._store_file = os.path.join(cls._tmp_dir.name, "test_phase3_store.json")
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

    def _register_user(self, prefix: str, plan: str = "free"):
        email = f"{prefix}_{uuid.uuid4().hex[:6]}@fingroww.tech"
        r = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "Phase3Pass123",
            "full_name": f"{prefix.title()} Trader",
            "username": f"{prefix}_{uuid.uuid4().hex[:5]}",
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        uid = data["user"]["user_id"]
        if plan != "free":
            db_manager.collection("users").update_one({"user_id": uid}, {"$set": {"subscription_plan": plan}})
        return uid, {"Authorization": f"Bearer {data['access_token']}"}

    def test_01_multi_account_quota_lifecycle_and_isolation(self):
        uid_free, hdr_free = self._register_user("free_p3", plan="free")
        uid_pro, hdr_pro = self._register_user("pro_p3", plan="pro_algo_swarm")

        # Free user has 1 primary account, blocked from creating a 2nd account (403)
        r_list_f = self.client.get("/api/v2/paper/accounts", headers=hdr_free)
        self.assertEqual(r_list_f.status_code, 200)
        self.assertEqual(r_list_f.get_json()["count"], 1)

        r_block = self.client.post("/api/v2/paper/accounts", headers=hdr_free, json={
            "name": "Extra Scalping Lab",
            "virtual_capital": 50000.0,
        })
        self.assertEqual(r_block.status_code, 403)

        # Pro user creates a 2nd sub-account with ₹5,00,000 capital
        r_create = self.client.post("/api/v2/paper/accounts", headers=hdr_pro, json={
            "name": "Swing Lab 5L",
            "virtual_capital": 500000.0,
            "trading_style": "swing_trader",
        })
        self.assertEqual(r_create.status_code, 201)
        acc_id = r_create.get_json()["account"]["account_id"]

        # Place BUY order on sub-account
        r_ord = self.client.post(f"/api/v2/paper/accounts/{acc_id}/orders", headers=hdr_pro, json={
            "symbol": "RELIANCE",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "quantity": 100,
            "entry_price": 1350.0,
            "stop_loss": 1320.0,
            "target_1": 1410.0,
        })
        self.assertEqual(r_ord.status_code, 201)
        pos_id = r_ord.get_json()["position"]["position_id"]
        self.assertLess(r_ord.get_json()["available_balance"], 500000.0)

        # Cross-user isolation: Free user cannot access, trade, or close Pro user's account
        self.assertEqual(self.client.get(f"/api/v2/paper/accounts/{acc_id}", headers=hdr_free).status_code, 404)
        self.assertEqual(
            self.client.post(f"/api/v2/paper/accounts/{acc_id}/close", headers=hdr_free, json={"position_id": pos_id}).status_code,
            404,
        )

        # Pro user closes position profitably at 1400.0
        r_cls = self.client.post(f"/api/v2/paper/accounts/{acc_id}/close", headers=hdr_pro, json={
            "position_id": pos_id,
            "exit_price": 1400.0,
            "exit_reason": "TARGET_1_HIT",
        })
        self.assertEqual(r_cls.status_code, 200)
        trade = r_cls.get_json()["trade"]
        self.assertEqual(trade["gross_pnl"], 5000.0)
        self.assertGreater(trade["charges_and_slippage"], 0.0)
        self.assertLess(trade["net_pnl"], 5000.0)
        self.assertEqual(r_cls.get_json()["metrics"]["win_rate_pct"], 100.0)

        # CSV export
        r_csv = self.client.get(f"/api/v2/paper/accounts/{acc_id}/export.csv", headers=hdr_pro)
        self.assertEqual(r_csv.status_code, 200)
        self.assertIn("text/csv", r_csv.content_type)
        self.assertIn("RELIANCE", r_csv.data.decode("utf-8"))

        # Reset & Archive sub-account
        r_rst = self.client.post(f"/api/v2/paper/accounts/{acc_id}/reset", headers=hdr_pro, json={"virtual_capital": 250000.0})
        self.assertEqual(r_rst.status_code, 200)
        self.assertEqual(r_rst.get_json()["account"]["virtual_capital"], 250000.0)
        self.assertEqual(r_rst.get_json()["account"]["total_trades"], 0)

        r_arch = self.client.post(f"/api/v2/paper/accounts/{acc_id}/archive", headers=hdr_pro)
        self.assertEqual(r_arch.status_code, 200)

    def test_02_trading_journal_ai_coach_and_isolation(self):
        _, hdr_a = self._register_user("jrn_a")
        _, hdr_b = self._register_user("jrn_b")

        # Empty state returns no fabricated discipline score
        r_empty_coach = self.client.get("/api/v2/coach/insights", headers=hdr_a).get_json()
        self.assertFalse(r_empty_coach["has_sufficient_data"])
        self.assertIsNone(r_empty_coach["discipline_score"])

        # User A logs an undisciplined FOMO trade
        r_create = self.client.post("/api/v2/journal", headers=hdr_a, json={
            "symbol": "BANK NIFTY 63500 CE",
            "side": "BUY",
            "net_pnl": -1850.0,
            "timeframe": "5m",
            "mood": "fomo",
            "rules_followed": False,
            "mistake_tags": ["chased_entry", "moved_stop_loss"],
            "notes": "Chased breakout candle without waiting for 15m pullback.",
        })
        self.assertEqual(r_create.status_code, 201)
        entry = r_create.get_json()["entry"]
        jid = entry["journal_id"]
        self.assertIn("fomo", entry["ai_feedback"].lower())

        # Coach insights reflect exact logged patterns
        coach = self.client.get("/api/v2/coach/insights", headers=hdr_a).get_json()
        self.assertTrue(coach["has_sufficient_data"])
        self.assertEqual(coach["stats"]["rule_compliance_pct"], 0.0)
        self.assertEqual(coach["emotional_leakage_inr"], -1850.0)
        self.assertTrue(any(m["tag"] == "moved_stop_loss" for m in coach["top_mistakes"]))

        # Cross-user isolation: User B cannot update or delete User A's journal entry
        self.assertEqual(
            self.client.put(f"/api/v2/journal/{jid}", headers=hdr_b, json={"notes": "Tampered"}).status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"/api/v2/journal/{jid}", headers=hdr_b).status_code, 404)

        # User A updates & deletes entry
        r_upd = self.client.put(f"/api/v2/journal/{jid}", headers=hdr_a, json={"rules_followed": True})
        self.assertEqual(r_upd.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v2/journal/{jid}", headers=hdr_a).status_code, 200)

    def test_03_three_timeframe_confluence_verifiable_math(self):
        # Missing candles returns INSUFFICIENT_DATA cleanly (no fabricated signals)
        res_empty = evaluate_three_timeframe_confluence("TESTSYM", candles_1h=[], candles_15m=[], candles_5m=[])
        self.assertEqual(res_empty["verdict"], "INSUFFICIENT_DATA")
        self.assertFalse(res_empty["data_verified"])

        # Uptrend candles across 1H, 15M, 5M -> STRONG_BUY_CONFLUENCE (3/3)
        bull_candles = [{"c": 100.0 + i * 2.0} for i in range(30)]
        res_bull = evaluate_three_timeframe_confluence(
            "TESTSYM", candles_1h=bull_candles, candles_15m=bull_candles, candles_5m=bull_candles
        )
        self.assertTrue(res_bull["data_verified"])
        self.assertEqual(res_bull["verdict"], "STRONG_BUY_CONFLUENCE")
        self.assertEqual(res_bull["alignment_score"], "3/3")

    def test_04_fastapi_openapi_and_journal_html_serving(self):
        from backend.app import app as fastapi_app
        paths = set(fastapi_app.openapi().get("paths", {}).keys())
        self.assertIn("/api/v2/paper/accounts", paths)
        self.assertIn("/api/v2/journal", paths)
        self.assertIn("/api/v2/coach/insights", paths)
        self.assertIn("/api/v2/intelligence/confluence", paths)

        self.assertEqual(self.client.get("/journal.html").status_code, 200)
        self.assertEqual(self.client.get("/journal").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
