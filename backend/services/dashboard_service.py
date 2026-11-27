"""
FinGroww SaaS Platform — Personalised User Dashboard, Watchlist, Saved Signals & Notifications Service.
Strictly enforces authenticated user ownership across every read/write operation.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.database import db_manager

logger = logging.getLogger("FinGroww.Services.Dashboard")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_live_quote(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import fingroww_market_server as srv
        q = srv.resolve_quote(srv.normalize_symbol(symbol))
        if q and q.get("lastPrice") is not None:
            return {
                "lastPrice": float(q["lastPrice"]),
                "pChange": float(q.get("pChange") or 0.0),
                "source": q.get("source", "Live Market Feed"),
            }
    except Exception:
        pass
    return None


def _compute_verified_metrics(initial_capital: float, closed_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes strictly verifiable performance metrics from closed trades (no fabricated figures)."""
    total = len(closed_trades)
    if total == 0:
        return {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "realized_pnl": 0.0,
            "equity_curve": [{"label": "Start", "equity": round(initial_capital, 2)}],
        }

    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    realized = 0.0

    # Chronological order for equity curve & peak-to-trough drawdown
    ordered = sorted(closed_trades, key=lambda t: str(t.get("closed_at") or t.get("exit_time") or ""))
    running_equity = float(initial_capital)
    peak_equity = running_equity
    max_dd_pct = 0.0
    curve = [{"label": "Start", "equity": round(running_equity, 2)}]

    for idx, t in enumerate(ordered, start=1):
        pnl = float(t.get("net_pnl") if t.get("net_pnl") is not None else (t.get("pnl") or 0.0))
        realized += pnl
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += abs(pnl)

        running_equity += pnl
        if running_equity > peak_equity:
            peak_equity = running_equity
        if peak_equity > 0:
            dd = ((peak_equity - running_equity) / peak_equity) * 100.0
            if dd > max_dd_pct:
                max_dd_pct = dd

        sym = t.get("symbol") or f"T{idx}"
        curve.append({"label": sym, "equity": round(running_equity, 2), "pnl": round(pnl, 2)})

    win_rate = round((wins / total) * 100.0, 2)
    if gross_loss > 0:
        pf = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        pf = round(gross_profit, 2)
    else:
        pf = 0.0

    return {
        "total_trades": total,
        "win_trades": wins,
        "loss_trades": losses,
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "max_drawdown_pct": round(max_dd_pct, 2),
        "realized_pnl": round(realized, 2),
        "equity_curve": curve,
    }


