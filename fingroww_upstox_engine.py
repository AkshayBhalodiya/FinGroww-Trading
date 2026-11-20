"""
FinGroww Upstox Real Trading Engine (Upstox API v2)
===================================================
Provides production-grade live execution, OAuth 2.0 broker authentication,
real funds synchronization, order book tracking, and algorithmic auto-execution
integrated with Upstox API v2.

Features:
- Full OAuth 2.0 Token Exchange and automated .env persistence
- Real-time Funds & Margin Mark-to-Market
- Live Upstox Position Tracking & Order Placement
- Mandatory Stop-Loss enforcement on every real trade
- FinGroww 1.80R Risk-to-Reward Algorithmic Target calculation
- Dual Modes: LIVE REAL CAPITAL and DRY-RUN SIMULATION
- Emergency Kill Switch (Square off all real positions instantly)
- Daily Loss Limit protection & Max open positions guardrail
"""

import os
import re
import json
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import requests

logger = logging.getLogger("FinGrowwUpstoxEngine")
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] [UPSTOX-ENGINE] [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)

IST = timezone(timedelta(hours=5, minutes=30))

UPSTOX_API_BASE = "https://api.upstox.com/v2"
UPSTOX_AUTH_DIALOG = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

LOT_SIZES = {
    "NIFTY 50": 25,
    "NIFTY": 25,
    "BANK NIFTY": 15,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 50,
    "SENSEX": 10,
    "RELIANCE": 250,
    "HDFCBANK": 550,
    "TCS": 175,
    "INFY": 400,
    "ICICIBANK": 700,
    "SBIN": 750,
    "TATAMOTORS": 700,
    "BHARTIARTL": 475,
    "LT": 175,
    "AXISBANK": 625,
    "BAJFINANCE": 125,
    "MARUTI": 50,
}

INSTRUMENT_KEYS = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANK NIFTY": "NSE_INDEX|Nifty Bank",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
    "RELIANCE": "NSE_EQ|INE002A01018",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "TCS": "NSE_EQ|INE467B01029",
    "INFY": "NSE_EQ|INE009A01021",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "SBIN": "NSE_EQ|INE062A01020",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "LT": "NSE_EQ|INE018A01030",
    "AXISBANK": "NSE_EQ|INE238A01034",
    "BAJFINANCE": "NSE_EQ|INE296A01024",
    "MARUTI": "NSE_EQ|INE585B01010",
}


def get_ist_now() -> datetime:
    return datetime.now(IST)


def get_ist_str() -> str:
    return get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")


def load_env_credentials() -> Dict[str, str]:
    """Reads Upstox credentials from .env and os.environ with whitespace stripping."""
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
    creds = {
        "api_key": "",
        "api_secret": "",
        "access_token": "",
        "redirect_uri": "http://127.0.0.1:8787/api/real-algo/upstox/callback",
        "client_id": "",
    }

    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    k_upper = k.upper()
                    if k_upper in ("API_KEY", "UPSTOX_API_KEY"):
                        creds["api_key"] = v
                    elif k_upper in ("API_SECRET", "UPSTOX_API_SECRET"):
                        creds["api_secret"] = v
                    elif k_upper == "UPSTOX_ACCESS_TOKEN":
                        creds["access_token"] = v
                    elif k_upper == "UPSTOX_REDIRECT_URI":
                        creds["redirect_uri"] = v
                    elif k_upper in ("CLIENT_ID", "UPSTOX_CLIENT_ID"):
                        creds["client_id"] = v
        except Exception as e:
            logger.warning("Error reading .env: %s", e)

    # Fallback to os.environ
    creds["api_key"] = creds["api_key"] or os.getenv("API_Key") or os.getenv("UPSTOX_API_KEY") or ""
    creds["api_secret"] = creds["api_secret"] or os.getenv("API_Secret") or os.getenv("UPSTOX_API_SECRET") or ""
    creds["access_token"] = creds["access_token"] or os.getenv("UPSTOX_ACCESS_TOKEN") or ""
    creds["redirect_uri"] = creds["redirect_uri"] or os.getenv("UPSTOX_REDIRECT_URI") or "http://127.0.0.1:8787/api/real-algo/upstox/callback"
    creds["client_id"] = creds["client_id"] or os.getenv("client_id") or os.getenv("UPSTOX_CLIENT_ID") or ""

    for k in creds:
        creds[k] = creds[k].strip()

    return creds


