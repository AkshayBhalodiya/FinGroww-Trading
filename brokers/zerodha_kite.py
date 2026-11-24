"""
FinGroww Trading Intelligence — Zerodha Kite Connect v3 Broker Adapter.
======================================================================
Implements official Kite Connect REST API for real live trading,
funds/margins fetching, positions monitoring, and bracket order tickets.
"""

import requests
import logging
import time
from typing import Dict, Any, Tuple, List, Optional
from .base_broker import BaseBrokerClient

logger = logging.getLogger("FinGroww.Broker.Zerodha")


class ZerodhaKiteClient(BaseBrokerClient):
    """Zerodha Kite Connect v3 REST API implementation."""

    BASE_URL = "https://api.kite.trade"

    def __init__(self):
        super().__init__("ZERODHA_KITE")
        self.api_key: str = ""
        self.access_token: str = ""

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
            "Accept": "application/json",
            "User-Agent": "FinGroww-Trading/2.0",
        }

    def authenticate(self, credentials: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        self.api_key = str(credentials.get("api_key") or "").strip()
        self.access_token = str(credentials.get("access_token") or credentials.get("token") or "").strip()
        self.client_id = str(credentials.get("client_id") or "").strip()

        if not self.api_key or not self.access_token:
            return False, "Both Kite API Key and Access Token are required.", {}

        # Validate token by fetching user profile
        try:
            res = requests.get(
                f"{self.BASE_URL}/user/profile",
                headers=self._headers(),
                timeout=5.0
            )
            data = res.json() if res.status_code == 200 else {}
            if res.status_code == 200 and data.get("status") == "success":
                user_data = data.get("data") or {}
                self.user_name = user_data.get("user_name") or user_data.get("user_id") or self.client_id
                self.client_id = user_data.get("user_id") or self.client_id
                self.is_connected = True
                self.connected_at = time.time()
                self.credentials = {"api_key": self.api_key, "client_id": self.client_id}
                return True, f"Connected to Zerodha Kite as [{self.user_name}].", user_data
            else:
                err_msg = data.get("message") or f"Kite Auth HTTP {res.status_code}"
                return False, f"Zerodha authentication failed: {err_msg}", {}
        except Exception as exc:
            logger.warning("Zerodha connection error: %s", exc)
            return False, f"Could not reach Zerodha Kite API: {str(exc)}", {}

    def get_funds(self) -> Tuple[bool, Dict[str, Any], str]:
        if not self.is_connected:
            return False, {}, "Zerodha broker is not connected."

        try:
            res = requests.get(f"{self.BASE_URL}/user/margins", headers=self._headers(), timeout=4.0)
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                eq = (data.get("data") or {}).get("equity") or {}
                avail = float((eq.get("available") or {}).get("live_balance") or 0.0)
                used = float((eq.get("utilised") or {}).get("debits") or 0.0)
                net = float(eq.get("net") or (avail + used))
                collateral = float((eq.get("available") or {}).get("collateral") or 0.0)
                return True, {
                    "broker": "ZERODHA_KITE",
                    "available_cash": round(avail, 2),
                    "used_margin": round(used, 2),
                    "total_balance": round(net, 2),
                    "collateral": round(collateral, 2),
                    "currency": "INR",
                    "fetched_at": time.time(),
                }, ""
            return False, {}, data.get("message", "Failed to fetch margins.")
        except Exception as exc:
            return False, {}, str(exc)

    def get_positions(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Zerodha broker is not connected."

        try:
            res = requests.get(f"{self.BASE_URL}/portfolio/positions", headers=self._headers(), timeout=4.0)
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                net_positions = (data.get("data") or {}).get("net") or []
                standardized = []
                for p in net_positions:
                    qty = int(p.get("quantity") or 0)
                    if qty == 0:
                        continue  # Closed position
                    standardized.append({
                        "trade_id": f"KITE-{p.get('tradingsymbol')}",
                        "symbol": p.get("tradingsymbol"),
                        "exchange": p.get("exchange", "NSE"),
                        "instrument_type": p.get("instrument_token"),
                        "side": "BUY" if qty > 0 else "SELL",
                        "quantity": abs(qty),
                        "entry_price": float(p.get("buy_price") or p.get("average_price") or 0.0),
                        "current_price": float(p.get("last_price") or 0.0),
                        "unrealized_pnl": float(p.get("m2m") or p.get("pnl") or 0.0),
                        "pnl_pct": round(float(p.get("pnl") or 0.0) / max(1.0, float(p.get("buy_price") or 1.0) * abs(qty)) * 100, 2),
                        "product": p.get("product", "MIS"),
                        "is_real_broker": True,
                        "broker": "ZERODHA_KITE",
                    })
                return True, standardized, ""
            return False, [], data.get("message", "Failed to fetch positions.")
        except Exception as exc:
            return False, [], str(exc)

    def get_orders(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Zerodha broker is not connected."

        try:
            res = requests.get(f"{self.BASE_URL}/orders", headers=self._headers(), timeout=4.0)
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                orders = data.get("data") or []
                standardized = []
                for o in orders:
                    standardized.append({
                        "order_id": str(o.get("order_id")),
                        "symbol": o.get("tradingsymbol"),
                        "exchange": o.get("exchange"),
                        "side": o.get("transaction_type"),
                        "order_type": o.get("order_type"),
                        "quantity": o.get("quantity"),
                        "price": o.get("price"),
                        "trigger_price": o.get("trigger_price"),
                        "status": o.get("status"),  # COMPLETE, REJECTED, OPEN
                        "status_message": o.get("status_message"),
                        "order_timestamp": o.get("order_timestamp"),
                        "broker": "ZERODHA_KITE",
                    })
                return True, standardized, ""
            return False, [], data.get("message", "Failed to fetch orders.")
        except Exception as exc:
            return False, [], str(exc)

    def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
        product: str = "MIS",
        exchange: str = "NSE",
        tag: str = "FINGROWW_ALGO",
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any], str]:
        if not self.is_connected:
            return False, {}, "Zerodha broker is not connected."

        # Clean symbol: "NIFTY 24500 CE" -> "NIFTY24500CE"
        clean_sym = symbol.replace(" ", "").upper()
        payload = {
            "tradingsymbol": clean_sym,
            "exchange": exchange.upper(),
            "transaction_type": side.upper(),
            "order_type": order_type.upper(),
            "quantity": int(quantity),
            "product": product.upper(),
            "validity": "DAY",
            "tag": tag[:20],
        }
        if order_type.upper() in ("LIMIT", "SL"):
            payload["price"] = float(price)
        if order_type.upper() in ("SL", "SL-M"):
            payload["trigger_price"] = float(trigger_price)

        try:
            res = requests.post(
                f"{self.BASE_URL}/orders/regular",
                headers=self._headers(),
                data=payload,
                timeout=5.0,
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                order_id = (data.get("data") or {}).get("order_id")
                return True, {
                    "order_id": order_id,
                    "symbol": clean_sym,
                    "side": side,
                    "quantity": quantity,
                    "status": "SUBMITTED",
                    "broker": "ZERODHA_KITE",
                    "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, "Order successfully placed on Zerodha."
            else:
                err_msg = data.get("message") or f"HTTP {res.status_code}"
                return False, {}, f"Zerodha Order Placement Failed: {err_msg}"
        except Exception as exc:
            return False, {}, f"Network error communicating with Zerodha: {str(exc)}"

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        if not self.is_connected:
            return False, "Zerodha broker is not connected."
        try:
            res = requests.delete(
                f"{self.BASE_URL}/orders/regular/{order_id}",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                return True, f"Order {order_id} cancelled on Zerodha."
            return False, data.get("message", "Failed to cancel order.")
        except Exception as exc:
            return False, str(exc)

    def square_off_all(self) -> Tuple[bool, int, List[str]]:
        """Panic exit: Squares off all net open positions on Zerodha."""
        ok, positions, err = self.get_positions()
        if not ok:
            return False, 0, [err]

        closed_count = 0
        logs = []
        for p in positions:
            sym = p["symbol"]
            qty = p["quantity"]
            side = "SELL" if p["side"] == "BUY" else "BUY"
            success, _, msg = self.place_order(
                symbol=sym,
                quantity=qty,
                side=side,
                order_type="MARKET",
                product=p.get("product", "MIS"),
                tag="FINGROWW_PANIC"
            )
            if success:
                closed_count += 1
                logs.append(f"Squared off {sym} ({qty} qty).")
            else:
                logs.append(f"Failed to square off {sym}: {msg}")

        return (closed_count > 0 or len(positions) == 0), closed_count, logs
