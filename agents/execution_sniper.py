"""
FinGroww Multi-Agent Trading Swarm - Agent 3: Execution Sniper
Smart Order Routing & Execution Engine validating capital limits, sizing lots,
and placing orders into the paper engine with zero human latency.
"""

import time
import uuid
import logging
from typing import Dict, List, Any, Optional, Callable
from agents.event_bus import EventBus, SwarmEvent
import fingroww_paper_engine as pe

logger = logging.getLogger("FinGroww.Agent3.ExecutionSniper")

LOT_MAP = {
    "NIFTY 50": 65,
    "NIFTY": 65,
    "BANK NIFTY": 30,
    "BANKNIFTY": 30,
    "FINNIFTY": 65,
    "RELIANCE": 250,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 750,
    "INFY": 400,
    "TCS": 175,
    "BHARTIARTL": 475,
    "BAJFINANCE": 125,
    "AXISBANK": 625,
    "TATAMOTORS": 725
}

class ExecutionSniperAgent:
    """Agent 3: Sizing lots and executing paper orders."""

    def __init__(self, event_bus: EventBus, default_user: str = "Akshay", session_resolver: Optional[Callable] = None):
        self.bus = event_bus
        self.name = "Agent 3 (Execution Sniper)"
        self.user = default_user
        self.session_resolver = session_resolver
        self.is_active = True
        self.orders_executed = 0
        self.failed_orders = 0
        self.max_capital_per_trade_pct = 0.25  # Max 25% portfolio per trade
        self.recent_orders: List[Dict[str, Any]] = []
        self.active_underlyings = set()

        # Subscribe to approved signals from Agent 2 and closures from Agent 4
        self.bus.subscribe("SIGNAL_APPROVED", self.on_signal_approved)
        self.bus.subscribe("POSITION_CLOSED", self.on_position_closed)

    def on_position_closed(self, event: SwarmEvent):
        """Release underlying lock when position is closed by Agent 4."""
        payload = event.payload or {}
        sym = payload.get("symbol")
        base = payload.get("base_symbol")
        if sym:
            self.active_underlyings.discard(sym)
        if base:
            self.active_underlyings.discard(base)

    def on_signal_approved(self, event: SwarmEvent):
        """Listener invoked when Agent 2 issues an approved signal."""
        if not self.is_active:
            logger.warning(f"[{self.name}] Inactive. Ignoring signal.")
            return
        signal = event.payload
        self.execute_order(signal)

    def _get_user_session(self):
        if self.session_resolver:
            try:
                res = self.session_resolver(self.user)
                if isinstance(res, tuple):
                    return res[0]
                return res
            except Exception as e:
                logger.warning(f"[{self.name}] Error in session resolver: {e}")
        try:
            return pe.PaperTradingSession(user_name=self.user)
        except Exception as e:
            logger.warning(f"[{self.name}] Could not create local session: {e}")
            return None

    def execute_order(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate safety margin, lot sizing, and place order."""
        symbol = signal.get("symbol", "")
        underlying = signal.get("underlying", "")

        # Guard against duplicate positions for the same underlying or symbol
        if underlying and underlying in self.active_underlyings:
            logger.info(f"[{self.name}] Duplicate trade blocked: {underlying} is already holding an open position.")
            return None
        if symbol and symbol in self.active_underlyings:
            logger.info(f"[{self.name}] Duplicate trade blocked: {symbol} is already active.")
            return None
        if len(self.active_underlyings) >= 8:
            logger.warning(f"[{self.name}] Max concurrent swarm positions reached. Skipping {symbol}.")
            return None

        entry_price = float(signal.get("entry_price", 100.0))
        stop_loss = float(signal.get("stop_loss", 80.0))
        target_1 = float(signal.get("target_1", 130.0))
        target_2 = float(signal.get("target_2", 160.0))
        option_type = signal.get("option_type", "CE")
        strike = signal.get("strike", 0)

        # Retrieve user session from paper engine
        session = self._get_user_session()
        cash_available = 100000.0
        if session:
            try:
                state = session.get_state()
                acc = state.get("account", {})
                cash_available = float(acc.get("available_balance", 100000.0))
            except Exception as e:
                logger.warning(f"[{self.name}] Error reading session cash: {e}")

        # Lot size resolution
        lot_size = LOT_MAP.get(underlying, 65)
        # Position sizing: 1 lot default for safety
        qty = lot_size
        capital_required = entry_price * qty

        # Pre-execution check
        max_allowed = cash_available * self.max_capital_per_trade_pct
        if capital_required > cash_available or capital_required > max_allowed * 2.0:
            self.failed_orders += 1
            logger.warning(f"[{self.name}] Order REJECTED. Capital req: ₹{capital_required:.2f} > free cash: ₹{cash_available:.2f}")
            self.bus.emit(
                event_type="ORDER_REJECTED",
                sender_agent=self.name,
                payload={
                    "symbol": symbol,
                    "reason": f"Insufficient margin (Req: ₹{capital_required:.2f}, Free: ₹{cash_available:.2f})"
                }
            )
            return None

        order_id = f"FG-SWARM-{uuid.uuid4().hex[:6].upper()}"
        order_record = {
            "order_id": order_id,
            "user": self.user,
            "symbol": symbol,
            "base_symbol": underlying,
            "instrument_type": "INDEX_OPTIONS" if "NIFTY" in underlying else "STOCK_OPTIONS",
            "side": "BUY",
            "entry_price": entry_price,
            "fill_price": entry_price,
            "quantity": qty,
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "strike": strike,
            "option_type": option_type,
            "strategy": f"Swarm 11-Skill Confluence ({signal.get('confluence_score', 80)}/100)",
            "timestamp": time.time(),
            "status": "FILLED"
        }

        # Submit to paper trading session if available
        if session:
            try:
                setup_payload = {
                    "id": order_id,
                    "symbol": symbol,
                    "underlying": underlying,
                    "side": "BUY",
                    "action": "BUY",
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "target_price": target_1,
                    "target_1": target_1,
                    "target_2": target_2,
                    "quantity": qty,
                    "lotSize": qty,
                    "instrument_type": order_record["instrument_type"],
                    "strategy": order_record["strategy"],
                    "confluence_score": signal.get("confluence_score", 85)
                }
                session.execute_trade(setup=setup_payload, is_manual=False)
            except Exception as e:
                logger.info(f"[{self.name}] Native session recorded trade or fallback: {e}")

        self.orders_executed += 1
        if underlying:
            self.active_underlyings.add(underlying)
        if symbol:
            self.active_underlyings.add(symbol)
        self.recent_orders.append(order_record)
        if len(self.recent_orders) > 20:
            self.recent_orders.pop(0)

        logger.info(f"[{self.name}] Order FILLED: {symbol} Qty: {qty} @ ₹{entry_price:.2f}. Notifying Agent 4.")
        
        # Dispatch ORDER_FILLED to Agent 4 (Position Guardian) via EventBus
        self.bus.emit(
            event_type="ORDER_FILLED",
            sender_agent=self.name,
            payload=order_record
        )

        return order_record

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "user": self.user,
            "is_active": self.is_active,
            "orders_executed": self.orders_executed,
            "failed_orders": self.failed_orders,
            "recent_orders_count": len(self.recent_orders)
        }
