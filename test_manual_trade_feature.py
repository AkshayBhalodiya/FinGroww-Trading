import unittest
import json
from fingroww_paper_engine import (
    PaperTradingSession,
    MultiUserPaperSessionManager,
    LOT_SIZES,
)
from fingroww_market_server import app


class TestManualTradeFeature(unittest.TestCase):
    def setUp(self):
        self.session = PaperTradingSession(user_name="UnitTest_ManualTrader")
        self.session.reset(initial_capital=200000.0)
        self.client = app.test_client()

    def test_01_mandatory_sl_rejection(self):
        """Verifies that execute_manual_trade fails without a positive Stop Loss."""
        # Omitted SL
        pos, err = self.session.execute_manual_trade(
            base_symbol="NIFTY",
            strike=24500,
            option_type="CE",
            stop_loss=None,
            stop_loss_pct=None,
            lots=1,
        )
        self.assertIsNone(pos)
        self.assertIn("mandatory", err.lower())

        # Zero SL
        pos, err = self.session.execute_manual_trade(
            base_symbol="NIFTY",
            strike=24500,
            option_type="CE",
            stop_loss=0,
            stop_loss_pct=0,
            lots=1,
        )
        self.assertIsNone(pos)
        self.assertIn("mandatory", err.lower())

    def test_02_execute_manual_trade_success_with_algo_target(self):
        """Verifies manual trade execution, lot sizing, margin allocation, and 1.8R algo target."""
        pos, err = self.session.execute_manual_trade(
            base_symbol="NIFTY",
            strike=24500,
            option_type="CE",
            stop_loss_pct=20.0,
            algo_target=True,
            lots=2,
        )
        self.assertIsNotNone(pos, f"Manual trade failed: {err}")
        self.assertEqual(pos["execution_type"], "MANUAL")
        self.assertEqual(pos["quantity"], 2 * LOT_SIZES.get("NIFTY 50", LOT_SIZES.get("NIFTY", 25)))
        self.assertTrue(pos["is_algo_target"])
        self.assertGreater(pos["target_price"], pos["entry_price"])
        self.assertLess(pos["stop_loss"], pos["entry_price"])
        self.assertEqual(len(self.session.positions), 1)

    def test_03_close_position_retains_execution_type(self):
        """Verifies closing a manual trade preserves execution_type in closed_trades."""
        pos, err = self.session.execute_manual_trade(
            base_symbol="BANK NIFTY",
            strike=52000,
            option_type="PE",
            stop_loss_pct=15.0,
            target_price=1200.0,
            lots=1,
        )
        self.assertIsNotNone(pos, f"Failed: {err}")
        trade_id = pos["trade_id"]

        # Close position
        closed, msg = self.session.manual_close_position(trade_id, force=True)
        self.assertTrue(closed, f"manual_close_position failed: {msg}")
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 1)
        self.assertEqual(self.session.closed_trades[0]["execution_type"], "MANUAL")

    def test_04_analytics_filters_by_execution_type(self):
        """Verifies get_performance_analytics splits AUTO and MANUAL trades."""
        # 1 manual trade
        pos, _ = self.session.execute_manual_trade(
            base_symbol="NIFTY",
            strike=24500,
            option_type="CE",
            stop_loss_pct=10.0,
            lots=1,
        )
        self.session.manual_close_position(pos["trade_id"], force=True)

        # 1 auto trade mock setup
        self.session.start()
        auto_setup = {
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "type": "STOCK",
            "market_cap": "LARGE_CAP",
            "action": "BUY",
            "current_price": 2800.0,
            "entry_price": 2800.0,
            "stop_loss": 2700.0,
            "target_price": 3000.0,
            "holding_duration_mins": 1440,
            "status": "VALIDATED",
            "rr_ratio": 2.0,
            "confidence_score": 85,
        }
        auto_pos, err = self.session.execute_trade(
            auto_setup,
            quote_resolver=lambda s: {"symbol": s, "lastPrice": 2800.0},
            market_is_open=True,
            is_manual=False,
        )
        self.assertIsNotNone(auto_pos, f"Auto trade failed: {err}")
        self.session.manual_close_position(auto_pos["trade_id"], force=True)

        all_ana = self.session.get_performance_analytics()
        auto_ana = self.session.get_performance_analytics(execution_type="AUTO")
        man_ana = self.session.get_performance_analytics(execution_type="MANUAL")

        self.assertEqual(all_ana["total_trades"], 2)
        self.assertEqual(auto_ana["total_trades"], 1)
        self.assertEqual(man_ana["total_trades"], 1)

    def test_05_leaderboard_modes(self):
        """Verifies 3-way leaderboard mode filtering: mix, ai_only, manual_only."""
        manager = MultiUserPaperSessionManager(db=None)
        sess, _ = manager.get_session("LeaderboardUser")
        sess.reset(initial_capital=100000.0)

        # Execute manual trade
        pos_m, _ = sess.execute_manual_trade(
            base_symbol="NIFTY",
            strike=24500,
            option_type="CE",
            stop_loss_pct=10.0,
            lots=1,
        )
        sess.manual_close_position(pos_m["trade_id"], force=True)

        lb_mix = manager.get_leaderboard(mode="mix")
        lb_ai = manager.get_leaderboard(mode="ai_only")
        lb_man = manager.get_leaderboard(mode="manual_only")

        user_mix = next((p for p in lb_mix if p["user_name"] == "LeaderboardUser"), None)
        user_ai = next((p for p in lb_ai if p["user_name"] == "LeaderboardUser"), None)
        user_man = next((p for p in lb_man if p["user_name"] == "LeaderboardUser"), None)

        self.assertIsNotNone(user_mix)
        self.assertEqual(user_mix["mode_filter"], "MIX")
        self.assertEqual(user_mix["total_trades"], 1)

        self.assertIsNotNone(user_ai)
        self.assertEqual(user_ai["mode_filter"], "AI_ONLY")
        self.assertEqual(user_ai["total_trades"], 0)

        self.assertIsNotNone(user_man)
        self.assertEqual(user_man["mode_filter"], "MANUAL_ONLY")
        self.assertEqual(user_man["total_trades"], 1)

    def test_06_manual_order_api_endpoint(self):
        """Verifies POST /api/paper/manual-order endpoint."""
        import uuid
        user = f"ApiUser_{uuid.uuid4().hex[:6]}"
        # 1. Invalid payload without SL
        res = self.client.post(
            f"/api/paper/manual-order?user={user}",
            json={
                "base_symbol": "NIFTY",
                "strike": 24500,
                "option_type": "CE",
                "lots": 1,
            },
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data.get("ok", True))
        self.assertIn("mandatory", data.get("error", "").lower())

        # 2. Valid payload
        res = self.client.post(
            f"/api/paper/manual-order?user={user}",
            json={
                "base_symbol": "NIFTY",
                "strike": 24500,
                "option_type": "CE",
                "stop_loss_pct": 20.0,
                "algo_target": True,
                "lots": 1,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["position"]["execution_type"], "MANUAL")

    def test_07_option_quote_api_endpoint(self):
        """Verifies GET /api/paper/option-quote endpoint."""
        res = self.client.get("/api/paper/option-quote?symbol=NIFTY&strike=24500&type=CE")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("lastPrice", data)
        self.assertIn("suggested_sl", data)
        self.assertIn("suggested_target", data)
        self.assertGreater(data["lot_size"], 0)


if __name__ == "__main__":
    unittest.main()
