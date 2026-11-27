"""
FinGroww SaaS Platform — Multi-Account Isolated Paper Trading Service (Phase 3).
Supports multiple virtual accounts per user, plan-based account quotas, Indian brokerage/slippage,
account-scoped positions & trade ledgers, CSV export, and reset/archive workflows.
"""

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.database import db_manager
from backend.services.dashboard_service import _compute_verified_metrics, _safe_live_quote


class PaperServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _calculate_indian_charges(turnover: float, side: str, instrument_type: str) -> Dict[str, float]:
    """Calculates realistic Indian brokerage, STT, exchange fees, and 18% GST."""
    brokerage = 20.0 if turnover > 0 else 0.0
    is_option = "OPTION" in (instrument_type or "").upper()
    stt = (turnover * 0.000625) if (is_option and side == "SELL") else (turnover * 0.00025 if side == "SELL" else 0.0)
    exch_tx = turnover * (0.0005 if is_option else 0.0000325)
    sebi = turnover * 0.000001
    gst = (brokerage + exch_tx + sebi) * 0.18
    total_charges = round(brokerage + stt + exch_tx + sebi + gst, 2)
    slippage = round(turnover * 0.0003, 2)  # 3 bps realistic execution slippage
    return {"charges": total_charges, "slippage": slippage}


def _get_owned_account(user_id: str, account_id: str) -> Dict[str, Any]:
    acc = db_manager.collection("paper_accounts").find_one({"account_id": account_id, "user_id": user_id}, {"_id": 0})
    if not acc:
        raise PaperServiceError("Paper account not found or unauthorized", 404)
    return acc