def get_dashboard_overview(user_id: str, username: str) -> Dict[str, Any]:
    """Aggregates real user portfolio state, verified trade analytics, watchlists, journals & alerts."""
    user_doc = db_manager.collection("users").find_one({"user_id": user_id}, {"_id": 0, "password_hash": 0})
    acc_doc = db_manager.collection("paper_accounts").find_one({"user_id": user_id, "is_default": True}, {"_id": 0})
    initial_cap = float(acc_doc.get("virtual_capital", 100000.0)) if acc_doc else 100000.0
    available_bal = float(acc_doc.get("available_balance", initial_cap)) if acc_doc else initial_cap
    unrealized_pnl = 0.0
    active_positions: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = list(
        db_manager.collection("paper_trades").find({"user_id": user_id}, {"_id": 0})
    )

    # Sync live state from PaperTradingManager for the authenticated user
    try:
        import fingroww_market_server as srv
        if hasattr(srv, "paper_manager") and srv.paper_manager:
            u_sess, _ = srv.paper_manager.get_session(username)
            state = u_sess.get_state()
            if state:
                initial_cap = float(state.get("initial_capital") or initial_cap)
                available_bal = float(state.get("available_cash") if state.get("available_cash") is not None else available_bal)
                unrealized_pnl = float(state.get("unrealized_pnl") or 0.0)
                active_positions = list(state.get("open_positions") or [])
                engine_trades = list(state.get("closed_trades") or [])
                if len(engine_trades) >= len(closed_trades):
                    closed_trades = engine_trades
    except Exception as exc:
        logger.debug("Paper manager sync skipped: %s", exc)

    metrics = _compute_verified_metrics(initial_cap, closed_trades)
    net_equity = round(initial_cap + metrics["realized_pnl"] + unrealized_pnl, 2)

    watchlists = list(db_manager.collection("watchlists").find({"user_id": user_id}, {"_id": 0}))
    watchlist_symbols_count = sum(len(w.get("items") or []) for w in watchlists)
    saved_signals_count = db_manager.collection("saved_signals").count_documents({"user_id": user_id})
    journals_count = db_manager.collection("trading_journals").count_documents({"user_id": user_id})
    unread_notifs = db_manager.collection("notifications").count_documents({"user_id": user_id, "is_read": False})
    academy_completed = db_manager.collection("academy_progress").count_documents({"user_id": user_id, "completed": True})

    return {
        "ok": True,
        "summary": {
            "virtual_capital": round(initial_cap, 2),
            "available_balance": round(available_bal, 2),
            "net_equity": net_equity,
            "realized_pnl": metrics["realized_pnl"],
            "unrealized_pnl": round(unrealized_pnl, 2),
            "win_rate_pct": metrics["win_rate_pct"],
            "profit_factor": metrics["profit_factor"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "total_trades": metrics["total_trades"],
            "win_trades": metrics["win_trades"],
            "loss_trades": metrics["loss_trades"],
        },
        "equity_curve": metrics["equity_curve"],
        "active_positions": active_positions,
        "recent_trades": sorted(
            closed_trades,
            key=lambda t: str(t.get("closed_at") or t.get("exit_time") or ""),
            reverse=True,
        )[:10],
        "counts": {
            "watchlists_items": watchlist_symbols_count,
            "saved_signals": saved_signals_count,
            "journal_entries": journals_count,
            "unread_notifications": unread_notifs,
            "academy_completed_lessons": academy_completed,
        },
        "subscription_plan": (user_doc or {}).get("subscription_plan", "free"),
    }


# -------------------------------------------------------------------------
# PERSONAL WATCHLISTS
# -------------------------------------------------------------------------
def get_watchlists(user_id: str, include_live_quotes: bool = True) -> List[Dict[str, Any]]:
    col = db_manager.collection("watchlists")
    lists = list(col.find({"user_id": user_id}, {"_id": 0}))
    if not lists:
        default_wl = {
            "watchlist_id": f"WL-{uuid.uuid4().hex[:8].upper()}",
            "user_id": user_id,
            "name": "Primary Watchlist",
            "items": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        col.insert_one(default_wl)
        lists = [default_wl]

    if include_live_quotes:
        for wl in lists:
            for item in wl.get("items") or []:
                q = _safe_live_quote(item["symbol"])
                if q:
                    item["ltp"] = q["lastPrice"]
                    item["pChange"] = q["pChange"]
                    item["quote_source"] = q["source"]
    return lists


def add_watchlist_item(
    user_id: str,
    watchlist_name: str,
    symbol: str,
    alert_above: Optional[float] = None,
    alert_below: Optional[float] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    col = db_manager.collection("watchlists")
    sym_clean = symbol.strip().upper()
    wl_name = (watchlist_name or "Primary Watchlist").strip()

    wl = col.find_one({"user_id": user_id, "name": wl_name})
    now_iso = _now_iso()
    new_item = {
        "symbol": sym_clean,
        "alert_above": alert_above,
        "alert_below": alert_below,
        "notes": notes,
        "added_at": now_iso,
    }

    if not wl:
        wl = {
            "watchlist_id": f"WL-{uuid.uuid4().hex[:8].upper()}",
            "user_id": user_id,
            "name": wl_name,
            "items": [new_item],
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        col.insert_one(wl)
    else:
        items = list(wl.get("items") or [])
        updated = False
        for i, existing in enumerate(items):
            if existing.get("symbol") == sym_clean:
                items[i] = {**existing, **new_item, "added_at": existing.get("added_at", now_iso)}
                updated = True
                break
        if not updated:
            items.append(new_item)
        col.update_one(
            {"user_id": user_id, "name": wl_name},
            {"$set": {"items": items, "updated_at": now_iso}},
        )

    return {"ok": True, "watchlists": get_watchlists(user_id, include_live_quotes=True)}


def remove_watchlist_item(user_id: str, watchlist_name: str, symbol: str) -> Dict[str, Any]:
    col = db_manager.collection("watchlists")
    sym_clean = symbol.strip().upper()
    wl_name = (watchlist_name or "Primary Watchlist").strip()

    wl = col.find_one({"user_id": user_id, "name": wl_name})
    if wl:
        items = [it for it in (wl.get("items") or []) if it.get("symbol") != sym_clean]
        col.update_one(
            {"user_id": user_id, "name": wl_name},
            {"$set": {"items": items, "updated_at": _now_iso()}},
        )
    return {"ok": True, "watchlists": get_watchlists(user_id, include_live_quotes=True)}


# -------------------------------------------------------------------------
# SAVED SIGNALS
# -------------------------------------------------------------------------
def get_saved_signals(user_id: str) -> List[Dict[str, Any]]:
    return list(
        db_manager.collection("saved_signals")
        .find({"user_id": user_id}, {"_id": 0})
        .sort("saved_at", -1)
    )


def save_signal_for_user(user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    col = db_manager.collection("saved_signals")
    doc = {
        "saved_id": f"SIG-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "symbol": str(payload["symbol"]).strip().upper(),
        "side": payload.get("side", "BUY"),
        "strategy": payload.get("strategy", "15m Confluence"),
        "entry_price": float(payload["entry_price"]),
        "stop_loss": float(payload["stop_loss"]),
        "target_1": float(payload["target_1"]),
        "target_2": float(payload["target_2"]) if payload.get("target_2") else None,
        "confidence": float(payload["confidence"]) if payload.get("confidence") is not None else None,
        "rationale": payload.get("rationale"),
        "status": "SAVED",
        "saved_at": _now_iso(),
    }
    col.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "signal": doc}


def delete_saved_signal(user_id: str, saved_id: str) -> bool:
    res = db_manager.collection("saved_signals").delete_one({"user_id": user_id, "saved_id": saved_id})
    return res.deleted_count > 0


# -------------------------------------------------------------------------
# USER NOTIFICATIONS
# -------------------------------------------------------------------------
def get_notifications(user_id: str, unread_only: bool = False, limit: int = 30) -> Dict[str, Any]:
    col = db_manager.collection("notifications")
    filt: Dict[str, Any] = {"user_id": user_id}
    if unread_only:
        filt["is_read"] = False
    items = list(col.find(filt, {"_id": 0}).sort("created_at", -1).limit(min(limit, 100)))
    unread_count = col.count_documents({"user_id": user_id, "is_read": False})
    return {"ok": True, "unread_count": unread_count, "notifications": items}


def mark_notifications_read(user_id: str, notification_id: Optional[str] = None, mark_all: bool = False) -> Dict[str, Any]:
    col = db_manager.collection("notifications")
    now_iso = _now_iso()
    if mark_all or not notification_id:
        col.update_many({"user_id": user_id, "is_read": False}, {"$set": {"is_read": True, "read_at": now_iso}})
    else:
        col.update_one(
            {"user_id": user_id, "notification_id": notification_id},
            {"$set": {"is_read": True, "read_at": now_iso}},
        )
    unread_count = col.count_documents({"user_id": user_id, "is_read": False})
    return {"ok": True, "unread_count": unread_count}
