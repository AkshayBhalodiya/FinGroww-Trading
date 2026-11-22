import unittest
import json
import time
import os
import tempfile
import sqlite3
from unittest.mock import patch, MagicMock

import fingroww_market_server
from fingroww_paper_engine import (
    PaperTradingSession,
    PaperTradingEngine,
    send_telegram_alert,
    _connect_paper_db,
    _save_local_paper_record,
    LOCAL_USER_DATASTORE,
)


class TestPhase2And3Features(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp_dir.cleanup)
        db_patcher = patch.dict(
            os.environ,
            {"FINGROWW_PAPER_DB_PATH": os.path.join(self.temp_dir.name, "paper_trading.db")},
        )
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

        LOCAL_USER_DATASTORE["sessions"].clear()
        LOCAL_USER_DATASTORE["profiles"].clear()
        LOCAL_USER_DATASTORE["trades"].clear()

        self.app = fingroww_market_server.app.test_client()
        self.user = f"PhaseUser_{self._testMethodName}"
        self.session = PaperTradingSession(user_name=self.user, config={"initial_capital": 100000.0, "max_daily_drawdown_pct": 5.0})
        self.session.positions = []
        self.session.closed_trades = []
        fingroww_market_server.paper_manager.sessions[self.user] = self.session
        fingroww_market_server.paper_manager.engines[self.user] = PaperTradingEngine(session=self.session)

    def test_01_circuit_breaker_blocks_trades_when_limit_breached(self):
        """Phase 2: Daily max drawdown circuit breaker halts entries when threshold exceeded."""
        self.session.status = "RUNNING"
        # Simulate max drawdown exceeding 5%
        self.session.max_drawdown_pct = 6.2
        can_trade, reason = self.session.can_open_new_trade()
        self.assertFalse(can_trade)
        self.assertTrue(self.session.is_circuit_breaker_triggered)
        self.assertIn("Daily max drawdown reached", reason)

        state = self.session.get_state()
        self.assertTrue(state["circuit_breaker"]["is_triggered"])
        self.assertEqual(state["circuit_breaker"]["max_daily_drawdown_pct"], 5.0)

        # Test manual reset
        self.session.reset_circuit_breaker()
        self.assertFalse(self.session.is_circuit_breaker_triggered)

    def test_02_dynamic_continuous_tsl_trailing(self):
        """Phase 2: Continuous dynamic TSL trails peak favorable price."""
        self.session.config["tsl_mode"] = "DYNAMIC"
        self.session.config["tsl_trail_pct"] = 2.0 # 2% trail
        
        pos = {
            "trade_id": "PT-TEST-001",
            "symbol": "TCS",
            "side": "BUY",
            "entry_price": 3500.0,
            "current_price": 3500.0,
            "quantity": 10,
            "allocated_margin": 35000.0,
            "stop_loss": 3400.0,
            "target_price": 3800.0,
            "instrument_type": "EQUITY",
            "trailing_state": "INITIAL",
            "tsl_mode": "DYNAMIC",
            "is_intraday": False,
            "product_type": "CNC",
            "peak_price": 3500.0,
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0
        }
        self.session.positions = [pos]

        # Price rallies to 3700
        mock_quote = lambda _sym: {"source": "NSE", "lastPrice": 3700.0, "fetched_at": time.time()}
        self.session.update_positions(mock_quote, market_is_open=True)

        updated_pos = self.session.positions[0]
        # Dynamic SL should trail 2% below 3700 -> 3700 * 0.98 = 3626.0
        expected_sl = round(3700.0 * 0.98, 2)
        self.assertEqual(updated_pos["stop_loss"], expected_sl)
        self.assertEqual(updated_pos["trailing_state"], "DYNAMIC_TSL")
        self.assertGreater(updated_pos["stop_loss"], 3500.0) # SL locked into profit!

    def test_03_sqlite_trades_history_table(self):
        """Phase 2: Structured SQLite relational table stores closed trades."""
        conn = _connect_paper_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades_history'")
        row = cursor.fetchone()
        self.assertIsNotNone(row, "paper_trades_history table must exist in SQLite DB")

        # Verify saving closed trades writes to relational table
        dummy_trade = {
            "trade_id": f"TEST-TR-{int(time.time()*1000)}",
            "symbol": "INFY",
            "side": "BUY",
            "quantity": 25,
            "entry_price": 1800.0,
            "exit_price": 1860.0,
            "gross_pnl": 1500.0,
            "net_pnl": 1465.0,
            "return_pct": 3.3,
            "entry_time": "2026-11-22 10:00:00",
            "exit_time": "2026-11-22 11:30:00",
            "exit_reason": "TARGET_HIT",
            "strategy": "15m Breakout",
            "instrument_type": "EQUITY"
        }
        _save_local_paper_record("UnitTest_SqliteUser", {"closed_trades": [dummy_trade]}, {"user_name": "UnitTest_SqliteUser"})

        cursor.execute("SELECT symbol, net_pnl, exit_reason FROM paper_trades_history WHERE trade_id = ?", (dummy_trade["trade_id"],))
        record = cursor.fetchone()
        self.assertIsNotNone(record)
        self.assertEqual(record[0], "INFY")
        self.assertEqual(record[1], 1465.0)
        self.assertEqual(record[2], "TARGET_HIT")

    def test_04_1click_paper_trade_execution_api(self):
        """Phase 2: POST /api/paper/order/execute executes 1-click paper trade from options.html."""
        payload = {
            "user": self.user,
            "symbol": "NIFTY24500CE",
            "base_symbol": "NIFTY 50",
            "instrument_type": "INDEX_OPTIONS",
            "side": "BUY",
            "entry_price": 140.0,
            "stop_loss": 110.0,
            "target_price": 195.0,
            "quantity": 25,
            "strategy": "Options Golden Zone 1-Click"
        }
        resp = self.app.post("/api/paper/order/execute", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("NIFTY24500CE", data["message"])
        self.assertEqual(len(self.session.positions), 1)
        self.assertEqual(self.session.positions[0]["symbol"], "NIFTY24500CE")

    def test_05_circuit_breaker_reset_api(self):
        """Phase 2: POST /api/paper/circuit-breaker/reset resets circuit breaker."""
        self.session.is_circuit_breaker_triggered = True
        self.session.circuit_breaker_reason = "Test breach"

        resp = self.app.post("/api/paper/circuit-breaker/reset", json={"user": self.user})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertFalse(self.session.is_circuit_breaker_triggered)

    def test_06_telegram_alerts_dispatcher(self):
        """Phase 3: Telegram alert helper executes gracefully without errors."""
        # Unconfigured returns False gracefully
        res = send_telegram_alert("Test Alert", {})
        self.assertFalse(res)

        # Configured runs async dispatcher thread without raising
        res_cfg = send_telegram_alert("Test Alert", {"telegram_bot_token": "fake_token", "telegram_chat_id": "12345"})
        self.assertTrue(res_cfg)

        # Test API endpoint
        resp = self.app.post("/api/paper/alerts/telegram/test", json={"user": self.user, "bot_token": "123:ABC", "chat_id": "999"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_07_server_sent_events_stream_endpoint(self):
        """Phase 3: GET /api/paper/stream provides text/event-stream headers."""
        resp = self.app.get(f"/api/paper/stream?user={self.user}", buffered=False)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers.get("Content-Type", ""))
        first_event = next(resp.response)
        self.assertIn(b"event: tick", first_event)
        self.assertIn(b"data:", first_event)


if __name__ == "__main__":
    unittest.main()
