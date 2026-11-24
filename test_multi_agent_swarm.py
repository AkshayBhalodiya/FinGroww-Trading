"""
FinGroww Multi-Agent Trading Swarm - Unit Test Suite
Validates all 5 agents, event routing, full auto and copilot modes,
trailing stop-loss, and circuit breaker guardrails.
"""

import unittest
import time
from agents.event_bus import EventBus, SwarmEvent
from agents.sentinel_scout import SentinelScoutAgent
from agents.quant_brain import QuantBrainAgent
from agents.execution_sniper import ExecutionSniperAgent
from agents.position_guardian import PositionGuardianAgent
from agents.risk_supervisor import RiskSupervisorAgent
from agents.swarm_orchestrator import SwarmOrchestrator
import fingroww_paper_engine as pe

class TestMultiAgentSwarm(unittest.TestCase):

    def setUp(self):
        self.bus = EventBus(max_audit_history=100)

    def test_01_event_bus_pub_sub_and_audit(self):
        """Test event publishing, specific handlers, and audit logging."""
        received = []
        def handler(event: SwarmEvent):
            received.append(event)

        self.bus.subscribe("TEST_EVENT", handler)
        evt = self.bus.emit("TEST_EVENT", "Tester", {"message": "Hello Agent"})

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].event_type, "TEST_EVENT")
        self.assertEqual(received[0].payload["message"], "Hello Agent")

        # Verify audit trail
        trail = self.bus.get_audit_trail(limit=5)
        self.assertTrue(len(trail) >= 1)
        self.assertEqual(trail[0]["event_type"], "TEST_EVENT")

    def test_02_sentinel_scout_detection(self):
        """Test Agent 1 detection of Golden Zone setup with volume surge."""
        scout = SentinelScoutAgent(self.bus)
        
        # Test candidate symbol
        quote = {
            "symbol": "NIFTY 50",
            "ltp": 22750.0,
            "high": 22900.0,
            "low": 22600.0,
            "open": 22700.0,
            "vwap": 22730.0,
            "vol_ratio": 2.2
        }
        candidate = scout.scan_symbol(quote)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["symbol"], "NIFTY 50")
        self.assertEqual(candidate["direction"], "BULLISH")
        self.assertTrue(candidate["vol_ratio"] >= 1.5)

    def test_03_quant_brain_confluence_full_auto(self):
        """Test Agent 2 confluence scoring and automatic approval in FULL_AUTO mode."""
        approved_events = []
        self.bus.subscribe("SIGNAL_APPROVED", lambda e: approved_events.append(e))

        brain = QuantBrainAgent(self.bus)
        brain.mode = "FULL_AUTO"
        brain.risk_profile = "BALANCED"  # Requires 75

        candidate = {
            "symbol": "NIFTY 50",
            "ltp": 22750.0,
            "direction": "BULLISH",
            "fib_50": 22750.0,
            "vwap": 22730.0,
            "vol_ratio": 2.2
        }

        signal = brain.evaluate_candidate(candidate)
        self.assertIsNotNone(signal)
        self.assertTrue(signal["confluence_score"] >= 75)
        self.assertEqual(signal["action"], "BUY")
        self.assertIn("CE", signal["symbol"])
        self.assertEqual(len(approved_events), 1)

    def test_04_quant_brain_copilot_mode_pending_approval(self):
        """Test Agent 2 holding signal for 1-click human approval in COPILOT mode."""
        pending_events = []
        approved_events = []
        self.bus.subscribe("SIGNAL_PENDING_APPROVAL", lambda e: pending_events.append(e))
        self.bus.subscribe("SIGNAL_APPROVED", lambda e: approved_events.append(e))

        brain = QuantBrainAgent(self.bus)
        brain.mode = "COPILOT"

        candidate = {
            "symbol": "BANK NIFTY",
            "ltp": 53900.0,
            "direction": "BULLISH",
            "fib_50": 53900.0,
            "vwap": 53800.0,
            "vol_ratio": 2.0
        }

        signal = brain.evaluate_candidate(candidate)
        self.assertIsNotNone(signal)
        # Should NOT automatically dispatch approved event
        self.assertEqual(len(approved_events), 0)
        self.assertEqual(len(pending_events), 1)
        self.assertIn(signal["signal_id"], brain.pending_approvals)

        # Now simulate 1-click user approval
        approved = brain.approve_pending_signal(signal["signal_id"])
        self.assertIsNotNone(approved)
        self.assertEqual(len(approved_events), 1)
        self.assertEqual(len(brain.pending_approvals), 0)

    def test_05_execution_sniper_sizing(self):
        """Test Agent 3 order execution, lot sizing, and event emission."""
        filled_events = []
        self.bus.subscribe("ORDER_FILLED", lambda e: filled_events.append(e))

        sniper = ExecutionSniperAgent(self.bus, default_user="UnitTestUser")
        test_session = pe.PaperTradingSession(user_name="UnitTestUser")
        test_session.available_cash = 100000.0
        test_session.account_equity = 100000.0
        sniper.session_resolver = lambda u: test_session
        signal = {
            "symbol": "NIFTY 22750 CE",
            "underlying": "NIFTY 50",
            "entry_price": 125.0,
            "stop_loss": 100.0,
            "target_1": 155.0,
            "target_2": 185.0,
            "strike": 22750,
            "option_type": "CE",
            "confluence_score": 88
        }

        order = sniper.execute_order(signal)
        self.assertIsNotNone(order)
        self.assertEqual(order["status"], "FILLED")
        self.assertEqual(order["quantity"], 65)  # Nifty lot size
        self.assertEqual(len(filled_events), 1)

    def test_06_position_guardian_breakeven_and_trailing(self):
        """Test Agent 4 trailing stop loss: moving to breakeven, taking partial profit at Target 1."""
        guardian = PositionGuardianAgent(self.bus)
        order_event = SwarmEvent(
            event_type="ORDER_FILLED",
            sender_agent="Agent 3",
            payload={
                "order_id": "POS-001",
                "symbol": "NIFTY 22750 CE",
                "base_symbol": "NIFTY 50",
                "entry_price": 100.0,
                "quantity": 60,
                "stop_loss": 80.0,
                "target_1": 130.0,
                "target_2": 160.0
            }
        )
        guardian.on_order_filled(order_event)
        self.assertIn("POS-001", guardian.active_positions)

        # Step 1: Price goes to 118 (+18% gain) -> Breakeven rule should trigger (SL -> 100)
        guardian.update_prices({"NIFTY 22750 CE": 118.0})
        pos = guardian.active_positions["POS-001"]
        self.assertEqual(pos["stop_loss"], 100.0)
        self.assertTrue(pos["tsl_active"])

        # Step 2: Price goes to 132 (Target 1 hit) -> Partial profit taken (50% closed), SL -> 110
        guardian.update_prices({"NIFTY 22750 CE": 132.0})
        pos = guardian.active_positions["POS-001"]
        self.assertTrue(pos["partial_taken"])
        self.assertEqual(pos["remaining_qty"], 30)
        self.assertEqual(pos["stop_loss"], 110.0)

        # Step 3: Price hits Target 2 (162.0) -> Full closure with WIN
        guardian.update_prices({"NIFTY 22750 CE": 162.0})
        self.assertNotIn("POS-001", guardian.active_positions)
        self.assertEqual(len(guardian.closed_positions), 1)
        self.assertIn("TARGET_2_HIT", guardian.closed_positions[0]["exit_reason"])
        self.assertTrue(guardian.closed_positions[0]["net_pnl"] > 0)

    def test_07_risk_supervisor_circuit_breaker(self):
        """Test Agent 5 enforcing consecutive loss and daily drawdown circuit breakers."""
        supervisor = RiskSupervisorAgent(self.bus)
        supervisor.daily_starting_capital = 100000.0

        # Simulate 2 consecutive losses
        loss_evt1 = SwarmEvent("POSITION_CLOSED", "Agent 4", {"net_pnl": -1600.0})
        supervisor.on_position_closed(loss_evt1)
        self.assertFalse(supervisor.circuit_breaker_active)

        loss_evt2 = SwarmEvent("POSITION_CLOSED", "Agent 4", {"net_pnl": -1500.0})
        supervisor.on_position_closed(loss_evt2)
        # 2 consecutive losses should trigger cooldown circuit breaker
        self.assertTrue(supervisor.circuit_breaker_active)
        can_open, reason = supervisor.can_open_new_trade()
        self.assertFalse(can_open)
        self.assertIn("Cooldown", reason)

        # Manual reset
        supervisor.reset_circuit_breaker()
        can_open, _ = supervisor.can_open_new_trade()
        self.assertTrue(can_open)

    def test_08_swarm_orchestrator_end_to_end(self):
        """Test end-to-end multi-agent execution pipeline through SwarmOrchestrator."""
        orchestrator = SwarmOrchestrator.get_instance()
        status = orchestrator.get_full_status()
        self.assertTrue(status["swarm_online"])
        self.assertIn("agent1_scout", status)
        self.assertIn("agent2_brain", status)
        self.assertIn("agent3_sniper", status)
        self.assertIn("agent4_guardian", status)
        self.assertIn("agent5_supervisor", status)

        # Trigger an evaluation cycle
        res = orchestrator.trigger_manual_cycle()
        self.assertTrue(res["scanned"])
        self.assertIsNotNone(orchestrator.bus.get_audit_trail())

if __name__ == "__main__":
    unittest.main()
