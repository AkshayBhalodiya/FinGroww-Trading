"""
FinGroww Trading Intelligence — DhanHQ v2 Broker Adapter.
=========================================================
Implements official DhanHQ v2 REST API for real live trading,
instant margin balance queries, position book sync, and order management.
"""

import requests
import logging
import time
from typing import Dict, Any, Tuple, List, Optional
from .base_broker import BaseBrokerClient

logger = logging.getLogger("FinGroww.Broker.Dhan")


class DhanHqClient(BaseBrokerClient):
    """DhanHQ API v2 implementation."""

    BASE_URL = "https://api.dhan.co/v2"

    def __init__(self):
        super().__init__("DHAN")
        self.access_token: str = ""
        self.dhan_client_id: str = ""

    def _headers(self) -> Dict[str, str]:
        return {
            "access-token": self.access_token,
            "client-id": self.dhan_client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FinGroww-Trading/2.0",
        }

    def authenticate(self, credentials: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        self.access_token = str(credentials.get("access_token") or credentials.get("token") or "").strip()
        self.dhan_client_id = str(credentials.get("client_id") or credentials.get("dhan_client_id") or "").strip()
        self.client_id = self.dhan_client_id

        if not self.access_token or not self.dhan_client_id:
            return False, "Both Dhan Client ID and Access Token are required.", {}

        # Validate by testing fundlimit endpoint
        try:
            res = requests.get(f"{self.BASE_URL}/fundlimit", headers=self._headers(), timeout=5.0)
            data = res.json() if res.status_code == 200 else {}
            if res.status_code == 200:
                self.is_connected = True
                self.connected_at = time.time()
                self.user_name = f"DhanTrader ({self.dhan_client_id})"
                self.credentials = {"client_id": self.dhan_client_id}
                return True, f"Connected to DhanHQ as [{self.dhan_client_id}].", data
            else:
                err_msg = data.get("errorMessage") or data.get("remarks") or f"HTTP {res.status_code}"
                return False, f"DhanHQ connection failed: {err_msg}", {}
        except Exception as exc:
            logger.warning("Dhan connection exception: %s", exc)
            return False, f"Could not reach DhanHQ API: {str(exc)}", {}

    def get_funds(self) -> Tuple[bool, Dict[str, Any], str]:
        if not self.is_connected:
            return False, {}, "Dhan broker is not connected."

        try:
            res = requests.get(f"{self.BASE_URL}/fundlimit", headers=self._headers(), timeout=4.0)
            data = res.json()
            if res.status_code == 200:
                avail = float(data.get("availabelBalance") or data.get("availableBalance") or 0.0)
                used = float(data.get("utilizedAmount") or 0.0)
                collateral = float(data.get("collateralAmount") or 0.0)
                total = float(data.get("sodLimit") or (avail + used))
                return True, {
                    "broker": "DHAN",
                    "available_cash": round(avail, 2),
                    "used_margin": round(used, 2),
                    "total_balance": round(total, 2),
                    "collateral": round(collateral, 2),
                    "currency": "INR",
                    "fetched_at": time.time(),
                }, ""
            return False, {}, data.get("errorMessage", "Failed to fetch Dhan funds.")
        except Exception as exc:
            return False, {}, str(exc)

    def get_positions(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Dhan broker is not connected."

        try:
            res = requests.get(f"{self.BASE_URL}/positions", headers=self._headers(), timeout=4.0)
            data = res.json()
            if res.status_code == 200 and isinstance(data, list):
                standardized = []
                for p in data:
                    qty = int(p.get("netQty") or 0)
                    if qty == 0:
                        continue
                    standardized.append({
                        "trade_id": f"DHAN-{p.get('tradingSymbol')}",
                        "symbol": p.get("tradingSymbol"),
                        "exchange": "NSE",
                        "side": "BUY" if qty > 0 else "SELL",
                        "quantity": abs(qty),
                        "entry_price": float(p.get("costPrice") or 0.0),
                        "current_price": float(p.get("costPrice") or 0.0) + (float(p.get("unrealizedProfit") or 0.0) / max(1, abs(qty))),
                        "unrealized_pnl": float(p.get("unrealizedProfit") or 0.0),
                        "product": p.get("productType", "INTRADAY"),
                        "is_real_broker": True,
                        "broker": "DHAN",
                    })
                return True, standardized, ""
            return False, [], "Failed to parse Dhan positions."
        except Exception as exc:
            return False, [], str(exc)

    def get_orders(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Dhan broker is not connected."

        try:
            res = requests.get(f"{self.BASE_URL}/orders", headers=self._headers(), timeout=4.0)
            data = res.json()
            if res.status_code == 200 and isinstance(data, list):
                standardized = []
                for o in data:
                    standardized.append({
                        "order_id": str(o.get("orderId")),
                        "symbol": o.get("tradingSymbol"),
                        "side": o.get("transactionType"),
                        "order_type": o.get("orderType"),
                        "quantity": int(o.get("quantity") or 0),
                        "price": float(o.get("price") or 0.0),
                        "trigger_price": float(o.get("triggerPrice") or 0.0),
                        "status": o.get("orderStatus"),
                        "order_timestamp": o.get("createTime"),
                        "broker": "DHAN",
                    })
                return True, standardized, ""
            return False, [], "Failed to parse Dhan orders."
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
            return False, {}, "Dhan broker is not connected."

        clean_sym = symbol.replace(" ", "").upper()
        is_opt = any(w in clean_sym for w in ("CE", "PE", "FUT"))

        payload = {
            "dhanClientId": self.dhan_client_id,
            "correlationId": f"FG_{int(time.time())}",
            "transactionType": side.upper(),
            "exchangeSegment": "NSE_FNO" if is_opt else "NSE_EQ",
            "productType": "INTRADAY" if product.upper() == "MIS" else "CNC",
            "orderType": order_type.upper(),
            "validity": "DAY",
            "tradingSymbol": clean_sym,
            "securityId": "0",
            "quantity": int(quantity),
            "price": float(price if order_type.upper() == "LIMIT" else 0.0),
            "triggerPrice": float(trigger_price if "SL" in order_type.upper() else 0.0),
        }

        try:
            res = requests.post(f"{self.BASE_URL}/orders", headers=self._headers(), json=payload, timeout=5.0)
            data = res.json()
            if res.status_code in (200, 201) and data.get("orderStatus") in ("TRANSIT", "PENDING", "CONFIRMED"):
                order_id = data.get("orderId")
                return True, {
                    "order_id": order_id,
                    "symbol": clean_sym,
                    "side": side,
                    "quantity": quantity,
                    "status": "SUBMITTED",
                    "broker": "DHAN",
                    "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, "Order successfully placed on Dhan."
            else:
                err_msg = data.get("errorMessage") or data.get("remarks") or f"HTTP {res.status_code}"
                return False, {}, f"Dhan Order Placement Failed: {err_msg}"
        except Exception as exc:
            return False, {}, f"Network error communicating with Dhan: {str(exc)}"

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        if not self.is_connected:
            return False, "Dhan broker is not connected."
        try:
            res = requests.delete(f"{self.BASE_URL}/orders/{order_id}", headers=self._headers(), timeout=4.0)
            if res.status_code in (200, 202):
                return True, f"Order {order_id} cancelled on Dhan."
            data = res.json()
            return False, data.get("errorMessage", "Failed to cancel Dhan order.")
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
                logs.append(f"Squared off {sym} ({qty} qty) on Dhan.")
            else:
                logs.append(f"Failed to square off {sym}: {msg}")

        return (closed_count > 0 or len(positions) == 0), closed_count, logs
