"""
FinGroww Trading Intelligence — Angel One SmartAPI Broker Adapter.
==================================================================
Implements official Angel One SmartAPI REST protocol for live trading,
RMS margins fetching, portfolio position synchronization, and order execution.
"""

import requests
import logging
import time
from typing import Dict, Any, Tuple, List, Optional
from .base_broker import BaseBrokerClient

logger = logging.getLogger("FinGroww.Broker.AngelOne")


class AngelSmartApiClient(BaseBrokerClient):
    """Angel One SmartAPI REST implementation."""

    BASE_URL = "https://apiconnect.angelbroking.com"

    def __init__(self):
        super().__init__("ANGEL_ONE")
        self.api_key: str = ""
        self.jwt_token: str = ""
        self.refresh_token: str = ""
        self.feed_token: str = ""

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "fe80::1",
            "X-PrivateKey": self.api_key,
            "Authorization": f"Bearer {self.jwt_token}",
        }

    def authenticate(self, credentials: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        self.api_key = str(credentials.get("api_key") or "").strip()
        self.client_id = str(credentials.get("client_id") or credentials.get("clientcode") or "").strip()
        jwt_direct = str(credentials.get("jwt_token") or credentials.get("auth_token") or "").strip()

        if not self.api_key:
            return False, "Angel One SmartAPI Key is required.", {}

        # 1. If JWT token provided directly
        if jwt_direct:
            self.jwt_token = jwt_direct
            self.is_connected = True
            self.connected_at = time.time()
            self.user_name = self.client_id or "AngelTrader"
            return True, f"Connected to Angel One SmartAPI for [{self.client_id}].", {"client_id": self.client_id}

        # 2. Or login via Client Code + Password/PIN + TOTP
        password = str(credentials.get("password") or credentials.get("mpin") or "").strip()
        totp = str(credentials.get("totp") or "").strip()

        if not self.client_id or not password:
            return False, "Angel One Client Code and MPIN/Password are required.", {}

        login_payload = {
            "clientcode": self.client_id,
            "password": password,
            "totp": totp or "000000"
        }

        try:
            res = requests.post(
                f"{self.BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-UserType": "USER",
                    "X-SourceID": "WEB",
                    "X-ClientLocalIP": "127.0.0.1",
                    "X-ClientPublicIP": "127.0.0.1",
                    "X-MACAddress": "fe80::1",
                    "X-PrivateKey": self.api_key,
                },
                json=login_payload,
                timeout=6.0,
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") is True:
                resp_data = data.get("data") or {}
                self.jwt_token = resp_data.get("jwtToken", "")
                self.refresh_token = resp_data.get("refreshToken", "")
                self.feed_token = resp_data.get("feedToken", "")
                self.user_name = resp_data.get("name") or self.client_id
                self.is_connected = True
                self.connected_at = time.time()
                return True, f"Connected to Angel One as [{self.user_name}].", resp_data
            else:
                err_msg = data.get("message") or f"Angel Auth HTTP {res.status_code}"
                return False, f"Angel One login failed: {err_msg}", {}
        except Exception as exc:
            logger.warning("Angel One connection exception: %s", exc)
            return False, f"Could not reach Angel One SmartAPI: {str(exc)}", {}

    def get_funds(self) -> Tuple[bool, Dict[str, Any], str]:
        if not self.is_connected:
            return False, {}, "Angel One broker is not connected."

        try:
            res = requests.get(
                f"{self.BASE_URL}/rest/secure/angelbroking/user/v1/getRMS",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") is True:
                rms = data.get("data") or {}
                avail = float(rms.get("availablecash") or rms.get("net") or 0.0)
                used = float(rms.get("utilisedamount") or 0.0)
                total = float(rms.get("net") or (avail + used))
                collateral = float(rms.get("collateral") or 0.0)
                return True, {
                    "broker": "ANGEL_ONE",
                    "available_cash": round(avail, 2),
                    "used_margin": round(used, 2),
                    "total_balance": round(total, 2),
                    "collateral": round(collateral, 2),
                    "currency": "INR",
                    "fetched_at": time.time(),
                }, ""
            return False, {}, data.get("message", "Failed to fetch RMS funds.")
        except Exception as exc:
            return False, {}, str(exc)

    def get_positions(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Angel One broker is not connected."

        try:
            res = requests.get(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/getPosition",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") is True:
                raw_positions = data.get("data") or []
                standardized = []
                for p in raw_positions:
                    net_qty = int(p.get("netqty") or 0)
                    if net_qty == 0:
                        continue
                    standardized.append({
                        "trade_id": f"ANGEL-{p.get('tradingsymbol')}",
                        "symbol": p.get("tradingsymbol"),
                        "exchange": p.get("exchange", "NSE"),
                        "side": "BUY" if net_qty > 0 else "SELL",
                        "quantity": abs(net_qty),
                        "entry_price": float(p.get("avgnetprice") or 0.0),
                        "current_price": float(p.get("ltp") or 0.0),
                        "unrealized_pnl": float(p.get("unrealised") or p.get("m2m") or 0.0),
                        "product": p.get("producttype", "INTRADAY"),
                        "is_real_broker": True,
                        "broker": "ANGEL_ONE",
                    })
                return True, standardized, ""
            return False, [], data.get("message", "Failed to fetch positions.")
        except Exception as exc:
            return False, [], str(exc)

    def get_orders(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        if not self.is_connected:
            return False, [], "Angel One broker is not connected."

        try:
            res = requests.get(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/getOrderBook",
                headers=self._headers(),
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") is True:
                orders = data.get("data") or []
                standardized = []
                for o in orders:
                    standardized.append({
                        "order_id": str(o.get("orderid")),
                        "symbol": o.get("tradingsymbol"),
                        "exchange": o.get("exchange"),
                        "side": o.get("transactiontype"),
                        "order_type": o.get("ordertype"),
                        "quantity": int(o.get("quantity") or 0),
                        "price": float(o.get("price") or 0.0),
                        "trigger_price": float(o.get("triggerprice") or 0.0),
                        "status": o.get("orderstatus"),
                        "status_message": o.get("text"),
                        "order_timestamp": o.get("updatetime"),
                        "broker": "ANGEL_ONE",
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
            return False, {}, "Angel One broker is not connected."

        clean_sym = symbol.replace(" ", "").upper()
        # Map product
        prod_map = {"MIS": "INTRADAY", "CNC": "DELIVERY", "NRML": "CARRYFORWARD"}
        angel_product = prod_map.get(product.upper(), "INTRADAY")

        payload = {
            "variety": "NORMAL",
            "tradingsymbol": clean_sym,
            "symboltoken": "0",  # SmartAPI accepts 0 with proper tradingsymbol
            "transactiontype": side.upper(),
            "exchange": "NFO" if any(w in clean_sym for w in ("CE", "PE", "FUT")) else exchange.upper(),
            "ordertype": order_type.upper(),
            "producttype": angel_product,
            "duration": "DAY",
            "price": str(price if order_type.upper() == "LIMIT" else 0.0),
            "triggerprice": str(trigger_price if "SL" in order_type.upper() else 0.0),
            "quantity": str(quantity),
        }

        try:
            res = requests.post(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                headers=self._headers(),
                json=payload,
                timeout=5.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") is True:
                order_id = (data.get("data") or {}).get("orderid")
                return True, {
                    "order_id": order_id,
                    "symbol": clean_sym,
                    "side": side,
                    "quantity": quantity,
                    "status": "SUBMITTED",
                    "broker": "ANGEL_ONE",
                    "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, "Order successfully placed on Angel One."
            else:
                err_msg = data.get("message") or f"HTTP {res.status_code}"
                return False, {}, f"Angel One Order Placement Failed: {err_msg}"
        except Exception as exc:
            return False, {}, f"Network error communicating with Angel One: {str(exc)}"

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        if not self.is_connected:
            return False, "Angel One broker is not connected."
        try:
            res = requests.post(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/cancelOrder",
                headers=self._headers(),
                json={"variety": "NORMAL", "orderid": str(order_id)},
                timeout=4.0
            )
            data = res.json()
            if res.status_code == 200 and data.get("status") is True:
                return True, f"Order {order_id} cancelled on Angel One."
            return False, data.get("message", "Failed to cancel order.")
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
                logs.append(f"Squared off {sym} ({qty} qty) on Angel One.")
            else:
                logs.append(f"Failed to square off {sym}: {msg}")

        return (closed_count > 0 or len(positions) == 0), closed_count, logs
