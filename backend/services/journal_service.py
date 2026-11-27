"""
FinGroww SaaS Platform — Trading Journal & Verifiable AI Trading Coach Service (Phase 3).
"""

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.database import db_manager


class JournalError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_entry_feedback(entry: Dict[str, Any]) -> str:
    """Produces deterministic, rule-based coaching feedback for a single journal entry."""
    notes = []
    mood = entry.get("mood", "disciplined")
    rules_ok = bool(entry.get("rules_followed", True))
    mistakes = entry.get("mistake_tags") or []
    pnl = entry.get("net_pnl")

    if not rules_ok:
        notes.append("Rule breach logged — prioritize process compliance over outcome on the next setup.")
    if mood in ("fomo", "revenge", "anxious"):
        notes.append(f"Emotional trigger detected ('{mood}'): step away for 15 minutes after any impulsive execution.")
    if "moved_stop_loss" in mistakes:
        notes.append("Never widen stop-loss once entered; predefined risk protects account longevity.")
    if "oversized_position" in mistakes:
        notes.append("Position exceeded standard 1-2% risk budget; recalibrate quantity via Position Sizing Calculator.")
    if "chased_entry" in mistakes:
        notes.append("Wait for 15m/5m pullback confirmation into VWAP or 0.618 Fibonacci zone instead of chasing extended candles.")
    if not notes:
        if pnl is not None and float(pnl) < 0:
            notes.append("Disciplined loss: setup followed rules and respected stop-loss. Good execution.")
        else:
            notes.append("Clean, rule-compliant trade execution aligned with FinGroww discipline standards.")
    return " ".join(notes)


def list_journals(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    return list(
        db_manager.collection("trading_journals")
        .find({"user_id": user_id}, {"_id": 0})
        .sort("trade_date", -1)
        .limit(min(limit, 200))
    )


def create_journal_entry(user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    now_iso = _now_iso()
    entry = {
        "journal_id": f"JRN-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "account_id": payload.get("account_id"),
        "trade_id": payload.get("trade_id"),
        "symbol": str(payload["symbol"]).strip().upper(),
        "side": payload.get("side", "BUY"),
        "entry_price": payload.get("entry_price"),
        "exit_price": payload.get("exit_price"),
        "net_pnl": float(payload["net_pnl"]) if payload.get("net_pnl") is not None else None,
        "timeframe": payload.get("timeframe", "15m"),
        "setup_tag": payload.get("setup_tag", "15m Fib Golden Zone"),
        "mood": payload.get("mood", "disciplined"),
        "rules_followed": bool(payload.get("rules_followed", True)),
        "mistake_tags": list(payload.get("mistake_tags") or []),
        "notes": payload.get("notes", ""),
        "trade_date": now_iso,
        "created_at": now_iso,
    }
    entry["ai_feedback"] = _generate_entry_feedback(entry)
    db_manager.collection("trading_journals").insert_one(entry)
    entry.pop("_id", None)
    return {"ok": True, "entry": entry}


def update_journal_entry(user_id: str, journal_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    col = db_manager.collection("trading_journals")
    existing = col.find_one({"user_id": user_id, "journal_id": journal_id}, {"_id": 0})
    if not existing:
        raise JournalError("Journal entry not found or unauthorized", 404)

    clean = {k: v for k, v in updates.items() if v is not None}
    merged = {**existing, **clean}
    clean["ai_feedback"] = _generate_entry_feedback(merged)
    clean["updated_at"] = _now_iso()
    col.update_one({"user_id": user_id, "journal_id": journal_id}, {"$set": clean})
    return {"ok": True, "entry": col.find_one({"user_id": user_id, "journal_id": journal_id}, {"_id": 0})}


def delete_journal_entry(user_id: str, journal_id: str) -> bool:
    res = db_manager.collection("trading_journals").delete_one({"user_id": user_id, "journal_id": journal_id})
    return res.deleted_count > 0


def get_ai_coach_insights(user_id: str) -> Dict[str, Any]:
    """Computes verifiable, data-backed AI Trading Coach diagnostics from journal + closed trades."""
    journals = list(db_manager.collection("trading_journals").find({"user_id": user_id}, {"_id": 0}))
    trades = list(db_manager.collection("paper_trades").find({"user_id": user_id}, {"_id": 0}))

    j_count = len(journals)
    t_count = len(trades)
    if j_count == 0 and t_count == 0:
        return {
            "ok": True,
            "has_sufficient_data": False,
            "discipline_score": None,
            "stats": {"journal_entries": 0, "closed_trades": 0, "rule_compliance_pct": None},
            "top_mistakes": [],
            "emotional_leakage_inr": 0.0,
            "recommendations": [
                "Log your first 3-5 paper trades and journal entries so the AI Coach can analyze your execution discipline and emotional patterns."
            ],
        }

    # Journal analytics
    compliant_count = sum(1 for j in journals if j.get("rules_followed", True))
    rule_compliance_pct = round((compliant_count / j_count) * 100.0, 1) if j_count > 0 else 100.0

    mistake_counter: Counter = Counter()
    emotional_pnl = 0.0
    emotional_trades = 0
    for j in journals:
        for tag in (j.get("mistake_tags") or []):
            mistake_counter[tag] += 1
        if j.get("mood") in ("fomo", "revenge", "anxious"):
            emotional_trades += 1
            if j.get("net_pnl") is not None:
                emotional_pnl += float(j["net_pnl"])

    top_mistakes = [{"tag": tag, "count": cnt} for tag, cnt in mistake_counter.most_common(4)]

    # Trade win rate
    wins = sum(1 for t in trades if float(t.get("net_pnl", 0)) > 0)
    win_rate = round((wins / t_count) * 100.0, 1) if t_count > 0 else None

    # Compute discipline score strictly from logged compliance minus penalty for high mistake density
    discipline_score = round(max(0.0, min(100.0, rule_compliance_pct - (emotional_trades / max(1, j_count)) * 15.0)), 1) if j_count > 0 else None

    recs: List[str] = []
    if j_count > 0 and rule_compliance_pct < 75.0:
        recs.append(f"Your rule compliance is {rule_compliance_pct}%. Pause automated entries until compliance exceeds 80% over 10 consecutive trades.")
    if emotional_trades > 0:
        recs.append(f"Detected {emotional_trades} emotional trade(s) (FOMO/Revenge/Anxious) with net impact ₹{emotional_pnl:,.2f}. Enforce a mandatory 15-minute cooldown after losses.")
    if top_mistakes:
        top_tag, top_cnt = top_mistakes[0]["tag"], top_mistakes[0]["count"]
        recs.append(f"Most frequent mistake: '{top_tag}' ({top_cnt} times). Make eliminating this habit your single priority this week.")
    if win_rate is not None and win_rate < 45.0:
        recs.append(f"Verified closed trade win rate is {win_rate}%. Require full 3-timeframe confluence (1H + 15M + 5M) before taking entries.")
    if not recs:
        recs.append("Execution discipline is strong. Continue logging post-trade emotions and keep risk capped at 1-2% per setup.")

    return {
        "ok": True,
        "has_sufficient_data": True,
        "discipline_score": discipline_score,
        "stats": {
            "journal_entries": j_count,
            "closed_trades": t_count,
            "rule_compliance_pct": rule_compliance_pct if j_count > 0 else None,
            "verified_win_rate_pct": win_rate,
        },
        "top_mistakes": top_mistakes,
        "emotional_leakage_inr": round(emotional_pnl, 2),
        "recommendations": recs,
    }