def list_accounts(user_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
    filt: Dict[str, Any] = {"user_id": user_id}
    if not include_archived:
        filt["is_archived"] = {"$ne": True}
    accounts = list(db_manager.collection("paper_accounts").find(filt, {"_id": 0}))
    # Auto-provision default account if missing
    if not accounts and not include_archived:
        default_acc = {
            "account_id": f"ACC-{uuid.uuid4().hex[:8].upper()}",
            "user_id": user_id,
            "name": "Primary AI Paper Account",
            "virtual_capital": 100000.0,
            "available_balance": 100000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "max_drawdown_pct": 0.0,
            "trading_style": "intraday_momentum",
            "is_default": True,
            "is_archived": False,
            "circuit_breaker_triggered": False,
            "created_at": _now_iso(),
        }
        db_manager.collection("paper_accounts").insert_one(default_acc)
        default_acc.pop("_id", None)
        accounts = [default_acc]
    return accounts


def create_account(user_id: str, name: str, virtual_capital: float, trading_style: str = "intraday_momentum") -> Dict[str, Any]:
    user_doc = db_manager.collection("users").find_one({"user_id": user_id}) or {}
    plan_code = user_doc.get("subscription_plan", "free")
    plan_doc = db_manager.collection("plans").find_one({"plan_code": plan_code}) or {"max_paper_accounts": 1}
    max_accounts = int(plan_doc.get("max_paper_accounts", 1))

    active_count = db_manager.collection("paper_accounts").count_documents({"user_id": user_id, "is_archived": {"$ne": True}})
    if active_count >= max_accounts:
        raise PaperServiceError(
            f"Account limit reached ({active_count}/{max_accounts} on '{plan_code}' plan). Upgrade to Pro Algo Swarm for up to 10 accounts.",
            403,
        )

    new_acc = {
        "account_id": f"ACC-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "name": name.strip(),
        "virtual_capital": round(float(virtual_capital), 2),
        "available_balance": round(float(virtual_capital), 2),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_trades": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "max_drawdown_pct": 0.0,
        "trading_style": trading_style,
        "is_default": active_count == 0,
        "is_archived": False,
        "circuit_breaker_triggered": False,
        "created_at": _now_iso(),
    }
    db_manager.collection("paper_accounts").insert_one(new_acc)
    new_acc.pop("_id", None)
    return {"ok": True, "account": new_acc}


def reset_account(user_id: str, account_id: str, new_capital: Optional[float] = None) -> Dict[str, Any]:
    acc = _get_owned_account(user_id, account_id)
    cap = round(float(new_capital), 2) if new_capital is not None else float(acc.get("virtual_capital", 100000.0))

    db_manager.collection("paper_positions").delete_many({"user_id": user_id, "account_id": account_id})
    db_manager.collection("paper_trades").delete_many({"user_id": user_id, "account_id": account_id})
    db_manager.collection("paper_orders").delete_many({"user_id": user_id, "account_id": account_id})

    updates = {
        "virtual_capital": cap,
        "available_balance": cap,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_trades": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "max_drawdown_pct": 0.0,
        "circuit_breaker_triggered": False,
        "reset_at": _now_iso(),
    }
    db_manager.collection("paper_accounts").update_one({"account_id": account_id, "user_id": user_id}, {"$set": updates})
    return {"ok": True, "account": _get_owned_account(user_id, account_id)}


def archive_account(user_id: str, account_id: str) -> Dict[str, Any]:
    acc = _get_owned_account(user_id, account_id)
    if acc.get("is_default"):
        raise PaperServiceError("Cannot archive your primary default account. Reset it instead.", 400)
    open_cnt = db_manager.collection("paper_positions").count_documents({"user_id": user_id, "account_id": account_id, "status": "OPEN"})
    if open_cnt > 0:
        raise PaperServiceError("Close all open positions before archiving this account.", 400)

    db_manager.collection("paper_accounts").update_one(
        {"account_id": account_id, "user_id": user_id},
        {"$set": {"is_archived": True, "archived_at": _now_iso()}},
    )
    return {"ok": True, "message": "Account archived"}


def place_account_order(user_id: str, account_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    acc = _get_owned_account(user_id, account_id)
    if acc.get("is_archived"):
        raise PaperServiceError("Cannot trade on an archived account", 400)
    if acc.get("circuit_breaker_triggered"):
        raise PaperServiceError("Daily 5% risk circuit breaker is active on this account", 403)

    sym = str(payload["symbol"]).strip().upper()
    side = payload["side"]
    qty = int(payload["quantity"])
    inst_type = payload.get("instrument_type", "EQUITY")
    sl = float(payload["stop_loss"])
    t1 = float(payload["target_1"])

    entry_price = payload.get("entry_price")
    if entry_price is None:
        q = _safe_live_quote(sym)
        if not q:
            raise PaperServiceError(f"Live market quote unavailable for {sym}; specify limit/entry price explicitly.", 400)
        entry_price = q["lastPrice"]
    entry_price = float(entry_price)

    if side == "BUY" and sl >= entry_price:
        raise PaperServiceError("For BUY orders, Stop-Loss must be below Entry Price", 400)
    if side == "SELL" and sl <= entry_price:
        raise PaperServiceError("For SELL orders, Stop-Loss must be above Entry Price", 400)

    turnover = entry_price * qty
    costs = _calculate_indian_charges(turnover, side, inst_type)
    required_margin = round(turnover + costs["charges"], 2)
    avail = float(acc.get("available_balance", 0.0))

    if required_margin > avail:
        raise PaperServiceError(f"Insufficient virtual margin: required ₹{required_margin:,.2f}, available ₹{avail:,.2f}", 400)

    now_iso = _now_iso()
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    pos_id = f"POS-{uuid.uuid4().hex[:8].upper()}"

    order_doc = {
        "order_id": order_id,
        "account_id": account_id,
        "user_id": user_id,
        "symbol": sym,
        "instrument_type": inst_type,
        "side": side,
        "quantity": qty,
        "executed_price": round(entry_price, 2),
        "stop_loss": round(sl, 2),
        "target_1": round(t1, 2),
        "charges_inr": costs["charges"],
        "slippage_inr": costs["slippage"],
        "status": "FILLED",
        "strategy": payload.get("strategy", "Manual Setup"),
        "created_at": now_iso,
    }
    db_manager.collection("paper_orders").insert_one(order_doc)
    order_doc.pop("_id", None)

    pos_doc = {
        "position_id": pos_id,
        "order_id": order_id,
        "account_id": account_id,
        "user_id": user_id,
        "symbol": sym,
        "instrument_type": inst_type,
        "side": side,
        "quantity": qty,
        "avg_entry_price": round(entry_price, 2),
        "current_ltp": round(entry_price, 2),
        "stop_loss": round(sl, 2),
        "target_1": round(t1, 2),
        "entry_charges": costs["charges"],
        "slippage_inr": costs["slippage"],
        "unrealized_pnl": 0.0,
        "status": "OPEN",
        "strategy": payload.get("strategy", "Manual Setup"),
        "entry_timestamp": now_iso,
    }
    db_manager.collection("paper_positions").insert_one(pos_doc)
    pos_doc.pop("_id", None)

    new_avail = round(avail - required_margin, 2)
    db_manager.collection("paper_accounts").update_one(
        {"account_id": account_id, "user_id": user_id},
        {"$set": {"available_balance": new_avail}},
    )

    return {"ok": True, "order": order_doc, "position": pos_doc, "available_balance": new_avail}


def close_account_position(
    user_id: str,
    account_id: str,
    position_id: str,
    exit_price: Optional[float] = None,
    exit_reason: str = "MANUAL_SQUARE_OFF",
) -> Dict[str, Any]:
    acc = _get_owned_account(user_id, account_id)
    pos = db_manager.collection("paper_positions").find_one(
        {"position_id": position_id, "account_id": account_id, "user_id": user_id, "status": "OPEN"}
    )
    if not pos:
        raise PaperServiceError("Open position not found or unauthorized", 404)

    if exit_price is None:
        q = _safe_live_quote(pos["symbol"])
        exit_price = q["lastPrice"] if q else float(pos["avg_entry_price"])
    exit_price = float(exit_price)

    qty = int(pos["quantity"])
    entry = float(pos["avg_entry_price"])
    side = pos["side"]

    gross_pnl = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
    exit_side = "SELL" if side == "BUY" else "BUY"
    exit_costs = _calculate_indian_charges(exit_price * qty, exit_side, pos.get("instrument_type", "EQUITY"))
    total_charges = round(float(pos.get("entry_charges", 0.0)) + exit_costs["charges"] + exit_costs["slippage"], 2)
    net_pnl = round(gross_pnl - exit_costs["charges"] - exit_costs["slippage"] - float(pos.get("slippage_inr", 0.0)), 2)

    now_iso = _now_iso()
    trade_id = f"TRD-{uuid.uuid4().hex[:8].upper()}"
    return_pct = round((net_pnl / (entry * qty)) * 100.0, 2) if entry * qty > 0 else 0.0

    trade_doc = {
        "trade_id": trade_id,
        "position_id": position_id,
        "account_id": account_id,
        "user_id": user_id,
        "symbol": pos["symbol"],
        "instrument_type": pos.get("instrument_type", "EQUITY"),
        "side": side,
        "quantity": qty,
        "entry_price": entry,
        "exit_price": round(exit_price, 2),
        "gross_pnl": round(gross_pnl, 2),
        "charges_and_slippage": total_charges,
        "net_pnl": net_pnl,
        "return_pct": return_pct,
        "exit_reason": exit_reason,
        "strategy": pos.get("strategy", "Manual Setup"),
        "entry_time": pos.get("entry_timestamp"),
        "closed_at": now_iso,
    }
    db_manager.collection("paper_trades").insert_one(trade_doc)
    trade_doc.pop("_id", None)

    db_manager.collection("paper_positions").update_one(
        {"position_id": position_id},
        {"$set": {"status": "CLOSED", "closed_at": now_iso, "exit_price": round(exit_price, 2)}},
    )

    # Recompute verified account aggregates
    all_trades = list(db_manager.collection("paper_trades").find({"user_id": user_id, "account_id": account_id}, {"_id": 0}))
    metrics = _compute_verified_metrics(float(acc["virtual_capital"]), all_trades)
    released_principal = entry * qty + float(pos.get("entry_charges", 0.0))
    new_avail = round(float(acc.get("available_balance", 0.0)) + released_principal + net_pnl - exit_costs["charges"], 2)
    new_avail = max(0.0, new_avail)

    # Check 5% Daily Drawdown Circuit Breaker
    cb_triggered = metrics["max_drawdown_pct"] >= 5.0
    db_manager.collection("paper_accounts").update_one(
        {"account_id": account_id, "user_id": user_id},
        {
            "$set": {
                "available_balance": new_avail,
                "realized_pnl": metrics["realized_pnl"],
                "total_trades": metrics["total_trades"],
                "win_trades": metrics["win_trades"],
                "loss_trades": metrics["loss_trades"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "circuit_breaker_triggered": cb_triggered,
            }
        },
    )

    return {"ok": True, "trade": trade_doc, "metrics": metrics, "available_balance": new_avail}


def get_account_details(user_id: str, account_id: str) -> Dict[str, Any]:
    acc = _get_owned_account(user_id, account_id)
    positions = list(db_manager.collection("paper_positions").find({"user_id": user_id, "account_id": account_id, "status": "OPEN"}, {"_id": 0}))
    trades = list(db_manager.collection("paper_trades").find({"user_id": user_id, "account_id": account_id}, {"_id": 0}).sort("closed_at", -1))
    metrics = _compute_verified_metrics(float(acc.get("virtual_capital", 100000.0)), trades)
    return {
        "ok": True,
        "account": acc,
        "positions": positions,
        "trades": trades,
        "metrics": metrics,
        "equity_curve": metrics["equity_curve"],
    }


def export_account_trades_csv(user_id: str, account_id: str) -> str:
    _get_owned_account(user_id, account_id)
    trades = list(db_manager.collection("paper_trades").find({"user_id": user_id, "account_id": account_id}, {"_id": 0}).sort("closed_at", -1))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "trade_id", "account_id", "symbol", "instrument_type", "side", "quantity",
        "entry_price", "exit_price", "gross_pnl", "charges_and_slippage", "net_pnl",
        "return_pct", "exit_reason", "strategy", "entry_time", "closed_at",
    ])
    for t in trades:
        writer.writerow([
            t.get("trade_id"), t.get("account_id"), t.get("symbol"), t.get("instrument_type"),
            t.get("side"), t.get("quantity"), t.get("entry_price"), t.get("exit_price"),
            t.get("gross_pnl"), t.get("charges_and_slippage"), t.get("net_pnl"),
            t.get("return_pct"), t.get("exit_reason"), t.get("strategy"),
            t.get("entry_time"), t.get("closed_at"),
        ])
    return buf.getvalue()
