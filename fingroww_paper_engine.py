#!/usr/bin/env python3
"""
FinGroww AI-Powered Automated Paper Trading Engine
=================================================
Automated execution, position sizing, technical analysis, risk management,
and real-time monitoring for Indian Equities, Futures, and Options.

Key Capabilities:
- Multi-instrument support: Stocks (Equity), Stock Futures, Index Futures, Index Options (CE/PE).
- Auto entries require confirmed NSE market status, a fresh NSE cash-equity quote, and a completed-candle 15m EMA/VWAP/ATR setup.
- Dynamic holding duration: 1m, 5m, 15m, 30m, 1h, or custom duration with automated time exit.
- Institutional Risk Supervision: Max risk per trade, daily max loss limit, max open positions,
  realistic slippage, Indian brokerage, STT, exchange turnover fees, and GST.
- Persistent session state: Syncs with MongoDB Atlas with automatic fallback to local datastore.
"""

import os
import time
import math
import uuid
import random
import json
import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone, timedelta
from functools import wraps

# IST Timezone helper
IST_OFFSET = timedelta(hours=5, minutes=30)

def get_ist_now():
    return datetime.now(timezone.utc) + IST_OFFSET

def get_ist_str():
    return get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

def format_duration_display(seconds):
    """Formats duration in seconds into human-readable minutes, hours, days, weeks, or months."""
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    mins = seconds // 60
    if mins < 60:
        secs = seconds % 60
        return f"{mins}m {secs}s" if secs > 0 else f"{mins}m"
    hours = mins // 60
    if hours < 24:
        rem_mins = mins % 60
        return f"{hours}h {rem_mins}m" if rem_mins > 0 else f"{hours}h"
    days = hours // 24
    if days < 7:
        rem_hours = hours % 24
        return f"{days}d {rem_hours}h" if rem_hours > 0 else f"{days}d"
    weeks = days // 7
    if days < 30:
        rem_days = days % 7
        return f"{weeks}w {rem_days}d" if rem_days > 0 else f"{weeks}w"
    months = days // 30
    rem_days = days % 30
    return f"{months}mo {rem_days}d" if rem_days > 0 else f"{months}mo"

# F&O Lot Sizes for Indian Instruments
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
    "ICICIBANK": 700,
    "INFY": 400,
    "TCS": 175,
    "SBIN": 750,
    "TATAMOTORS": 700,
    "BHARTIARTL": 475,
    "ITC": 1600,
    "LT": 150,
    "AXISBANK": 625,
    "KOTAKBANK": 400,
    "MARUTI": 50,
    "BAJFINANCE": 125,
}

# Supported Watchlist Universe
UNIVERSE = [
    {"symbol": "NIFTY 50", "name": "Nifty 50 Index", "type": "INDEX", "default_price": 24850.0},
    {"symbol": "BANK NIFTY", "name": "Bank Nifty Index", "type": "INDEX", "default_price": 53200.0},
    {"symbol": "FINNIFTY", "name": "FinNifty Index", "type": "INDEX", "default_price": 24200.0},
    {"symbol": "RELIANCE", "name": "Reliance Industries", "type": "STOCK", "default_price": 1285.0},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "type": "STOCK", "default_price": 685.0},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "type": "STOCK", "default_price": 1390.0},
    {"symbol": "INFY", "name": "Infosys Ltd", "type": "STOCK", "default_price": 1175.0},
    {"symbol": "TCS", "name": "Tata Consultancy Services", "type": "STOCK", "default_price": 2510.0},
    {"symbol": "SBIN", "name": "State Bank of India", "type": "STOCK", "default_price": 948.0},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd", "type": "STOCK", "default_price": 1220.0},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "type": "STOCK", "default_price": 1980.0},
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "type": "STOCK", "default_price": 3680.0},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "type": "STOCK", "default_price": 920.0},
]


def _is_fresh_nse_quote(quote, max_age_seconds=120):
    if not isinstance(quote, dict) or quote.get("source") != "NSE":
        return False
    try:
        price = float(quote.get("lastPrice"))
        fetched_at = float(quote.get("fetched_at", time.time()))
        exchange_timestamp = float(quote.get("exchange_timestamp", fetched_at))
    except (TypeError, ValueError):
        return False
    if price <= 0:
        return False
    now = time.time()
    return (
        0 <= now - fetched_at <= max_age_seconds
        and (exchange_timestamp <= 0 or 0 <= now - exchange_timestamp <= max(max_age_seconds, 86400))
    )


def _ema(values, period):
    if len(values) < period:
        return []
    multiplier = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append((value * multiplier) + (result[-1] * (1.0 - multiplier)))
    return result


def _atr(candles, period=14):
    if len(candles) <= period:
        return None
    true_ranges = []
    for index in range(1, len(candles)):
        current = candles[index]
        previous_close = float(candles[index - 1]["c"])
        true_ranges.append(max(
            float(current["h"]) - float(current["l"]),
            abs(float(current["h"]) - previous_close),
            abs(float(current["l"]) - previous_close),
        ))
    return sum(true_ranges[-period:]) / period


def _session_vwap(candles):
    session_date = datetime.fromtimestamp(
        int(candles[-1]["t"]) / 1000, timezone.utc
    ).astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    session_candles = []
    for candle in candles:
        candle_date = datetime.fromtimestamp(
            int(candle["t"]) / 1000, timezone.utc
        ).astimezone(timezone(timedelta(hours=5, minutes=30))).date()
        if candle_date == session_date:
            session_candles.append(candle)
    volume_sum = sum(float(candle.get("v") or 0) for candle in session_candles)
    if volume_sum <= 0:
        return None
    return sum(
        ((float(candle["h"]) + float(candle["l"]) + float(candle["c"])) / 3)
        * float(candle.get("v") or 0)
        for candle in session_candles
    ) / volume_sum


class PaperTradeCostModel:
    """Calculates realistic Indian brokerage, STT, turnover charges, and slippage."""
    
    @classmethod
    def calculate_charges(cls, instrument_type, side, price, quantity):
        turnover = price * quantity
        if turnover <= 0:
            return {"brokerage": 0.0, "stt": 0.0, "exchange_txn": 0.0, "sebi": 0.0, "stamp_duty": 0.0, "gst": 0.0, "total": 0.0}

        # 1. Brokerage
        if instrument_type == "EQUITY":
            # 0.03% or ₹20 whichever is lower (Zerodha / Angel One model)
            brokerage = min(20.0, round(turnover * 0.0003, 2))
        else: # Futures or Options
            brokerage = 20.0 # flat ₹20 per executed order

        # 2. STT / CTT
        stt = 0.0
        if instrument_type == "EQUITY":
            stt = round(turnover * 0.00025, 2) if side == "SELL" else 0.0 # Intraday STT 0.025% on sell
        elif "FUTURE" in instrument_type:
            stt = round(turnover * 0.000125, 2) if side == "SELL" else 0.0 # 0.0125% on sell
        elif "OPTION" in instrument_type:
            stt = round(turnover * 0.000625, 2) if side == "SELL" else 0.0 # 0.0625% on sell of premium

        # 3. Exchange Turnover Charges (NSE: ~0.00325% on equity, ~0.0019% futures, ~0.05% options premium)
        if "OPTION" in instrument_type:
            exchange_txn = round(turnover * 0.0005, 2)
        elif "FUTURE" in instrument_type:
            exchange_txn = round(turnover * 0.000019, 2)
        else:
            exchange_txn = round(turnover * 0.0000325, 2)

        # 4. SEBI turnover fee (₹10 per crore = 0.0001%)
        sebi = round(turnover * 0.000001, 2)

        # 5. Stamp duty (on buy side only)
        stamp_duty = 0.0
        if side == "BUY":
            if instrument_type == "EQUITY":
                stamp_duty = round(turnover * 0.00003, 2)
            elif "FUTURE" in instrument_type:
                stamp_duty = round(turnover * 0.00002, 2)
            elif "OPTION" in instrument_type:
                stamp_duty = round(turnover * 0.00003, 2)

        # 6. GST: 18% on (Brokerage + Exchange Txn + SEBI)
        taxable_services = brokerage + exchange_txn + sebi
        gst = round(taxable_services * 0.18, 2)

        total_charges = round(brokerage + stt + exchange_txn + sebi + stamp_duty + gst, 2)
        return {
            "brokerage": brokerage,
            "stt": stt,
            "exchange_txn": exchange_txn,
            "sebi": sebi,
            "stamp_duty": stamp_duty,
            "gst": gst,
            "total": total_charges,
        }

    @classmethod
    def apply_slippage(cls, price, side, instrument_type):
        """Simulates realistic market order slippage (0.02% - 0.04%)."""
        is_opt = "OPTION" in instrument_type
        slippage_pct = random.uniform(0.0005, 0.0015) if is_opt else random.uniform(0.0002, 0.0004)
        if side == "BUY":
            return round(price * (1.0 + slippage_pct), 2)
        else:
            return round(price * (1.0 - slippage_pct), 2)


DATASTORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_datastore.json")

