import sys
import os
import unittest
from unittest.mock import patch
import threading
import time
import math
from datetime import datetime

import fingroww_paper_engine as fpe
from fingroww_paper_engine import (
    PaperTradingSession,
    PaperTradingEngine,
    MultiUserPaperSessionManager,
    PaperTradeCostModel,
    LOT_SIZES,
)

# Simulated weekday market hours: Wednesday 10:30 AM IST
MOCK_MARKET_TIME = datetime(2026, 11, 4, 10, 30, 0)

class TestPaperTradingCornerCases(unittest.TestCase):

    def setUp(self):
        self.session = PaperTradingSession(
            user_name="CornerCaseTestUser",
            config={
                "initial_capital": 100000.0,
                "risk_profile": "MODERATE",
                "instrument_types": ["EQUITY", "INDEX_OPTIONS", "INDEX_FUTURES", "STOCK_FUTURES"],
                "max_open_positions": 5,
                "daily_loss_limit_inr": 5000.0,
                "max_daily_loss": 5000.0,
                "per_trade_risk_pct": 1.0,
                "enable_trailing_stop": True,
                "enable_breakeven_stop": True,
                "cooldown_period_mins": 10,
                "max_consecutive_losses": 3,
            }
        )
        self.session.start()

    def make_quote_resolver(self, price_dict):
        def resolver(sym):
            p = price_dict.get(sym, 1000.0)
            now_ts = time.time()
            return {
                "source": "NSE",
                "lastPrice": p,
                "pChange": 1.2,
                "fetched_at": now_ts,
                "exchange_timestamp": now_ts,
                "timestamp": datetime.now().strftime("%d-%b-%Y %H:%M:%S")
            }
        return resolver

    # -------------------------------------------------------------
    # 1. Zero & Negative Capital Edge Cases
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_01_zero_and_negative_capital(self, mock_time):
        """Corner Case: User sets capital to 0 or exhausts available margin."""
        self.session.reset(initial_capital=0.0)
        self.session.start()
        
        can_trade, reason = self.session.can_open_new_trade()
        self.assertFalse(can_trade, "Should not be able to trade with 0 capital")
        self.assertIn("Insufficient virtual balance", reason)
        
        setup = {
            "symbol": "RELIANCE",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 2500.0,
            "stop_loss": 2480.0,
            "target_price": 2540.0,
            "atr": 20.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 85,
            "setup_type": "PULLBACK",
        }
        res, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"RELIANCE": 2500.0}),
            market_is_open=True
        )
        self.assertIsNone(res, "Trade must be rejected when balance is 0")
        self.assertIsNotNone(err)

    # -------------------------------------------------------------
    # 2. Bad Quote Data (None, NaN, 0, Negative, Missing Keys)
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_02_bad_quote_resilience(self, mock_time):
        """Corner Case: Quote resolver returns invalid/corrupted price data."""
        self.session.reset()
        self.session.start()
        setup = {
            "symbol": "TCS",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 3500.0,
            "stop_loss": 3465.0,
            "target_price": 3570.0,
            "atr": 35.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 88,
            "setup_type": "PULLBACK",
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"TCS": 3500.0}),
            market_is_open=True
        )
        self.assertIsNotNone(pos, f"Trade execution failed: {err}")
        self.assertEqual(len(self.session.positions), 1)

        # Test updates with bad quote data
        try:
            self.session.update_positions(quote_resolver=lambda s: None, market_is_open=True)
            self.session.update_positions(quote_resolver=lambda s: {}, market_is_open=True)
            self.session.update_positions(quote_resolver=lambda s: {"source": "NSE", "lastPrice": None}, market_is_open=True)
            self.session.update_positions(quote_resolver=lambda s: {"source": "NSE", "lastPrice": 0.0}, market_is_open=True)
            self.session.update_positions(quote_resolver=lambda s: {"source": "NSE", "lastPrice": -100.0}, market_is_open=True)
            self.session.update_positions(quote_resolver=lambda s: {"source": "NSE", "lastPrice": float('nan')}, market_is_open=True)
        except Exception as e:
            self.fail(f"update_positions crashed on bad quote data: {e}")

        # The position should remain safely open and not be falsely closed or corrupted
        self.assertEqual(len(self.session.positions), 1, "Position was wrongly closed on bad quote data")

    # -------------------------------------------------------------
    # 3. Double / Rapid Concurrent Close Race Condition
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_03_double_rapid_close_concurrency(self, mock_time):
        """Corner Case: User clicks Close twice in rapid succession or concurrent threads close same trade."""
        self.session.reset()
        self.session.start()
        setup = {
            "symbol": "INFY",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1800.0,
            "stop_loss": 1780.0,
            "target_price": 1840.0,
            "atr": 20.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 85,
            "setup_type": "PULLBACK",
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"INFY": 1800.0}),
            market_is_open=True
        )
        self.assertIsNotNone(pos)
        trade_id = pos["trade_id"]

        # First close
        ok1, msg1 = self.session.manual_close_position(
            trade_id,
            quote_resolver=self.make_quote_resolver({"INFY": 1820.0}),
            market_is_open=True
        )
        self.assertTrue(ok1, "First close should succeed")
        
        # Second immediate close
        ok2, msg2 = self.session.manual_close_position(
            trade_id,
            quote_resolver=self.make_quote_resolver({"INFY": 1820.0}),
            market_is_open=True
        )
        self.assertFalse(ok2, "Second close must be rejected and not double-credited")
        self.assertEqual(self.session.allocated_margin, 0.0, "Allocated margin must be exactly 0 after close")

    # -------------------------------------------------------------
    # 4. Multi-threaded Concurrent Ticks
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_04_thread_safety_concurrent_ticks(self, mock_time):
        """Corner Case: 10 concurrent threads call update_positions at the exact same time."""
        self.session.reset()
        self.session.start()
        setup = {
            "symbol": "HDFCBANK",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 1600.0,
            "stop_loss": 1580.0,
            "target_price": 1640.0,
            "atr": 20.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 85,
            "setup_type": "PULLBACK",
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"HDFCBANK": 1600.0}),
            market_is_open=True
        )
        self.assertIsNotNone(pos)

        errors = []
        def run_update(price):
            try:
                self.session.update_positions(
                    quote_resolver=self.make_quote_resolver({"HDFCBANK": price}),
                    market_is_open=True
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_update, args=(1605.0 + i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent updates produced errors: {errors}")

    # -------------------------------------------------------------
    # 5. Breakeven Trailing Boundaries & Micro-increments
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_05_breakeven_trailing_boundaries(self, mock_time):
        """Corner Case: Price touches exact breakeven trigger and locks profit."""
        self.session.reset()
        self.session.start()
        setup = {
            "symbol": "RELIANCE",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 2000.0,
            "stop_loss": 1960.0, # risk = 40 (1R)
            "target_price": 2080.0, # reward = 80 (2R)
            "atr": 20.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 90,
            "setup_type": "PULLBACK",
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"RELIANCE": 2000.0}),
            market_is_open=True
        )
        self.assertIsNotNone(pos)
        original_sl = self.session.positions[0]["stop_loss"]

        # Move price up to +1R / 45% progress towards 2080 (45% of 80 is 36 -> price 2036.0)
        self.session.update_positions(
            quote_resolver=self.make_quote_resolver({"RELIANCE": 2040.0}),
            market_is_open=True
        )
        
        # Stop loss should now be adjusted to Breakeven (+0.08% buffer above entry: 2000 * 1.0008 = 2001.6)
        updated_trade = self.session.positions[0]
        self.assertGreater(updated_trade["stop_loss"], original_sl, "Stop Loss was not moved to Breakeven")
        self.assertGreaterEqual(updated_trade["stop_loss"], 2000.0, "SL must be at least entry price")

        # Now pull price back to touch the new Breakeven SL
        be_sl = updated_trade["stop_loss"]
        self.session.update_positions(
            quote_resolver=self.make_quote_resolver({"RELIANCE": be_sl}),
            market_is_open=True
        )
        
        # Trade should have closed cleanly
        self.assertEqual(len(self.session.positions), 0, "Position should be closed when BE SL is hit")
        closed_trade = self.session.closed_trades[0]
        self.assertIn("BREAKEVEN", closed_trade["exit_reason"].upper())
        self.assertTrue(closed_trade["is_win"], "Breakeven trade must be counted as scratch/protected win")

    # -------------------------------------------------------------
    # 6. Options OTM Expiry Max Loss Cap (100% of Premium)
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_06_option_otm_expiry_max_loss_cap(self, mock_time):
        """Corner Case: Option expires completely OTM. Loss must NOT exceed 100% of premium paid + charges."""
        self.session.reset()
        self.session.start()
        setup = {
            "symbol": "NIFTY 24500 CE",
            "base_symbol": "NIFTY 50",
            "instrument_type": "INDEX_OPTIONS",
            "option_type": "CE",
            "strike": 24500,
            "side": "BUY",
            "entry_price": 100.0, # Option premium = Rs 100
            "underlying_price": 24300.0,
            "stop_loss": 50.0,
            "target_price": 200.0,
            "atr": 20.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 85,
            "setup_type": "PULLBACK",
            "lot_size": 75,
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"NIFTY 50": 24300.0}),
            market_is_open=True
        )
        self.assertIsNotNone(pos, f"Option execution failed: {err}")
        premium_paid = pos["entry_price"] * pos["quantity"]

        # Deep OTM expiry: Spot price falls to 23000
        ok, msg = self.session.test_expire_position(
            pos["trade_id"],
            quote_resolver=self.make_quote_resolver({"NIFTY 50": 23000.0}),
            market_is_open=True
        )
        self.assertTrue(ok)
        
        closed_trade = self.session.closed_trades[0]
        # Gross loss is bounded by premium paid minus 0.05 tick size
        self.assertLessEqual(abs(closed_trade["gross_pnl"]), premium_paid)
        self.assertGreater(self.session.available_balance, 0, "Account should not be wiped out by single capped option loss")

    # -------------------------------------------------------------
    # 7. Max Daily Loss Enforcement (Kill Switch)
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_07_max_daily_loss_enforcement(self, mock_time):
        """Corner Case: Daily loss exceeds limit. Supervisor must strictly block further trades."""
        self.session.reset()
        self.session.start()
        self.session.total_pnl = -5500.0 # Exceeds daily_loss_limit_inr of 5000.0
        
        can_trade, reason = self.session.can_open_new_trade()
        self.assertFalse(can_trade, "Should block trades when max daily loss is breached")
        self.assertIn("Daily max loss limit", reason)

        setup = {
            "symbol": "SBIN",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 800.0,
            "stop_loss": 790.0,
            "target_price": 820.0,
            "atr": 10.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 85,
            "setup_type": "PULLBACK",
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"SBIN": 800.0}),
            market_is_open=True
        )
        self.assertIsNone(pos)
        self.assertIn("Daily max loss limit", err)

    # -------------------------------------------------------------
    # 8. Max Open Positions Limit Enforcement
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_08_max_open_positions_limit(self, mock_time):
        """Corner Case: Reaching max open positions must prevent any further trade entries."""
        self.session.reset()
        self.session.start()
        self.session.config["max_open_positions"] = 2

        for i, sym in enumerate(["TCS", "INFY"]):
            setup = {
                "symbol": sym,
                "instrument_type": "EQUITY",
                "side": "BUY",
                "entry_price": 2000.0,
                "stop_loss": 1960.0,
                "target_price": 2080.0,
                "atr": 20.0,
                "strategy": "Triple Confluence Pullback",
                "timeframe": "15m",
                "confidence": 85,
                "setup_type": "PULLBACK",
            }
            pos, err = self.session.execute_trade(
                setup,
                quote_resolver=self.make_quote_resolver({sym: 2000.0}),
                market_is_open=True
            )
            self.assertIsNotNone(pos, f"Failed on trade {i+1}: {err}")

        # Now 3rd trade should be rejected by supervisor
        can_trade, reason = self.session.can_open_new_trade()
        self.assertFalse(can_trade)
        self.assertIn("Maximum concurrent positions reached", reason)

    # -------------------------------------------------------------
    # 9. Closed Market Rejection
    # -------------------------------------------------------------
    def test_corner_09_market_closed_rejection(self):
        """Corner Case: Market is closed (e.g. Weekend/Sunday). Live auto-trade must be rejected."""
        self.session.reset()
        self.session.start()
        setup = {
            "symbol": "TCS",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 3500.0,
            "stop_loss": 3465.0,
            "target_price": 3570.0,
            "atr": 35.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 88,
            "setup_type": "PULLBACK",
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"TCS": 3500.0}),
            market_is_open=False
        )
        self.assertIsNone(pos)
        self.assertIn("market is closed", err.lower())

    # -------------------------------------------------------------
    # 10. Available Margin vs Account Equity Consistency
    # -------------------------------------------------------------
    @patch("fingroww_paper_engine.get_ist_now", return_value=MOCK_MARKET_TIME)
    def test_corner_10_margin_equity_consistency(self, mock_time):
        """Corner Case: Verify available_balance + allocated_margin + entry_charges == initial_capital."""
        self.session.reset()
        self.session.start()
        setup = {
            "symbol": "BAJFINANCE",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "entry_price": 7000.0,
            "stop_loss": 6900.0,
            "target_price": 7200.0,
            "atr": 50.0,
            "strategy": "Triple Confluence Pullback",
            "timeframe": "15m",
            "confidence": 85,
            "setup_type": "PULLBACK",
        }
        pos, err = self.session.execute_trade(
            setup,
            quote_resolver=self.make_quote_resolver({"BAJFINANCE": 7000.0}),
            market_is_open=True
        )
        self.assertIsNotNone(pos)
        
        state = self.session.get_state()
        cash = state["account"]["available_balance"]
        margin = state["account"]["allocated_margin"]
        entry_charges = pos["entry_charges"]
        initial_cap = self.session.initial_capital
        
        # Cash + Margin + Entry charges deducted upfront == Initial capital
        self.assertAlmostEqual(cash + margin + entry_charges, initial_cap, delta=0.01)

    # -------------------------------------------------------------
    # 11. Revised SEBI Lot Sizes Check
    # -------------------------------------------------------------
    def test_corner_11_revised_lot_sizes(self):
        """Corner Case: Ensure all F&O lot sizes match latest SEBI specifications."""
        self.assertEqual(LOT_SIZES.get("NIFTY 50"), 75, "NIFTY 50 lot size must be 75")
        self.assertEqual(LOT_SIZES.get("NIFTY"), 75, "NIFTY lot size must be 75")
        self.assertEqual(LOT_SIZES.get("BANK NIFTY"), 30, "BANK NIFTY lot size must be 30")
        self.assertEqual(LOT_SIZES.get("FINNIFTY"), 65, "FINNIFTY lot size must be 65")
        self.assertEqual(LOT_SIZES.get("MIDCPNIFTY"), 120, "MIDCPNIFTY lot size must be 120")
        self.assertEqual(LOT_SIZES.get("SENSEX"), 20, "SENSEX lot size must be 20")
        self.assertEqual(LOT_SIZES.get("BANKEX"), 30, "BANKEX lot size must be 30")

if __name__ == "__main__":
    unittest.main()