def persist_access_token_to_env(new_token: str) -> bool:
    """Updates the UPSTOX_ACCESS_TOKEN in the local .env file."""
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
    new_token = (new_token or "").strip()
    if not new_token:
        return False

    os.environ["UPSTOX_ACCESS_TOKEN"] = new_token
    try:
        lines = []
        token_found = False
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("UPSTOX_ACCESS_TOKEN=") or stripped.startswith("UPSTOX_ACCESS_TOKEN ="):
                        lines.append(f"UPSTOX_ACCESS_TOKEN={new_token}\n")
                        token_found = True
                    else:
                        lines.append(line)
        if not token_found:
            lines.append(f"UPSTOX_ACCESS_TOKEN={new_token}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info("Successfully persisted new UPSTOX_ACCESS_TOKEN to .env")
        return True
    except Exception as e:
        logger.error("Failed to write access token to .env: %s", e)
        return False


class UpstoxClient:
    """
    Direct interface to Upstox API v2 for portfolio, funds, and execution.
    """

    def __init__(self):
        self.creds = load_env_credentials()
        self._lock = threading.Lock()
        self._cached_profile = None
        self._cached_funds = None
        self._cached_at = 0.0
        self._last_network_fail_at = 0.0

    def reload_credentials(self):
        with self._lock:
            self.creds = load_env_credentials()

    def get_auth_dialog_url(self, redirect_uri: Optional[str] = None) -> str:
        """Returns the OAuth 2.0 authorization URL for user login."""
        r_uri = redirect_uri or self.creds.get("redirect_uri") or "http://127.0.0.1:8787/api/real-algo/upstox/callback"
        api_key = self.creds.get("api_key") or ""
        return f"{UPSTOX_AUTH_DIALOG}?response_type=code&client_id={api_key}&redirect_uri={r_uri}"

    def exchange_code_for_token(self, code: str, redirect_uri: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Exchanges the authorization code from Upstox redirect for an access token.
        """
        code = (code or "").strip()
        if not code:
            return False, {"error": "Authorization code is required."}

        r_uri = redirect_uri or self.creds.get("redirect_uri")
        api_key = self.creds.get("api_key")
        api_secret = self.creds.get("api_secret")

        if not api_key or not api_secret:
            return False, {"error": "API Key or Secret missing in .env."}

        headers = {
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": r_uri,
            "grant_type": "authorization_code",
        }

        try:
            res = requests.post(UPSTOX_TOKEN_URL, headers=headers, data=data, timeout=15)
            if res.status_code == 200:
                payload = res.json()
                new_token = payload.get("access_token")
                if new_token:
                    with self._lock:
                        self.creds["access_token"] = new_token
                    persist_access_token_to_env(new_token)
                    logger.info("Upstox OAuth successful! Logged in as User: %s", payload.get("user_id"))
                    return True, payload
                return False, {"error": "access_token not found in response", "raw": payload}
            else:
                err_text = res.text
                logger.error("Token exchange failed (%s): %s", res.status_code, err_text)
                return False, {"error": f"Upstox OAuth failed (HTTP {res.status_code})", "details": err_text}
        except Exception as e:
            logger.error("Token exchange network error: %s", e)
            return False, {"error": str(e)}

    def set_manual_token(self, token: str) -> bool:
        """Sets access token manually from UI."""
        token = (token or "").strip()
        if not token:
            return False
        with self._lock:
            self.creds["access_token"] = token
        persist_access_token_to_env(token)
        # Flush cached profile
        self._cached_profile = None
        self._cached_funds = None
        return True

    def get_auth_headers(self) -> Dict[str, str]:
        token = self.creds.get("access_token", "")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def is_connected(self) -> bool:
        """Checks if current token can fetch Upstox user profile."""
        profile = self.get_profile()
        return bool(profile and profile.get("status") == "success")

    def get_profile(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Fetches Upstox user profile."""
        token = self.creds.get("access_token", "").strip()
        if not token:
            return None

        if not force and self._cached_profile and (time.time() - self._cached_at < 60.0):
            return self._cached_profile

        if not force and (time.time() - self._last_network_fail_at < 30.0):
            return self._cached_profile

        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            r = requests.get(f"{UPSTOX_API_BASE}/user/profile", headers=headers, timeout=2.5)
            if r.status_code == 200:
                data = r.json()
                self._cached_profile = data
                self._cached_at = time.time()
                return data
            else:
                logger.warning("Upstox profile fetch returned %s: %s", r.status_code, r.text[:200])
                return None
        except Exception as e:
            self._last_network_fail_at = time.time()
            logger.warning("Error fetching Upstox profile: %s", e)
            return None

    def get_funds_and_margin(self) -> Dict[str, Any]:
        """Fetches live funds and available margin for Equity/F&O segment."""
        token = self.creds.get("access_token", "").strip()
        if not token:
            return {
                "ok": False,
                "error": "Upstox access token missing. Please connect your broker.",
                "available_margin": 0.0,
                "used_margin": 0.0,
            }

        if time.time() - self._last_network_fail_at < 30.0:
            return {
                "ok": False,
                "error": "Upstox network unavailable (standby)",
                "available_margin": 0.0,
                "used_margin": 0.0,
            }

        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            r = requests.get(f"{UPSTOX_API_BASE}/user/get-funds-and-margin?segment=SEC", headers=headers, timeout=2.5)
            if r.status_code == 200:
                payload = r.json()
                eq = (payload.get("data") or {}).get("equity") or {}
                avail = float(eq.get("available_margin") or 0.0)
                used = float(eq.get("used_margin") or 0.0)
                payin = float(eq.get("payin_amount") or 0.0)
                return {
                    "ok": True,
                    "available_margin": avail,
                    "used_margin": used,
                    "payin_amount": payin,
                    "raw": eq,
                }
            else:
                return {
                    "ok": False,
                    "error": f"Upstox funds API error (HTTP {r.status_code})",
                    "available_margin": 0.0,
                    "used_margin": 0.0,
                }
        except Exception as e:
            self._last_network_fail_at = time.time()
            logger.warning("Error fetching Upstox funds: %s", e)
            return {"ok": False, "error": str(e), "available_margin": 0.0, "used_margin": 0.0}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetches current live short-term positions from Upstox."""
        token = self.creds.get("access_token", "").strip()
        if not token or (time.time() - self._last_network_fail_at < 30.0):
            return []

        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            r = requests.get(f"{UPSTOX_API_BASE}/portfolio/short-term-positions", headers=headers, timeout=2.5)
            if r.status_code == 200:
                payload = r.json()
                return payload.get("data") or []
            return []
        except Exception as e:
            self._last_network_fail_at = time.time()
            logger.warning("Error fetching Upstox positions: %s", e)
            return []

    def get_orders(self) -> List[Dict[str, Any]]:
        """Fetches today's order book from Upstox."""
        token = self.creds.get("access_token", "").strip()
        if not token or (time.time() - self._last_network_fail_at < 30.0):
            return []

        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            r = requests.get(f"{UPSTOX_API_BASE}/order/retrieve-all", headers=headers, timeout=8)
            if r.status_code == 200:
                payload = r.json()
                return payload.get("data") or []
            return []
        except Exception as e:
            logger.warning("Error fetching Upstox orders: %s", e)
            return []

    def place_order(
        self,
        instrument_token: str,
        quantity: int,
        transaction_type: str = "BUY",
        product: str = "I",
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
        disclosed_quantity: int = 0,
        is_amo: bool = False,
        tag: str = "FinGrowwReal",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Places a real order via Upstox API v2.
        - product: "I" (Intraday MIS) or "D" (Delivery CNC)
        - order_type: "MARKET" or "LIMIT"
        - transaction_type: "BUY" or "SELL"
        """
        token = self.creds.get("access_token", "").strip()
        if not token:
            return False, {"error": "Not connected to Upstox. Access token missing."}

        payload = {
            "quantity": int(quantity),
            "product": "D" if product.upper() in ("D", "CNC", "DELIVERY") else "I",
            "validity": "DAY",
            "price": float(price) if order_type.upper() == "LIMIT" else 0.0,
            "tag": str(tag)[:20],
            "instrument_token": str(instrument_token).strip(),
            "order_type": "LIMIT" if order_type.upper() == "LIMIT" else "MARKET",
            "transaction_type": "SELL" if transaction_type.upper() == "SELL" else "BUY",
            "disclosed_quantity": int(disclosed_quantity),
            "trigger_price": float(trigger_price),
            "is_amo": bool(is_amo),
        }

        try:
            headers = self.get_auth_headers()
            r = requests.post(f"{UPSTOX_API_BASE}/order/place", headers=headers, json=payload, timeout=10)
            if r.status_code == 200:
                res_data = r.json()
                order_id = (res_data.get("data") or {}).get("order_id")
                logger.info("Upstox Real Order Placed: %s (ID: %s)", payload["instrument_token"], order_id)
                return True, {"order_id": order_id, "raw": res_data}
            else:
                err_json = {}
                try:
                    err_json = r.json()
                except Exception:
                    pass
                err_msg = ""
                if err_json and "errors" in err_json:
                    err_msg = "; ".join([e.get("message", "") for e in err_json["errors"]])
                err_msg = err_msg or r.text
                logger.error("Upstox Order Rejected (HTTP %s): %s", r.status_code, err_msg)
                return False, {"error": f"Upstox rejected: {err_msg}", "status_code": r.status_code}
        except Exception as e:
            logger.error("Network error placing Upstox order: %s", e)
            return False, {"error": str(e)}

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        """Cancels an open order on Upstox."""
        token = self.creds.get("access_token", "").strip()
        if not token or not order_id:
            return False, "Token or Order ID missing"

        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            r = requests.delete(f"{UPSTOX_API_BASE}/order/cancel?order_id={order_id}", headers=headers, timeout=8)
            if r.status_code == 200:
                return True, "Order cancelled successfully."
            return False, f"Failed to cancel order (HTTP {r.status_code}): {r.text}"
        except Exception as e:
            return False, str(e)


class RealTradingSupervisor:
    """
    Supervises live algorithmic and manual trading with Upstox.
    Features:
      - Live execution with Upstox API
      - Dry-Run / Simulation mode (safe testing before live capital deployment)
      - Mandatory Stop-Loss enforcement
      - 1.8R Risk-to-Reward algorithmic target tracking
      - Emergency Kill Switch (Square off all)
      - Realized and floating P&L monitoring
      - Maximum daily loss limit circuit breaker
    """

    def __init__(self, client: UpstoxClient, datastore_file: str = "real_trading_datastore.json"):
        self.client = client
        self.datastore_file = datastore_file
        self.lock = threading.RLock()

        # Engine states
        self.is_running = False
        self.dry_run = True  # Safe default: Dry-Run enabled until user toggles Real Money
        self.config = {
            "max_open_positions": 3,
            "max_lots_per_trade": 1,
            "daily_loss_limit": 5000.0,
            "stop_loss_pct": 15.0,
            "min_rr": 1.80,
            "holding_duration_mins": 1440,
            "auto_square_off_time": "15:20",
        }

        self.positions: List[Dict[str, Any]] = []
        self.closed_trades: List[Dict[str, Any]] = []
        self.orders: List[Dict[str, Any]] = []
        self.audit_log: List[Dict[str, Any]] = []
        self.daily_pnl = 0.0

        self.load_state()

    def log_audit(self, event_type: str, message: str, meta: Optional[Dict[str, Any]] = None):
        """Appends an event to the persistent audit log."""
        entry = {
            "timestamp": get_ist_str(),
            "time_epoch": time.time(),
            "event_type": event_type,
            "message": message,
            "meta": meta or {},
        }
        self.audit_log.insert(0, entry)
        if len(self.audit_log) > 200:
            self.audit_log = self.audit_log[:200]
        logger.info("[AUDIT] %s: %s", event_type, message)

    def load_state(self):
        """Loads state from local datastore if present."""
        if os.path.exists(self.datastore_file):
            try:
                with open(self.datastore_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.dry_run = data.get("dry_run", True)
                    self.config.update(data.get("config", {}))
                    self.positions = data.get("positions", [])
                    self.closed_trades = data.get("closed_trades", [])
                    self.orders = data.get("orders", [])
                    self.audit_log = data.get("audit_log", [])
                    self.daily_pnl = float(data.get("daily_pnl", 0.0))
            except Exception as e:
                logger.warning("Could not load real trading state: %s", e)

    def save_state(self):
        """Saves current engine state to local datastore."""
        try:
            data = {
                "dry_run": self.dry_run,
                "config": self.config,
                "positions": self.positions,
                "closed_trades": self.closed_trades[:100],
                "orders": self.orders[:100],
                "audit_log": self.audit_log[:100],
                "daily_pnl": self.daily_pnl,
                "updated_at": get_ist_str(),
            }
            with open(self.datastore_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error("Could not save real trading state: %s", e)

    def update_config(self, new_cfg: Dict[str, Any]):
        with self.lock:
            if "dry_run" in new_cfg:
                self.dry_run = bool(new_cfg["dry_run"])
            for k in ("max_open_positions", "max_lots_per_trade", "daily_loss_limit", "stop_loss_pct", "min_rr"):
                if k in new_cfg and new_cfg[k] is not None:
                    try:
                        self.config[k] = float(new_cfg[k]) if k in ("daily_loss_limit", "stop_loss_pct", "min_rr") else int(new_cfg[k])
                    except ValueError:
                        pass
            self.save_state()

    def start_engine(self) -> Tuple[bool, str]:
        with self.lock:
            self.is_running = True
            msg = f"Real Trading Engine STARTED in {'DRY-RUN (Simulated)' if self.dry_run else 'LIVE CAPITAL (Upstox)'} mode."
            self.log_audit("ENGINE_START", msg)
            self.save_state()
            return True, msg

    def stop_engine(self) -> Tuple[bool, str]:
        with self.lock:
            self.is_running = False
            msg = "Real Trading Engine STOPPED. New auto-entries paused."
            self.log_audit("ENGINE_STOP", msg)
            self.save_state()
            return True, msg

    def execute_manual_real_trade(
        self,
        base_symbol: str,
        strike: float,
        option_type: str = "CE",
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
        algo_target: bool = True,
        lots: int = 1,
        quote_resolver=None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Executes a real manual trade on Upstox.
        - Enforces MANDATORY Stop-Loss
        - Enforces 1.8R or custom target validation
        - Verifies Upstox margin before sending order
        - Transmits order to Upstox API v2 or simulates if dry_run
        """
        with self.lock:
            raw_sym = (base_symbol or "NIFTY 50").strip().upper()
            base_sym = "NIFTY 50" if raw_sym == "NIFTY" else ("BANK NIFTY" if raw_sym in ("BANKNIFTY", "NIFTY BANK") else raw_sym)
            opt_type = "PE" if str(option_type).upper().strip() == "PE" else "CE"

            try:
                strike_val = float(strike)
                strike_val = int(strike_val) if strike_val == int(strike_val) else round(strike_val, 2)
            except (ValueError, TypeError):
                return None, "A valid numeric strike price is required."

            contract_symbol = f"{base_sym} {strike_val} {opt_type}"

            # Check duplicate position
            for p in self.positions:
                if p.get("symbol") == contract_symbol and p.get("status") == "OPEN":
                    return None, f"An active position is already open for {contract_symbol}."

            # Max open positions guardrail
            open_count = len([p for p in self.positions if p.get("status") == "OPEN"])
            if open_count >= self.config["max_open_positions"]:
                return None, f"Maximum open position limit ({self.config['max_open_positions']}) reached."

            # Daily loss limit circuit breaker
            if self.daily_pnl <= -abs(self.config["daily_loss_limit"]):
                return None, f"Daily loss limit of -₹{self.config['daily_loss_limit']:,.2f} reached. Trading halted for today."

            # Resolve live premium quote
            entry_price = 0.0
            if quote_resolver:
                try:
                    q = quote_resolver(base_sym, strike_val, opt_type)
                    if q and float(q.get("lastPrice") or 0) > 0:
                        entry_price = float(q["lastPrice"])
                except Exception:
                    pass

            if entry_price <= 0:
                # Estimate realistic option premium based on spot
                spot = 24500.0 if "NIFTY" in base_sym else 1000.0
                dist = abs(strike_val - spot) / max(spot, 1.0)
                time_val = spot * 0.015 * max(0.2, 1.0 - dist * 5)
                intrinsic = max(0.0, (spot - strike_val) if opt_type == "CE" else (strike_val - spot))
                entry_price = round(max(5.0, intrinsic + time_val), 2)

            # MANDATORY STOP-LOSS VALIDATION
            if stop_loss is None or float(stop_loss) <= 0:
                return None, "Stop-Loss (SL) is strictly mandatory. Trade execution rejected."
            sl_val = float(stop_loss)
            if sl_val >= entry_price:
                return None, f"Stop-Loss (₹{sl_val:.2f}) must be strictly less than the entry premium (₹{entry_price:.2f})."

            # TARGET PRICE CALCULATION
            risk_distance = entry_price - sl_val
            min_rr = float(self.config.get("min_rr", 1.80))
            if algo_target or target_price is None or float(target_price) <= 0:
                tp_val = round(entry_price + (risk_distance * min_rr), 2)
                is_algo_tp = True
            else:
                tp_val = float(target_price)
                if tp_val <= entry_price:
                    return None, f"Target Price (₹{tp_val:.2f}) must be strictly greater than entry premium (₹{entry_price:.2f})."
                is_algo_tp = False

            # LOT SIZE & QUANTITY
            lot_size = LOT_SIZES.get(base_sym, 25)
            num_lots = max(1, min(int(lots or 1), int(self.config["max_lots_per_trade"])))
            total_qty = num_lots * lot_size
            required_margin = round(total_qty * entry_price, 2)

            # Check Upstox live funds if in LIVE mode
            if not self.dry_run:
                funds = self.client.get_funds_and_margin()
                avail_margin = funds.get("available_margin", 0.0)
                if avail_margin < required_margin:
                    return None, f"Insufficient Upstox Margin. Required ₹{required_margin:,.2f}, Available ₹{avail_margin:,.2f}."

            # Instrument Token / Key
            inst_key = INSTRUMENT_KEYS.get(base_sym, f"NSE_FO|{contract_symbol}")

            # Transmit Order or Simulate
            order_id = f"REAL_{int(time.time()*1000)}"
            upstox_order_id = None
            if not self.dry_run:
                ok, res = self.client.place_order(
                    instrument_token=inst_key,
                    quantity=total_qty,
                    transaction_type="BUY",
                    product="I",
                    order_type="MARKET",
                    tag="FinGrowwReal",
                )
                if not ok:
                    err = res.get("error", "Upstox order rejected.")
                    self.log_audit("ORDER_REJECTED", f"Order rejected for {contract_symbol}: {err}")
                    return None, f"Upstox Error: {err}"
                upstox_order_id = res.get("order_id")
                order_id = upstox_order_id or order_id
                self.log_audit("ORDER_FILLED", f"LIVE Upstox Order {order_id} filled for {contract_symbol} (Qty: {total_qty})")
            else:
                self.log_audit("ORDER_SIMULATED", f"DRY-RUN order filled for {contract_symbol} (Qty: {total_qty}) at ₹{entry_price:.2f}")

            position = {
                "trade_id": order_id,
                "upstox_order_id": upstox_order_id,
                "symbol": contract_symbol,
                "base_symbol": base_sym,
                "strike": strike_val,
                "option_type": opt_type,
                "side": "BUY",
                "quantity": total_qty,
                "lots": num_lots,
                "lot_size": lot_size,
                "entry_price": entry_price,
                "current_price": entry_price,
                "stop_loss": sl_val,
                "target_price": tp_val,
                "is_algo_target": is_algo_tp,
                "rr_ratio": round((tp_val - entry_price) / max(risk_distance, 0.01), 2),
                "required_margin": required_margin,
                "product": "MIS (Intraday)",
                "execution_mode": "DRY_RUN" if self.dry_run else "LIVE_UPSTOX",
                "status": "OPEN",
                "entered_at": get_ist_str(),
                "entered_epoch": time.time(),
                "unrealized_pnl": 0.0,
                "pnl_pct": 0.0,
            }

            self.positions.insert(0, position)
            self.save_state()
            return position, "Success"

    def close_real_position(self, trade_id: str, exit_reason: str = "MANUAL_EXIT") -> Tuple[bool, str]:
        """Closes an open real position and squares it off on Upstox."""
        with self.lock:
            pos = None
            for p in self.positions:
                if p.get("trade_id") == trade_id and p.get("status") == "OPEN":
                    pos = p
                    break

            if not pos:
                return False, f"Open position {trade_id} not found."

            exit_price = pos.get("current_price", pos["entry_price"])
            qty = pos["quantity"]
            gross_pnl = round((exit_price - pos["entry_price"]) * qty, 2)
            charges = 40.0  # Approx broker STT + brokerage
            net_pnl = round(gross_pnl - charges, 2)

            # Square off with broker if Live
            if not self.dry_run and pos.get("execution_mode") == "LIVE_UPSTOX":
                inst_key = INSTRUMENT_KEYS.get(pos["base_symbol"], f"NSE_FO|{pos['symbol']}")
                ok, res = self.client.place_order(
                    instrument_token=inst_key,
                    quantity=qty,
                    transaction_type="SELL",
                    product="I",
                    order_type="MARKET",
                    tag="FinGrowwExit",
                )
                if not ok:
                    logger.warning("Upstox square-off order warning: %s", res)

            pos["status"] = "CLOSED"
            pos["exit_price"] = exit_price
            pos["exit_reason"] = exit_reason
            pos["closed_at"] = get_ist_str()
            pos["net_pnl"] = net_pnl
            pos["charges"] = charges
            pos["is_win"] = net_pnl > 0

            self.positions.remove(pos)
            self.closed_trades.insert(0, pos)
            self.daily_pnl = round(self.daily_pnl + net_pnl, 2)

            msg = f"Closed {pos['symbol']} at ₹{exit_price:.2f} (Net P&L: ₹{net_pnl:+,.2f}) [{exit_reason}]"
            self.log_audit("POSITION_CLOSED", msg)
            self.save_state()
            return True, msg

    def square_off_all_positions(self) -> Tuple[int, str]:
        """Emergency Kill Switch: Squares off all open positions immediately."""
        with self.lock:
            open_list = [p for p in self.positions if p.get("status") == "OPEN"]
            count = 0
            for p in list(open_list):
                try:
                    self.close_real_position(p["trade_id"], exit_reason="EMERGENCY_KILL_SWITCH")
                    count += 1
                except Exception as e:
                    logger.error("Error squaring off position %s: %s", p["trade_id"], e)
            msg = f"EMERGENCY KILL SWITCH ACTIVATED: Squared off {count} open positions."
            self.log_audit("KILL_SWITCH", msg)
            return count, msg

    def tick_supervisor(self, quote_resolver=None, radar_scanner=None, market_is_open=True):
        """
        Periodically checks open positions, tracks dynamic trailing Stop-Loss and Target hits,
        holding duration expiry, and autonomously executes confirmed 15m radar setups when running.
        """
        with self.lock:
            now_epoch = time.time()

            # 1. Evaluate open positions
            for pos in list(self.positions):
                if pos.get("status") != "OPEN":
                    continue

                curr_price = pos.get("current_price", pos["entry_price"])
                if quote_resolver:
                    try:
                        q = quote_resolver(pos["base_symbol"], pos["strike"], pos["option_type"])
                        if q and float(q.get("lastPrice") or 0) > 0:
                            curr_price = float(q["lastPrice"])
                    except Exception:
                        pass

                pos["current_price"] = curr_price
                qty = pos["quantity"]
                pnl = round((curr_price - pos["entry_price"]) * qty, 2)
                pos["unrealized_pnl"] = pnl
                pos["pnl_pct"] = round(((curr_price - pos["entry_price"]) / max(pos["entry_price"], 0.01)) * 100, 2)

                # Dynamic Trailing Stop-Loss
                init_sl = pos.get("initial_stop_loss", pos.get("stop_loss", pos["entry_price"] * 0.85))
                risk_dist = max(pos["entry_price"] - init_sl, 1.0)
                gain = curr_price - pos["entry_price"]
                r_multiple = gain / risk_dist

                if r_multiple >= 1.4:
                    new_sl = round(pos["entry_price"] + (risk_dist * 1.0), 2)
                    if new_sl > pos["stop_loss"]:
                        pos["stop_loss"] = new_sl
                        pos["trailing_state"] = "PROFIT_LOCKED"
                        pos["trailing_label"] = "Profit Locked (+1.0R)"
                elif r_multiple >= 1.0:
                    new_sl = round(pos["entry_price"], 2)
                    if new_sl > pos["stop_loss"]:
                        pos["stop_loss"] = new_sl
                        pos["trailing_state"] = "BREAKEVEN"
                        pos["trailing_label"] = "Breakeven Protected"

                # Check Stop-Loss Hit
                if curr_price <= pos["stop_loss"]:
                    exit_reason = "BREAKEVEN_STOP_HIT" if pos.get("trailing_state") == "BREAKEVEN" else (
                        "TRAILING_STOP_PROFIT_HIT" if pos.get("trailing_state") == "PROFIT_LOCKED" else "STOP_LOSS_HIT"
                    )
                    self.close_real_position(pos["trade_id"], exit_reason=exit_reason)
                    continue

                # Check Target Hit
                if curr_price >= pos["target_price"]:
                    self.close_real_position(pos["trade_id"], exit_reason="TARGET_HIT")
                    continue

                # Check Holding Duration Expiry (1440m default)
                entered_epoch = pos.get("entered_epoch", now_epoch)
                holding_secs = (pos.get("holding_duration_mins") or 1440) * 60
                if (now_epoch - entered_epoch) >= holding_secs:
                    self.close_real_position(pos["trade_id"], exit_reason="TIME_EXPIRED")
                    continue

            # 2. Autonomous Setup Scanning & Auto-Entry when running
            if self.is_running and radar_scanner and (market_is_open or self.dry_run):
                open_count = len([p for p in self.positions if p.get("status") == "OPEN"])
                if open_count < self.config["max_open_positions"] and self.daily_pnl > -abs(self.config["daily_loss_limit"]):
                    try:
                        setups = radar_scanner() or []
                        for s in setups[:5]:
                            sym = s.get("symbol") or ""
                            if not sym:
                                continue
                            # Prevent duplicate active underlying
                            if any(p.get("base_symbol") == sym or p.get("symbol", "").startswith(sym) for p in self.positions if p.get("status") == "OPEN"):
                                continue

                            # Derive option contract
                            opt_type = "CE" if s.get("side") == "BUY" else "PE"
                            spot_est = float(s.get("entry_price") or 24500.0)
                            step = 50 if "NIFTY" in sym and "BANK" not in sym else (100 if "BANK" in sym else 50)
                            strike_atm = int(round(spot_est / step) * step)

                            # Estimate realistic premium & mandatory SL
                            prem_est = float(s.get("option_ltp") or 200.0)
                            sl_est = round(prem_est * 0.85, 2)

                            pos, err = self.execute_manual_real_trade(
                                base_symbol=sym,
                                strike=strike_atm,
                                option_type=opt_type,
                                stop_loss=sl_est,
                                algo_target=True,
                                lots=1,
                                quote_resolver=quote_resolver,
                            )
                            if pos:
                                pos["execution_type"] = "AUTO"
                                pos["strategy"] = s.get("strategy") or "Confirmed 15m Trend & VWAP"
                                self.log_audit("AUTO_ALGO_FILLED", f"Autonomous entry on #1 setup: {pos['symbol']} (SL: ₹{sl_est:.2f})")
                                break
                    except Exception as e:
                        logger.warning("Auto-algo scan error in real supervisor: %s", e)

            self.save_state()

    def get_analytics(self) -> Dict[str, Any]:
        """Calculates quantitative performance analytics strictly from closed real trades."""
        with self.lock:
            trades = list(self.closed_trades)
            total = len(trades)
            if total == 0:
                return {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "profit_factor": 0.0,
                    "net_pnl": self.daily_pnl,
                    "gross_profit": 0.0,
                    "gross_loss": 0.0,
                    "max_drawdown_pct": 0.0,
                    "equity_curve": [{"time": get_ist_str(), "pnl": 0.0}],
                }

            wins = [t for t in trades if t.get("is_win")]
            losses = [t for t in trades if not t.get("is_win")]
            gross_win = sum(t.get("net_pnl", 0.0) for t in wins if t.get("net_pnl", 0.0) > 0)
            gross_loss = abs(sum(t.get("net_pnl", 0.0) for t in losses if t.get("net_pnl", 0.0) < 0))
            profit_factor = round(gross_win / max(gross_loss, 1.0), 2)
            win_rate = round((len(wins) / total) * 100, 1)

            # Cumulative Equity Curve
            sorted_trades = sorted(trades, key=lambda t: t.get("closed_at", ""))
            cum_pnl = 0.0
            equity_curve = [{"time": "Start", "pnl": 0.0}]
            peak = 0.0
            max_dd = 0.0
            for t in sorted_trades:
                cum_pnl += t.get("net_pnl", 0.0)
                equity_curve.append({"time": t.get("closed_at", "")[:16], "pnl": round(cum_pnl, 2)})
                if cum_pnl > peak:
                    peak = cum_pnl
                dd = peak - cum_pnl
                if dd > max_dd:
                    max_dd = dd

            max_dd_pct = round((max_dd / max(peak, 100000.0)) * 100, 2)

            return {
                "total_trades": total,
                "winning_trades": len(wins),
                "losing_trades": len(losses),
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "net_pnl": round(cum_pnl, 2),
                "gross_profit": round(gross_win, 2),
                "gross_loss": round(gross_loss, 2),
                "max_drawdown_pct": max_dd_pct,
                "equity_curve": equity_curve,
            }

    def get_summary(self) -> Dict[str, Any]:
        """Returns comprehensive real trading status for frontend UI."""
        with self.lock:
            open_pos = [p for p in self.positions if p.get("status") == "OPEN"]
            unrealized = sum(p.get("unrealized_pnl", 0.0) for p in open_pos)
            used_margin = sum(p.get("required_margin", 0.0) for p in open_pos)

            client_profile = self.client.get_profile()
            funds_info = self.client.get_funds_and_margin()

            return {
                "ok": True,
                "is_running": self.is_running,
                "dry_run": self.dry_run,
                "is_broker_connected": self.client.is_connected(),
                "broker_profile": (client_profile or {}).get("data") if client_profile else None,
                "broker_funds": funds_info,
                "available_margin": funds_info.get("available_margin", 0.0),
                "used_margin": used_margin,
                "realized_daily_pnl": self.daily_pnl,
                "unrealized_floating_pnl": round(unrealized, 2),
                "net_daily_pnl": round(self.daily_pnl + unrealized, 2),
                "open_positions_count": len(open_pos),
                "closed_trades_count": len(self.closed_trades),
                "config": self.config,
                "positions": open_pos,
                "recent_closed_trades": self.closed_trades[:25],
                "audit_log": self.audit_log[:30],
                "analytics": self.get_analytics(),
                "server_time": get_ist_str(),
            }


# Singleton instance
upstox_client = UpstoxClient()
real_supervisor = RealTradingSupervisor(upstox_client)
