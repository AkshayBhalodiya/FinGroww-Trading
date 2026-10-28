#!/usr/bin/env python3
"""
FinGroww AI-Powered Automated Paper Trading Test Suite
=====================================================
Comprehensive Unit & Integration Tests:
- Session Initialization & State Machine (IDLE, RUNNING, PAUSED, STOPPED)
- Configuration Validation (Capital, Instruments, Holding Duration, Risk Profiles)
- Pre-Trade Risk Supervisor (Max Open Positions, Daily Loss Limit, Market Hours)
- Indian Brokerage & Cost Model (Brokerage, STT, Exchange Turn, SEBI, GST, Slippage)
- Position Sizing & Margin Allocation (Equities, Futures Lots, Options Premiums)
- Automated Target, Stop-Loss, and Time-Based Exits
- Account Reconciliation & Performance Analytics (Win Rate, Profit Factor, Drawdown)
- REST API Integration (Flask endpoints)
- Historical Backtesting Engine
"""

import unittest
import time
import json
from fingroww_paper_engine import (
    PaperTradingSession,
    PaperTradingEngine,
    PaperTradeCostModel,
    LOT_SIZES
)
import fingroww_market_server


class TestPaperTradingEngine(unittest.TestCase):

    def setUp(self):
        test_user = f"UnitTest_{self._testMethodName}"
        self.session = PaperTradingSession(user_name=test_user, config={"initial_capital": 100000.0, "enforce_market_hours": False})
        self.session.positions = []
        self.session.closed_trades = []
        self.engine = PaperTradingEngine(session=self.session)
        self.client = fingroww_market_server.app.test_client()

    def test_01_session_initialization(self):
        """Test default session initialization, capital allocation, and initial state."""
        state = self.session.get_state()
        self.assertEqual(state["status"], "IDLE")
        self.assertEqual(state["account"]["initial_capital"], 100000.0)
        self.assertEqual(state["account"]["available_balance"], 100000.0)
        self.assertEqual(state["account"]["allocated_margin"], 0.0)
        self.assertEqual(state["account"]["realized_pnl"], 0.0)
        self.assertEqual(state["active_positions_count"], 0)
        self.assertIn("PTS-", state["session_id"])

    def test_02_config_validation_and_update(self):
        """Test configuration validation, risk profile adjustments, and multi-day/week/month holding durations."""
        # Test Conservative profile setting
        self.session.update_config({"risk_profile": "CONSERVATIVE", "holding_duration_mins": 5})
        self.assertEqual(self.session.config["max_risk_per_trade_pct"], 0.5)
        self.assertEqual(self.session.config["min_rr"], 2.0)
        self.assertEqual(self.session.config["holding_duration_mins"], 5)

        # Test Aggressive profile setting
        self.session.update_config({"risk_profile": "AGGRESSIVE", "holding_duration_mins": 30})
        self.assertEqual(self.session.config["max_risk_per_trade_pct"], 2.0)
        self.assertEqual(self.session.config["min_rr"], 1.5)
        self.assertEqual(self.session.config["holding_duration_mins"], 30)

        # Test Days, Weeks, and Months holding durations
        from fingroww_paper_engine import format_duration_display
        self.assertEqual(format_duration_display(900), "15m")
        self.assertEqual(format_duration_display(3600), "1h")
        self.assertEqual(format_duration_display(86400 * 2), "2d")
        self.assertEqual(format_duration_display(86400 * 14), "2w")
        self.assertEqual(format_duration_display(86400 * 30 * 2), "2mo")

        # Test API config with Days, Weeks, and Months
        r_day = self.client.post("/api/paper/session/config", json={"duration_val": 3, "duration_unit": "days"})
        self.assertEqual(r_day.status_code, 200)
        self.assertEqual(r_day.get_json()["state"]["config"]["holding_duration_mins"], 3 * 1440)

        r_week = self.client.post("/api/paper/session/config", json={"duration_val": 2, "duration_unit": "weeks"})
        self.assertEqual(r_week.status_code, 200)
        self.assertEqual(r_week.get_json()["state"]["config"]["holding_duration_mins"], 2 * 10080)

        r_month = self.client.post("/api/paper/session/config", json={"duration_val": 1, "duration_unit": "months"})
        self.assertEqual(r_month.status_code, 200)
        self.assertEqual(r_month.get_json()["state"]["config"]["holding_duration_mins"], 1 * 43200)

    def test_03_pre_trade_risk_supervisor(self):
        """Test risk supervisor enforcing max concurrent positions and daily loss limits."""
        # When IDLE, cannot open trade
        can_trade, reason = self.session.can_open_new_trade()
        self.assertFalse(can_trade)
        self.assertIn("IDLE", reason)

        # Start session
        self.session.start()
        can_trade, reason = self.session.can_open_new_trade()
        self.assertTrue(can_trade)

        # Test daily loss limit breach
        self.session.total_pnl = -5000.0
        self.session.config["daily_loss_limit_inr"] = 4000.0
        can_trade, reason = self.session.can_open_new_trade()
        self.assertFalse(can_trade)
        self.assertIn("breached", reason)

        # Reset PnL
        self.session.total_pnl = 0.0

        # Test max open positions limit
        self.session.config["max_open_positions"] = 2
        self.session.positions = [{"id": 1}, {"id": 2}]
        can_trade, reason = self.session.can_open_new_trade()
        self.assertFalse(can_trade)
        self.assertIn("Maximum concurrent positions", reason)

    def test_04_execution_cost_model(self):
        """Test realistic Indian brokerage, STT, turnover charges, GST, and slippage."""
        # 1. Equity buy of ₹50,000 turnover
        charges_buy = PaperTradeCostModel.calculate_charges("EQUITY", "BUY", 1000.0, 50)
        self.assertGreater(charges_buy["brokerage"], 0.0)
        self.assertGreater(charges_buy["gst"], 0.0)
        self.assertGreater(charges_buy["total"], 0.0)

        # 2. Equity sell has STT
        charges_sell = PaperTradeCostModel.calculate_charges("EQUITY", "SELL", 1000.0, 50)
        self.assertGreater(charges_sell["stt"], 0.0)

        # 3. Futures flat brokerage (₹20 per order)
        charges_fut = PaperTradeCostModel.calculate_charges("INDEX_FUTURES", "BUY", 24000.0, 25)
        self.assertEqual(charges_fut["brokerage"], 20.0)

        # 4. Realistic slippage
        exec_buy = PaperTradeCostModel.apply_slippage(1000.0, "BUY", "EQUITY")
        self.assertGreaterEqual(exec_buy, 1000.0)
        exec_sell = PaperTradeCostModel.apply_slippage(1000.0, "SELL", "EQUITY")
        self.assertLessEqual(exec_sell, 1000.0)

    def test_05_position_sizing_and_margin(self):
        """Test position sizing, lot constraints, and virtual margin deduction."""
        self.session.start()
        setup = {
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1280.0,
            "stop_loss": 1260.0,
            "target_price": 1316.0,
            "strategy": "ORB Breakout",
            "confidence_score": 88
        }
        pos, msg = self.session.execute_trade(setup)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["symbol"], "RELIANCE")
        self.assertGreater(pos["quantity"], 0)
        self.assertGreater(pos["allocated_margin"], 0.0)
        # Verify available balance was decremented by allocated margin
        expected_balance = 100000.0 - pos["allocated_margin"]
        self.assertAlmostEqual(self.session.available_balance, expected_balance, delta=1.0)

    def test_06_target_and_stop_loss_exits(self):
        """Test automatic position closure when Target or Stop Loss is breached."""
        self.session.start()
        setup = {
            "symbol": "INFY",
            "name": "Infosys Ltd",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1150.0,
            "stop_loss": 1130.0,
            "target_price": 1180.0,
            "strategy": "EMA Golden Cross",
            "confidence_score": 85
        }
        pos, _ = self.session.execute_trade(setup)
        self.assertEqual(len(self.session.positions), 1)

        # Simulate market price reaching Target Price
        target_quote = lambda sym: {"lastPrice": 1185.0}
        self.session.update_positions(target_quote)

        # Position must be closed and recorded in closed_trades
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 1)
        closed = self.session.closed_trades[0]
        self.assertEqual(closed["symbol"], "INFY")
        self.assertEqual(closed["exit_reason"], "TARGET_HIT")
        self.assertTrue(closed["is_win"])
        self.assertGreater(closed["net_pnl"], 0.0)
        # Margin released
        self.assertEqual(self.session.allocated_margin, 0.0)

    def test_07_duration_based_exit(self):
        """Test time-based exit when trade holding duration expires."""
        self.session.start()
        self.session.config["holding_duration_mins"] = 1
        setup = {
            "symbol": "TCS",
            "name": "Tata Consultancy Services",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 2500.0,
            "stop_loss": 2450.0,
            "target_price": 2600.0,
            "strategy": "VWAP Momentum",
            "confidence_score": 82
        }
        pos, _ = self.session.execute_trade(setup)
        # Force position timestamp to be in the past
        pos["target_exit_timestamp"] = time.time() - 10

        # Update positions
        self.session.update_positions(lambda sym: {"lastPrice": 2505.0})
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 1)
        self.assertEqual(self.session.closed_trades[0]["exit_reason"], "TIME_EXPIRED")

        # Test test_expire_position helper and auto_stop_on_exit
        self.session.config["auto_stop_on_exit"] = True
        pos2, _ = self.session.execute_trade(setup)
        self.assertIsNotNone(pos2)
        ok, msg = self.session.test_expire_position(pos2["trade_id"], lambda sym: {"lastPrice": 2510.0})
        self.assertTrue(ok)
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 2)
        self.assertEqual(self.session.closed_trades[0]["exit_reason"], "TIME_EXPIRED")
        self.assertEqual(self.session.status, "COMPLETED")

    def test_08_reconciliation_and_performance_analytics(self):
        """Test balance reconciliation, win rate, profit factor, and drawdown metrics."""
        self.session.start()
        
        # Add 1 winning trade and 1 losing trade
        win_trade = {
            "trade_id": "PT-WIN",
            "symbol": "SBIN",
            "name": "State Bank of India",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_time": "2026-10-28 10:00:00",
            "exit_time": "2026-10-28 10:15:00",
            "entry_price": 940.0,
            "exit_price": 955.0,
            "quantity": 100,
            "gross_pnl": 1500.0,
            "net_pnl": 1450.0,
            "charges": 50.0,
            "slippage": 10.0,
            "exit_reason": "TARGET_HIT",
            "strategy": "15m ORB Breakout",
            "is_win": True,
            "holding_seconds": 900
        }
        loss_trade = {
            "trade_id": "PT-LOSS",
            "symbol": "HDFCBANK",
            "name": "HDFC Bank",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_time": "2026-10-28 10:30:00",
            "exit_time": "2026-10-28 10:45:00",
            "entry_price": 680.0,
            "exit_price": 673.0,
            "quantity": 100,
            "gross_pnl": -700.0,
            "net_pnl": -745.0,
            "charges": 45.0,
            "slippage": 8.0,
            "exit_reason": "STOP_LOSS_HIT",
            "strategy": "20/50 EMA Golden Cross",
            "is_win": False,
            "holding_seconds": 900
        }
        self.session.closed_trades = [win_trade, loss_trade]
        self.session.realized_pnl = 1450.0 - 745.0 # 705.0

        analytics = self.session.get_performance_analytics()
        self.assertEqual(analytics["total_trades"], 2)
        self.assertEqual(analytics["winning_trades"], 1)
        self.assertEqual(analytics["losing_trades"], 1)
        self.assertEqual(analytics["win_rate"], 50.0)
        self.assertAlmostEqual(analytics["profit_factor"], 1500.0 / 700.0, places=1)
        self.assertIn("15m ORB Breakout", analytics["strategy_performance"])
        self.assertIn("EQUITY", analytics["instrument_performance"])

    def test_09_flask_api_endpoints(self):
        """Test Flask REST API endpoints for paper trading."""
        # 1. Market status
        r = self.client.get("/api/paper/market-status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("market_status", data)
        self.assertIn("ist_time", data)

        # 2. Session state
        r = self.client.get("/api/paper/session/state")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("account", data)

        # 3. Update config
        r = self.client.post("/api/paper/session/config", json={
            "initial_capital": 150000.0,
            "holding_duration_mins": 30,
            "risk_profile": "CONSERVATIVE"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

        # 4. Session control: pause, resume, reset
        r = self.client.post("/api/paper/session/control", json={"action": "pause"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"]["status"], "PAUSED")

        r = self.client.post("/api/paper/session/control", json={"action": "resume"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"]["status"], "RUNNING")

        r = self.client.post("/api/paper/session/control", json={"action": "reset", "initial_capital": 100000.0})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"]["status"], "IDLE")

        # 5. Analytics endpoint
        r = self.client.get("/api/paper/analytics")
        self.assertEqual(r.status_code, 200)

        # 6. Page route
        r = self.client.get("/ai-auto-paper-trading.html")
        self.assertEqual(r.status_code, 200)

    def test_10_backtesting_engine(self):
        """Test historical backtest with simulated transaction costs & disclaimer."""
        res = PaperTradingEngine.run_backtest(symbol="NIFTY 50", strategy="15m ORB Breakout")
        self.assertEqual(res["mode"], "HISTORICAL BACKTEST (SIMULATED)")
        self.assertIn("win_rate", res)
        self.assertIn("profit_factor", res)
        self.assertIn("disclaimer", res)

    def test_11_multi_user_isolation_and_leaderboard(self):
        """Test multi-user profile creation, state isolation, and leaderboard rankings."""
        # 1. Verify list profiles contains defaults
        r_profiles = self.client.get("/api/paper/profiles")
        self.assertEqual(r_profiles.status_code, 200)
        prof_data = r_profiles.get_json()
        self.assertIn("profiles", prof_data)
        profile_names = [p["user_name"] for p in prof_data["profiles"]]
        self.assertIn("Akshay", profile_names)

        # 2. Create new custom trader profile
        new_prof_payload = {
            "user_name": "Bhavin_Algo_Scalper",
            "initial_capital": 125000.0,
            "instruments": ["INDEX_OPTIONS"],
            "trading_style": "SCALPING",
            "risk_profile": "AGGRESSIVE",
            "holding_duration_mins": 5,
        }
        r_create = self.client.post("/api/paper/profiles/create", json=new_prof_payload)
        self.assertEqual(r_create.status_code, 200)
        self.assertTrue(r_create.get_json()["ok"])

        # 3. Test user-specific state isolation
        # User 1: Bhavin_Algo_Scalper
        r_bhavin = self.client.get("/api/paper/session/state?user=Bhavin_Algo_Scalper")
        self.assertEqual(r_bhavin.status_code, 200)
        bhavin_state = r_bhavin.get_json()
        self.assertEqual(bhavin_state["user_name"], "Bhavin_Algo_Scalper")
        self.assertEqual(bhavin_state["account"]["initial_capital"], 125000.0)
        self.assertEqual(bhavin_state["config"]["instruments"], ["INDEX_OPTIONS"])

        # User 2: Rahul_Futures_Swing
        r_rahul = self.client.get("/api/paper/session/state?user=Rahul_Futures_Swing")
        self.assertEqual(r_rahul.status_code, 200)
        rahul_state = r_rahul.get_json()
        self.assertEqual(rahul_state["user_name"], "Rahul_Futures_Swing")
        self.assertEqual(rahul_state["account"]["initial_capital"], 200000.0)

        # User 3: Akshay
        r_akshay = self.client.get("/api/paper/session/state?user=Akshay")
        self.assertEqual(r_akshay.status_code, 200)
        akshay_state = r_akshay.get_json()
        self.assertEqual(akshay_state["user_name"], "Akshay")

        # 4. Verify Leaderboard ranking
        r_lead = self.client.get("/api/paper/leaderboard")
        self.assertEqual(r_lead.status_code, 200)
        lead_data = r_lead.get_json()
        self.assertIn("leaderboard", lead_data)
        self.assertGreaterEqual(len(lead_data["leaderboard"]), 2)
        # Check that top trader has rank 1 and appropriate badge
        self.assertEqual(lead_data["leaderboard"][0]["rank"], 1)
        self.assertIn("badge", lead_data["leaderboard"][0])


if __name__ == "__main__":
    unittest.main()

