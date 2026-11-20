"""
Unit Tests for FinGroww Upstox Real Trading Engine & REST API
============================================================
"""

import unittest
import json
from fingroww_upstox_engine import upstox_client, real_supervisor, UpstoxClient, RealTradingSupervisor
from fingroww_market_server import app


class TestUpstoxRealTradingEngine(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def test_01_credentials_loaded(self):
        """Verify Upstox API credentials loaded from .env."""
        self.assertTrue(bool(upstox_client.creds.get("api_key")), "API Key should be loaded")
        self.assertTrue(bool(upstox_client.creds.get("api_secret")), "API Secret should be loaded")
        self.assertIn("dialog", upstox_client.get_auth_dialog_url(), "Auth dialog URL must contain dialog")

    def test_02_mandatory_stop_loss_validation(self):
        """Verify that real trades CANNOT be placed without a mandatory Stop-Loss."""
        # 1. Missing SL
        pos, err = real_supervisor.execute_manual_real_trade(
            base_symbol="NIFTY 50",
            strike=24500,
            option_type="CE",
            stop_loss=None,
        )
        self.assertIsNone(pos)
        self.assertIn("mandatory", err.lower())

        # 2. SL >= entry price
        pos, err = real_supervisor.execute_manual_real_trade(
            base_symbol="NIFTY 50",
            strike=24500,
            option_type="CE",
            stop_loss=250.0,
            quote_resolver=lambda s, st, o: {"lastPrice": 200.0},
        )
        self.assertIsNone(pos)
        self.assertIn("strictly less", err.lower())

    def test_03_algorithmic_180r_target_calculation(self):
        """Verify 1.80R Risk-Reward target calculation on real trade."""
        entry_price = 200.0
        stop_loss = 150.0  # Risk = 50.0
        # Expected target = 200.0 + (50.0 * 1.80) = 290.0

        pos, err = real_supervisor.execute_manual_real_trade(
            base_symbol="NIFTY 50",
            strike=24500,
            option_type="CE",
            stop_loss=stop_loss,
            algo_target=True,
            lots=1,
            quote_resolver=lambda s, st, o: {"lastPrice": entry_price},
        )
        self.assertIsNotNone(pos, f"Trade should succeed: {err}")
        self.assertEqual(pos["entry_price"], 200.0)
        self.assertEqual(pos["stop_loss"], 150.0)
        self.assertEqual(pos["target_price"], 290.0)
        self.assertAlmostEqual(pos["rr_ratio"], 1.80, places=1)
        self.assertTrue(pos["is_algo_target"])

        # Clean up by closing
        ok, _ = real_supervisor.close_real_position(pos["trade_id"])
        self.assertTrue(ok)

    def test_04_emergency_kill_switch(self):
        """Verify emergency kill switch squares off all open positions."""
        # Open 2 positions
        real_supervisor.execute_manual_real_trade("NIFTY 50", 24600, "CE", stop_loss=100.0, quote_resolver=lambda s, st, o: {"lastPrice": 150.0})
        real_supervisor.execute_manual_real_trade("BANK NIFTY", 52000, "PE", stop_loss=200.0, quote_resolver=lambda s, st, o: {"lastPrice": 250.0})

        self.assertGreaterEqual(len(real_supervisor.positions), 2)
        count, msg = real_supervisor.square_off_all_positions()
        self.assertGreaterEqual(count, 2)
        self.assertEqual(len(real_supervisor.positions), 0, "All positions must be cleared by kill switch")

    def test_05_rest_status_endpoint(self):
        """Test GET /api/real-algo/status."""
        res = self.client.get("/api/real-algo/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("dry_run", data)
        self.assertIn("available_margin", data)
        self.assertIn("realized_daily_pnl", data)

    def test_06_rest_manual_order_and_exit(self):
        """Test POST /api/real-algo/manual-order and POST /api/real-algo/close-position."""
        # 1. Reject without SL
        res = self.client.post("/api/real-algo/manual-order", json={
            "base_symbol": "NIFTY 50",
            "strike": 24700,
            "option_type": "CE",
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("mandatory", res.get_json()["error"].lower())

        # 2. Place valid trade
        res = self.client.post("/api/real-algo/manual-order", json={
            "base_symbol": "NIFTY 50",
            "strike": 24700,
            "option_type": "CE",
            "stop_loss": 50.0,
            "algo_target": True,
            "lots": 1,
        })
        self.assertEqual(res.status_code, 200)
        trade_id = res.get_json()["position"]["trade_id"]
        self.assertTrue(trade_id.startswith("REAL_"))

        # 3. Check positions
        res_pos = self.client.get("/api/real-algo/positions")
        self.assertEqual(res_pos.status_code, 200)
        self.assertTrue(any(p["trade_id"] == trade_id for p in res_pos.get_json()["algo_positions"]))

        # 4. Exit position
        res_close = self.client.post("/api/real-algo/close-position", json={"trade_id": trade_id})
        self.assertEqual(res_close.status_code, 200)
        self.assertTrue(res_close.get_json()["ok"])

    def test_07_page_serving(self):
        """Verify ai-auto-real-trading.html is served."""
        res = self.client.get("/ai-auto-real-trading.html")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"AI Real Trading", res.data)
        self.assertIn(b"Upstox API v2", res.data)


if __name__ == "__main__":
    unittest.main()