def load_datastore_from_disk():
    """Restores persistent sessions, profiles, positions, and trades from disk."""
    try:
        if os.path.exists(DATASTORE_FILE):
            with open(DATASTORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {
                        "sessions": data.get("sessions", {}),
                        "profiles": data.get("profiles", {}),
                        "positions": data.get("positions", {}),
                        "trades": data.get("trades", {}),
                    }
    except Exception:
        pass
    return {"sessions": {}, "profiles": {}, "positions": {}, "trades": {}}

def save_datastore_to_disk(datastore):
    """Safely writes datastore to disk using an atomic rename operation."""
    try:
        tmp_file = DATASTORE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(datastore, f, indent=2)
        os.replace(tmp_file, DATASTORE_FILE)
    except Exception:
        pass

LOCAL_USER_DATASTORE = load_datastore_from_disk()
if "sessions" not in LOCAL_USER_DATASTORE:
    LOCAL_USER_DATASTORE["sessions"] = {}
if "profiles" not in LOCAL_USER_DATASTORE:
    LOCAL_USER_DATASTORE["profiles"] = {}
if "positions" not in LOCAL_USER_DATASTORE:
    LOCAL_USER_DATASTORE["positions"] = {}
if "trades" not in LOCAL_USER_DATASTORE:
    LOCAL_USER_DATASTORE["trades"] = {}


logger = logging.getLogger(__name__)


def _session_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return wrapped


def _paper_db_path():
    return os.getenv(
        "FINGROWW_PAPER_DB_PATH",
        os.path.join(os.path.dirname(__file__), "data", "paper_trading.db"),
    )


def _connect_paper_db():
    db_path = _paper_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_user_data (
            user_name TEXT PRIMARY KEY,
            session_json TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def _load_local_paper_record(user_name):
    with closing(_connect_paper_db()) as conn:
        with conn:
            row = conn.execute(
                "SELECT session_json, profile_json FROM paper_user_data WHERE user_name = ?",
                (user_name,),
            ).fetchone()
    if not row:
        return None
    return {"session": json.loads(row[0]), "profile": json.loads(row[1])}


def _save_local_paper_record(user_name, session_doc, profile_doc):
    with closing(_connect_paper_db()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO paper_user_data (user_name, session_json, profile_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_name) DO UPDATE SET
                    session_json = excluded.session_json,
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_name,
                    json.dumps(session_doc, separators=(",", ":")),
                    json.dumps(profile_doc, separators=(",", ":")),
                    get_ist_str(),
                ),
            )


def _load_local_paper_profiles():
    with closing(_connect_paper_db()) as conn:
        with conn:
            rows = conn.execute(
                "SELECT profile_json FROM paper_user_data ORDER BY user_name"
            ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _document_updated_at(document):
    return str(document.get("last_updated") or document.get("last_active") or "")


class PaperTradingSession:
    """Manages virtual capital, open positions, closed trade history, and execution state for a user."""

    def __init__(self, user_name="Akshay", session_id=None, config=None, db=None, user_id=None):
        self._state_lock = threading.RLock()
        self.user_name = (user_name or "Akshay").strip()
        stable_user_id = uuid.uuid5(uuid.NAMESPACE_URL, f"fingroww-paper-user:{self.user_name.casefold()}").hex[:12].upper()
        self.user_id = user_id or f"USR-{stable_user_id}"
        self.session_id = session_id or f"PTS-{self.user_name[:4].upper()}-{int(time.time())}"
        self.db = db
        self.status = "IDLE" # IDLE, RUNNING, PAUSED, STOPPED_NEW_TRADES
        self.created_at = get_ist_str()
        self.last_updated = get_ist_str()
        self.last_tick_at = 0

        # Configuration defaults
        self.config = {
            "initial_capital": 100000.0,
            "instruments": ["EQUITY", "INDEX_FUTURES", "INDEX_OPTIONS"],
            "market": "NSE",
            "trading_style": "INTRADAY", # INTRADAY, SCALPING, SWING, POSITIONAL
            "holding_duration_mins": 15, # 1, 5, 15, 30, 60, days, weeks, months
            "risk_profile": "MODERATE", # CONSERVATIVE, MODERATE, AGGRESSIVE
            "max_risk_per_trade_pct": 1.0,
            "daily_loss_limit_inr": 4000.0,
            "max_open_positions": 4,
            "auto_square_off_time": "15:15",
            "auto_stop_on_exit": False, # If True, engine automatically stops after all positions exit
        }
        if config:
            self.config.update(config)

        # Financial Balances
        cap = float(self.config.get("initial_capital", 100000.0))
        self.initial_capital = cap
        self.available_balance = cap
        self.allocated_margin = 0.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.total_pnl = 0.0
        self.total_charges = 0.0
        self.total_slippage = 0.0
        self.account_equity = cap
        self.peak_equity = cap
        self.max_drawdown_inr = 0.0
        self.max_drawdown_pct = 0.0

        # Data stores
        self.positions = []       # Active open trades
        self.closed_trades = []   # Completed trade records
        self.logs = []            # Decision and audit logs
        self.scanned_signals = [] # Recent AI trade setups evaluated

        # Try to restore from database if exists
        self.load_from_db()

        if not self.logs:
            self.log_event("SESSION_INIT", f"Trader profile [{self.user_name}] initialized with Rs.{cap:,.2f} virtual capital.")

    def log_event(self, event_type, message, details=None):
        entry = {
            "id": f"LOG-{int(time.time()*1000)%1000000}",
            "timestamp": get_ist_str(),
            "type": event_type,
            "message": message,
            "details": details or {},
        }
        self.logs.insert(0, entry)
        if len(self.logs) > 150:
            self.logs.pop()

    @_session_locked
    def update_config(self, new_config):
        if not new_config:
            return
        for k in ["instruments", "market", "trading_style", "holding_duration_mins", "risk_profile",
                  "max_risk_per_trade_pct", "daily_loss_limit_inr", "max_open_positions",
                  "auto_stop_on_exit"]:
            if k in new_config:
                self.config[k] = new_config[k]

        # Risk profile adjustments
        rp = self.config.get("risk_profile", "MODERATE")
        if rp == "CONSERVATIVE":
            self.config["max_risk_per_trade_pct"] = 0.5
            self.config["min_rr"] = 2.0
        elif rp == "AGGRESSIVE":
            self.config["max_risk_per_trade_pct"] = 2.0
            self.config["min_rr"] = 1.5
        else: # MODERATE
            self.config["max_risk_per_trade_pct"] = 1.0
            self.config["min_rr"] = 1.8

        self.last_updated = get_ist_str()
        self.log_event("CONFIG_UPDATE", f"Trading configuration updated. Risk profile: {rp}, Max trades: {self.config['max_open_positions']}")

    @_session_locked
    def start(self):
        self.status = "RUNNING"
        self.log_event("SESSION_START", "AI Auto Paper Trading engine started. Autonomous execution active.")

    @_session_locked
    def pause(self):
        self.status = "PAUSED"
        self.log_event("SESSION_PAUSED", "Trading paused. Existing positions remain monitored but no new entries will be taken.")

    @_session_locked
    def resume(self):
        self.status = "RUNNING"
        self.log_event("SESSION_RESUMED", "Trading resumed. Autonomous scanning and entry reactivated.")

    @_session_locked
    def stop_new_trades(self):
        self.status = "STOPPED_NEW_TRADES"
        self.log_event("SESSION_STOP_NEW", "Stopped new trades. Monitoring open positions until target, stop loss, or duration exit.")

    @_session_locked
    def reset(self, initial_capital=None):
        if initial_capital:
            self.config["initial_capital"] = float(initial_capital)
        cap = float(self.config.get("initial_capital", 100000.0))
        self.initial_capital = cap
        self.available_balance = cap
        self.allocated_margin = 0.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.total_pnl = 0.0
        self.total_charges = 0.0
        self.total_slippage = 0.0
        self.account_equity = cap
        self.peak_equity = cap
        self.max_drawdown_inr = 0.0
        self.max_drawdown_pct = 0.0
        self.positions = []
        self.closed_trades = []
        self.status = "IDLE"
        self.log_event("SESSION_RESET", f"Paper trading session reset. Capital restored to ₹{cap:,.2f}.")

    def can_open_new_trade(self):
        """Enforces pre-trade risk supervisor checks."""
        if self.status != "RUNNING":
            return False, f"Session is in {self.status} state."

        ist = get_ist_now()
        cur_mins = ist.hour * 60 + ist.minute
        if ist.weekday() >= 5 or cur_mins < 555 or cur_mins >= 915:
            return False, "New trades are allowed only on NSE weekdays from 09:15 to 15:15 IST."

        # Max open positions check
        max_pos = int(self.config.get("max_open_positions", 4))
        if len(self.positions) >= max_pos:
            return False, f"Maximum concurrent positions reached ({len(self.positions)}/{max_pos})."

        # Daily loss limit check
        daily_loss_limit = float(self.config.get("daily_loss_limit_inr", 4000.0))
        if self.total_pnl <= -daily_loss_limit:
            return False, f"Daily max loss limit ₹{daily_loss_limit:,.2f} breached. New trades halted."

        # Available capital check
        if self.available_balance < 3000.0:
            return False, "Insufficient virtual balance for required margin."

        return True, "All pre-trade risk checks passed."

    @_session_locked
    def execute_trade(self, setup, quote_resolver=None, market_is_open=False):
        """Executes a paper order with realistic slippage, margin allocation, and charges."""
        if not market_is_open:
            return None, "NSE market is closed or its status is unavailable; no trade was opened."
        can_trade, reason = self.can_open_new_trade()
        if not can_trade:
            return None, reason

        sym = setup["symbol"]
        inst_type = setup.get("instrument_type", "EQUITY")
        side = setup.get("side", "BUY")
        raw_entry = float(setup["entry_price"])
        sl = float(setup["stop_loss"])
        tp = float(setup["target_price"])
        holding_duration_mins = float(self.config.get("holding_duration_mins", 15))

        supported_types = ("EQUITY", "INDEX_FUTURES", "INDEX_OPTIONS", "STOCK_FUTURES")
        if side not in ("BUY", "SELL") or inst_type not in supported_types:
            return None, f"Instrument type [{inst_type}] is not supported for auto trading."
        if quote_resolver:
            base_sym = setup.get("base_symbol", sym)
            try:
                live_quote = quote_resolver(base_sym)
            except Exception as exc:
                logger.warning("Live entry quote failed for %s: %s", base_sym, exc)
                return None, f"Could not get a fresh quote for {base_sym}."
            if not _is_fresh_nse_quote(live_quote):
                return None, f"Could not get a fresh quote for {base_sym}; no trade was opened."
            if inst_type == "INDEX_OPTIONS":
                # For options, entry price is the option premium
                raw_entry = float(setup["entry_price"])
                risk_distance = float(setup.get("risk_distance", raw_entry * 0.25))
                reward_risk = float(setup.get("reward_risk", self.config.get("min_rr", 1.8)))
                sl = max(1.0, round(raw_entry - risk_distance, 2))
                tp = round(raw_entry + (risk_distance * reward_risk), 2)
            else:
                raw_entry = float(live_quote["lastPrice"])
                risk_distance = float(setup.get("risk_distance", 0))
                reward_risk = float(setup.get("reward_risk", self.config.get("min_rr", 1.8)))
                if risk_distance <= 0 or reward_risk <= 0:
                    return None, f"Invalid ATR risk levels for {sym}; no trade was opened."
                if side == "BUY":
                    sl = raw_entry - risk_distance
                    tp = raw_entry + (risk_distance * reward_risk)
                else:
                    sl = raw_entry + risk_distance
                    tp = raw_entry - (risk_distance * reward_risk)

        # Check for duplicate open trade on identical symbol
        for pos in self.positions:
            if pos["symbol"] == sym and pos["side"] == side:
                return None, f"Position already active for {sym} {side}."

        # Apply realistic execution slippage
        exec_price = PaperTradeCostModel.apply_slippage(raw_entry, side, inst_type)
        slippage_amt = round(abs(exec_price - raw_entry), 2)

        if quote_resolver:
            if side == "BUY":
                sl = exec_price - risk_distance
                tp = exec_price + (risk_distance * reward_risk)
            else:
                sl = exec_price + risk_distance
                tp = exec_price - (risk_distance * reward_risk)

        if side == "BUY" and not sl < exec_price < tp:
            return None, f"Invalid stop-loss or target relative to live entry for {sym}."
        if side == "SELL" and not tp < exec_price < sl:
            return None, f"Invalid stop-loss or target relative to live entry for {sym}."

        # Risk calculation
        risk_per_unit = abs(exec_price - sl)
        if risk_per_unit <= 0:
            risk_per_unit = max(exec_price * 0.01, 1.0)

        # Position Sizing based on risk profile
        risk_pct = float(self.config.get("max_risk_per_trade_pct", 1.0)) / 100.0
        max_risk_inr = self.initial_capital * risk_pct
        max_qty_by_risk = math.floor(max_risk_inr / risk_per_unit)

        # Max margin allowed for this trade: 35% of current available balance
        max_margin = self.available_balance * 0.35
        lot_size = LOT_SIZES.get(sym.upper(), 1)

        if "FUTURE" in inst_type:
            # Futures intraday MIS margin (~10% in Indian market)
            margin_per_unit = exec_price * 0.10
            max_qty_by_margin = math.floor(max_margin / margin_per_unit) if margin_per_unit > 0 else 0
            raw_lots = math.floor(min(max_qty_by_risk, max_qty_by_margin) / lot_size)
            if raw_lots < 1:
                req_margin = lot_size * margin_per_unit
                if self.available_balance >= req_margin:
                    lots = 1
                else:
                    return None, f"Insufficient margin for 1 lot of {sym} Futures (requires Rs.{req_margin:,.2f}, available Rs.{self.available_balance:,.2f})"
            else:
                lots = raw_lots
            actual_qty = lots * lot_size
            allocated_capital = round(actual_qty * margin_per_unit, 2)
        elif "OPTION" in inst_type:
            # Option buying requires 100% premium margin
            premium = exec_price
            max_qty_by_margin = math.floor(max_margin / premium) if premium > 0 else 0
            raw_lots = math.floor(min(max_qty_by_risk, max_qty_by_margin) / lot_size)
            if raw_lots < 1:
                req_margin = lot_size * premium
                if self.available_balance >= req_margin:
                    lots = 1
                else:
                    return None, f"Insufficient margin for 1 lot of {sym} Options (requires Rs.{req_margin:,.2f}, available Rs.{self.available_balance:,.2f})"
            else:
                lots = raw_lots
            actual_qty = lots * lot_size
            allocated_capital = round(actual_qty * premium, 2)
        else: # EQUITY (Intraday MIS 5x leverage approx)
            margin_per_unit = exec_price * 0.20
            max_qty_by_margin = math.floor(max_margin / margin_per_unit) if margin_per_unit > 0 else 1
            actual_qty = max(1, min(max_qty_by_risk, max_qty_by_margin))
            lots = 1
            allocated_capital = round(actual_qty * margin_per_unit, 2)

        # Entry charges
        entry_costs = PaperTradeCostModel.calculate_charges(inst_type, side, exec_price, actual_qty)
        required_balance = round(allocated_capital + entry_costs["total"], 2)
        if required_balance > self.available_balance:
            return None, (
                f"Insufficient virtual balance. Required ₹{required_balance:,.2f} "
                f"including charges, available ₹{self.available_balance:,.2f}."
            )

        # Margin and entry charges are both unavailable once the order is filled.
        self.available_balance = round(self.available_balance - required_balance, 2)
        self.allocated_margin += allocated_capital
        self.total_charges += entry_costs["total"]
        self.total_slippage += (slippage_amt * actual_qty)

        now_ist = get_ist_now()
        target_exit_dt = now_ist + timedelta(seconds=int(holding_duration_mins * 60))

        trade_id = f"PT-{now_ist.strftime('%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        position = {
            "trade_id": trade_id,
            "symbol": sym,
            "base_symbol": setup.get("base_symbol", sym),
            "name": setup.get("name", sym),
            "instrument_type": inst_type,
            "side": side,
            "entry_time": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
            "entry_timestamp": time.time(),
            "target_exit_time": target_exit_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "target_exit_timestamp": time.time() + (holding_duration_mins * 60),
            "holding_duration_mins": holding_duration_mins,
            "holding_duration_display": format_duration_display(int(holding_duration_mins * 60)),
            "is_intraday": holding_duration_mins <= 375,
            "entry_price": exec_price,
            "original_entry_price": raw_entry,
            "current_price": exec_price,
            "quantity": actual_qty,
            "lots": lots if ("FUTURE" in inst_type or "OPTION" in inst_type) else 1,
            "lot_size": lot_size,
            "allocated_margin": allocated_capital,
            "target_price": tp,
            "stop_loss": sl,
            "risk_reward": round(abs(tp - exec_price) / risk_per_unit, 2),
            "max_risk_inr": round(actual_qty * risk_per_unit, 2),
            "strategy": setup.get("strategy", "AI Quantitative Momentum"),
            "confidence_score": setup.get("confidence_score", 84),
            "signal_rationale": setup.get("rationale"),
            "signal_indicators": setup.get("signal_indicators", {}),
            "market_data_source": setup.get("market_data_source", "MANUAL"),
            "market_data_timestamp": setup.get("market_data_timestamp"),
            "risk_distance": round(risk_per_unit, 4),
            "status": "OPEN",
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0,
            "entry_charges": entry_costs["total"],
            "total_charges": entry_costs["total"],
            "slippage": round(slippage_amt * actual_qty, 2),
            "last_updated": get_ist_str(),
        }

        self.positions.append(position)
        self.log_event("ORDER_FILLED", f"Filled {side} {actual_qty} {sym} ({inst_type}) @ ₹{exec_price:,.2f}. Target: ₹{tp:,.2f}, SL: ₹{sl:,.2f}")
        self._recalculate_equity()
        self.save_to_db()
        return position, "Success"

    @_session_locked
    def update_positions(self, quote_resolver, market_is_open=False):
        """
        Refreshes live market prices for all open positions.
        Checks for Target Hit, Stop-Loss Hit, Holding Duration Expiry, or 15:15 IST Square-Off.
        """
        if not market_is_open:
            return

        now_ts = time.time()
        ist_now = get_ist_now()
        is_eod_square_off = (ist_now.hour == 15 and ist_now.minute >= 20)

        positions_to_close = []

        for pos in self.positions:
            sym = pos.get("base_symbol", pos["symbol"])
            inst_type = pos["instrument_type"]
            side = pos["side"]
            qty = pos["quantity"]
            entry_p = pos["entry_price"]
            tp = pos["target_price"]
            sl = pos["stop_loss"]

            # Fetch fresh market price
            curr_price = None
            if quote_resolver:
                try:
                    q = quote_resolver(sym)
                    if _is_fresh_nse_quote(q):
                        curr_price = float(q["lastPrice"])
                except Exception as exc:
                    logger.warning("Live position quote failed for %s: %s", sym, exc)

            if curr_price is None or curr_price <= 0:
                continue

            pos["current_price"] = curr_price

            # Calculate Unrealized PnL
            if side == "BUY":
                gross_pnl = (curr_price - entry_p) * qty
            else: # SELL
                gross_pnl = (entry_p - curr_price) * qty

            # Subtract estimated exit charges to show realistic net PnL
            est_exit_charges = PaperTradeCostModel.calculate_charges(inst_type, "SELL" if side == "BUY" else "BUY", curr_price, qty)["total"]
            net_unrealized = round(gross_pnl - pos["entry_charges"] - est_exit_charges, 2)
            pos["unrealized_pnl"] = net_unrealized
            pos["pnl_pct"] = round((net_unrealized / max(pos["allocated_margin"], 1.0)) * 100, 2)
            pos["last_updated"] = get_ist_str()

            # Check Exit Conditions:
            exit_reason = None
            if side == "BUY":
                if curr_price >= tp:
                    exit_reason = "TARGET_HIT"
                elif curr_price <= sl:
                    exit_reason = "STOP_LOSS_HIT"
            else: # SELL
                if curr_price <= tp:
                    exit_reason = "TARGET_HIT"
                elif curr_price >= sl:
                    exit_reason = "STOP_LOSS_HIT"

            # Time Duration Check
            if not exit_reason and now_ts >= pos["target_exit_timestamp"]:
                exit_reason = "TIME_EXPIRED"

            # EOD Square-Off Check (Applies strictly to Intraday trades <= 375 mins)
            is_intraday = pos.get("holding_duration_mins", 15) <= 375
            if not exit_reason and is_eod_square_off and is_intraday:
                exit_reason = "INTRADAY_AUTO_SQUAREOFF"

            if exit_reason:
                positions_to_close.append((pos, exit_reason, curr_price))

        # Close triggered positions
        for pos, reason, exit_price in positions_to_close:
            self._close_position(pos, reason, exit_price)

        # Check if auto_stop_on_exit is triggered or session was waiting to finish open trades
        if len(positions_to_close) > 0 and len(self.positions) == 0:
            if self.config.get("auto_stop_on_exit", False) or self.status == "STOPPED_NEW_TRADES":
                self.status = "COMPLETED"
                self.log_event("SESSION_COMPLETED", "All active positions reached holding duration expiry and auto-closed. Auto-paper trading engine completed.")

        self._recalculate_equity()
        self.save_to_db()

    @_session_locked
    def _close_position(self, pos, reason, exit_price=None):
        """Closes an open position, calculates final P&L, fees, and updates balances."""
        if not any(
            open_pos.get("trade_id") == pos.get("trade_id")
            for open_pos in self.positions
        ):
            return False

        sym = pos["symbol"]
        side = pos["side"]
        qty = pos["quantity"]
        entry_p = pos["entry_price"]
        inst_type = pos["instrument_type"]

        exit_p = exit_price or pos["current_price"]
        # Apply exit slippage
        exec_exit_p = PaperTradeCostModel.apply_slippage(exit_p, "SELL" if side == "BUY" else "BUY", inst_type)

        # Gross P&L
        if side == "BUY":
            gross_pnl = round((exec_exit_p - entry_p) * qty, 2)
        else:
            gross_pnl = round((entry_p - exec_exit_p) * qty, 2)

        # Exit Charges
        exit_costs = PaperTradeCostModel.calculate_charges(inst_type, "SELL" if side == "BUY" else "BUY", exec_exit_p, qty)
        total_charges = round(pos["entry_charges"] + exit_costs["total"], 2)
        self.total_charges += exit_costs["total"]

        net_pnl = round(gross_pnl - total_charges, 2)
        is_win = net_pnl > 0

        # Entry charges were deducted when the position opened; settle only exit cash flow here.
        margin_to_release = pos["allocated_margin"]
        self.allocated_margin = max(0.0, round(self.allocated_margin - margin_to_release, 2))
        self.available_balance = round(
            self.available_balance + margin_to_release + gross_pnl - exit_costs["total"],
            2,
        )
        self.realized_pnl = round(self.realized_pnl + net_pnl, 2)

        entry_ts = pos["entry_timestamp"]
        exit_ts = time.time()
        holding_secs = int(exit_ts - entry_ts)
        holding_str = format_duration_display(holding_secs)

        closed_trade = {
            "trade_id": pos["trade_id"],
            "symbol": sym,
            "name": pos["name"],
            "instrument_type": inst_type,
            "side": side,
            "entry_time": pos["entry_time"],
            "exit_time": get_ist_now().strftime("%Y-%m-%d %H:%M:%S"),
            "entry_price": entry_p,
            "exit_price": exec_exit_p,
            "quantity": qty,
            "target_price": pos["target_price"],
            "stop_loss": pos["stop_loss"],
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "charges": total_charges,
            "slippage": pos["slippage"],
            "exit_reason": reason,
            "strategy": pos["strategy"],
            "signal_rationale": pos.get("signal_rationale"),
            "signal_indicators": pos.get("signal_indicators", {}),
            "market_data_source": pos.get("market_data_source"),
            "market_data_timestamp": pos.get("market_data_timestamp"),
            "risk_distance": pos.get("risk_distance"),
            "is_win": is_win,
            "holding_duration_str": holding_str,
            "holding_seconds": holding_secs,
            "return_pct": round((net_pnl / max(pos["allocated_margin"], 1.0)) * 100, 2),
            "closed_at": get_ist_str(),
        }

        self.closed_trades.insert(0, closed_trade)
        if pos in self.positions:
            self.positions.remove(pos)

        outcome_badge = "🟢 PROFIT" if is_win else "🔴 LOSS"
        if reason == "TIME_EXPIRED":
            self.log_event("DURATION_EXIT", f"⌛ Holding Duration Reached ({pos.get('holding_duration_display', '15m')}): Auto-closed {sym} @ ₹{exec_exit_p:,.2f} ({outcome_badge}). Net P&L: ₹{net_pnl:,.2f}")
        else:
            self.log_event("POSITION_CLOSED", f"{outcome_badge}: Closed {sym} @ ₹{exec_exit_p:,.2f} ({reason}). Net P&L: ₹{net_pnl:,.2f}")
        return True

    @_session_locked
    def test_expire_position(self, trade_id, quote_resolver=None, market_is_open=False):
        """Immediately simulates holding duration expiry for an open trade to test auto-closure in real-time."""
        if not market_is_open:
            return False, "NSE market is closed or its status is unavailable."
        target_pos = None
        for p in self.positions:
            if p["trade_id"] == trade_id:
                target_pos = p
                break
        if not target_pos:
            return False, "Position not found."

        # Set target exit timestamp to 5 seconds in the past
        target_pos["target_exit_timestamp"] = time.time() - 5
        self.update_positions(quote_resolver, market_is_open=market_is_open)
        self.save_to_db()
        return True, f"Simulated duration expiry for {target_pos['symbol']} ({trade_id}). Auto-closed with TIME_EXPIRED."

    @_session_locked
    def manual_close_position(self, trade_id, quote_resolver=None, market_is_open=False):
        """Manually exits a position only with an open market and a fresh NSE quote."""
        if not market_is_open:
            return False, "NSE market is closed or its status is unavailable."
        target_pos = None
        for p in self.positions:
            if p["trade_id"] == trade_id:
                target_pos = p
                break
        if not target_pos:
            return False, "Position not found."

        try:
            quote = quote_resolver(target_pos.get("base_symbol", target_pos["symbol"])) if quote_resolver else None
        except Exception as exc:
            logger.warning("Manual close quote failed for %s: %s", target_pos["symbol"], exc)
            quote = None
        if not _is_fresh_nse_quote(quote):
            return False, f"Could not get a fresh NSE quote for {target_pos['symbol']}; position remains open."

        target_pos["current_price"] = float(quote["lastPrice"])
        self._close_position(target_pos, "MANUAL_EXIT")
        self._recalculate_equity()
        self.save_to_db()
        return True, "Position closed manually."

    @_session_locked
    def close_all_positions(self, reason="MANUAL_CLOSE_ALL", quote_resolver=None, market_is_open=False):
        """Closes positions using fresh NSE quotes; leaves unquoted positions untouched."""
        if not market_is_open:
            return 0
        count = 0
        for pos in list(self.positions):
            try:
                quote = quote_resolver(pos.get("base_symbol", pos["symbol"])) if quote_resolver else None
            except Exception as exc:
                logger.warning("Close-all quote failed for %s: %s", pos["symbol"], exc)
                quote = None
            if not _is_fresh_nse_quote(quote):
                continue
            pos["current_price"] = float(quote["lastPrice"])
            self._close_position(pos, reason)
            count += 1
        if count == 0:
            return 0
        self._recalculate_equity()
        self.save_to_db()
        self.log_event("CLOSE_ALL", f"Closed all {count} active positions ({reason}).")
        return count

    @_session_locked
    def _recalculate_equity(self):
        """Recalculates account balance, equity, total PnL, and max drawdown."""
        self.allocated_margin = round(
            sum(float(position.get("allocated_margin", 0.0)) for position in self.positions),
            2,
        )
        expected_available_balance = round(
            self.initial_capital
            + self.realized_pnl
            - self.allocated_margin
            - sum(float(position.get("entry_charges", 0.0)) for position in self.positions),
            2,
        )
        if abs(self.available_balance - expected_available_balance) > 0.01:
            logger.error(
                "Reconciling paper cash balance for %s: stored=%.2f expected=%.2f",
                self.user_name,
                self.available_balance,
                expected_available_balance,
            )
            self.log_event(
                "ACCOUNT_RECONCILED",
                (
                    f"Available balance reconciled from ₹{self.available_balance:,.2f} "
                    f"to ₹{expected_available_balance:,.2f} using this profile's "
                    "capital, realized P&L, open-position margin, and entry charges."
                ),
            )
        self.available_balance = expected_available_balance
        unrealized = sum(p.get("unrealized_pnl", 0.0) for p in self.positions)
        self.unrealized_pnl = round(unrealized, 2)
        self.total_pnl = round(self.realized_pnl + self.unrealized_pnl, 2)
        self.account_equity = round(self.initial_capital + self.total_pnl, 2)

        # Track High Water Mark (Peak Equity) and Max Drawdown
        if self.account_equity > self.peak_equity:
            self.peak_equity = self.account_equity

        dd_inr = round(max(0.0, self.peak_equity - self.account_equity), 2)
        dd_pct = round((dd_inr / self.peak_equity) * 100, 2) if self.peak_equity > 0 else 0.0
        if dd_inr > self.max_drawdown_inr:
            self.max_drawdown_inr = dd_inr
        if dd_pct > self.max_drawdown_pct:
            self.max_drawdown_pct = dd_pct

    @_session_locked
    def get_state(self):
        """Returns the full state for frontend real-time rendering."""
        previous_accounting = (
            self.available_balance,
            self.allocated_margin,
            self.total_pnl,
            self.account_equity,
        )
        self._recalculate_equity()
        current_accounting = (
            self.available_balance,
            self.allocated_margin,
            self.total_pnl,
            self.account_equity,
        )
        if current_accounting != previous_accounting:
            self.save_to_db()
        ret_pct = round((self.total_pnl / self.initial_capital) * 100, 2) if self.initial_capital > 0 else 0.0

        return {
            "user_name": self.user_name,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at,
            "last_updated": get_ist_str(),
            "config": self.config,
            "account": {
                "initial_capital": self.initial_capital,
                "available_balance": round(self.available_balance, 2),
                "allocated_margin": round(self.allocated_margin, 2),
                "realized_pnl": self.realized_pnl,
                "unrealized_pnl": self.unrealized_pnl,
                "total_pnl": self.total_pnl,
                "total_charges": round(self.total_charges, 2),
                "total_slippage": round(self.total_slippage, 2),
                "account_equity": self.account_equity,
                "overall_return_pct": ret_pct,
                "peak_equity": self.peak_equity,
                "max_drawdown_inr": self.max_drawdown_inr,
                "max_drawdown_pct": self.max_drawdown_pct,
            },
            "active_positions_count": len(self.positions),
            "active_positions": self.positions,
            "recent_closed_trades": self.closed_trades[:25],
            "total_closed_trades_count": len(self.closed_trades),
            "logs": self.logs[:30],
            "scanned_signals": self.scanned_signals[:10],
        }

    @_session_locked
    def get_performance_analytics(self):
        """Calculates win rate, profit factor, strategy and instrument breakdowns."""
        total = len(self.closed_trades)
        if total == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "net_pnl": round(self.realized_pnl, 2),
                "profit_factor": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_drawdown_inr": self.max_drawdown_inr,
                "max_drawdown_pct": self.max_drawdown_pct,
                "avg_holding_duration_secs": 0,
                "strategy_performance": {},
                "instrument_performance": {},
            }

        wins = [t for t in self.closed_trades if t.get("is_win")]
        losses = [t for t in self.closed_trades if not t.get("is_win")]

        gross_profit = sum(t["gross_pnl"] for t in wins)
        gross_loss = abs(sum(t["gross_pnl"] for t in losses))

        win_rate = round((len(wins) / total) * 100, 2)
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)
        avg_win = round(gross_profit / len(wins), 2) if wins else 0.0
        avg_loss = round(gross_loss / len(losses), 2) if losses else 0.0
        avg_holding = int(sum(t.get("holding_seconds", 0) for t in self.closed_trades) / total)

        # Strategy Breakdown
        strat_map = {}
        for t in self.closed_trades:
            s = t.get("strategy", "Quantitative Momentum")
            if s not in strat_map:
                strat_map[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
            strat_map[s]["trades"] += 1
            if t.get("is_win"):
                strat_map[s]["wins"] += 1
            strat_map[s]["pnl"] = round(strat_map[s]["pnl"] + t.get("net_pnl", 0.0), 2)

        for s in strat_map:
            strat_map[s]["win_rate"] = round((strat_map[s]["wins"] / strat_map[s]["trades"]) * 100, 1)

        # Instrument Breakdown
        inst_map = {}
        for t in self.closed_trades:
            it = t.get("instrument_type", "EQUITY")
            if it not in inst_map:
                inst_map[it] = {"trades": 0, "wins": 0, "pnl": 0.0}
            inst_map[it]["trades"] += 1
            if t.get("is_win"):
                inst_map[it]["wins"] += 1
            inst_map[it]["pnl"] = round(inst_map[it]["pnl"] + t.get("net_pnl", 0.0), 2)

        for it in inst_map:
            inst_map[it]["win_rate"] = round((inst_map[it]["wins"] / inst_map[it]["trades"]) * 100, 1)

        return {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": win_rate,
            "net_pnl": round(self.realized_pnl, 2),
            "profit_factor": profit_factor,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown_inr": self.max_drawdown_inr,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_holding_duration_secs": avg_holding,
            "strategy_performance": strat_map,
            "instrument_performance": inst_map,
        }

    @_session_locked
    def save_to_db(self):
        """Persists session state, profile metrics, open stock positions, and completed trades to MongoDB Atlas & disk store."""
        self._recalculate_equity()
        analytics = self.get_performance_analytics()
        ret_pct = round((self.total_pnl / self.initial_capital) * 100, 2) if self.initial_capital > 0 else 0.0
        open_syms = [p.get("symbol") for p in self.positions]

        session_doc = {
            "user_name": self.user_name,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at,
            "last_updated": get_ist_str(),
            "config": self.config,
            "account": {
                "initial_capital": self.initial_capital,
                "available_balance": self.available_balance,
                "allocated_margin": self.allocated_margin,
                "realized_pnl": self.realized_pnl,
                "unrealized_pnl": self.unrealized_pnl,
                "total_pnl": self.total_pnl,
                "total_charges": self.total_charges,
                "total_slippage": self.total_slippage,
                "account_equity": self.account_equity,
                "peak_equity": self.peak_equity,
                "max_drawdown_inr": self.max_drawdown_inr,
                "max_drawdown_pct": self.max_drawdown_pct,
                "overall_return_pct": ret_pct,
            },
            "positions": self.positions,
            "closed_trades": self.closed_trades,
            "logs": self.logs[:50],
        }

        profile_doc = {
            "user_name": self.user_name,
            "user_id": self.user_id,
            "instruments": self.config.get("instruments", ["EQUITY"]),
            "trading_style": self.config.get("trading_style", "INTRADAY"),
            "risk_profile": self.config.get("risk_profile", "MODERATE"),
            "holding_duration_mins": self.config.get("holding_duration_mins", 15),
            "initial_capital": self.initial_capital,
            "account_equity": self.account_equity,
            "available_balance": self.available_balance,
            "net_pnl": self.total_pnl,
            "return_pct": ret_pct,
            "win_rate": analytics.get("win_rate", 0.0),
            "total_trades": analytics.get("total_trades", 0),
            "winning_trades": analytics.get("winning_trades", 0),
            "losing_trades": analytics.get("losing_trades", 0),
            "profit_factor": analytics.get("profit_factor", 0.0),
            "max_drawdown_pct": self.max_drawdown_pct,
            "open_positions_count": len(self.positions),
            "active_stocks": open_syms,
            "status": self.status,
            "last_active": get_ist_str(),
            "updated_at_ts": time.time(),
        }

        local_saved = False
        mongo_saved = False

        try:
            _save_local_paper_record(self.user_name, session_doc, profile_doc)
            local_saved = True
        except (OSError, sqlite3.Error, TypeError, ValueError):
            logger.exception("Could not persist paper trading data locally for %s", self.user_name)

        # 1. Update in-memory & disk datastore
        LOCAL_USER_DATASTORE["sessions"][self.user_name] = session_doc
        LOCAL_USER_DATASTORE["profiles"][self.user_name] = profile_doc
        LOCAL_USER_DATASTORE["positions"][self.user_name] = self.positions
        LOCAL_USER_DATASTORE["trades"][self.user_name] = self.closed_trades
        save_datastore_to_disk(LOCAL_USER_DATASTORE)

        # 2. Persist to MongoDB Atlas if connected
        if self.db is not None:
            try:
                # Sessions collection
                self.db["paper_sessions"].update_one(
                    {"user_name": self.user_name},
                    {"$set": dict(session_doc)},
                    upsert=True
                )
                # Profiles collection (for Leaderboard & Profiles listing)
                self.db["paper_profiles"].update_one(
                    {"user_name": self.user_name},
                    {"$set": dict(profile_doc)},
                    upsert=True
                )
                # Active stock positions collection
                current_trade_ids = []
                for pos in self.positions:
                    p_doc = dict(pos)
                    p_doc["user_name"] = self.user_name
                    p_doc["status"] = "OPEN"
                    p_doc["last_synced"] = get_ist_str()
                    trade_id = pos.get("trade_id")
                    if trade_id:
                        current_trade_ids.append(trade_id)
                        self.db["paper_positions"].update_one(
                            {"trade_id": trade_id},
                            {"$set": p_doc},
                            upsert=True
                        )
                # Mark exited positions as CLOSED in MongoDB
                if current_trade_ids:
                    self.db["paper_positions"].update_many(
                        {"user_name": self.user_name, "status": "OPEN", "trade_id": {"$nin": current_trade_ids}},
                        {"$set": {"status": "CLOSED", "closed_at_sync": get_ist_str()}}
                    )
                else:
                    self.db["paper_positions"].update_many(
                        {"user_name": self.user_name, "status": "OPEN"},
                        {"$set": {"status": "CLOSED", "closed_at_sync": get_ist_str()}}
                    )
                # Completed trades collection
                for tr in self.closed_trades:
                    t_doc = dict(tr)
                    t_doc["user_name"] = self.user_name
                    trade_id = tr.get("trade_id")
                    if trade_id:
                        self.db["paper_trades"].update_one(
                            {"trade_id": trade_id},
                            {"$set": t_doc},
                            upsert=True
                        )
                mongo_saved = True
            except Exception as e:
                logger.warning("Could not persist paper trading data to MongoDB for %s: %s", self.user_name, e)

        if not local_saved and not mongo_saved:
            raise RuntimeError(f"Unable to persist paper trading data for profile [{self.user_name}].")

    @_session_locked
    def load_from_db(self):
        """Restores user session state, balances, and history from MongoDB or durable SQLite."""
        mongo_doc = None
        if self.db is not None:
            try:
                mongo_doc = self.db["paper_sessions"].find_one({"user_name": self.user_name})
            except Exception as e:
                logger.warning("Could not load paper trading data from MongoDB for %s: %s", self.user_name, e)

        local_record = None
        try:
            local_record = _load_local_paper_record(self.user_name)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            logger.exception("Could not load local paper trading data for %s", self.user_name)

        local_doc = local_record["session"] if local_record else None
        doc = mongo_doc
        if local_doc and (
            not mongo_doc
            or _document_updated_at(local_doc) > _document_updated_at(mongo_doc)
        ):
            doc = local_doc

        if not doc:
            doc = LOCAL_USER_DATASTORE["sessions"].get(self.user_name)

        if not doc:
            return False

        try:
            self.session_id = doc.get("session_id", self.session_id)
            self.user_id = doc.get("user_id", self.user_id)
            self.status = doc.get("status", self.status)
            self.created_at = doc.get("created_at", self.created_at)
            if "config" in doc and doc["config"]:
                self.config.update(doc["config"])
            acc = doc.get("account", {})
            self.initial_capital = float(acc.get("initial_capital", self.initial_capital))
            self.available_balance = float(acc.get("available_balance", self.available_balance))
            self.allocated_margin = float(acc.get("allocated_margin", self.allocated_margin))
            self.realized_pnl = float(acc.get("realized_pnl", self.realized_pnl))
            self.unrealized_pnl = float(acc.get("unrealized_pnl", self.unrealized_pnl))
            self.total_pnl = float(acc.get("total_pnl", self.total_pnl))
            self.total_charges = float(acc.get("total_charges", self.total_charges))
            self.total_slippage = float(acc.get("total_slippage", self.total_slippage))
            self.account_equity = float(acc.get("account_equity", self.account_equity))
            self.peak_equity = float(acc.get("peak_equity", self.peak_equity))
            self.max_drawdown_inr = float(acc.get("max_drawdown_inr", self.max_drawdown_inr))
            self.max_drawdown_pct = float(acc.get("max_drawdown_pct", self.max_drawdown_pct))
            self.positions = doc.get("positions", [])
            self.closed_trades = doc.get("closed_trades", [])
            self.logs = doc.get("logs", [])
            return True
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            logger.exception("Could not restore paper trading data for %s", self.user_name)
            return False


class PaperTradingEngine:
    """
    AI Autonomous Paper Trading Orchestrator.
    Scans the Indian market, confirms setups, executes paper orders, and updates positions.
    """

    def __init__(
        self,
        session: PaperTradingSession,
        quote_resolver=None,
        chart_resolver=None,
        market_status_resolver=None,
    ):
        self.session = session
        self.quote_resolver = quote_resolver
        self.chart_resolver = chart_resolver
        self.market_status_resolver = market_status_resolver
        self.last_scan_at = 0.0

    def scan_and_evaluate_setups(self):
        """
        Scans instrument universe using real-time quotes, multi-strategy quantitative confluence,
        and institutional risk-reward models for Equities, Index Futures, Index Options, and Stock Futures.
        """
        cfg_types = list(self.session.config.get("instruments") or [])
        allowed_types = list(cfg_types) if cfg_types else ["EQUITY", "INDEX_FUTURES", "INDEX_OPTIONS"]
        # Ensure EQUITY is available if only F&O was selected so stocks are never starved
        if "EQUITY" not in allowed_types:
            allowed_types.append("EQUITY")

        setups = []

        for item in UNIVERSE:
            sym = item["symbol"]
            item_type = item["type"]

            # Match target instrument type
            target_inst_type = None
            if item_type == "INDEX":
                if "INDEX_OPTIONS" in allowed_types:
                    target_inst_type = "INDEX_OPTIONS"
                elif "INDEX_FUTURES" in allowed_types:
                    target_inst_type = "INDEX_FUTURES"
            elif item_type == "STOCK":
                if "EQUITY" in allowed_types:
                    target_inst_type = "EQUITY"
                elif "STOCK_FUTURES" in allowed_types:
                    target_inst_type = "STOCK_FUTURES"
                else:
                    target_inst_type = "EQUITY"

            if not target_inst_type:
                continue

            if not self.quote_resolver or not self.chart_resolver:
                continue
            try:
                quote = self.quote_resolver(sym)
                chart_rows = self.chart_resolver(sym, "15m", "5d")
            except Exception as exc:
                logger.warning("Could not scan %s using live market data: %s", sym, exc)
                continue
            if not _is_fresh_nse_quote(quote):
                continue

            now_ms = int(time.time() * 1000)
            candles = [
                candle for candle in (chart_rows or [])
                if isinstance(candle, dict)
                and all(key in candle for key in ("o", "h", "l", "c", "v", "t"))
                and int(candle["t"]) + (15 * 60 * 1000) <= now_ms
            ]
            if len(candles) < 20:
                continue
            candles = candles[-100:]

            closes = [float(candle["c"]) for candle in candles]
            ema20 = _ema(closes, 20)
            ema50 = _ema(closes, 50)
            atr14 = _atr(candles, 14)
            vwap = _session_vwap(candles)
            if len(ema20) < 2 or len(ema50) < 2 or not atr14:
                continue

            live_price = float(quote["lastPrice"])
            p_change = float(quote.get("pChange") or 0.0)
            latest = candles[-1]
            recent_volumes = [float(candle.get("v") or 0) for candle in candles[-21:-1]]
            avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
            volume_active = (avg_volume <= 0) or (float(latest.get("v") or 0) >= avg_volume * 0.20)
            min_rr = float(self.session.config.get("min_rr", 1.8))

            # Multi-Factor Quantitative Confluence Scoring
            buy_score = 0
            sell_score = 0

            # 1. EMA20 vs EMA50 Trend
            if ema20[-1] > ema50[-1]:
                buy_score += 25
            else:
                sell_score += 25

            # 2. Session VWAP Confluence
            if vwap:
                if live_price > vwap and float(latest["c"]) > vwap:
                    buy_score += 25
                elif live_price < vwap and float(latest["c"]) < vwap:
                    sell_score += 25

            # 3. Momentum & Relative Strength
            if p_change >= 0.1 and live_price >= ema20[-1]:
                buy_score += 25
            elif p_change <= -0.1 and live_price <= ema20[-1]:
                sell_score += 25

            # 4. Price Action & Breakout / Pullback Confirmation
            is_long_breakout = live_price >= float(latest["h"]) * 0.998
            is_long_pullback = abs(live_price - ema20[-1]) / ema20[-1] < 0.008
            if is_long_breakout or is_long_pullback:
                buy_score += 20

            is_short_breakdown = live_price <= float(latest["l"]) * 1.002
            is_short_pullback = abs(live_price - ema20[-1]) / ema20[-1] < 0.008
            if is_short_breakdown or is_short_pullback:
                sell_score += 20

            is_index = "NIFTY" in sym or "SENSEX" in sym
            vol_floor = 0.002 if is_index else 0.004
            risk_distance = max(1.5 * atr14, live_price * vol_floor)

            if buy_score >= 70 and buy_score > sell_score:
                side = "BUY"
                score = buy_score
                strat = "15m EMA20/50 + VWAP Breakout" if is_long_breakout else "VWAP Momentum Expansion"
            elif sell_score >= 70 and sell_score > buy_score:
                side = "SELL"
                score = sell_score
                strat = "15m EMA20/50 + VWAP Breakdown" if is_short_breakdown else "Supertrend ATR Continuation"
            else:
                continue

            display_sym = sym
            entry_price = round(live_price, 2)
            stop_loss = round(entry_price - risk_distance if side == "BUY" else entry_price + risk_distance, 2)
            target_price = round(entry_price + (risk_distance * min_rr) if side == "BUY" else entry_price - (risk_distance * min_rr), 2)
            setup_risk = round(risk_distance, 4)

            # Synthesize option contract if INDEX_OPTIONS
            if target_inst_type == "INDEX_OPTIONS":
                step = 50 if "NIFTY" in sym and "BANK" not in sym else 100
                strike = int(round(live_price / step) * step)
                opt_type = "CE" if side == "BUY" else "PE"
                display_sym = f"{sym} {strike} {opt_type}"
                opt_premium = round(live_price * 0.010, 2)
                opt_risk = round(opt_premium * 0.25, 2)
                entry_price = opt_premium
                stop_loss = max(1.0, round(entry_price - opt_risk, 2))
                target_price = round(entry_price + (opt_risk * min_rr), 2)
                setup_risk = opt_risk

            setups.append({
                "symbol": display_sym,
                "base_symbol": sym,
                "name": item["name"],
                "instrument_type": target_inst_type,
                "market_data_source": "NSE",
                "market_data_fetched_at": quote.get("fetched_at", time.time()),
                "market_data_timestamp": quote.get("timestamp"),
                "signal_indicators": {
                    "ema20": round(ema20[-1], 4),
                    "ema50": round(ema50[-1], 4),
                    "session_vwap": round(vwap, 4) if vwap else 0.0,
                    "atr14": round(atr14, 4),
                    "volume_ratio": round(float(latest.get("v") or 0) / avg_volume, 3) if avg_volume else 1.0,
                    "breakout_level": round(float(latest["h"] if side == "BUY" else latest["l"]), 4),
                },
                "side": side,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "target_price": target_price,
                "risk_distance": setup_risk,
                "reward_risk": min_rr,
                "strategy": strat,
                "confidence_score": score,
                "status": "VALIDATED",
                "timestamp": get_ist_str(),
                "rationale": (
                    f"{side}: confirmed 15m trend (EMA20/50), VWAP alignment, and momentum. "
                    f"Entry uses NSE LTP; stop is 1.5x ATR(14), target is {min_rr:.2f}R."
                ),
            })

        self.session.scanned_signals = setups
        return setups

    def tick(self):
        """
        Main execution step:
        1. Updates open positions against current market quotes (checks Target/SL/Time exits).
        2. If running and capacity allows, scans for top setups and executes new paper trades.
        """
        self.session.last_tick_at = time.time()

        market_is_open = False
        if self.market_status_resolver:
            try:
                status = self.market_status_resolver()
                market_is_open = bool(status and status.get("is_trading_hours"))
            except Exception as exc:
                logger.warning("Could not confirm NSE market status: %s", exc)

        # Without confirmed exchange status or fresh quotes, do not simulate fills or exits.
        self.session.update_positions(self.quote_resolver, market_is_open=market_is_open)

        # Step 2: Autonomous entry evaluation
        if self.session.status == "RUNNING" and market_is_open:
            can_trade, reason = self.session.can_open_new_trade()
            if can_trade and (time.time() - self.last_scan_at >= 10 or not self.session.positions):
                self.last_scan_at = time.time()
                setups = self.scan_and_evaluate_setups()
                open_symbols = {p["symbol"] for p in self.session.positions}
                viable_setups = [s for s in setups if s["status"] == "VALIDATED" and s["symbol"] not in open_symbols]
                
                # Sort by highest confidence score
                viable_setups.sort(key=lambda x: x["confidence_score"], reverse=True)

                for candidate in viable_setups:
                    pos, err = self.session.execute_trade(
                        candidate,
                        self.quote_resolver,
                        market_is_open=market_is_open,
                    )
                    if pos:
                        break # Executed candidate trade

        return self.session.get_state()

    @classmethod
    def run_backtest(cls, symbol="NIFTY 50", strategy="15m ORB Breakout", initial_capital=100000.0, candles=None, risk_profile="MODERATE"):
        """
        Runs deterministic historical backtest with transaction costs & slippage.
        Guarantees realistic execution modeling without look-ahead bias.
        """
        cap = float(initial_capital)
        equity = cap
        peak_equity = cap
        max_dd_inr = 0.0
        max_dd_pct = 0.0

        rr_map = {"CONSERVATIVE": 2.0, "MODERATE": 1.8, "AGGRESSIVE": 1.5}
        rr_target = rr_map.get(risk_profile, 1.8)
        risk_pct = 0.005 if risk_profile == "CONSERVATIVE" else (0.02 if risk_profile == "AGGRESSIVE" else 0.01)

        # Generate or use candles
        rows = candles or []
        if not rows or len(rows) < 20:
            # Generate deterministic synthetic 60-day 15m candle series
            random.seed(42 + abs(hash(symbol)))
            base_p = 24800.0 if "NIFTY" in symbol else (1280.0 if "RELIANCE" in symbol else 1000.0)
            rows = []
            curr_c = base_p
            for i in range(120):
                ret = random.gauss(0.0003, 0.005)
                o = curr_c
                c = round(o * (1.0 + ret), 2)
                h = round(max(o, c) * (1.0 + abs(random.gauss(0, 0.002))), 2)
                l = round(min(o, c) * (1.0 - abs(random.gauss(0, 0.002))), 2)
                rows.append({"o": o, "h": h, "l": l, "c": c, "v": int(random.uniform(50000, 250000))})
                curr_c = c

        trades = []
        in_pos = None

        for idx in range(15, len(rows) - 1):
            bar = rows[idx]
            o, h, l, c = bar["o"], bar["h"], bar["l"], bar["c"]

            if in_pos:
                # Check exit conditions against this bar
                target = in_pos["target"]
                stop = in_pos["stop"]
                side = in_pos["side"]
                entry = in_pos["entry"]
                qty = in_pos["qty"]
                exit_price = None
                exit_reason = None

                if side == "BUY":
                    if h >= target:
                        exit_price = target
                        exit_reason = "TARGET_HIT"
                    elif l <= stop:
                        exit_price = stop
                        exit_reason = "STOP_LOSS_HIT"
                else: # SELL
                    if l <= target:
                        exit_price = target
                        exit_reason = "TARGET_HIT"
                    elif h >= stop:
                        exit_price = stop
                        exit_reason = "STOP_LOSS_HIT"

                # Check duration exit after 6 bars (~1.5 hours)
                if not exit_reason and (idx - in_pos["entry_bar"]) >= 6:
                    exit_price = c
                    exit_reason = "TIME_EXPIRED"

                if exit_reason:
                    # Apply slippage & charges
                    exec_exit = PaperTradeCostModel.apply_slippage(exit_price, "SELL" if side == "BUY" else "BUY", in_pos["inst_type"])
                    gross_pnl = round((exec_exit - entry) * qty if side == "BUY" else (entry - exec_exit) * qty, 2)
                    charges = PaperTradeCostModel.calculate_charges(in_pos["inst_type"], "SELL" if side == "BUY" else "BUY", exec_exit, qty)["total"] + in_pos["entry_charges"]
                    net_pnl = round(gross_pnl - charges, 2)
                    equity = round(equity + net_pnl, 2)

                    if equity > peak_equity:
                        peak_equity = equity
                    dd = peak_equity - equity
                    if dd > max_dd_inr:
                        max_dd_inr = dd
                        max_dd_pct = round((dd / peak_equity) * 100, 2)

                    trades.append({
                        "trade_index": len(trades) + 1,
                        "side": side,
                        "entry": entry,
                        "exit": exec_exit,
                        "gross_pnl": gross_pnl,
                        "net_pnl": net_pnl,
                        "charges": round(charges, 2),
                        "exit_reason": exit_reason,
                        "is_win": net_pnl > 0,
                    })
                    in_pos = None
            else:
                # Check Entry Signal
                # Simple moving average / breakout condition
                prev_10 = rows[idx-10:idx]
                ma10 = sum(b["c"] for b in prev_10) / 10.0
                high10 = max(b["h"] for b in prev_10)
                low10 = min(b["l"] for b in prev_10)

                trigger_buy = c > high10 or (c > ma10 and rows[idx-1]["c"] <= ma10)
                trigger_sell = c < low10 or (c < ma10 and rows[idx-1]["c"] >= ma10)

                if trigger_buy or trigger_sell:
                    side = "BUY" if trigger_buy else "SELL"
                    entry_p = PaperTradeCostModel.apply_slippage(c, side, "EQUITY")
                    vol_factor = 0.008
                    stop_p = round(entry_p * (1.0 - vol_factor) if side == "BUY" else entry_p * (1.0 + vol_factor), 2)
                    risk_pts = abs(entry_p - stop_p)
                    target_p = round(entry_p + (risk_pts * rr_target) if side == "BUY" else entry_p - (risk_pts * rr_target), 2)

                    max_risk = equity * risk_pct
                    qty = max(1, math.floor(max_risk / max(risk_pts, 1.0)))
                    entry_charges = PaperTradeCostModel.calculate_charges("EQUITY", side, entry_p, qty)["total"]

                    in_pos = {
                        "entry": entry_p,
                        "stop": stop_p,
                        "target": target_p,
                        "side": side,
                        "qty": qty,
                        "inst_type": "EQUITY",
                        "entry_bar": idx,
                        "entry_charges": entry_charges,
                    }

        total_t = len(trades)
        wins = [t for t in trades if t["is_win"]]
        losses = [t for t in trades if not t["is_win"]]
        gross_p = sum(t["gross_pnl"] for t in wins)
        gross_l = abs(sum(t["gross_pnl"] for t in losses))
        net_ret = round(equity - cap, 2)
        net_ret_pct = round((net_ret / cap) * 100, 2)

        return {
            "mode": "HISTORICAL BACKTEST (SIMULATED)",
            "symbol": symbol,
            "strategy": strategy,
            "risk_profile": risk_profile,
            "initial_capital": cap,
            "final_equity": equity,
            "net_profit_loss": net_ret,
            "return_pct": net_ret_pct,
            "total_trades": total_t,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round((len(wins) / total_t) * 100, 2) if total_t > 0 else 0.0,
            "profit_factor": round(gross_p / gross_l, 2) if gross_l > 0 else 99.0,
            "max_drawdown_inr": round(max_dd_inr, 2),
            "max_drawdown_pct": max_dd_pct,
            "disclaimer": "Backtested performance is simulated with slippage and charges. Past results do not guarantee future profits.",
        }


class MultiUserPaperSessionManager:
    """
    Manages profile-isolated paper trading sessions.
    Each user/profile has independent capital, preferences, active positions, and trade history.
    Persists to MongoDB Atlas and durable local SQLite & disk datastore.
    """
    def __init__(self, db=None, quote_resolver=None, chart_resolver=None, market_status_resolver=None):
        self.db = db
        self.quote_resolver = quote_resolver
        self.chart_resolver = chart_resolver
        self.market_status_resolver = market_status_resolver
        self.sessions = {} # { user_name: PaperTradingSession }
        self.engines = {}  # { user_name: PaperTradingEngine }
        self._init_defaults()

    def _init_defaults(self):
        """Discovers and restores all user profiles from MongoDB Atlas & persistent disk store."""
        known_profiles = {}

        # 1. Load from persistent disk store
        for uname, pdata in LOCAL_USER_DATASTORE.get("profiles", {}).items():
            if uname and isinstance(pdata, dict):
                known_profiles[uname] = dict(pdata)

        # 2. Load all profiles from MongoDB Atlas if connected
        if self.db is not None:
            try:
                for doc in self.db["paper_profiles"].find({}, {"_id": 0}):
                    uname = doc.get("user_name")
                    if uname:
                        known_profiles[uname] = doc
            except Exception:
                pass

        # 3. Ensure standard benchmark profiles exist if not already present
        default_benchmarks = [
            {"user_name": "Akshay", "instruments": ["EQUITY", "INDEX_FUTURES", "INDEX_OPTIONS"], "capital": 100000.0, "style": "INTRADAY", "risk": "MODERATE"},
            {"user_name": "Vijay_Options_Pro", "instruments": ["INDEX_OPTIONS"], "capital": 50000.0, "style": "SCALPING", "risk": "AGGRESSIVE"},
            {"user_name": "Rahul_Futures_Swing", "instruments": ["INDEX_FUTURES", "STOCK_FUTURES"], "capital": 200000.0, "style": "SWING", "risk": "CONSERVATIVE"},
            {"user_name": "Pooja_Equity_Value", "instruments": ["EQUITY"], "capital": 75000.0, "style": "POSITIONAL", "risk": "MODERATE"},
        ]
        for p in default_benchmarks:
            uname = p["user_name"]
            existing = None
            if self.db is not None:
                try:
                    existing = self.db["paper_profiles"].find_one({"user_name": uname})
                except Exception as e:
                    logger.warning("Could not check MongoDB profile %s: %s", uname, e)
            if not existing:
                try:
                    existing = _load_local_paper_record(uname)
                except (OSError, sqlite3.Error, TypeError, ValueError) as e:
                    logger.exception("Could not check local profile %s", uname)
            if not existing and uname not in LOCAL_USER_DATASTORE["profiles"]:
                sess = PaperTradingSession(
                    user_name=uname,
                    config={
                        "initial_capital": p["capital"],
                        "instruments": p["instruments"],
                        "trading_style": p["style"],
                        "risk_profile": p["risk"],
                        "holding_duration_mins": 15 if p["style"] == "INTRADAY" else (1440 if p["style"] == "SWING" else 10080),
                    },
                    db=self.db
                )
                sess.save_to_db()
                self.sessions[uname] = sess
                self.engines[uname] = PaperTradingEngine(
                    session=sess,
                    quote_resolver=self.quote_resolver,
                    chart_resolver=self.chart_resolver,
                    market_status_resolver=self.market_status_resolver,
                )

    def get_session(self, user_name="Akshay"):
        uname = (user_name or "Akshay").strip()
        if uname in self.sessions:
            return self.sessions[uname], self.engines[uname]

        sess = PaperTradingSession(user_name=uname, db=self.db)
        eng = PaperTradingEngine(
            session=sess,
            quote_resolver=self.quote_resolver,
            chart_resolver=self.chart_resolver,
            market_status_resolver=self.market_status_resolver,
        )
        self.sessions[uname] = sess
        self.engines[uname] = eng
        sess.save_to_db()
        return sess, eng

    def create_profile(self, user_name, config=None):
        uname = (user_name or "").strip()
        if not uname:
            return None, "Profile name cannot be empty."
        if uname in self.sessions or uname in LOCAL_USER_DATASTORE["profiles"]:
            return None, f"Profile [{uname}] already exists."
        try:
            if _load_local_paper_record(uname):
                return None, f"Profile [{uname}] already exists."
        except (OSError, sqlite3.Error, TypeError, ValueError) as e:
            logger.exception("Could not check local profile %s", uname)
            raise RuntimeError(f"Unable to verify whether profile [{uname}] already exists.") from e
        if self.db is not None:
            try:
                if self.db["paper_profiles"].find_one({"user_name": uname}):
                    return None, f"Profile [{uname}] already exists."
            except Exception as e:
                logger.warning("Could not check MongoDB profile %s: %s", uname, e)

        sess = PaperTradingSession(user_name=uname, config=config, db=self.db)
        eng = PaperTradingEngine(
            session=sess,
            quote_resolver=self.quote_resolver,
            chart_resolver=self.chart_resolver,
            market_status_resolver=self.market_status_resolver,
        )
        self.sessions[uname] = sess
        self.engines[uname] = eng
        sess.save_to_db()
        return sess, f"Profile [{uname}] created and persisted in MongoDB Atlas!"

    def list_profiles(self):
        """Returns list of all registered profile names and up-to-date metrics across all users."""
        prof_map = {}

        # 1. Fetch all profiles from MongoDB Atlas if available
        if self.db is not None:
            try:
                cursor = self.db["paper_profiles"].find({}, {"_id": 0}).sort("net_pnl", -1)
                for doc in cursor:
                    u = doc.get("user_name")
                    if u:
                        prof_map[u] = doc
            except Exception as e:
                logger.warning("Could not load profiles from MongoDB: %s", e)

        # 2. Load from local SQLite store
        try:
            persisted_profiles = _load_local_paper_profiles()
            for profile in persisted_profiles:
                u = profile.get("user_name")
                if u and (u not in prof_map or _document_updated_at(profile) >= _document_updated_at(prof_map[u])):
                    prof_map[u] = profile
        except Exception:
            pass

        # 3. Merge with disk/in-memory store
        for u, pdata in LOCAL_USER_DATASTORE.get("profiles", {}).items():
            if u and (u not in prof_map or _document_updated_at(pdata) >= _document_updated_at(prof_map[u])):
                prof_map[u] = dict(pdata)

        # 3. Synchronize with active in-memory sessions for real-time live equity, PnL, active stocks, and status
        for uname, sess in self.sessions.items():
            ret_pct = round((sess.total_pnl / sess.initial_capital) * 100, 2) if sess.initial_capital > 0 else 0.0
            analytics = sess.get_performance_analytics()
            open_syms = [p.get("symbol") for p in sess.positions]
            prof_map[uname] = {
                "user_name": sess.user_name,
                "user_id": sess.user_id,
                "instruments": sess.config.get("instruments", ["EQUITY"]),
                "trading_style": sess.config.get("trading_style", "INTRADAY"),
                "risk_profile": sess.config.get("risk_profile", "MODERATE"),
                "holding_duration_mins": sess.config.get("holding_duration_mins", 15),
                "initial_capital": sess.initial_capital,
                "account_equity": sess.account_equity,
                "available_balance": sess.available_balance,
                "net_pnl": sess.total_pnl,
                "return_pct": ret_pct,
                "win_rate": analytics.get("win_rate", 0.0),
                "total_trades": analytics.get("total_trades", 0),
                "winning_trades": analytics.get("winning_trades", 0),
                "losing_trades": analytics.get("losing_trades", 0),
                "profit_factor": analytics.get("profit_factor", 0.0),
                "max_drawdown_pct": sess.max_drawdown_pct,
                "open_positions_count": len(sess.positions),
                "active_stocks": open_syms,
                "status": sess.status,
                "last_active": get_ist_str(),
            }

        # 4. Fallback if still empty
        if not prof_map:
            sess, _ = self.get_session("Akshay")
            prof_map["Akshay"] = LOCAL_USER_DATASTORE["profiles"].get("Akshay", {})

        return list(prof_map.values())

    def get_leaderboard(self):
        """Returns sorted, universally consistent leaderboard ranking users by Net PnL and Return %."""
        profiles = self.list_profiles()
        # Sort by Net PnL (descending), Return % (descending), Win Rate (descending)
        profiles.sort(key=lambda x: (x.get("net_pnl", 0.0), x.get("return_pct", 0.0), x.get("win_rate", 0.0)), reverse=True)
        for idx, p in enumerate(profiles):
            p["rank"] = idx + 1
            net = p.get("net_pnl", 0.0)
            if idx == 0 and net > 0:
                p["badge"] = "🥇 Champion"
            elif idx == 1 and net > 0:
                p["badge"] = "🥈 Runner Up"
            elif idx == 2 and net > 0:
                p["badge"] = "🥉 3rd Place"
            elif net > 0:
                p["badge"] = "⚡ In Profit"
            elif net < 0:
                p["badge"] = "🔻 Drawdown"
            else:
                p["badge"] = "⏸️ Break-even"
        return profiles

    def tick_all_running(self):
        """Evaluates every active user session running concurrently."""
        results = {}
        for uname, sess in list(self.sessions.items()):
            try:
                if sess.status in ("RUNNING", "STOPPED_NEW_TRADES"):
                    eng = self.engines.get(uname)
                    if eng:
                        results[uname] = eng.tick()
            except Exception:
                logger.exception("Paper trading tick failed for profile %s", uname)
        return results
