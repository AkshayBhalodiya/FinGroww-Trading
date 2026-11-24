import unittest
import json
import re
import csv
import io
import uuid
from bs4 import BeautifulSoup
from fingroww_paper_engine import (
    PaperTradingSession,
    MultiUserPaperSessionManager,
    LOT_SIZES,
)
from fingroww_market_server import app, paper_manager


class TestE2EFullFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_01_frontend_html_structure_and_modal_elements(self):
        """Verifies frontend HTML contains all modal elements, buttons, and badges."""
        with open("ai-auto-paper-trading.html", "r", encoding="utf-8") as f:
            html = f.read()

        soup = BeautifulSoup(html, "html.parser")

        # 1. Manual Order Modal and Inputs
        modal = soup.find(id="modalManualOrder")
        self.assertIsNotNone(modal, "Modal #modalManualOrder is missing from HTML")

        required_ids = [
            "manualOrderSymbol",
            "manualOrderStrike",
            "manualOrderLots",
            "manualOrderSl",
            "manualOrderTarget",
            "manualUseAlgoTarget",
            "manualLtpDisplay",
            "manualLotSizeDisplay",
            "manualLotMarginDisplay",
            "manualSpotBadge",
            "manualContractTitle",
            "manualSummaryLoss",
            "manualSummaryGain",
            "manualSummaryRr",
            "manualRiskPerShare",
            "manualRewardPerShare",
            "manualTotalReqMargin",
            "manualTotalQtyBadge",
            "manualAvailBalDisplay",
            "btnSubmitManualOrder",
        ]
        for el_id in required_ids:
            el = soup.find(id=el_id)
            self.assertIsNotNone(el, f"Required element #{el_id} is missing in modal")

        # 2. 3-Way Leaderboard Mode Buttons
        for btn_id in ["btnLbModeMix", "btnLbModeAi", "btnLbModeManual"]:
            btn = soup.find(id=btn_id)
            self.assertIsNotNone(btn, f"Leaderboard mode button #{btn_id} is missing")

        # 3. Manual Trade Open Buttons in HUD / Header
        manual_btns = [b for b in soup.find_all("button") if "openManualOrderModal" in (b.get("onclick") or "")]
        self.assertGreaterEqual(len(manual_btns), 2, "Expected at least 2 Manual Trade trigger buttons")

    def test_02_backend_manual_and_ai_trade_coexistence(self):
        """Verifies manual and AI auto trades run concurrently with perfect margin accounting."""
        user = f"E2E_DualTrader_{uuid.uuid4().hex[:6]}"
        sess = PaperTradingSession(user_name=user)
        sess.reset(initial_capital=200000.0)

        # 1. Place Manual Trade
        man_pos, err = sess.execute_manual_trade(
            base_symbol="NIFTY",
            strike=24500,
            option_type="CE",
            stop_loss_pct=20.0,
            algo_target=True,
            lots=2,
        )
        self.assertIsNotNone(man_pos, f"Manual trade failed: {err}")
        self.assertEqual(man_pos["execution_type"], "MANUAL")
        self.assertEqual(len(sess.positions), 1)
        man_margin = sess.allocated_margin
        self.assertGreater(man_margin, 0)

        # 2. Place Auto AI Trade concurrently
        sess.start()
        auto_setup = {
            "symbol": "TCS",
            "name": "Tata Consultancy Services",
            "type": "STOCK",
            "market_cap": "LARGE_CAP",
            "action": "BUY",
            "current_price": 4000.0,
            "entry_price": 4000.0,
            "stop_loss": 3900.0,
            "target_price": 4200.0,
            "holding_duration_mins": 1440,
            "status": "VALIDATED",
            "rr_ratio": 2.0,
            "confidence_score": 90,
        }
        auto_pos, a_err = sess.execute_trade(
            auto_setup,
            quote_resolver=lambda s: {"symbol": s, "lastPrice": 4000.0},
            market_is_open=True,
            is_manual=False,
        )
        self.assertIsNotNone(auto_pos, f"Auto trade failed: {a_err}")
        self.assertEqual(auto_pos["execution_type"], "AUTO")
        self.assertEqual(len(sess.positions), 2)

        # Check total allocated margin
        expected_total_margin = round(man_margin + auto_pos["allocated_margin"], 2)
        self.assertAlmostEqual(sess.allocated_margin, expected_total_margin, places=2)

        # 3. Close Manual Trade
        ok_m, _ = sess.manual_close_position(man_pos["trade_id"], force=True)
        self.assertTrue(ok_m)
        self.assertEqual(len(sess.positions), 1)
        self.assertEqual(len(sess.closed_trades), 1)
        self.assertEqual(sess.closed_trades[0]["execution_type"], "MANUAL")

        # 4. Close Auto Trade
        ok_a, _ = sess.manual_close_position(auto_pos["trade_id"], force=True)
        self.assertTrue(ok_a)
        self.assertEqual(len(sess.positions), 0)
        self.assertEqual(len(sess.closed_trades), 2)
        # Latest closed trade is at index 0 (newest first)
        self.assertEqual(sess.closed_trades[0]["execution_type"], "AUTO")
        self.assertEqual(sess.closed_trades[1]["execution_type"], "MANUAL")

        # Verify margin fully released
        self.assertEqual(sess.allocated_margin, 0.0)

        # 5. Check Analytics Isolation
        all_ana = sess.get_performance_analytics()
        auto_ana = sess.get_performance_analytics(execution_type="AUTO")
        man_ana = sess.get_performance_analytics(execution_type="MANUAL")

        self.assertEqual(all_ana["total_trades"], 2)
        self.assertEqual(auto_ana["total_trades"], 1)
        self.assertEqual(man_ana["total_trades"], 1)

    def test_03_3way_leaderboard_consistency(self):
        """Verifies 3-way leaderboard correctly separates AI and Manual performances."""
        manager = MultiUserPaperSessionManager(db=None)

        # User 1: Only Manual Trader
        u1, _ = manager.get_session("Trader_Manual_Only")
        u1.reset(100000.0)
        p1, _ = u1.execute_manual_trade("NIFTY", 24500, "CE", stop_loss_pct=10.0, lots=1)
        u1.manual_close_position(p1["trade_id"], force=True)

        # User 2: Only AI Trader
        u2, _ = manager.get_session("Trader_AI_Only")
        u2.reset(100000.0)
        u2.start()
        setup = {
            "symbol": "INFY", "name": "Infosys", "type": "STOCK", "market_cap": "LARGE_CAP",
            "action": "BUY", "entry_price": 1800.0, "stop_loss": 1750.0, "target_price": 1900.0,
            "status": "VALIDATED", "holding_duration_mins": 1440
        }
        p2, _ = u2.execute_trade(setup, quote_resolver=lambda s: {"symbol": s, "lastPrice": 1800.0}, market_is_open=True)
        u2.manual_close_position(p2["trade_id"], force=True)

        # Leaderboard Queries
        lb_mix = manager.get_leaderboard(mode="mix")
        lb_ai = manager.get_leaderboard(mode="ai_only")
        lb_man = manager.get_leaderboard(mode="manual_only")

        # Find user 1 and user 2 in each mode
        def find_u(lb, name):
            return next((x for x in lb if x["user_name"] == name), None)

        # Mix mode
        self.assertEqual(find_u(lb_mix, "Trader_Manual_Only")["total_trades"], 1)
        self.assertEqual(find_u(lb_mix, "Trader_AI_Only")["total_trades"], 1)

        # AI-only mode
        self.assertEqual(find_u(lb_ai, "Trader_Manual_Only")["total_trades"], 0)
        self.assertEqual(find_u(lb_ai, "Trader_AI_Only")["total_trades"], 1)

        # Manual-only mode
        self.assertEqual(find_u(lb_man, "Trader_Manual_Only")["total_trades"], 1)
        self.assertEqual(find_u(lb_man, "Trader_AI_Only")["total_trades"], 0)

    def test_04_circuit_breaker_manual_reset_and_no_retrigger(self):
        """Verifies Circuit Breaker does NOT re-trigger immediately after manual reset."""
        sess = PaperTradingSession(user_name="CB_Reset_Tester")
        sess.reset(100000.0)
        sess.config["max_daily_drawdown_pct"] = 5.0

        # Simulate a 9% loss
        sess.account_equity = 91000.0
        sess.peak_equity = 100000.0

        # can_open_new_trade triggers Circuit Breaker
        can_trade, reason = sess.can_open_new_trade(is_manual=False)
        self.assertFalse(can_trade)
        self.assertTrue(sess.is_circuit_breaker_triggered)
        self.assertIn("9.0%", sess.circuit_breaker_reason)

        # Reset Circuit Breaker
        sess.reset_circuit_breaker()
        self.assertFalse(sess.is_circuit_breaker_triggered)
        self.assertEqual(sess.max_drawdown_pct, 0.0)
        self.assertEqual(sess.peak_equity, sess.account_equity)

        # Update configuration (which previously triggered the loop)
        sess.update_config({"risk_profile": "AGGRESSIVE", "max_open_positions": 10})

        # Next check should NOT re-trigger because peak_equity has been adjusted
        can_trade_after, msg_after = sess.can_open_new_trade(is_manual=True)
        self.assertTrue(can_trade_after, f"Circuit breaker falsely re-triggered: {msg_after}")
        self.assertFalse(sess.is_circuit_breaker_triggered)

    def test_05_rest_api_full_flow(self):
        """Tests live API calls: option-quote, manual-order, leaderboard, analytics, and csv export."""
        user = f"RestApi_FullUser_{uuid.uuid4().hex[:6]}"
        sess, _ = paper_manager.get_session(user)
        sess.reset(initial_capital=200000.0)

        # 1. Option Quote
        q_res = self.client.get("/api/paper/option-quote?symbol=BANK NIFTY&strike=52000&option_type=CE")
        self.assertEqual(q_res.status_code, 200)
        q_data = json.loads(q_res.data)
        self.assertTrue(q_data["ok"])
        self.assertEqual(q_data["base_symbol"], "BANK NIFTY")
        self.assertGreater(q_data["premium"], 0)
        self.assertGreater(q_data["margin_1_lot"], 0)

        # 2. Manual Order Rejection (Missing SL)
        bad_order = self.client.post(
            f"/api/paper/manual-order?user={user}",
            json={"base_symbol": "BANK NIFTY", "strike": 52000, "option_type": "CE", "lots": 1}
        )
        self.assertEqual(bad_order.status_code, 400)
        self.assertIn("mandatory", json.loads(bad_order.data).get("error", "").lower())

        # 3. Manual Order Placement (Success with Algo Target)
        good_order = self.client.post(
            f"/api/paper/manual-order?user={user}",
            json={
                "base_symbol": "BANK NIFTY",
                "strike": 52000,
                "option_type": "CE",
                "stop_loss_pct": 15.0,
                "algo_target": True,
                "lots": 1
            }
        )
        self.assertEqual(good_order.status_code, 200)
        order_res = json.loads(good_order.data)
        self.assertTrue(order_res["ok"])
        trade_id = order_res["position"]["trade_id"]
        self.assertEqual(order_res["position"]["execution_type"], "MANUAL")

        # 4. Manual Close Position
        close_res = self.client.post(
            f"/api/paper/manual-close?user={user}",
            json={"trade_id": trade_id, "force": True}
        )
        self.assertEqual(close_res.status_code, 200)

        # 5. Query Analytics with mode filter
        ana_res = self.client.get(f"/api/paper/analytics?user={user}&mode=manual")
        self.assertEqual(ana_res.status_code, 200)
        ana_data = json.loads(ana_res.data)
        self.assertEqual(ana_data["total_trades"], 1)

        # 6. Query Leaderboard with mode filter
        lb_res = self.client.get("/api/paper/leaderboard?mode=manual_only")
        self.assertEqual(lb_res.status_code, 200)
        lb_data = json.loads(lb_res.data)
        self.assertTrue(lb_data["ok"])
        self.assertEqual(lb_data["mode"], "manual_only")

        # 7. CSV Export
        csv_res = self.client.get(f"/api/paper/trades/export?user={user}")
        self.assertEqual(csv_res.status_code, 200)
        csv_text = csv_res.data.decode("utf-8")
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        self.assertGreater(len(rows), 1) # Header + 1 trade row
        self.assertIn("Execution Type", rows[0])
        exec_type_col = rows[0].index("Execution Type")
        self.assertEqual(rows[1][exec_type_col], "MANUAL")


if __name__ == "__main__":
    unittest.main()
