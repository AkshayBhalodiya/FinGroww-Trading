"""
FinGroww Trading Intelligence — 11-Skill Confluence REST API Blueprint.
Modularized under routes/skills_routes.py for scalable, maintainable architecture.
"""

from flask import Blueprint, request, jsonify
import fingroww_market_server as srv
import uuid
from datetime import datetime, timezone

skills_bp = Blueprint("skills_api", __name__)


@skills_bp.get("/api/skills/suite")
def skills_suite():
    """Returns end-to-end synchronized intelligence across all 11 day-trading skills."""
    sym = srv.normalize_symbol(request.args.get("symbol", "NIFTY 50"))
    capital = float(request.args.get("capital", 100000.0))
    max_loss = float(request.args.get("max_loss", 2000.0))
    try:
        quote_data = srv.resolve_quote(sym) or {}
        price = float(quote_data.get("lastPrice") or 0.0)
        suite = srv.get_full_11_skill_suite(sym, price if price > 0 else None, capital, max_loss)

        # Inject live scanner quotes so all 15 symbols show genuine live prices
        live_quotes = srv.get_scanner_live_quotes()
        if live_quotes:
            if price > 0 and sym not in live_quotes:
                live_quotes[sym] = quote_data
            suite["skills"]["scanner"] = srv.IndianMarketScanner.scan(setup_filter="all", custom_quotes=live_quotes)
        return jsonify(suite)
    except Exception as exc:
        return jsonify({"error": str(exc), "symbol": sym}), 500


@skills_bp.get("/api/skills/scanner")
def skills_scanner():
    """Skill 1: Scans Indian universe for ORB 15m, 20D Breakouts, Bull Flags, Reclaims & Oversold Bounces."""
    setup = request.args.get("setup", "all").lower().strip()
    try:
        live_quotes = srv.get_scanner_live_quotes()
        res = srv.IndianMarketScanner.scan(setup_filter=setup, custom_quotes=live_quotes)
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@skills_bp.get("/api/skills/timemachine")
def skills_timemachine():
    """Skill 5: 10,000-run Monte Carlo simulation to evaluate target vs stop odds & expected value."""
    sym = srv.normalize_symbol(request.args.get("symbol", "NIFTY 50"))
    entry = float(request.args.get("entry", 0.0))
    stop = float(request.args.get("stop", 0.0))
    target = float(request.args.get("target", 0.0))
    replays = int(request.args.get("replays", 10000))

    if entry <= 0:
        quote_data = srv.resolve_quote(sym) or {}
        entry = float(quote_data.get("lastPrice") or 25000.0)
    if stop <= 0:
        stop = round(entry * 0.993, 2)
    if target <= 0:
        target = round(entry * 1.014, 2)

    try:
        res = srv.IndianTimeMachine.run_simulation(sym, entry, stop, target, replays=replays)
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@skills_bp.post("/api/skills/budget")
def skills_budget():
    """Skill 6: Professional Indian capital & F&O lot sizing engine."""
    data = request.get_json(silent=True) or {}
    sym = srv.normalize_symbol(data.get("symbol", "NIFTY 50"))
    entry = float(data.get("entry", 0.0))
    stop = float(data.get("stop", 0.0))
    target = float(data.get("target", 0.0))
    capital = float(data.get("capital", 100000.0))
    max_loss = float(data.get("max_loss", 2000.0))
    is_fo = bool(data.get("is_fo", False))

    if entry <= 0:
        quote_data = srv.resolve_quote(sym) or {}
        entry = float(quote_data.get("lastPrice") or 25000.0)
    if stop <= 0:
        stop = round(entry * 0.993, 2)
    if target <= 0:
        target = round(entry * 1.014, 2)

    try:
        res = srv.IndianBudgetManager.size_position(sym, entry, stop, target, capital, max_loss, is_fo)
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@skills_bp.post("/api/skills/risk-check")
def skills_risk_check():
    """Skill 7: Pre-trade risk check (Daily Loss Limit, Window, Overtrading, R:R)."""
    data = request.get_json(silent=True) or {}
    order = data.get("order") or data
    daily_pnl = float(data.get("daily_pnl", 0.0))
    trade_count = int(data.get("trade_count", 1))
    loss_limit = float(data.get("daily_loss_limit", 5000.0))
    try:
        res = srv.IndianRiskSupervisor.check_order(order, daily_pnl, trade_count, loss_limit)
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@skills_bp.post("/api/skills/paper-order")
def skills_paper_order():
    """Skill 8: Executes paper trade order or produces broker ticket."""
    data = request.get_json(silent=True) or {}
    sym = srv.normalize_symbol(data.get("symbol", "NIFTY 50"))
    entry = float(data.get("entry_price") or data.get("limit_price") or 24800.0)
    sl = float(data.get("stop_loss") or data.get("stop_loss_trigger") or 24650.0)
    tp = float(data.get("target_1") or data.get("target_trigger") or 25100.0)
    qty = int(data.get("quantity", 25))

    order_doc = {
        "order_id": f"ORD-PAPER-{uuid.uuid4().hex[:8].upper()}",
        "symbol": sym,
        "side": data.get("side", "BUY"),
        "quantity": qty,
        "entry_price": entry,
        "stop_loss": sl,
        "target_price": tp,
        "status": "FILLED (PAPER)",
        "filled_at": datetime.now(timezone.utc).isoformat(),
        "execution_engine": "FinGroww Paper Trading v7"
    }

    # Save to datastore
    srv.local_datastore["trade_outcomes"].append(order_doc)
    if srv.mongo_db is not None:
        try:
            srv.mongo_db["trade_outcomes"].insert_one(dict(order_doc))
        except Exception:
            pass

    return jsonify({"ok": True, "order": order_doc}), 201


@skills_bp.get("/api/skills/institutional")
def skills_institutional():
    """Skill 11: Indian Pelosi tracker — FII / DII net cash & F&O flows, Bulk & Block deals."""
    try:
        res = srv.IndianInstitutionalTracker.get_institutional_flow()
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@skills_bp.get("/api/skills/analyst")
def skills_analyst():
    """Skill 10: Quarterly earnings & margin scorecard for NSE stock."""
    sym = srv.normalize_symbol(request.args.get("symbol", "RELIANCE"))
    try:
        res = srv.IndianEarningsAnalyst.get_fundamentals(sym)
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@skills_bp.get("/api/skills/news")
def skills_news():
    """Skill 2: Company announcements & catalyst news."""
    sym = srv.normalize_symbol(request.args.get("symbol", "NIFTY 50"))
    try:
        res = srv.IndianMarketNews.get_news(sym)
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@skills_bp.get("/api/skills/alerts")
def skills_alerts():
    """Skill 9: Real-time price alerts & 15:15 IST flatten watchers."""
    sym = request.args.get("symbol")
    try:
        res = srv.IndianAlertsManager.get_alerts(sym)
        return jsonify({"alerts": res})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
