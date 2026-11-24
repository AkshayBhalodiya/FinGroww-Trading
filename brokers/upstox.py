"""
FinGroww Trading Intelligence — Upstox API v2 Broker Adapter.
=============================================================
Implements official Upstox API v2 REST interfaces for real live trading,
instant margin balance queries, position book sync, and order execution.
"""

import requests
import logging
import time
from typing import Dict, Any, Tuple, List, Optional
from .base_broker import BaseBrokerClient

logger = logging.getLogger("FinGroww.Broker.Upstox")


class UpstoxClient(BaseBrokerClient):
    """Upstox API v2 implementation for live trading."""

    BASE_URL = "https://api.upstox.com/v2"

    def __init__(self):
        super().__init__("UPSTOX")
        self.access_token: str = ""
        self.upstox_client_id: str = ""
        self.api_key: str = ""

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Api-Version": "2.0",
            "Content-Type": "application/json",
            "User-Agent": "FinGroww-Trading/2.0",
        }

    def authenticate(self, credentials: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        self.access_token = str(
            credentials.get("access_token")
            or credentials.get("token")
            or credentials.get("jwt_token")
            or ""
        ).strip()
        self.upstox_client_id = str(
            credentials.get("client_id")
            or credentials.get("user_id")
            or credentials.get("upstox_client_id")
            or ""
        ).strip()
        self.api_key = str(credentials.get("api_key") or "").strip()

        if not self.access_token:
            return False, "Upstox Access Token is required.", {}

        # Validate by calling Upstox profile endpoint
        try:
            res = requests.get(f"{self.BASE_URL}/user/profile", headers=self._headers(), timeout=5.0)
            data = res.json() if res.status_code in (200, 201) else {}
            if res.status_code == 200 and data.get("status") == "success":
                user_info = data.get("data") or {}
                self.is_connected = True
                self.connected_at = time.time()
                self.client_id = self.upstox_client_id or str(user_info.get("user_id") or "UPSTOX_USER")
                self.user_name = user_info.get("user_name") or f"UpstoxTrader ({self.client_id})"
                self.credentials = {"client_id": self.client_id}
                return True, f"Connected to Upstox API v2 as [{self.user_name}].", user_info
            else:
                err_msg = data.get("message") or (data.get("errors") and data["errors"][0].get("message")) or f"HTTP {res.status_code}"
                return False, f"Upstox authentication failed: {err_msg}", {}
        except Exception as exc:
            logger.warning("Upstox connection error: %s", exc)
            return False, f"Could not reach Upstox API: {str(exc)}", {}

    def get_funds(self) -> Tuple[bool, Dict[str, Any], str]:
        if not self.is_connected:
            return False, {}, "Upstox broker is not connected."

        try:
            res = requests.get(
                f"{self.BASE_URL}/user/get-funds-and-margin?segment=SEC",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                eq = (data.get("data") or {}).get("equity") or {}
                avail = float(eq.get("available_margin") or 0.0)
                used = float(eq.get("used_margin") or 0.0)
                total = float(avail + used)
                collateral = float(eq.get("payin_amount") or eq.get("notional_cash") or 0.0)

                return True, {
                    "broker": "UPSTOX",
                    "available_cash": round(avail, 2),
                    "used_margin": round(used, 2),
                    "total_balance": round(total, 2),
                    "collateral": round(collateral, 2),
                    "currency": "INR",
                    "fetched_at": time.time(),
                }, ""
            err_msg = data.get("message") or "Failed to fetch Upstox margins."
            return False, {}, err_msg
        except Exception as exc:
            return False, {}, str(exc)

    def get_positions(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Upstox broker is not connected."

        try:
            res = requests.get(
                f"{self.BASE_URL}/portfolio/short-term-positions",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                pos_list = data.get("data") or []
                standardized = []
                for p in pos_list:
                    qty = int(p.get("quantity") or p.get("net_quantity") or 0)
                    if qty == 0:
                        continue  # Closed position

                    buy_price = float(p.get("buy_price") or p.get("average_price") or 0.0)
                    last_price = float(p.get("last_price") or 0.0)
                    unrealized = float(p.get("unrealised") or p.get("pnl") or 0.0)
                    pnl_pct = round(
                        (unrealized / max(1.0, buy_price * abs(qty))) * 100, 2
                    ) if buy_price > 0 else 0.0

                    standardized.append({
                        "trade_id": f"UPSTOX-{p.get('trading_symbol')}",
                        "symbol": p.get("trading_symbol"),
                        "exchange": p.get("exchange", "NSE_FO"),
                        "instrument_type": p.get("instrument_token"),
                        "side": "BUY" if qty > 0 else "SELL",
                        "quantity": abs(qty),
                        "entry_price": buy_price,
                        "current_price": last_price,
                        "unrealized_pnl": unrealized,
                        "pnl_pct": pnl_pct,
                        "product": "MIS" if p.get("product") in ("I", "MIS") else "CNC",
                        "is_real_broker": True,
                        "broker": "UPSTOX",
                    })
                return True, standardized, ""
            err_msg = data.get("message") or "Failed to fetch Upstox positions."
            return False, [], err_msg
        except Exception as exc:
            return False, [], str(exc)

    def get_orders(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Upstox broker is not connected."

        try:
            res = requests.get(
                f"{self.BASE_URL}/order/retrieve-all",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") == "success":
                orders = data.get("data") or []
                standardized = []
                for o in orders:
                    raw_status = str(o.get("status") or "").upper()
                    status_map = {
                        "COMPLETE": "COMPLETE",
                        "FILLED": "COMPLETE",
                        "REJECTED": "REJECTED",
                        "CANCELLED": "CANCELLED",
                        "OPEN": "OPEN",
                        "TRIGGER PENDING": "PENDING",
                    }
                    std_status = status_map.get(raw_status, raw_status or "OPEN")

                    standardized.append({
                        "order_id": str(o.get("order_id")),
                        "symbol": o.get("trading_symbol"),
                        "exchange": o.get("exchange"),
                        "side": o.get("transaction_type"),
                        "order_type": o.get("order_type"),
                        "quantity": o.get("quantity"),
                        "price": o.get("price"),
                        "trigger_price": o.get("trigger_price"),
                        "status": std_status,
                        "status_message": o.get("status_message"),
                        "order_timestamp": o.get("order_timestamp"),
                        "broker": "UPSTOX",
                    })
                return True, standardized, ""
            err_msg = data.get("message") or "Failed to fetch Upstox orders."
            return False, [], err_msg
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
            return False, {}, "Upstox broker is not connected."

        clean_sym = symbol.replace(" ", "").upper()
        # Upstox uses 'I' for Intraday/MIS, 'D' for Delivery/CNC
        prod = "I" if product.upper() in ("MIS", "INTRADAY", "I") else "D"
        otype = order_type.upper()

        payload = {
            "quantity": int(quantity),
            "product": prod,
            "validity": "DAY",
            "price": float(price) if otype in ("LIMIT", "SL") else 0.0,
            "tag": tag[:20],
            "instrument_token": clean_sym,
            "order_type": otype,
            "transaction_type": side.upper(),
            "disclosed_quantity": 0,
            "trigger_price": float(trigger_price) if otype in ("SL", "SL-M") else 0.0,
            "is_amo": False,
        }

        try:
            res = requests.post(
                f"{self.BASE_URL}/order/place",
                headers=self._headers(),
                json=payload,
                timeout=5.0
            )
            data = res.json()
            if res.status_code in (200, 201) and data.get("status") == "success":
                order_id = str((data.get("data") or {}).get("order_id") or "")
                return True, {
                    "order_id": order_id,
                    "symbol": clean_sym,
                    "side": side.upper(),
                    "quantity": quantity,
                    "status": "PLACED",
                    "broker": "UPSTOX",
                    "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "raw": data,
                }, "Order successfully placed on Upstox."
            else:
                err_msg = data.get("message") or (data.get("errors") and data["errors"][0].get("message")) or f"HTTP {res.status_code}"
                return False, {}, f"Upstox Order Placement Failed: {err_msg}"
        except Exception as exc:
            return False, {}, f"Network error communicating with Upstox API: {str(exc)}"

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        if not self.is_connected:
            return False, "Upstox broker is not connected."
        try:
            res = requests.delete(
                f"{self.BASE_URL}/order/cancel?order_id={order_id}",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code in (200, 202) and data.get("status") == "success":
                return True, f"Order {order_id} cancelled on Upstox."
            err_msg = data.get("message") or "Failed to cancel Upstox order."
            return False, err_msg
        except Exception as exc:
            return False, str(exc)

    def square_off_all(self) -> Tuple[bool, int, List[str]]:
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
                product="MIS"
            )
            if success:
                closed_count += 1
                logs.append(f"Squared off {sym} ({qty} qty) on Upstox.")
            else:
                logs.append(f"Failed to square off {sym}: {msg}")

        return (closed_count > 0 or len(positions) == 0), closed_count, logs
