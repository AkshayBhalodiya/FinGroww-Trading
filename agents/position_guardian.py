"""
FinGroww Multi-Agent Trading Swarm - Agent 4: Position Guardian
Real-time tick-by-tick supervisor managing Trailing Stop-Loss (TSL),
partial profit taking at Target 1, and momentum capital preservation.
"""

import time
import logging
from typing import Dict, List, Any, Optional
from agents.event_bus import EventBus, SwarmEvent

logger = logging.getLogger("FinGroww.Agent4.PositionGuardian")

class PositionGuardianAgent:
    """Agent 4: Active position monitor & trailing stop-loss manager."""

    def __init__(self, event_bus: EventBus):
        self.bus = event_bus
        self.name = "Agent 4 (Position Guardian)"
        self.is_active = True
        self.active_positions: Dict[str, Dict[str, Any]] = {}
        self.closed_positions: List[Dict[str, Any]] = []
        self.trailing_updates_count = 0
        self.partial_profits_taken = 0
        self.total_realized_pnl = 0.0

        # Subscribe to filled orders from Agent 3 and price ticks
        self.bus.subscribe("ORDER_FILLED", self.on_order_filled)
        self.bus.subscribe("TICK_UPDATE", self.on_tick_update)

    def on_order_filled(self, event: SwarmEvent):
        """Listener invoked when Agent 3 fills a new trade order."""
        order = event.payload
        pos_id = order.get("order_id")
        if not pos_id:
            return

        position = {
            "pos_id": pos_id,
            "symbol": order.get("symbol"),
            "base_symbol": order.get("base_symbol"),
            "side": order.get("side", "BUY"),
            "entry_price": float(order.get("entry_price", 100.0)),
            "current_price": float(order.get("entry_price", 100.0)),
            "quantity": int(order.get("quantity", 65)),
            "remaining_qty": int(order.get("quantity", 65)),
            "stop_loss": float(order.get("stop_loss", 80.0)),
            "initial_sl": float(order.get("stop_loss", 80.0)),
            "target_1": float(order.get("target_1", 130.0)),
            "target_2": float(order.get("target_2", 160.0)),
            "partial_taken": False,
            "tsl_active": False,
            "highest_price": float(order.get("entry_price", 100.0)),
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "opened_at": order.get("timestamp", time.time())
        }

        self.active_positions[pos_id] = position
        logger.info(f"[{self.name}] Tracking active position: {pos_id} ({position['symbol']}) SL: ₹{position['stop_loss']}")

    def on_tick_update(self, event: SwarmEvent):
        """Process incoming live price ticks across all active positions."""
        if not self.is_active:
            return
        tick_data = event.payload
        self.update_prices(tick_data)

    def update_prices(self, price_map: Dict[str, float]):
        """
        Evaluate and trail all active positions based on updated market prices.
        price_map: dict of {symbol: current_ltp}
        """
        if not self.active_positions:
            return

        to_close = []

        for pos_id, pos in list(self.active_positions.items()):
            symbol = pos["symbol"]
            curr = price_map.get(symbol) or price_map.get(pos["base_symbol"])
            if not curr:
                continue

            pos["current_price"] = curr
            entry = pos["entry_price"]
            rem_qty = pos["remaining_qty"]

            # Update highest price seen
            if curr > pos["highest_price"]:
                pos["highest_price"] = curr

            # Calculate Unrealized PnL
            gain_per_share = curr - entry
            pos["unrealized_pnl"] = round(gain_per_share * rem_qty, 2)
            gain_pct = ((curr - entry) / entry) * 100.0

            # 1. Breakeven rule: If gain >= +15%, move SL to Entry Price
            if gain_pct >= 15.0 and pos["stop_loss"] < entry:
                old_sl = pos["stop_loss"]
                pos["stop_loss"] = entry
                pos["tsl_active"] = True
                self.trailing_updates_count += 1
                logger.info(f"[{self.name}] Breakeven reached (+{gain_pct:.1f}%). Trailed SL from ₹{old_sl:.1f} to Entry ₹{entry:.1f}")
                self.bus.emit(
                    event_type="POSITION_TRAILED",
                    sender_agent=self.name,
                    payload={"pos_id": pos_id, "symbol": symbol, "old_sl": old_sl, "new_sl": entry, "reason": "Breakeven lock (+15%)"}
                )

            # 2. Target 1 partial profit booking (50% closed at Target 1)
            if curr >= pos["target_1"] and not pos["partial_taken"]:
                close_qty = rem_qty // 2
                if close_qty > 0:
                    profit = round((curr - entry) * close_qty, 2)
                    pos["realized_pnl"] += profit
                    pos["remaining_qty"] -= close_qty
                    pos["partial_taken"] = True
                    # Set SL to (Entry + 10%)
                    new_sl = round(entry * 1.10, 1)
                    pos["stop_loss"] = max(pos["stop_loss"], new_sl)
                    self.partial_profits_taken += 1
                    self.total_realized_pnl += profit

                    logger.info(f"[{self.name}] Target 1 hit! Closed 50% ({close_qty} qty) @ ₹{curr:.2f}. Profit: +₹{profit}. New SL: ₹{pos['stop_loss']}")
                    self.bus.emit(
                        event_type="PARTIAL_PROFIT_BOOKED",
                        sender_agent=self.name,
                        payload={"pos_id": pos_id, "symbol": symbol, "closed_qty": close_qty, "price": curr, "profit": profit}
                    )

            # 3. Dynamic Continuous Trailing SL (Keep trailing on subsequent ticks after Target 1)
            elif pos["partial_taken"] and curr > pos["target_1"]:
                trail_sl = round(pos["highest_price"] * 0.88, 1)  # 12% buffer from peak
                if trail_sl > pos["stop_loss"]:
                    old_sl = pos["stop_loss"]
                    pos["stop_loss"] = trail_sl
                    self.trailing_updates_count += 1
                    logger.info(f"[{self.name}] Dynamic Trailing: SL raised to ₹{trail_sl} (Peak ₹{pos['highest_price']})")
                    self.bus.emit(
                        event_type="POSITION_TRAILED",
                        sender_agent=self.name,
                        payload={"pos_id": pos_id, "symbol": symbol, "old_sl": old_sl, "new_sl": trail_sl, "reason": "Trailing peak buffer"}
                    )

            # 4. Target 2 Hit (Final profit exit)
            if curr >= pos["target_2"]:
                logger.info(f"[{self.name}] Target 2 reached @ ₹{curr:.2f}! Closing full position.")
                to_close.append((pos_id, "TARGET_2_HIT (WIN 🎯)", curr))
                continue

            # 5. Stop-Loss Triggered
            if curr <= pos["stop_loss"]:
                reason = "TRAILING_SL_HIT (PROFIT LOCKED)" if pos["stop_loss"] >= entry else "INITIAL_SL_HIT"
                logger.info(f"[{self.name}] SL hit @ ₹{curr:.2f} <= ₹{pos['stop_loss']:.2f}. Closing position.")
                to_close.append((pos_id, reason, curr))

        # Close marked positions
        for pos_id, reason, exit_price in to_close:
            self.close_position(pos_id, reason, exit_price)

    def close_position(self, pos_id: str, reason: str, exit_price: float) -> Optional[Dict[str, Any]]:
        """Close an active position and emit closure event."""
        pos = self.active_positions.pop(pos_id, None)
        if not pos:
            return None

        rem_qty = pos["remaining_qty"]
        pnl = round(pos["realized_pnl"] + ((exit_price - pos["entry_price"]) * rem_qty), 2)
        pos["closed_at"] = time.time()
        pos["exit_price"] = exit_price
        pos["exit_reason"] = reason
        pos["net_pnl"] = pnl
        self.total_realized_pnl += round((exit_price - pos["entry_price"]) * rem_qty, 2)

        self.closed_positions.append(pos)
        if len(self.closed_positions) > 30:
            self.closed_positions.pop(0)

        logger.info(f"[{self.name}] Position {pos_id} CLOSED. Net P&L: ₹{pnl} ({reason})")

        self.bus.emit(
            event_type="POSITION_CLOSED",
            sender_agent=self.name,
            payload=pos
        )
        return pos

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "is_active": self.is_active,
            "active_positions_count": len(self.active_positions),
            "active_positions": list(self.active_positions.values()),
            "closed_positions_count": len(self.closed_positions),
            "trailing_updates_count": self.trailing_updates_count,
            "partial_profits_taken": self.partial_profits_taken,
            "total_realized_pnl": round(self.total_realized_pnl, 2)
        }
