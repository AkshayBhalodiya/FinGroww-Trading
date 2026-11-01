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
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from fingroww_paper_engine import (
    PaperTradingSession,
    PaperTradingEngine,
    PaperTradeCostModel,
    MultiUserPaperSessionManager,
    LOCAL_USER_DATASTORE,
    LOT_SIZES
)
import fingroww_market_server


class TestPaperTradingEngine(unittest.TestCase):

    def setUp(self):
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        days_offset = (now.weekday() - 2) if now.weekday() >= 5 else 0
        today_ist = (now - timedelta(days=days_offset)).replace(
            hour=11, minute=0, second=0, microsecond=0
        )
        trading_time_patcher = patch(
            "fingroww_paper_engine.get_ist_now",
            return_value=today_ist,
        )
        trading_time_patcher.start()
        self.addCleanup(trading_time_patcher.stop)

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_patcher = patch.dict(
            os.environ,
            {"FINGROWW_PAPER_DB_PATH": os.path.join(self.temp_dir.name, "paper_trading.db")},
        )
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

        self.original_local_data = deepcopy(LOCAL_USER_DATASTORE)
        LOCAL_USER_DATASTORE["sessions"].clear()
        LOCAL_USER_DATASTORE["profiles"].clear()
        LOCAL_USER_DATASTORE["trades"].clear()
        self.addCleanup(self._restore_local_data)

        self.original_paper_manager = fingroww_market_server.paper_manager
        fingroww_market_server.paper_manager = MultiUserPaperSessionManager(
            db=fingroww_market_server.mongo_db,
            quote_resolver=fingroww_market_server.resolve_quote,
            chart_resolver=fingroww_market_server.fetch_yahoo_chart,
        )
        fingroww_market_server.paper_session, fingroww_market_server.paper_engine = (
            fingroww_market_server.paper_manager.get_session("Akshay")
        )
        self.addCleanup(self._restore_paper_manager)

        test_user = f"UnitTest_{self._testMethodName}"
        self.session = PaperTradingSession(user_name=test_user, config={"initial_capital": 100000.0})
        self.session.positions = []
        self.session.closed_trades = []
        self.engine = PaperTradingEngine(session=self.session)
        self.client = fingroww_market_server.app.test_client()

    def _restore_paper_manager(self):
        fingroww_market_server.paper_manager = self.original_paper_manager
        fingroww_market_server.paper_session, fingroww_market_server.paper_engine = (
            self.original_paper_manager.get_session("Akshay")
        )

    def _restore_local_data(self):
        LOCAL_USER_DATASTORE.clear()
        LOCAL_USER_DATASTORE.update(self.original_local_data)

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
        pos, msg = self.session.execute_trade(setup, market_is_open=True)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["symbol"], "RELIANCE")
        self.assertGreater(pos["quantity"], 0)
        self.assertGreater(pos["allocated_margin"], 0.0)
        # Available balance reserves both the position margin and entry charges.
        expected_balance = 100000.0 - pos["allocated_margin"] - pos["entry_charges"]
        self.assertAlmostEqual(self.session.available_balance, expected_balance, places=2)

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
        pos, _ = self.session.execute_trade(setup, market_is_open=True)
        self.assertEqual(len(self.session.positions), 1)

        # Simulate market price reaching Target Price
        target_quote = lambda sym: {
            "source": "NSE", "lastPrice": 1185.0,
            "fetched_at": time.time(), "exchange_timestamp": time.time(),
        }
        self.session.update_positions(target_quote, market_is_open=True)

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
        pos, _ = self.session.execute_trade(setup, market_is_open=True)
        # Force position timestamp to be in the past
        pos["target_exit_timestamp"] = time.time() - 10

        # Update positions
        self.session.update_positions(lambda sym: {
            "source": "NSE", "lastPrice": 2505.0,
            "fetched_at": time.time(), "exchange_timestamp": time.time(),
        }, market_is_open=True)
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 1)
        self.assertEqual(self.session.closed_trades[0]["exit_reason"], "TIME_EXPIRED")

        # Test test_expire_position helper and auto_stop_on_exit
        self.session.config["auto_stop_on_exit"] = True
        pos2, _ = self.session.execute_trade(setup, market_is_open=True)
        self.assertIsNotNone(pos2)
        ok, msg = self.session.test_expire_position(
            pos2["trade_id"],
            lambda sym: {
                "source": "NSE", "lastPrice": 2510.0,
                "fetched_at": time.time(), "exchange_timestamp": time.time(),
            },
            market_is_open=True,
        )
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
        status_response = {
            "marketState": [{
                "market": "Capital Market",
                "marketStatus": "Open",
                "tradeDate": "28-Oct-2026",
            }]
        }
        fingroww_market_server.paper_market_cache.update({"at": 0, "status": None})
        with patch.object(fingroww_market_server, "nse_get", return_value=status_response), \
             patch.object(fingroww_market_server, "get_ist_now", return_value=datetime(2026, 10, 28, 11, 0)):
            r = self.client.get("/api/paper/market-status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("market_status", data)
        self.assertIn("ist_time", data)
        self.assertTrue(data["is_trading_hours"])
        self.assertEqual(data["market_status_source"], "NSE official market status")

        fingroww_market_server.paper_market_cache.update({"at": 0, "status": None})
        with patch.object(fingroww_market_server, "nse_get", return_value=None):
            closed = self.client.get("/api/paper/market-status").get_json()
        self.assertFalse(closed["is_trading_hours"])
        self.assertEqual(closed["freshness"], "NO_LIVE_TRADING")

        # 2. Session state
        r = self.client.get("/api/paper/session/state")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("account", data)

        with patch.object(
            fingroww_market_server,
            "get_nse_market_status",
            return_value={
                "is_trading_hours": False,
                "market_status": "CLOSED",
                "reason": "NSE regular trading session is closed.",
            },
        ):
            start_closed = self.client.post(
                "/api/paper/session/start",
                json={"user_name": "Akshay"},
            )
        self.assertEqual(start_closed.status_code, 409)
        self.assertNotEqual(
            fingroww_market_server.paper_manager.get_session("Akshay")[0].status,
            "RUNNING",
        )

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

        with patch.object(
            fingroww_market_server,
            "get_nse_market_status",
            return_value={"is_trading_hours": False, "market_status": "CLOSED"},
        ):
            resume_closed = self.client.post(
                "/api/paper/session/control",
                json={"action": "resume"},
            )
        self.assertEqual(resume_closed.status_code, 409)
        self.assertEqual(
            fingroww_market_server.paper_manager.get_session("Akshay")[0].status,
            "PAUSED",
        )

        with patch.object(
            fingroww_market_server,
            "get_nse_market_status",
            return_value={"is_trading_hours": True, "market_status": "OPEN"},
        ):
            r = self.client.post(
                "/api/paper/session/control",
                json={"action": "resume"},
            )
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
        r_duplicate = self.client.post("/api/paper/profiles/create", json=new_prof_payload)
        self.assertEqual(r_duplicate.status_code, 409)

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

    def test_12_user_data_persists_across_manager_restart(self):
        """Paper account state and complete trade history survive process restarts."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "paper_trading.db")
            profile_name = f"Persistence_{self._testMethodName}"
            with patch.dict(os.environ, {"FINGROWW_PAPER_DB_PATH": db_path}):
                manager = MultiUserPaperSessionManager()
                session, message = manager.create_profile(
                    profile_name,
                    {"initial_capital": 125000.0, "instruments": ["EQUITY"]},
                )
                self.assertIsNotNone(session, message)
                session.closed_trades = [
                    {
                        "trade_id": f"PT-{index}",
                        "gross_pnl": index,
                        "net_pnl": index,
                        "is_win": True,
                    }
                    for index in range(125)
                ]
                session.save_to_db()

                restarted_manager = MultiUserPaperSessionManager()
                restored, _ = restarted_manager.get_session(profile_name)
                self.assertEqual(restored.initial_capital, 125000.0)
                self.assertEqual(len(restored.closed_trades), 125)
                self.assertEqual(restored.closed_trades[-1]["trade_id"], "PT-124")

                stale_mongo_doc = deepcopy(LOCAL_USER_DATASTORE["sessions"][profile_name])
                stale_mongo_doc["last_updated"] = "2000-01-01 00:00:00 IST"
                stale_mongo_doc["account"]["initial_capital"] = 5000.0
                stale_mongo_doc["closed_trades"] = []

                class StaleMongoCollection:
                    def find_one(self, *_args, **_kwargs):
                        return stale_mongo_doc

                class StaleMongoDatabase:
                    def __getitem__(self, _collection_name):
                        return StaleMongoCollection()

                restored_with_stale_mongo = PaperTradingSession(
                    user_name=profile_name,
                    db=StaleMongoDatabase(),
                )
                self.assertEqual(restored_with_stale_mongo.initial_capital, 125000.0)
                self.assertEqual(len(restored_with_stale_mongo.closed_trades), 125)

                duplicate, duplicate_message = restarted_manager.create_profile(profile_name)
                self.assertIsNone(duplicate)
                self.assertIn("already exists", duplicate_message)
                self.assertEqual(
                    len(restarted_manager.get_session(profile_name)[0].closed_trades),
                    125,
                )

    def test_13_closed_market_blocks_automatic_entries(self):
        self.session.start()
        quote_calls = []
        engine = PaperTradingEngine(
            self.session,
            quote_resolver=lambda symbol: quote_calls.append(symbol),
            chart_resolver=lambda *_args: [],
            market_status_resolver=lambda: {"is_trading_hours": False},
        )

        state = engine.tick()

        self.assertEqual(state["active_positions_count"], 0)
        self.assertEqual(quote_calls, [])

    def test_closed_market_blocks_new_trades_and_position_loss_updates(self):
        self.session.start()
        setup = {
            "symbol": "RELIANCE",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1280.0,
            "stop_loss": 1260.0,
            "target_price": 1316.0,
        }
        position, message = self.session.execute_trade(setup, market_is_open=True)
        self.assertIsNotNone(position, message)
        previous_price = position["current_price"]
        previous_unrealized = position["unrealized_pnl"]

        quote_calls = []
        engine = PaperTradingEngine(
            self.session,
            quote_resolver=lambda symbol: quote_calls.append(symbol) or {
                "source": "NSE",
                "lastPrice": 1200.0,
                "fetched_at": time.time(),
                "exchange_timestamp": time.time(),
            },
            chart_resolver=lambda *_args: [],
            market_status_resolver=lambda: {"is_trading_hours": False},
        )
        state = engine.tick()

        self.assertEqual(quote_calls, [])
        self.assertEqual(state["active_positions_count"], 1)
        self.assertEqual(position["current_price"], previous_price)
        self.assertEqual(position["unrealized_pnl"], previous_unrealized)
        rejected, rejection_message = self.session.execute_trade(
            {**setup, "symbol": "INFY"},
        )
        self.assertIsNone(rejected)
        self.assertIn("market is closed", rejection_message)

    def test_14_cached_open_status_turns_closed_at_market_end(self):
        fingroww_market_server.paper_market_cache.update({
            "at": time.time(),
            "status": {
                "is_trading_hours": True,
                "market_status": "OPEN",
                "source": "NSE official market status",
                "trade_date": "28-Oct-2026",
                "reason": None,
            },
        })

        with patch.object(
            fingroww_market_server,
            "get_ist_now",
            return_value=datetime(2026, 10, 28, 21, 49),
        ), patch.object(fingroww_market_server, "nse_get") as nse_request:
            status = fingroww_market_server.get_nse_market_status()

        self.assertFalse(status["is_trading_hours"])
        self.assertEqual(status["market_status"], "CLOSED")
        nse_request.assert_not_called()

    def test_15_missing_or_non_nse_quotes_never_mark_positions(self):
        self.session.start()
        setup = {
            "symbol": "INFY",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1150.0,
            "stop_loss": 1130.0,
            "target_price": 1180.0,
        }
        position, _ = self.session.execute_trade(setup, market_is_open=True)
        original_price = position["current_price"]
        position["target_exit_timestamp"] = time.time() - 10

        self.session.update_positions(
            lambda _symbol: {"source": "Yahoo Finance", "lastPrice": 5000.0},
            market_is_open=True,
        )

        self.assertEqual(len(self.session.positions), 1)
        self.assertEqual(position["current_price"], original_price)
        self.assertEqual(self.session.closed_trades, [])
        closed, message = self.session.manual_close_position(
            position["trade_id"],
            quote_resolver=lambda _symbol: {
                "source": "Yahoo Finance",
                "lastPrice": 5000.0,
                "fetched_at": time.time(),
                "exchange_timestamp": time.time(),
            },
            market_is_open=True,
        )
        self.assertFalse(closed)
        self.assertIn("fresh NSE quote", message)
        self.assertEqual(len(self.session.positions), 1)

    def test_16_live_quote_resolver_does_not_fall_back(self):
        fingroww_market_server.paper_live_quote_cache.pop("RELIANCE", None)
        with patch.object(fingroww_market_server, "quote_from_nse_equity", return_value=None), \
             patch.object(fingroww_market_server, "quote_from_yahoo") as yahoo_fallback:
            quote = fingroww_market_server.resolve_live_quote("RELIANCE")

        self.assertIsNone(quote)
        yahoo_fallback.assert_not_called()

    def test_17_signal_uses_confirmed_candles_and_atr_levels_from_live_entry(self):
        now_ms = int(time.time() * 1000)
        candle_count = 70
        first_candle_ms = now_ms - (candle_count * 15 * 60 * 1000) - (16 * 60 * 1000)
        candles = []
        for index in range(candle_count):
            close = 100.0 + index * 0.1
            candles.append({
                "o": close - 0.02,
                "h": close + 0.02,
                "l": close - 0.04,
                "c": close,
                "v": 150.0 if index == candle_count - 1 else 100.0,
                "t": first_candle_ms + index * 15 * 60 * 1000,
            })
        live_price = candles[-1]["c"] + 0.1
        self.session.config["instruments"] = ["EQUITY"]
        self.engine.quote_resolver = lambda _symbol: {
            "source": "NSE",
            "lastPrice": live_price,
            "fetched_at": time.time(),
            "exchange_timestamp": time.time(),
        }
        self.engine.chart_resolver = lambda *_args: candles

        setups = self.engine.scan_and_evaluate_setups()
        setup = next(candidate for candidate in setups if candidate["symbol"] == "RELIANCE")

        self.assertEqual(setup["strategy"], "15m EMA20/50 + VWAP Breakout")
        self.assertEqual(setup["status"], "VALIDATED")
        self.assertEqual(setup["entry_price"], live_price)
        self.assertLess(setup["stop_loss"], setup["entry_price"])
        self.assertGreater(setup["target_price"], setup["entry_price"])
        self.assertIn("ATR(14)", setup["rationale"])

        self.session.start()
        new_live_price = live_price + 1.0
        self.engine.quote_resolver = lambda _symbol: {
            "source": "NSE",
            "lastPrice": new_live_price,
            "fetched_at": time.time(),
            "exchange_timestamp": time.time(),
        }
        position, message = self.session.execute_trade(
            setup,
            self.engine.quote_resolver,
            market_is_open=True,
        )

        self.assertIsNotNone(position, message)
        self.assertNotEqual(position["entry_price"], setup["entry_price"])
        risk = setup["risk_distance"]
        self.assertAlmostEqual(position["stop_loss"], position["entry_price"] - risk, places=2)
        self.assertAlmostEqual(
            position["target_price"],
            position["entry_price"] + (risk * setup["reward_risk"]),
            places=2,
        )

    def test_18_synthetic_option_quotes_are_not_scanned_for_auto_trading(self):
        self.session.config["instruments"] = ["INDEX_OPTIONS"]
        self.engine.quote_resolver = lambda _symbol: {
            "source": "NSE",
            "lastPrice": 25000.0,
            "fetched_at": time.time(),
        }
        self.engine.chart_resolver = lambda *_args: []

        self.assertEqual(self.engine.scan_and_evaluate_setups(), [])

    def test_19_available_balance_reconciles_to_this_users_equity(self):
        self.session.realized_pnl = -5101.58
        self.session.available_balance = 313988.13

        account = self.session.get_state()["account"]

        self.assertEqual(account["available_balance"], 94898.42)
        self.assertEqual(account["account_equity"], 94898.42)
        self.assertEqual(
            account["available_balance"] + account["allocated_margin"],
            account["initial_capital"] + account["realized_pnl"],
        )
        self.assertTrue(any(log["type"] == "ACCOUNT_RECONCILED" for log in self.session.logs))

        reloaded_user = PaperTradingSession(
            user_name=self.session.user_name,
            config={"initial_capital": 100000.0},
        )
        self.assertEqual(
            reloaded_user.get_state()["account"]["available_balance"],
            94898.42,
        )

        self.session.realized_pnl = 2000.0
        self.session.positions = [{"allocated_margin": 25000.0, "unrealized_pnl": 100.0}]
        self.session.available_balance = 99999.0
        account_with_position = self.session.get_state()["account"]
        self.assertEqual(account_with_position["allocated_margin"], 25000.0)
        self.assertEqual(account_with_position["available_balance"], 77000.0)
        self.assertEqual(account_with_position["account_equity"], 102100.0)

        other_user = PaperTradingSession(
            user_name=f"Independent_{self._testMethodName}",
            config={"initial_capital": 50000.0},
        )
        other_account = other_user.get_state()["account"]
        self.assertEqual(other_account["available_balance"], 50000.0)
        self.assertEqual(other_account["realized_pnl"], 0.0)

    def test_20_closing_a_trade_twice_does_not_credit_margin_twice(self):
        self.session.start()
        position, message = self.session.execute_trade({
            "symbol": "RELIANCE",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1280.0,
            "stop_loss": 1260.0,
            "target_price": 1316.0,
        }, market_is_open=True)
        self.assertIsNotNone(position, message)
        expected_open_balance = (
            self.session.initial_capital
            - position["allocated_margin"]
            - position["entry_charges"]
        )
        self.assertAlmostEqual(
            self.session.available_balance,
            expected_open_balance,
            places=2,
        )

        self.assertTrue(self.session._close_position(position, "MANUAL_EXIT", 1270.0))
        account_after_first_close = self.session.get_state()["account"]
        self.assertAlmostEqual(
            account_after_first_close["available_balance"],
            self.session.initial_capital + account_after_first_close["realized_pnl"],
            places=2,
        )
        self.assertFalse(self.session._close_position(position, "MANUAL_EXIT", 1270.0))
        account_after_second_close = self.session.get_state()["account"]

        self.assertEqual(
            account_after_second_close["available_balance"],
            account_after_first_close["available_balance"],
        )
        self.assertEqual(
            account_after_second_close["realized_pnl"],
            account_after_first_close["realized_pnl"],
        )
        self.assertEqual(len(self.session.closed_trades), 1)
    def test_21_mongo_and_disk_persistence_stocks_and_leaderboard(self):
        """Test persistent storage for new users, stock positions, and universal leaderboard rankings."""
        from fingroww_paper_engine import MultiUserPaperSessionManager, LOCAL_USER_DATASTORE, DATASTORE_FILE
        import os

        # 1. Create a new user profile "Parth_Trader"
        create_res = self.client.post("/api/paper/profiles/create", json={
            "user_name": "Parth_Trader",
            "initial_capital": 250000.0,
            "instruments": ["EQUITY", "INDEX_FUTURES"],
            "trading_style": "INTRADAY",
            "risk_profile": "MODERATE",
            "holding_duration_mins": 15
        })
        self.assertEqual(create_res.status_code, 200)
        self.assertTrue(create_res.get_json()["ok"])

        # 2. Verify profile is saved in LOCAL_USER_DATASTORE and persistent file
        self.assertIn("Parth_Trader", LOCAL_USER_DATASTORE["profiles"])
        self.assertEqual(LOCAL_USER_DATASTORE["profiles"]["Parth_Trader"]["initial_capital"], 250000.0)
        self.assertTrue(os.path.exists(DATASTORE_FILE))

        # 3. Simulate opening a stock position for Parth_Trader
        parth_sess, parth_eng = fingroww_market_server.paper_manager.get_session("Parth_Trader")
        parth_sess.start()
        pos_candidate = {
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "confidence_score": 88,
            "rationale": "ORB Breakout",
            "entry_price": 1285.0,
            "target_price": 1315.0,
            "stop_loss": 1270.0,
            "lot_size": 1,
            "expiry_type": "INTRADAY"
        }
        pos, err = parth_sess.execute_trade(pos_candidate, market_is_open=True)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["symbol"], "RELIANCE")

        # 4. Verify /api/paper/positions returns the active stock position
        r_pos = self.client.get("/api/paper/positions?user=Parth_Trader")
        self.assertEqual(r_pos.status_code, 200)
        pos_data = r_pos.get_json()
        self.assertEqual(pos_data["user_name"], "Parth_Trader")
        self.assertEqual(pos_data["count"], 1)
        self.assertEqual(pos_data["positions"][0]["symbol"], "RELIANCE")

        # 5. Verify /api/paper/leaderboard returns all profiles sorted identically with ranks
        r_lead = self.client.get("/api/paper/leaderboard")
        self.assertEqual(r_lead.status_code, 200)
        lead = r_lead.get_json()["leaderboard"]
        trader_names = [p["user_name"] for p in lead]
        self.assertIn("Parth_Trader", trader_names)

        # Check that Parth_Trader has active_stocks and open_positions_count
        parth_lead = next(p for p in lead if p["user_name"] == "Parth_Trader")
        self.assertIn("RELIANCE", parth_lead.get("active_stocks", []))
        self.assertEqual(parth_lead.get("open_positions_count"), 1)

        # 6. Verify that a newly instantiated MultiUserPaperSessionManager recovers Parth_Trader from persistent disk/DB
        new_manager = MultiUserPaperSessionManager(db=None)
        recovered_profiles = [p["user_name"] for p in new_manager.list_profiles()]
        self.assertIn("Parth_Trader", recovered_profiles)
        rec_sess, _ = new_manager.get_session("Parth_Trader")
        self.assertEqual(rec_sess.initial_capital, 250000.0)
        self.assertEqual(len(rec_sess.positions), 1)
        self.assertEqual(rec_sess.positions[0]["symbol"], "RELIANCE")

    def test_22_option_delta_pricing_and_update_positions_prevent_impossible_profits(self):
        """
        Verifies that INDEX_OPTIONS positions:
        1. Calculate current price based on option delta movement and underlying spot diff, NOT raw index spot.
        2. Prevent immediate false TARGET_HIT exit in 1 second.
        3. Unrealized and realized P&L are realistic (e.g. points in premium) rather than millions of rupees.
        4. Manual close and close all also evaluate at option premium.
        """
        # Test helper directly
        pos_ce = {
            "symbol": "NIFTY 50 23050 CE",
            "instrument_type": "INDEX_OPTIONS",
            "side": "BUY",
            "entry_price": 230.80,
            "underlying_entry_price": 23050.0,
            "option_type": "CE",
            "strike": 23050,
            "delta": 0.50,
        }
        # Spot rises from 23050 to 23054.05 (+4.05 points)
        curr_p = self.session._calculate_option_current_price(pos_ce, 23054.05)
        self.assertAlmostEqual(curr_p, 232.82, delta=0.05)

        # PE option: spot rises (+4.05 points) -> PE premium drops
        pos_pe = {
            "symbol": "NIFTY 50 23050 PE",
            "instrument_type": "INDEX_OPTIONS",
            "side": "BUY",
            "entry_price": 230.80,
            "underlying_entry_price": 23050.0,
            "option_type": "PE",
            "strike": 23050,
            "delta": 0.50,
        }
        curr_pe_p = self.session._calculate_option_current_price(pos_pe, 23054.05)
        self.assertAlmostEqual(curr_pe_p, 230.80 - (4.05 * 0.50), places=2)
        self.assertAlmostEqual(curr_pe_p, 228.78, places=2)

        # Test full execution and update_positions
        self.session.reset(100000.0)
        self.session.start()
        setup = {
            "symbol": "NIFTY 50 23050 CE",
            "base_symbol": "NIFTY 50",
            "name": "Nifty 50 23050 Call",
            "instrument_type": "INDEX_OPTIONS",
            "side": "BUY",
            "entry_price": 230.80,
            "stop_loss": 173.10,
            "target_price": 334.66,
            "underlying_price": 23050.0,
            "option_type": "CE",
            "strike": 23050,
            "delta": 0.50,
            "confidence_score": 85,
            "rationale": "Bullish breakout",
        }
        quote_resolver = lambda _sym: {
            "source": "NSE",
            "lastPrice": 23050.0,
            "fetched_at": time.time(),
        }
        pos, err = self.session.execute_trade(setup, quote_resolver=quote_resolver, market_is_open=True)
        self.assertIsNotNone(pos, err)
        self.assertEqual(pos["symbol"], "NIFTY 50 23050 CE")
        self.assertEqual(pos["instrument_type"], "INDEX_OPTIONS")
        self.assertAlmostEqual(pos["underlying_entry_price"], 23050.0, places=1)

        # Now simulate market tick with index spot at 23054.05
        spot_resolver = lambda _sym: {
            "source": "NSE",
            "lastPrice": 23054.05,
            "fetched_at": time.time(),
        }
        self.session.update_positions(spot_resolver, market_is_open=True)

        # Crucial assertions:
        # Position must STILL BE OPEN (TARGET_HIT should NOT trigger!)
        self.assertEqual(len(self.session.positions), 1)
        self.assertEqual(len(self.session.closed_trades), 0)
        open_pos = self.session.positions[0]
        # Current price should be around 232.83, NOT 23054.05!
        self.assertAlmostEqual(open_pos["current_price"], 232.82, delta=1.0)
        self.assertLess(open_pos["current_price"], 300.0)
        # Unrealized PnL should be around a few tens of rupees, NOT 182,586!
        self.assertLess(open_pos["unrealized_pnl"], 1000.0)

        # Now test manual close uses option price
        closed = self.session.manual_close_position(open_pos["trade_id"], quote_resolver=spot_resolver, market_is_open=True)
        self.assertTrue(closed)
        self.assertEqual(len(self.session.closed_trades), 1)
        trade = self.session.closed_trades[0]
        self.assertAlmostEqual(trade["exit_price"], 232.82, delta=2.0)
        self.assertLess(trade["exit_price"], 300.0)
        self.assertLess(trade["gross_pnl"], 1000.0)

        # 5. Test real TARGET_HIT when underlying spot actually moves substantially
        self.session.reset(100000.0)
        self.session.start()
        pos, _ = self.session.execute_trade(setup, quote_resolver=quote_resolver, market_is_open=True)
        # Spot rises 210 points to 23260 (delta gain +105, premium ~335.80 >= target 334.66)
        rally_resolver = lambda _sym: {
            "source": "NSE",
            "lastPrice": 23260.0,
            "fetched_at": time.time(),
        }
        self.session.update_positions(rally_resolver, market_is_open=True)
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 1)
        target_trade = self.session.closed_trades[0]
        self.assertEqual(target_trade["exit_reason"], "TARGET_HIT")
        self.assertAlmostEqual(target_trade["exit_price"], 335.80, delta=2.0)
        self.assertGreater(target_trade["gross_pnl"], 0)
        self.assertLess(target_trade["gross_pnl"], 10000.0)  # Realistic profit, not 182,586!



    def test_24_strict_instrument_selection_filters_only_requested_types(self):
        """
        Verifies that scan_and_evaluate_setups strictly respects the user's selected instruments:
        1. When only INDEX_OPTIONS is selected, NO EQUITY stocks are included.
        2. When only INDEX_FUTURES is selected, NO EQUITY stocks are included.
        3. When only EQUITY is selected, NO INDEX items are included.
        4. When volume is 0 on index candles, session average typical price is used for VWAP.
        """
        from fingroww_paper_engine import _session_vwap

        # Test index VWAP with zero volume candles
        sample_candles = [
            {"o": 23000, "h": 23100, "l": 22950, "c": 23050, "v": 0, "t": int(time.time() * 1000)}
        ]
        vwap_val = _session_vwap(sample_candles)
        self.assertIsNotNone(vwap_val)
        self.assertAlmostEqual(vwap_val, (23100 + 22950 + 23050) / 3, places=2)

        # Mock quote and chart resolvers that return valid candles for all symbols
        now_ms = int(time.time() * 1000)
        dummy_candles = []
        for i in range(65):
            t_candle = now_ms - (65 - i) * 15 * 60 * 1000 - 20000
            dummy_candles.append({"o": 23000.0 + i, "h": 23010.0 + i, "l": 22990.0 + i, "c": 23005.0 + i, "v": 0, "t": t_candle})

        self.engine.quote_resolver = lambda _sym: {
            "source": "NSE",
            "lastPrice": 23050.0,
            "pChange": 0.5,
            "fetched_at": time.time(),
        }
        self.engine.chart_resolver = lambda _sym, _tf, _rg: dummy_candles

        # Scenario 1: User selects ONLY INDEX_OPTIONS
        self.session.config["instruments"] = ["INDEX_OPTIONS"]
        setups_opts = self.engine.scan_and_evaluate_setups()
        self.assertGreater(len(setups_opts), 0)
        for s in setups_opts:
            self.assertEqual(s["instrument_type"], "INDEX_OPTIONS")
            self.assertIn(s["base_symbol"], ["NIFTY 50", "BANK NIFTY", "FINNIFTY", "MIDCPNIFTY"])

        # Scenario 2: User selects ONLY INDEX_FUTURES
        self.session.config["instruments"] = ["INDEX_FUTURES"]
        setups_futs = self.engine.scan_and_evaluate_setups()
        self.assertGreater(len(setups_futs), 0)
        for s in setups_futs:
            self.assertEqual(s["instrument_type"], "INDEX_FUTURES")
            self.assertIn(s["base_symbol"], ["NIFTY 50", "BANK NIFTY", "FINNIFTY", "MIDCPNIFTY"])

        # Scenario 3: User selects ONLY EQUITY
        # For equity, dummy candles with volume > 0
        dummy_stock_candles = [dict(c, v=50000) for c in dummy_candles]
        self.engine.chart_resolver = lambda _sym, _tf, _rg: dummy_stock_candles
        self.session.config["instruments"] = ["EQUITY"]
        setups_eq = self.engine.scan_and_evaluate_setups()
        self.assertGreater(len(setups_eq), 0)
        for s in setups_eq:
            self.assertEqual(s["instrument_type"], "EQUITY")
            self.assertNotIn(s["base_symbol"], ["NIFTY 50", "BANK NIFTY", "FINNIFTY", "MIDCPNIFTY"])

        # Scenario 4: User selects BOTH INDEX_OPTIONS and INDEX_FUTURES
        self.session.config["instruments"] = ["INDEX_OPTIONS", "INDEX_FUTURES"]
        setups_both = self.engine.scan_and_evaluate_setups()
        types = {s["instrument_type"] for s in setups_both}
        self.assertEqual(types, {"INDEX_OPTIONS", "INDEX_FUTURES"})


    def test_25_timewise_profit_ranking_and_anti_chasing_protection(self):
        """
        Verifies that:
        1. When User 1 enters at 100 with target 120, it has full R:R and profit potential.
        2. When price has already run up (e.g. 112 with target 120), it is marked EXHAUSTED and deprioritized.
        3. Fresh trades with maximum remaining profit & ROI (like Index Options) are picked first.
        4. Dynamic execution tightens stop loss to protect capital and guarantee achievable target hits.
        """
        from fingroww_paper_engine import evaluate_timewise_profit_metrics

        # Candidate A: Run up to 112 towards target 120 (breakout was 100, SL was 95)
        setup_a = {
            "symbol": "STOCK_A",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 112.0,
            "breakout_level": 100.0,
            "target_price": 120.0,
            "stop_loss": 95.0,
            "confidence_score": 95,
        }
        metrics_a = evaluate_timewise_profit_metrics(setup_a)
        # Consumed move is 12 / 20 = 60%, remaining R:R is 8 / 17 = 0.47
        self.assertTrue(metrics_a["is_exhausted"])
        self.assertLess(metrics_a["remaining_rr"], 1.0)
        self.assertLess(metrics_a["timewise_profit_score"], 25.0)

        # Candidate B: Fresh stock breakout at 500, target 540, SL 480
        setup_b = {
            "symbol": "STOCK_B",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 501.0,
            "breakout_level": 500.0,
            "target_price": 540.0,
            "stop_loss": 480.0,
            "confidence_score": 95,
        }
        metrics_b = evaluate_timewise_profit_metrics(setup_b)
        self.assertFalse(metrics_b["is_exhausted"])
        self.assertGreater(metrics_b["remaining_rr"], 1.8)
        self.assertGreater(metrics_b["timewise_profit_score"], 150.0)

        # Candidate C: Fresh Index Option (230 premium -> target 335, +45% gain)
        setup_c = {
            "symbol": "NIFTY 50 23050 CE",
            "instrument_type": "INDEX_OPTIONS",
            "side": "BUY",
            "entry_price": 230.5,
            "breakout_level": 230.5,
            "target_price": 335.0,
            "stop_loss": 173.0,
            "confidence_score": 95,
        }
        metrics_c = evaluate_timewise_profit_metrics(setup_c)
        self.assertFalse(metrics_c["is_exhausted"])
        self.assertGreater(metrics_c["margin_roi_pct"], 40.0)
        self.assertGreater(metrics_c["timewise_profit_score"], metrics_b["timewise_profit_score"])

        # Ranking order: Candidate C (Max Profit Option) > Candidate B (Fresh Stock) > Candidate A (Exhausted Stock)
        setups = [setup_a, setup_b, setup_c]
        for s in setups:
            s["timewise_metrics"] = evaluate_timewise_profit_metrics(s)
        setups.sort(key=lambda s: (
            0 if s["timewise_metrics"]["is_exhausted"] else 1,
            s["timewise_metrics"]["timewise_profit_score"],
            s["timewise_metrics"]["margin_roi_pct"],
        ), reverse=True)

        self.assertEqual(setups[0]["symbol"], "NIFTY 50 23050 CE")
        self.assertEqual(setups[1]["symbol"], "STOCK_B")
        self.assertEqual(setups[2]["symbol"], "STOCK_A")

        # Test dynamic stop-loss tightening on late entry to guarantee target hit
        self.session.reset(100000.0)
        self.session.start()
        late_setup = {
            "symbol": "RELIANCE",
            "base_symbol": "RELIANCE",
            "name": "Reliance",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 100.0,
            "target_price": 120.0,
            "stop_loss": 90.0,
            "risk_distance": 10.0,
            "reward_risk": 1.8,
            "confidence_score": 90,
        }
        # Live price has moved to 110.0
        quote_resolver_110 = lambda _s: {"source": "NSE", "lastPrice": 110.0, "fetched_at": time.time()}
        pos, _ = self.session.execute_trade(late_setup, quote_resolver=quote_resolver_110, market_is_open=True)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos["entry_price"], 110.0, delta=0.2)
        self.assertEqual(pos["target_price"], 120.0) # Structural target maintained
        self.assertGreater(pos["stop_loss"], 100.0)  # Stop loss tightened above 100 to protect capital
        self.assertAlmostEqual(pos["risk_reward"], 1.8, places=1)




    def test_26_market_cap_multi_select_and_long_term_equity_holding(self):
        """
        Verifies:
        1. Multi-select market cap filtering: Large Cap, Mid Cap, Small Cap.
        2. Small caps strictly generate Equity setups (no derivatives on NSE).
        3. Long-Term Equity Investment (CNC Cash Holding):
           - Requires 100% upfront cash margin (no 5x leverage).
           - Exempt from 15:20 IST EOD auto-square-off.
           - Delivery charges model (0 brokerage, 0.1% STT on buy and sell).
           - Macro trend alignment and structural +20% target.
        """
        # 1. Market Cap Filtering
        now_ms = int(time.time() * 1000)
        dummy_candles = []
        for i in range(65):
            t_candle = now_ms - (65 - i) * 15 * 60 * 1000 - 20000
            dummy_candles.append({"o": 1000.0 + i, "h": 1010.0 + i, "l": 995.0 + i, "c": 1005.0 + i, "v": 25000, "t": t_candle})

        self.engine.quote_resolver = lambda _sym: {
            "source": "NSE",
            "lastPrice": 1075.0,
            "pChange": 1.2,
            "fetched_at": time.time(),
        }
        self.engine.chart_resolver = lambda _sym, _tf, _rg: dummy_candles

        # Select ONLY SMALL_CAP
        self.session.config["instruments"] = ["EQUITY", "INDEX_OPTIONS", "INDEX_FUTURES"]
        self.session.config["market_caps"] = ["SMALL_CAP"]
        setups_small = self.engine.scan_and_evaluate_setups()
        self.assertGreater(len(setups_small), 0)
        for s in setups_small:
            self.assertEqual(s["market_cap"], "SMALL_CAP")
            self.assertEqual(s["instrument_type"], "EQUITY")  # Small caps on Indian exchanges only trade in Equity
            self.assertIn(s["base_symbol"], ["CDSL", "BSE", "ANGELONE", "SUZLON", "KALYANKJIL", "MAZDOCK", "RVNL", "HUDCO", "IREDA", "IRFC", "COCHINSHIP", "NBCC", "SJVN", "ZOMATO", "JIOFIN", "MOTHERSON"])

        # Select ONLY LARGE_CAP
        self.session.config["market_caps"] = ["LARGE_CAP"]
        setups_large = self.engine.scan_and_evaluate_setups()
        self.assertGreater(len(setups_large), 0)
        for s in setups_large:
            self.assertEqual(s["market_cap"], "LARGE_CAP")

        # Select MID_CAP + SMALL_CAP
        self.session.config["market_caps"] = ["MID_CAP", "SMALL_CAP"]
        setups_mid_small = self.engine.scan_and_evaluate_setups()
        mcaps = {s["market_cap"] for s in setups_mid_small}
        self.assertIn("MID_CAP", mcaps)
        self.assertIn("SMALL_CAP", mcaps)
        self.assertNotIn("LARGE_CAP", mcaps)

        # 2. Long-Term Equity Investment (CNC Cash Holding) Execution
        self.session.reset(100000.0)
        self.session.start()
        self.session.update_config({
            "trading_style": "LONG_TERM",
            "holding_duration_mins": 43200, # 1 Month (30 Days)
            "market_caps": ["LARGE_CAP", "MID_CAP", "SMALL_CAP"],
            "instruments": ["EQUITY"],
        })

        lt_setup = {
            "symbol": "CDSL",
            "base_symbol": "CDSL",
            "name": "Central Depository Services Ltd",
            "instrument_type": "EQUITY",
            "market_cap": "SMALL_CAP",
            "product_type": "CNC",
            "is_long_term": True,
            "side": "BUY",
            "entry_price": 1000.0,
            "target_price": 1200.0, # +20% structural target
            "stop_loss": 930.0,     # -7% protective stop
            "risk_distance": 70.0,
            "reward_risk": 2.85,
            "strategy": "Long-Term Quantitative Trend & Value (CNC)",
            "confidence_score": 92,
        }

        quote_1000 = lambda _s: {"source": "NSE", "lastPrice": 1000.0, "fetched_at": time.time()}
        pos, err = self.session.execute_trade(lt_setup, quote_resolver=quote_1000, market_is_open=True)
        self.assertIsNotNone(pos, msg=err)
        self.assertEqual(pos["product_type"], "CNC")
        self.assertFalse(pos["is_intraday"])
        self.assertTrue(pos["is_delivery"])
        self.assertTrue(pos["is_long_term"])

        # Delivery margin is 100% of price (no 5x leverage)
        expected_margin = round(pos["quantity"] * pos["entry_price"] * 1.0, 2)
        self.assertAlmostEqual(pos["allocated_margin"], expected_margin, delta=1.0)

        # Brokerage for delivery should be ₹0 (Zerodha/Groww model)
        delivery_charges = PaperTradeCostModel.calculate_charges("EQUITY", "BUY", 1000.0, 10, is_delivery=True)
        self.assertEqual(delivery_charges["brokerage"], 0.0)
        self.assertEqual(delivery_charges["stt"], 10.0) # 0.1% on ₹10,000 turnover

        # 3. Positional Holding Protection against 15:20 IST EOD Auto-Square-off
        eod_time = datetime.now(timezone(timedelta(hours=5, minutes=30))).replace(
            hour=15, minute=25, second=0
        )
        with patch("fingroww_paper_engine.get_ist_now", return_value=eod_time):
            # Price is at 1050 (neither target nor stop loss hit)
            quote_1050 = lambda _s: {"source": "NSE", "lastPrice": 1050.0, "fetched_at": time.time()}
            self.session.update_positions(quote_1050, market_is_open=True)
            # Must REMAIN OPEN across sessions! Not auto-closed at 3:15 PM!
            self.assertEqual(len(self.session.positions), 1)
            self.assertEqual(self.session.positions[0]["status"], "OPEN")

        # 4. Target Hit Exit (+20% achieved)
        quote_1210 = lambda _s: {"source": "NSE", "lastPrice": 1210.0, "fetched_at": time.time()}
        self.session.update_positions(quote_1210, market_is_open=True)
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 1)
        closed = self.session.closed_trades[0]
        self.assertEqual(closed["exit_reason"], "TARGET_HIT")
        self.assertGreater(closed["net_pnl"], 0)


    def test_27_high_winrate_dynamic_breakeven_and_profit_locking(self):
        """
        Verifies 80%+ Win-Rate Trailing System:
        1. When position moves >=45% towards target, SL trails automatically to Breakeven (entry + buffer).
        2. When position moves >=75% towards target, SL trails to lock in +40% profit.
        3. If market reverses after hitting Breakeven, position exits as protected win/scratch rather than a loss.
        """
        self.session.reset(100000.0)
        self.session.start()
        setup = {
            "symbol": "RELIANCE",
            "base_symbol": "RELIANCE",
            "name": "Reliance Industries",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1000.0,
            "stop_loss": 980.0,     # Risk = 20 pts
            "target_price": 1040.0, # Target = 40 pts
            "strategy": "🎯 80%+ Smart Money VWAP & EMA20 Pullback",
            "confidence_score": 92,
        }
        quote_1000 = lambda _s: {"source": "NSE", "lastPrice": 1000.0, "fetched_at": time.time()}
        pos, err = self.session.execute_trade(setup, quote_resolver=quote_1000, market_is_open=True)
        self.assertIsNotNone(pos, err)
        self.assertEqual(pos["trailing_state"], "INITIAL")
        self.assertAlmostEqual(pos["stop_loss"], 980.0, delta=1.5)

        # 1. Price moves to 1020.0 (50% of 40-pt target distance) -> Breakeven Trailing Triggers!
        quote_1020 = lambda _s: {"source": "NSE", "lastPrice": 1020.0, "fetched_at": time.time()}
        self.session.update_positions(quote_1020, market_is_open=True)
        open_pos = self.session.positions[0]
        self.assertEqual(open_pos["trailing_state"], "BREAKEVEN")
        self.assertGreaterEqual(open_pos["stop_loss"], 1000.0)

        # 2. Price moves to 1032.0 (80% of 40-pt target distance) -> Tier 2 Profit Lock Triggers!
        quote_1032 = lambda _s: {"source": "NSE", "lastPrice": 1032.0, "fetched_at": time.time()}
        self.session.update_positions(quote_1032, market_is_open=True)
        open_pos = self.session.positions[0]
        self.assertEqual(open_pos["trailing_state"], "PROFIT_LOCKED")
        self.assertGreaterEqual(open_pos["stop_loss"], 1015.0)

        # 3. Market reverses from 1032 down to 1010 -> Hits Trailing Profit Stop!
        quote_1010 = lambda _s: {"source": "NSE", "lastPrice": 1010.0, "fetched_at": time.time()}
        self.session.update_positions(quote_1010, market_is_open=True)
        self.assertEqual(len(self.session.positions), 0)
        self.assertEqual(len(self.session.closed_trades), 1)
        closed = self.session.closed_trades[0]
        self.assertEqual(closed["exit_reason"], "TRAILING_STOP_PROFIT_HIT")
        self.assertTrue(closed["is_win"])
        self.assertGreater(closed["net_pnl"], 0)


    def test_28_auto_trading_picks_pullback_and_protects_across_profiles_and_instruments(self):
        """
        Verifies that during live Auto Paper Trading (engine.tick()):
        1. 80%+ Smart Money Pullback setups are prioritized over regular breakouts across instruments (Stocks, Options, Futures).
        2. Auto-trading autonomously executes the high-probability pullback trade.
        3. Multi-tier Dynamic Breakeven trailing triggers on subsequent ticks.
        4. Switching profile configuration preserves high-winrate strategy and trailing protections.
        """
        self.session.reset(100000.0)
        self.session.config["trading_style"] = "HIGH_WINRATE"
        self.session.config["instruments"] = ["EQUITY"]
        self.session.start()

        self.engine.market_status_resolver = lambda: {"is_trading_hours": True}

        # Synthesize 70 candles with healthy trend and pullback near VWAP / EMA20
        now_ms = int(time.time() * 1000)
        candle_count = 70
        first_candle_ms = now_ms - (candle_count * 15 * 60 * 1000) - (16 * 60 * 1000)
        candles = []
        for index in range(candle_count):
            close = 2000.0 + (index * 0.1)
            candles.append({
                "o": close - 0.1,
                "h": close + 0.3,
                "l": close - 0.2,
                "c": close,
                "v": 200.0,
                "t": first_candle_ms + (index * 15 * 60 * 1000),
            })

        latest_close = candles[-1]["c"]
        self.engine.quote_resolver = lambda sym: {
            "source": "NSE",
            "lastPrice": latest_close,
            "pChange": 0.5,
            "fetched_at": time.time(),
            "exchange_timestamp": time.time(),
        }
        self.engine.chart_resolver = lambda sym, *args: candles

        # Trigger autonomous tick
        state = self.engine.tick()
        self.assertEqual(self.session.status, "RUNNING")
        self.assertGreaterEqual(len(self.session.positions), 1)
        pos = self.session.positions[0]
        self.assertIn("80%+", pos["strategy"])

        # Favorable move triggers Dynamic Breakeven Trailing
        tp = pos["target_price"]
        entry = pos["entry_price"]
        halfway_price = entry + ((tp - entry) * 0.55)
        self.engine.quote_resolver = lambda sym: {
            "source": "NSE",
            "lastPrice": halfway_price,
            "pChange": 1.2,
            "fetched_at": time.time(),
            "exchange_timestamp": time.time(),
        }
        self.engine.tick()
        self.assertEqual(pos["trailing_state"], "BREAKEVEN")
        self.assertGreaterEqual(pos["stop_loss"], entry)


if __name__ == "__main__":
    unittest.main()

