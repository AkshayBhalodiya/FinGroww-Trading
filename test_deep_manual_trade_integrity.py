import unittest
import json
import time
import copy
from fingroww_market_server import app, paper_manager
from fingroww_paper_engine import (
    PaperTradingSession,
    PaperTradingEngine,
    MultiUserPaperSessionManager,
    LOT_SIZES,
    DEFAULT_SPOTS,
)
from routes.paper_routes import session_stream_hub
from agents.swarm_orchestrator import SwarmOrchestrator


class TestDeepManualTradeIntegrity(unittest.TestCase):
    """
    Comprehensive verification to ensure Manual Trade execution does not break
    any part of the trading system, data models, AI auto engine, or multi-agent swarm.
    """

    def setUp(self):
        self.client = app.test_client()

    def test_01_instrument_matrix_ce_pe_execution(self):
        """Tests that all supported instruments (Index & Equity options) execute CE and PE cleanly."""
        instruments = [
            ("NIFTY 50", 25350, "CE"),
            ("NIFTY 50", 25300, "PE"),
            ("BANK NIFTY", 62600, "CE"),
            ("BANK NIFTY", 62500, "PE"),
            ("FINNIFTY", 28150, "CE"),
            ("RELIANCE", 1350, "CE"),
            ("TCS", 4150, "PE"),
        ]

        sess = PaperTradingSession(user_name="MatrixTestUser")
        sess.reset(initial_capital=500000.0)

        opened_positions = []
        for sym, strike, opt_type in instruments:
            pos, err = sess.execute_manual_trade(
                base_symbol=sym,
                strike=strike,
                option_type=opt_type,
                stop_loss_pct=20.0,
                algo_target=True,
                lots=1,
                market_is_open=True,
            )
            self.assertIsNotNone(pos, f"Failed for {sym} {strike} {opt_type}: {err}")
            self.assertEqual(pos["execution_type"], "MANUAL")
            self.assertEqual(pos["option_type"], opt_type)
            self.assertEqual(pos["strike"], strike)
            self.assertGreater(pos["entry_price"], 0)
            self.assertGreater(pos["stop_loss"], 0)
            self.assertLess(pos["stop_loss"], pos["entry_price"])
            self.assertGreater(pos["target_price"], pos["entry_price"])
            opened_positions.append(pos)

        self.assertEqual(len(sess.positions), len(instruments))
        self.assertGreater(sess.allocated_margin, 0)
        self.assertLess(sess.available_balance, 500000.0)

        # Close all one by one
        for p in opened_positions:
            ok, msg = sess.manual_close_position(p["trade_id"], force=True)
            self.assertTrue(ok, f"Close failed for {p['symbol']}: {msg}")

        self.assertEqual(len(sess.positions), 0)
        self.assertEqual(len(sess.closed_trades), len(instruments))
        self.assertEqual(sess.allocated_margin, 0.0)

    def test_02_sl_and_target_validation_boundary_conditions(self):
        """Verifies boundary conditions: invalid strikes, zero SL, negative target, SL >= entry."""
        sess = PaperTradingSession(user_name="BoundaryTestUser")
        sess.reset(initial_capital=100000.0)

        # 1. Non-numeric strike
        p, err = sess.execute_manual_trade("NIFTY", "INVALID_STRIKE", "CE", stop_loss_pct=10.0)
        self.assertIsNone(p)
        self.assertIn("valid numeric strike", err.lower())

        # 2. None / empty SL
        p, err = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss=None, stop_loss_pct=None)
        self.assertIsNone(p)
        self.assertIn("mandatory", err.lower())

        # 3. Zero SL
        p, err = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss=0, stop_loss_pct=0)
        self.assertIsNone(p)
        self.assertIn("mandatory", err.lower())

        # 4. SL greater than entry price (simulate by custom SL higher than likely premium)
        p, err = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss=99999.0)
        self.assertIsNone(p)
        self.assertIn("strictly less than", err.lower())

        # 5. Custom Target less than entry price
        p, err = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss_pct=10.0, target_price=1.0, algo_target=False)
        self.assertIsNone(p)
        self.assertIn("strictly greater than", err.lower())

        # 6. Insufficient Balance
        tiny_sess = PaperTradingSession(user_name="TinyCapitalUser")
        tiny_sess.reset(initial_capital=100.0) # Only ₹100
        p, err = tiny_sess.execute_manual_trade("BANK NIFTY", 52000, "CE", stop_loss_pct=10.0, lots=5)
        self.assertIsNone(p)
        self.assertIn("insufficient", err.lower())

    def test_03_autonomous_ai_engine_and_max_positions_respect(self):
        """Ensures autonomous AI scanner respects max_open_positions when manual trades are active."""
        sess = PaperTradingSession(user_name="ConcurrencyUser")
        sess.reset(initial_capital=300000.0)
        sess.config["max_open_positions"] = 2

        # 1. Open 1 Manual Trade
        man_pos, _ = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss_pct=15.0, lots=1, market_is_open=True)
        self.assertIsNotNone(man_pos)
        self.assertEqual(len(sess.positions), 1)

        # 2. Try opening 2 AI Auto Trades when max_open_positions = 2
        sess.start()
        setup1 = {
            "symbol": "RELIANCE", "name": "Reliance", "type": "STOCK", "market_cap": "LARGE_CAP",
            "action": "BUY", "entry_price": 2800.0, "stop_loss": 2700.0, "target_price": 3000.0,
            "status": "VALIDATED", "holding_duration_mins": 1440
        }
        setup2 = {
            "symbol": "TCS", "name": "TCS", "type": "STOCK", "market_cap": "LARGE_CAP",
            "action": "BUY", "entry_price": 4000.0, "stop_loss": 3900.0, "target_price": 4200.0,
            "status": "VALIDATED", "holding_duration_mins": 1440
        }

        # 1st AI trade should succeed (positions becomes 2 = max)
        pos1, err1 = sess.execute_trade(setup1, quote_resolver=lambda s: {"symbol": s, "lastPrice": 2800.0}, market_is_open=True)
        self.assertIsNotNone(pos1, f"Setup 1 failed: {err1}")
        self.assertEqual(len(sess.positions), 2)

        # 2nd AI trade MUST BE REJECTED because max_open_positions (2) is reached
        pos2, err2 = sess.execute_trade(setup2, quote_resolver=lambda s: {"symbol": s, "lastPrice": 4000.0}, market_is_open=True)
        self.assertIsNone(pos2)
        self.assertIn("maximum concurrent positions", err2.lower())

        # Cleanup
        sess.manual_close_position(man_pos["trade_id"], force=True)
        sess.manual_close_position(pos1["trade_id"], force=True)
        self.assertEqual(len(sess.positions), 0)

    def test_04_target_hit_and_sl_hit_auto_monitoring(self):
        """Simulates price ticks hitting target and stop-loss to verify update_positions auto-closes manual trades."""
        sess = PaperTradingSession(user_name="TickMonitorUser")
        sess.reset(initial_capital=200000.0)

        # Trade 1: Will hit Target
        pos_tp, _ = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss_pct=20.0, algo_target=True, lots=1, market_is_open=True)
        entry_price = pos_tp["entry_price"]
        target_price = pos_tp["target_price"]

        # Simulate price tick above target
        mock_option_resolver_tp = lambda sym, strike, otype, exp=None: {
            "symbol": f"{sym} {strike} {otype}",
            "lastPrice": target_price + 10.0, # Target breached!
            "is_market_open": True,
        }
        sess.update_positions(
            quote_resolver=lambda s: {"symbol": s, "lastPrice": 24500.0},
            market_is_open=True,
            option_quote_resolver=mock_option_resolver_tp,
        )

        self.assertEqual(len(sess.positions), 0, "Position should have been closed on Target Hit")
        self.assertEqual(len(sess.closed_trades), 1)
        self.assertEqual(sess.closed_trades[0]["exit_reason"], "TARGET_HIT")
        self.assertEqual(sess.closed_trades[0]["execution_type"], "MANUAL")
        self.assertTrue(sess.closed_trades[0]["is_win"])

        # Trade 2: Will hit Stop Loss
        pos_sl, _ = sess.execute_manual_trade("BANK NIFTY", 52000, "PE", stop_loss_pct=20.0, algo_target=True, lots=1, market_is_open=True)
        sl_price = pos_sl["stop_loss"]

        # Simulate price tick below stop-loss
        mock_option_resolver_sl = lambda sym, strike, otype, exp=None: {
            "symbol": f"{sym} {strike} {otype}",
            "lastPrice": max(0.5, sl_price - 5.0), # SL breached!
            "is_market_open": True,
        }
        sess.update_positions(
            quote_resolver=lambda s: {"symbol": s, "lastPrice": 52000.0},
            market_is_open=True,
            option_quote_resolver=mock_option_resolver_sl,
        )

        self.assertEqual(len(sess.positions), 0, "Position should have been closed on Stop-Loss Hit")
        self.assertEqual(len(sess.closed_trades), 2)
        self.assertEqual(sess.closed_trades[0]["exit_reason"], "STOP_LOSS_HIT")
        self.assertEqual(sess.closed_trades[0]["execution_type"], "MANUAL")

    def test_05_db_persistence_round_trip(self):
        """Verifies session state with active and closed manual trades can be saved and restored from datastore."""
        user = "PersistManualUser"
        sess = PaperTradingSession(user_name=user)
        sess.reset(initial_capital=200000.0)

        # 1. Execute 1 manual trade & close it
        p1, _ = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss_pct=15.0, lots=1, market_is_open=True)
        sess.manual_close_position(p1["trade_id"], force=True)

        # 2. Execute 1 active manual trade (keep open)
        p2, _ = sess.execute_manual_trade("BANK NIFTY", 52000, "PE", stop_loss_pct=20.0, lots=1, market_is_open=True)

        # Save to DB
        sess.save_to_db()

        # Create a fresh new session object for the same user and restore from DB
        restored_sess = PaperTradingSession(user_name=user)
        self.assertTrue(restored_sess._restored_from_db)

        # Assert data integrity
        self.assertEqual(len(restored_sess.positions), 1)
        self.assertEqual(restored_sess.positions[0]["trade_id"], p2["trade_id"])
        self.assertEqual(restored_sess.positions[0]["execution_type"], "MANUAL")
        self.assertEqual(restored_sess.positions[0]["option_type"], "PE")

        self.assertEqual(len(restored_sess.closed_trades), 1)
        self.assertEqual(restored_sess.closed_trades[0]["trade_id"], p1["trade_id"])
        self.assertEqual(restored_sess.closed_trades[0]["execution_type"], "MANUAL")

        # Cleanup
        restored_sess.manual_close_position(p2["trade_id"], force=True)

    def test_06_multi_agent_swarm_compatibility(self):
        """Verifies the 5-Agent Swarm Orchestrator initializes and ticks without conflict when manual trades exist."""
        sess, _ = paper_manager.get_session("SwarmCompatibilityUser")
        sess.reset(initial_capital=250000.0)

        # Place a manual trade in session
        m_pos, err = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss_pct=20.0, lots=1, market_is_open=True)
        self.assertIsNotNone(m_pos, f"Failed: {err}")

        # Initialize Swarm Orchestrator singleton
        orchestrator = SwarmOrchestrator.get_instance()
        status = orchestrator.get_full_status()
        self.assertTrue(status["swarm_online"])
        self.assertIn("agent1_scout", status)
        self.assertIn("agent5_supervisor", status)

        # Trigger an evaluation cycle
        res = orchestrator.trigger_manual_cycle()
        self.assertTrue(res.get("scanned", False))

        # Cleanup
        sess.manual_close_position(m_pos["trade_id"], force=True)

    def test_07_sse_stream_broadcast_structure(self):
        """Verifies session_stream_hub broadcasts correct manual trade payload."""
        user = "SseBroadcastUser"
        sess, _ = paper_manager.get_session(user)
        sess.reset(initial_capital=100000.0)

        p, _ = sess.execute_manual_trade("NIFTY", 24500, "CE", stop_loss_pct=20.0, lots=1, market_is_open=True)

        st = sess.get_state()
        # Verify get_state includes manual execution attributes
        self.assertEqual(len(st["active_positions"]), 1)
        self.assertEqual(st["active_positions"][0]["execution_type"], "MANUAL")

        # Verify stream hub queueing
        q = session_stream_hub.subscribe(user)
        session_stream_hub.broadcast(user, st)
        msg = q.get_nowait()
        self.assertEqual(msg["active_positions"][0]["execution_type"], "MANUAL")
        session_stream_hub.unsubscribe(user, q)

        # Cleanup
        sess.manual_close_position(p["trade_id"], force=True)


if __name__ == "__main__":
    unittest.main()
