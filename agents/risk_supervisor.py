"""
FinGroww Multi-Agent Trading Swarm - Agent 5: Chief Risk Supervisor
Platform-level risk supervisor enforcing SEBI-aligned risk preservation,
maximum daily drawdown circuit breakers, and anti-revenge trading cooldowns.
"""

import time
import logging
from typing import Dict, List, Any, Optional
from agents.event_bus import EventBus, SwarmEvent

logger = logging.getLogger("FinGroww.Agent5.RiskSupervisor")

class RiskSupervisorAgent:
    """Agent 5: Platform-level circuit breaker and risk guardian."""

    def __init__(self, event_bus: EventBus):
        self.bus = event_bus
        self.name = "Agent 5 (Chief Risk Supervisor)"
        self.is_active = True
        self.max_daily_drawdown_pct = 3.0  # 3% max daily loss
        self.max_consecutive_losses = 2    # Cooldown after 2 consecutive losses
        self.cooldown_duration_sec = 2700  # 45 minutes

        self.consecutive_losses = 0
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
        self.cooldown_until = 0.0
        self.daily_starting_capital = 100000.0
        self.current_capital = 100000.0
        self.daily_realized_loss = 0.0
        self.risk_alerts: List[Dict[str, Any]] = []

        # Subscribe to position closures to evaluate risk metrics
        self.bus.subscribe("POSITION_CLOSED", self.on_position_closed)

    def on_position_closed(self, event: SwarmEvent):
        """Analyze trade outcome and enforce circuit breakers."""
        pos = event.payload
        pnl = float(pos.get("net_pnl", 0.0))
        self.current_capital += pnl

        if pnl < 0:
            self.consecutive_losses += 1
            self.daily_realized_loss += abs(pnl)
            logger.warning(f"[{self.name}] Loss recorded: ₹{pnl:.2f}. Consecutive losses: {self.consecutive_losses}")

            # 1. Check Consecutive Loss Limit
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.trigger_cooldown("2 Consecutive Stop-Losses hit. Anti-revenge trading cooldown activated.")

            # 2. Check Daily Drawdown Limit
            drawdown_pct = (self.daily_realized_loss / self.daily_starting_capital) * 100.0
            if drawdown_pct >= self.max_daily_drawdown_pct:
                self.trigger_circuit_breaker(f"Daily drawdown limit reached ({drawdown_pct:.1f}% >= {self.max_daily_drawdown_pct}%).")
        else:
            # Win resets consecutive losses counter
            self.consecutive_losses = 0

    def trigger_cooldown(self, reason: str):
        self.cooldown_until = time.time() + self.cooldown_duration_sec
        self.circuit_breaker_active = True
        self.circuit_breaker_reason = reason
        logger.warning(f"[{self.name}] COOLDOWN TRIGGERED: {reason}")
        self.bus.emit(
            event_type="RISK_ALERT",
            sender_agent=self.name,
            payload={
                "alert_type": "COOLDOWN",
                "reason": reason,
                "cooldown_until": self.cooldown_until,
                "duration_min": self.cooldown_duration_sec // 60
            }
        )

    def trigger_circuit_breaker(self, reason: str):
        self.circuit_breaker_active = True
        self.circuit_breaker_reason = reason
        logger.error(f"[{self.name}] CIRCUIT BREAKER ACTIVATED: {reason}")
        self.bus.emit(
            event_type="RISK_ALERT",
            sender_agent=self.name,
            payload={
                "alert_type": "CIRCUIT_BREAKER",
                "reason": reason,
                "action": "HALT_NEW_TRADES"
            }
        )

    def can_open_new_trade(self) -> tuple[bool, str]:
        """Query function invoked before Agent 3 places an order."""
        if not self.is_active:
            return True, "Supervisor inactive"

        now = time.time()
        if self.cooldown_until > now:
            mins_left = int((self.cooldown_until - now) / 60) + 1
            return False, f"Cooldown active ({mins_left}m remaining)"

        if self.circuit_breaker_active:
            return False, f"Circuit breaker active: {self.circuit_breaker_reason}"

        return True, "Risk checks passed"

    def reset_circuit_breaker(self):
        """User or manual override to reset circuit breaker."""
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
        self.consecutive_losses = 0
        self.cooldown_until = 0.0
        logger.info(f"[{self.name}] Circuit breaker manually reset.")
        self.bus.emit(
            event_type="RISK_ALERT",
            sender_agent=self.name,
            payload={"alert_type": "RESET", "message": "Circuit breaker reset by user."}
        )

    def get_status(self) -> Dict[str, Any]:
        now = time.time()
        cooldown_remaining = max(0, int(self.cooldown_until - now)) if self.cooldown_until > now else 0
        return {
            "name": self.name,
            "is_active": self.is_active,
            "circuit_breaker_active": self.circuit_breaker_active or (cooldown_remaining > 0),
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "consecutive_losses": self.consecutive_losses,
            "cooldown_remaining_sec": cooldown_remaining,
            "daily_realized_loss": round(self.daily_realized_loss, 2),
            "max_drawdown_pct": self.max_daily_drawdown_pct
        }
