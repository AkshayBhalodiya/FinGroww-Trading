"""
FinGroww Trading Intelligence — AI-Powered Automated Paper Trading REST API Blueprint.
Modularized under routes/paper_routes.py.
"""

import time
import json
import csv
import io
import queue
import threading
from flask import Blueprint, request, jsonify, Response
import fingroww_market_server as srv
import fingroww_paper_engine as pe
from cache_manager import session_stream_hub

paper_bp = Blueprint("paper_api", __name__)


@paper_bp.get("/api/paper/market-status")
@paper_bp.get("/api/market-status")
def paper_market_status():
    """Returns NSE's official market status and the paper engine's quote policy."""
    ist = srv.get_ist_now()
    market = srv.get_nse_market_status()
    is_open = market["is_trading_hours"]
    return jsonify({
        "market": "NSE India Capital Market",
        "market_status": market["market_status"],
        "is_trading_hours": is_open,
        "ist_time": ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "time_str": ist.strftime("%I:%M:%S %p IST"),
        "date_str": ist.strftime("%A, %d %B %Y"),
        "freshness": "REAL_TIME_LIVE" if is_open else "NO_LIVE_TRADING",
        "provider": "NSE live quotes; Yahoo Finance historical indicator candles",
        "market_status_source": market["source"],
        "market_status_reason": market["reason"],
        "trade_date": market["trade_date"],
        "latency_ms": None,
        "server_timestamp": time.time(),
    })


@paper_bp.get("/api/paper/session/state")
def paper_session_state():
    """Returns full real-time session state, account metrics, active positions, and logs for a user."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    return jsonify(u_sess.get_state())


@paper_bp.post("/api/paper/session/config")
@paper_bp.route("/api/paper/config", methods=["GET", "POST"])
def paper_update_config():
    """Validates and updates paper trading session configuration for a user."""
    data = request.get_json(silent=True) or {}
    u_sess, u_eng = srv.get_user_session_and_engine(request)

    # Input validation
    if "initial_capital" in data:
        try:
            val = float(data["initial_capital"])
            if val < 5000.0:
                return jsonify({"error": "Initial virtual capital must be at least ₹5,000."}), 400
            if u_sess.status == "IDLE":
                u_sess.reset(initial_capital=val)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid initial capital amount."}), 400

    # Support minutes, hours, days, weeks, and months
    if "duration_val" in data and "duration_unit" in data:
        try:
            d_val = float(data["duration_val"])
            d_unit = (data["duration_unit"] or "minutes").lower().strip()
            unit_mult = {
                "seconds": 1 / 60.0,
                "second": 1 / 60.0,
                "sec": 1 / 60.0,
                "minutes": 1,
                "minute": 1,
                "min": 1,
                "hours": 60,
                "hour": 60,
                "days": 1440,
                "day": 1440,
                "weeks": 10080,
                "week": 10080,
                "months": 43200,
                "month": 43200,
            }
            mult = unit_mult.get(d_unit, 1)
            data["holding_duration_mins"] = d_val * mult
        except (ValueError, TypeError):
            pass

    if "holding_duration_mins" in data:
        try:
            dur = float(data["holding_duration_mins"])
            # Allow from 0.1 minutes (~6 seconds) up to 1 year (525,600 minutes)
            if dur < 0.1 or dur > 525600:
                return jsonify({"error": "Holding duration must be between 10 seconds and 12 months."}), 400
            data["holding_duration_mins"] = dur
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid holding duration value."}), 400

    if "instruments" in data:
        insts = data["instruments"]
        if not isinstance(insts, list) or len(insts) == 0:
            return jsonify({"error": "Please select at least one trading instrument."}), 400

    if "market_caps" in data:
        mcaps = data["market_caps"]
        if not isinstance(mcaps, list) or len(mcaps) == 0:
            return jsonify({"error": "Please select at least one market cap segment."}), 400

    if "max_open_positions" in data:
        try:
            m_pos = int(data["max_open_positions"])
            if 1 <= m_pos <= 50:
                data["max_open_positions"] = m_pos
        except (ValueError, TypeError):
            pass

    if "stop_loss_pct" in data:
        try:
            if data["stop_loss_pct"] is not None and str(data["stop_loss_pct"]).strip() != "":
                sl_val = float(data["stop_loss_pct"])
                if sl_val <= 0 or sl_val > 95:
                    return jsonify({"error": "Stop Loss (%) must be between 0.5% and 95%."}), 400
                data["stop_loss_pct"] = sl_val
            else:
                return jsonify({"error": "Stop Loss (%) is mandatory for every trade."}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid Stop Loss percentage value."}), 400

    if "target_pct" in data:
        try:
            if data["target_pct"] is not None and str(data["target_pct"]).strip() != "":
                tp_val = float(data["target_pct"])
                if tp_val <= 0 or tp_val > 500:
                    return jsonify({"error": "Target (%) must be between 0.5% and 500%."}), 400
                data["target_pct"] = tp_val
            else:
                data["target_pct"] = None
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid Target percentage value."}), 400

    u_sess.update_config(data)
    u_eng.last_scan_at = 0.0
    u_sess.save_to_db()
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)
    return jsonify({"ok": True, "state": st})


@paper_bp.post("/api/paper/session/start")
@paper_bp.route("/api/paper/start", methods=["POST"])
def paper_start_session():
    """Validates inputs and starts the AI auto paper trading engine for a user."""
    data = request.get_json(silent=True) or {}
    u_sess, u_eng = srv.get_user_session_and_engine(request)
    market_status = srv.get_nse_market_status()
    if not market_status["is_trading_hours"] and not data.get("allow_offline", False):
        return jsonify({
            "error": "Paper trading can only be started while NSE's regular market is confirmed open.",
            "market_status": market_status,
        }), 409
    if data:
        u_sess.update_config(data)

    u_sess.start()
    u_sess.save_to_db()
    # Trigger first tick immediately
    state = u_eng.tick()
    session_stream_hub.broadcast(u_sess.user_name, state)
    return jsonify({"ok": True, "message": f"AI Auto Paper Trading started for {u_sess.user_name}.", "state": state})


@paper_bp.post("/api/paper/session/control")
@paper_bp.post("/api/paper/session/stop")
def paper_session_control():
    """Handles session state transitions: pause, resume, stop_new_trades, close_all, reset, stop."""
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or ("stop" if request.path.endswith("/stop") else "")).lower().strip()
    u_sess, _ = srv.get_user_session_and_engine(request)

    if action in ("pause", "stop"):
        u_sess.pause()
    elif action == "resume":
        market_status = srv.get_nse_market_status()
        if not market_status["is_trading_hours"]:
            return jsonify({
                "error": "Paper trading cannot be resumed while NSE is closed or its market status is unavailable.",
                "market_status": market_status,
            }), 409
        u_sess.resume()
    elif action == "stop_new_trades":
        u_sess.stop_new_trades()
    elif action == "close_all":
        market_open = srv.get_nse_market_status()["is_trading_hours"]
        if not market_open:
            return jsonify({"error": "NSE market is closed or its status is unavailable; positions were not closed."}), 409
        count = u_sess.close_all_positions(
            reason="MANUAL_CLOSE_ALL",
            quote_resolver=srv.paper_manager.quote_resolver,
            market_is_open=market_open,
            option_quote_resolver=srv.paper_manager.option_quote_resolver,
        )
    elif action == "reset":
        cap = data.get("initial_capital")
        u_sess.reset(initial_capital=cap)
    else:
        return jsonify({"error": f"Unknown control action: {action}"}), 400

    u_sess.save_to_db()
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)
    return jsonify({"ok": True, "action": action, "state": st})


@paper_bp.post("/api/paper/session/tick")
@paper_bp.route("/api/paper/engine/tick", methods=["GET", "POST"])
@paper_bp.route("/api/paper/tick", methods=["GET", "POST"])
def paper_session_tick():
    """Triggers one evaluation cycle for a user session."""
    u_sess, u_eng = srv.get_user_session_and_engine(request)
    state = u_eng.tick()
    session_stream_hub.broadcast(u_sess.user_name, state)
    return jsonify({"ok": True, "state": state})


@paper_bp.route("/api/paper/session/scan", methods=["GET", "POST"])
@paper_bp.route("/api/paper/scan", methods=["GET", "POST"])
def paper_session_scan():
    """Read-only 15-minute setup radar scan matching user's active configuration (never auto-executes)."""
    data = request.get_json(silent=True) or {}
    u_sess, u_eng = srv.get_user_session_and_engine(request)

    scan_patch = {}
    for k in ("instruments", "market_caps", "trading_style", "risk_profile"):
        if k in data and data[k]:
            scan_patch[k] = data[k]
    if scan_patch:
        u_sess.update_config(scan_patch)

    force = bool(data.get("force", False) or request.args.get("force") in ("true", "1"))
    if force:
        def _bg_scan():
            try:
                u_eng.scan_and_evaluate_setups(force=True)
            except Exception:
                pass
        threading.Thread(target=_bg_scan, daemon=True).start()
    else:
        try:
            u_eng.scan_and_evaluate_setups(force=False)
        except Exception:
            pass

    market_status = srv.get_nse_market_status()

    # Optional pagination support for API callers
    page = int(request.args.get("page") or data.get("page") or 1)
    limit = int(request.args.get("limit") or data.get("limit") or 0)

    signals = list(u_sess.scanned_signals or [])
    total_count = len(signals)
    if limit > 0:
        start_idx = max(0, (page - 1) * limit)
        paged_signals = signals[start_idx:start_idx + limit]
    else:
        paged_signals = signals

    return jsonify({
        "ok": True,
        "market_open": bool(market_status.get("is_trading_hours")),
        "count": total_count,
        "page": page,
        "limit": limit if limit > 0 else total_count,
        "total_pages": (total_count + limit - 1) // limit if limit > 0 else 1,
        "scanned_signals": paged_signals,
        "state": u_sess.get_state(),
    })


@paper_bp.get("/api/paper/positions")
def paper_get_positions():
    """Returns active open stock/instrument positions for a user with live PnL and MongoDB persistence."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    positions = u_sess.positions
    if not positions and srv.mongo_db is not None:
        try:
            db_positions = list(srv.mongo_db["paper_positions"].find({"user_name": u_sess.user_name, "status": "OPEN"}, {"_id": 0}))
            if db_positions:
                positions = db_positions
        except Exception:
            pass

    return jsonify({
        "user_name": u_sess.user_name,
        "count": len(positions),
        "positions": positions,
        "total_unrealized_pnl": u_sess.unrealized_pnl,
        "account_equity": u_sess.account_equity,
        "allocated_margin": u_sess.allocated_margin,
    })


@paper_bp.get("/api/paper/trades")
def paper_get_trades():
    """Returns complete trade history for a user with filtering by instrument and outcome."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    trades = list(u_sess.closed_trades)
    inst_filter = request.args.get("instrument")
    outcome_filter = request.args.get("outcome")

    if inst_filter and inst_filter != "ALL":
        trades = [t for t in trades if t.get("instrument_type") == inst_filter]
    if outcome_filter:
        is_win = (outcome_filter.upper() == "WIN")
        trades = [t for t in trades if t.get("is_win") == is_win]

    limit_param = request.args.get("limit")
    if limit_param and str(limit_param).lower() not in ("all", "0", "none"):
        try:
            limit = max(int(limit_param), 1)
            trades = trades[:limit]
        except (ValueError, TypeError):
            pass

    return jsonify({
        "user_name": u_sess.user_name,
        "count": len(trades),
        "total_closed_trades": len(u_sess.closed_trades),
        "trades": trades,
    })


@paper_bp.get("/api/paper/export-csv")
@paper_bp.get("/api/paper/export/trades.csv")
@paper_bp.get("/api/paper/trades/export")
def paper_export_trades_csv():
    """Direct streaming/download endpoint for all closed trades in RFC 4180 CSV format with all details."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    trades = list(u_sess.closed_trades)

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Microsoft Excel
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    headers = [
        "Trade ID", "Symbol", "Company Name", "Instrument", "Execution Type", "Side", "Expiry / Contract",
        "Entry Time", "Exit Time", "Holding Duration", "Quantity",
        "Entry Price (₹)", "Exit Price (₹)", "Stop Loss (₹)", "Stop Loss %", "Target (₹)", "Target %",
        "Margin Used (₹)", "Gross PnL (₹)", "Charges & Taxes (₹)", "Slippage (₹)", "Net PnL (₹)", "ROI %",
        "Outcome", "Exit Reason", "Strategy", "Signal Rationale", "Market Data Source"
    ]
    writer.writerow(headers)

    for t in trades:
        margin = t.get("allocated_margin") or t.get("used_amount") or ((t.get("entry_price") or 0) * (t.get("quantity") or 0))
        writer.writerow([
            t.get("trade_id", ""),
            t.get("symbol", ""),
            t.get("name", t.get("symbol", "")),
            t.get("instrument_type", ""),
            t.get("execution_type", "AUTO"),
            t.get("side", ""),
            t.get("expiry_label") or t.get("expiry_date") or "N/A",
            t.get("entry_time", ""),
            t.get("exit_time") or t.get("closed_at", ""),
            t.get("holding_duration_str", ""),
            t.get("quantity", 0),
            round(float(t.get("entry_price") or 0), 2),
            round(float(t.get("exit_price") or 0), 2),
            round(float(t.get("stop_loss") or 0), 2) if t.get("stop_loss") is not None else "",
            f"{t.get('stop_loss_pct')}%" if t.get("stop_loss_pct") is not None else "",
            round(float(t.get("target_price") or 0), 2) if t.get("target_price") else "Open",
            f"{t.get('target_pct')}%" if t.get("target_pct") else "Open",
            round(float(margin or 0), 2),
            round(float(t.get("gross_pnl") or 0), 2),
            round(float(t.get("charges") or 0), 2),
            round(float(t.get("slippage") or 0), 2),
            round(float(t.get("net_pnl") or 0), 2),
            f"{round(float(t.get('return_pct') or 0), 2)}%",
            "WIN" if t.get("is_win") else "LOSS",
            t.get("exit_reason", ""),
            t.get("strategy", ""),
            t.get("signal_rationale", ""),
            t.get("market_data_source", "NSE Live")
        ])

    csv_data = output.getvalue()
    filename = f"FinGroww_{u_sess.user_name}_Paper_Trades_{int(time.time())}.csv"
    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )


@paper_bp.get("/api/paper/analytics")
def paper_get_analytics():
    """Returns quantitative performance analytics for a user with execution mode filter."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    mode = request.args.get("mode") or request.args.get("execution_type")
    analytics = u_sess.get_performance_analytics(execution_type=mode)
    analytics["user_name"] = u_sess.user_name
    return jsonify(analytics)


@paper_bp.post("/api/paper/manual-close")
@paper_bp.post("/api/paper/position/close")
def paper_manual_close():
    """Manually closes a specific open trade position by ID or symbol for a user."""
    data = request.get_json(silent=True) or {}
    u_sess, _ = srv.get_user_session_and_engine(request)
    trade_id = data.get("trade_id")
    if not trade_id and data.get("symbol"):
        sym = str(data.get("symbol")).strip().upper()
        for p in u_sess.positions:
            if p.get("symbol", "").upper() == sym or p.get("base_symbol", "").upper() == sym:
                trade_id = p.get("trade_id")
                break
    if not trade_id:
        return jsonify({"error": "Missing trade_id"}), 400

    market_open = srv.get_nse_market_status()["is_trading_hours"]
    force = bool(data.get("force", False) or not market_open)
    ok, msg = u_sess.manual_close_position(
        trade_id,
        quote_resolver=srv.paper_manager.quote_resolver,
        market_is_open=market_open,
        option_quote_resolver=srv.paper_manager.option_quote_resolver,
        force=force,
    )
    if not ok:
        return jsonify({"error": msg}), 404 if msg == "Position not found." else 409
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)
    return jsonify({"ok": True, "success": True, "message": msg, "state": st})


@paper_bp.post("/api/paper/test-expire-position")
def paper_test_expire_position():
    """Immediately triggers duration expiration for an active position to test auto-closure in real time."""
    data = request.get_json(silent=True) or {}
    trade_id = data.get("trade_id")
    if not trade_id:
        return jsonify({"error": "Missing trade_id"}), 400

    u_sess, u_eng = srv.get_user_session_and_engine(request)
    if not srv.get_nse_market_status()["is_trading_hours"]:
        return jsonify({"error": "NSE market is closed or its status is unavailable."}), 409
    ok, msg = u_sess.test_expire_position(
        trade_id,
        u_eng.quote_resolver,
        market_is_open=True,
        option_quote_resolver=u_eng.option_quote_resolver,
    )
    if not ok:
        return jsonify({"error": msg}), 404
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)
    return jsonify({"ok": True, "message": msg, "state": st})


@paper_bp.post("/api/paper/manual-order")
def paper_manual_order():
    """Places an immediate manual paper trade for a user session with mandatory SL."""
    data = request.get_json(silent=True) or {}
    u_sess, u_eng = srv.get_user_session_and_engine(request)
    if not u_sess:
        return jsonify({"ok": False, "error": "User session not found."}), 404

    # If payload is formatted as setup object (1-click style), forward to execute_trade
    if "setup" in data or ("symbol" in data and "strike" not in data):
        return paper_order_execute()

    base_sym = data.get("base_symbol") or data.get("symbol") or "NIFTY 50"
    strike = data.get("strike")
    if strike is None or str(strike).strip() == "":
        return jsonify({"ok": False, "error": "Strike price is required."}), 400

    opt_type = data.get("option_type", "CE")
    stop_loss = data.get("stop_loss")
    stop_loss_pct = data.get("stop_loss_pct")
    target_price = data.get("target_price")
    algo_target = bool(data.get("algo_target", False))
    lots = int(data.get("lots") or 1)
    holding_mins = float(data.get("holding_duration_mins") or 1440)

    market_status = srv.get_nse_market_status()
    market_is_open = bool(market_status.get("is_trading_hours"))

    pos, err = u_sess.execute_manual_trade(
        base_symbol=base_sym,
        strike=strike,
        option_type=opt_type,
        stop_loss=stop_loss,
        stop_loss_pct=stop_loss_pct,
        target_price=target_price,
        algo_target=algo_target,
        lots=lots,
        holding_duration_mins=holding_mins,
        quote_resolver=srv.resolve_paper_quote,
        option_quote_resolver=srv.resolve_option_quote,
        market_is_open=market_is_open,
    )

    if not pos:
        return jsonify({"ok": False, "error": err}), 400

    u_sess.save_to_db()
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)

    return jsonify({
        "ok": True,
        "success": True,
        "message": f"Manual trade executed for {pos['symbol']}",
        "position": pos,
        "state": st,
    })


@paper_bp.get("/api/paper/option-quote")
def paper_option_quote():
    """Returns live quote, lot size, and margin details for a specific strike and CE/PE contract."""
    from fingroww_paper_engine import DEFAULT_SPOTS
    sym = request.args.get("symbol") or "NIFTY 50"
    strike = request.args.get("strike")
    opt_type = request.args.get("option_type") or "CE"

    base_sym = srv.normalize_symbol(sym)
    quote = srv.resolve_paper_quote(base_sym) or {}
    spot_price = float(quote.get("lastPrice") or DEFAULT_SPOTS.get(base_sym, 24500.0))

    step = 50 if "NIFTY" in base_sym and "BANK" not in base_sym else (100 if "BANK" in base_sym else 50)
    if not strike:
        strike_val = int(round(spot_price / step) * step)
    else:
        try:
            strike_val = float(strike)
            strike_val = int(strike_val) if strike_val == int(strike_val) else round(strike_val, 2)
        except ValueError:
            strike_val = int(round(spot_price / step) * step)

    opt_quote = srv.resolve_option_quote(base_sym, strike_val, opt_type)
    premium = float(opt_quote.get("lastPrice") or 0.0) if opt_quote else 0.0

    if premium <= 0:
        dist = abs(strike_val - spot_price) / max(spot_price, 1.0)
        time_val = spot_price * 0.015 * max(0.2, 1.0 - dist * 5)
        intrinsic = max(0.0, (spot_price - strike_val) if opt_type.upper() == "CE" else (strike_val - spot_price))
        premium = round(max(1.0, intrinsic + time_val), 2)

    lot_size = srv.LOT_SIZES.get(base_sym.upper())
    if not lot_size:
        for k, v in srv.LOT_SIZES.items():
            if k in base_sym.upper():
                lot_size = v
                break
    lot_size = lot_size or (25 if "NIFTY" in base_sym else 15)
    margin_1_lot = round(premium * lot_size, 2)

    suggested_sl = max(0.05, round(premium * 0.80, 2))
    suggested_target = round(premium + ((premium - suggested_sl) * 1.80), 2)

    return jsonify({
        "ok": True,
        "base_symbol": base_sym,
        "spot_price": spot_price,
        "strike": strike_val,
        "option_type": opt_type.upper(),
        "premium": premium,
        "lastPrice": premium,
        "lot_size": lot_size,
        "margin_1_lot": margin_1_lot,
        "suggested_sl": suggested_sl,
        "suggested_target": suggested_target,
        "expiry_label": (opt_quote or {}).get("expiry_label") or "Upcoming Expiry",
        "market_source": (opt_quote or {}).get("source") or "NSE / Fair Value",
    })


@paper_bp.post("/api/paper/order/execute")
def paper_order_execute():
    """1-Click manual or external paper trade execution (from options.html / today-options.html / ticket)."""
    data = request.get_json(silent=True) or {}
    u_sess, u_eng = srv.get_user_session_and_engine(request)
    if not u_sess:
        return jsonify({"ok": False, "error": "User session not found."}), 404

    sym = str(data.get("symbol") or "NIFTY24000CE").strip().upper()
    base_sym = str(data.get("base_symbol") or sym.split()[0]).strip().upper()
    inst_type = str(data.get("instrument_type") or ("INDEX_OPTIONS" if "CE" in sym or "PE" in sym else "EQUITY")).strip().upper()
    side = str(data.get("side") or "BUY").strip().upper()
    entry_p = float(data.get("entry_price") or data.get("price") or 100.0)
    sl = float(data.get("stop_loss") or (entry_p * 0.8 if side == "BUY" else entry_p * 1.2))
    tp = float(data.get("target_price") or (entry_p * 1.3 if side == "BUY" else entry_p * 0.7))
    lot_size = srv.LOT_SIZES.get(base_sym, 25) if ("OPTION" in inst_type or "FUTURE" in inst_type) else 1
    qty = int(data.get("quantity") or data.get("qty") or (lot_size if ("OPTION" in inst_type or "FUTURE" in inst_type) else 10))
    strat = str(data.get("strategy") or "1-Click Options Execution")

    setup = {
        "symbol": sym,
        "base_symbol": base_sym,
        "name": sym,
        "instrument_type": inst_type,
        "side": side,
        "entry_price": entry_p,
        "stop_loss": sl,
        "target_price": tp,
        "quantity": qty,
        "lot_size": lot_size,
        "risk_distance": abs(entry_p - sl),
        "reward_risk": round(abs(tp - entry_p) / max(0.01, abs(entry_p - sl)), 2),
        "strategy": strat,
        "is_manual": True,
        "allow_offline": True,
        "confidence_score": 92,
        "rationale": f"1-Click paper trade placed from FinGroww Terminal ({strat})"
    }

    if "OPTION" in inst_type:
        setup["strike"] = data.get("strike")
        setup["option_type"] = data.get("option_type") or ("CE" if "CE" in sym else "PE")
        setup["expiry_date"] = data.get("expiry_date")
        setup["expiry_label"] = data.get("expiry_label")

    market_open = srv.get_nse_market_status()["is_trading_hours"]
    pos, err = u_sess.execute_trade(
        setup,
        quote_resolver=None,
        market_is_open=market_open,
        option_quote_resolver=None,
        is_manual=True
    )
    if not pos:
        return jsonify({"ok": False, "error": err or "Order execution rejected."}), 400

    u_sess.save_to_db()
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)
    return jsonify({
        "ok": True,
        "success": True,
        "message": f"Successfully executed 1-click paper order for {sym} ({side}) @ ₹{entry_p:,.2f}",
        "position": pos,
        "state": st,
        "available_balance": u_sess.available_balance,
        "active_positions_count": len(u_sess.positions)
    })


@paper_bp.post("/api/paper/circuit-breaker/trigger")
def paper_trigger_circuit_breaker():
    """Manually triggers the daily max drawdown circuit breaker for testing or safety."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    if not u_sess:
        return jsonify({"ok": False, "error": "User session not found."}), 404
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "Daily Max Drawdown breached (simulated).")
    u_sess.is_circuit_breaker_triggered = True
    u_sess.circuit_breaker_reason = reason
    u_sess.save_to_db()
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)
    return jsonify({
        "ok": True,
        "success": True,
        "message": f"Circuit Breaker triggered: {reason}",
        "state": st
    })


@paper_bp.post("/api/paper/circuit-breaker/reset")
def paper_reset_circuit_breaker():
    """Manually resets the daily max drawdown circuit breaker."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    if not u_sess:
        return jsonify({"ok": False, "error": "User session not found."}), 404
    u_sess.reset_circuit_breaker()
    u_sess.status = "RUNNING"
    u_sess.save_to_db()
    st = u_sess.get_state()
    session_stream_hub.broadcast(u_sess.user_name, st)
    return jsonify({
        "ok": True,
        "message": "Circuit Breaker successfully reset. Autonomous trading resumed.",
        "state": st
    })


@paper_bp.get("/api/paper/stream")
def paper_sse_stream():
    """Server-Sent Events (SSE) real-time streaming endpoint for zero-latency UI updates."""
    u_sess, _ = srv.get_user_session_and_engine(request)
    uname = u_sess.user_name if u_sess else "Akshay"
    client_q = session_stream_hub.subscribe(uname)

    def event_stream():
        start_t = time.time()
        last_heartbeat = start_t
        try:
            # 1. Immediately push current session state on initial connection
            initial_state = u_sess.get_state() if u_sess else {}
            yield f"event: tick\ndata: {json.dumps(initial_state, default=str)}\n\n"

            # 2. Event-driven push from queue + keepalive heartbeats
            while time.time() - start_t < 300:
                try:
                    # Reactive wake-up whenever an order, tick, or breaker event occurs
                    state = client_q.get(timeout=2.0)
                    yield f"event: tick\ndata: {json.dumps(state, default=str)}\n\n"
                    last_heartbeat = time.time()
                except queue.Empty:
                    # Periodically emit keepalive ping so proxy/firewall does not drop connection
                    now = time.time()
                    if now - last_heartbeat >= 15.0:
                        last_heartbeat = now
                        yield f": heartbeat {int(now)}\n\n"
        except GeneratorExit:
            pass
        except Exception as e:
            srv.logger.debug("SSE stream connection ended: %s", e)
        finally:
            session_stream_hub.unsubscribe(uname, client_q)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


@paper_bp.post("/api/paper/alerts/telegram/test")
def paper_test_telegram_alert():
    """Tests Telegram bot connectivity and sends verification notification."""
    data = request.get_json(silent=True) or {}
    u_sess, _ = srv.get_user_session_and_engine(request)
    cfg = dict(u_sess.config) if u_sess else {}
    if data.get("bot_token"):
        cfg["telegram_bot_token"] = data["bot_token"]
    if data.get("chat_id"):
        cfg["telegram_chat_id"] = data["chat_id"]

    delivered = pe.send_telegram_alert(
        "🔔 <b>FinGroww AI Paper Trading</b>\n\n"
        "Your Telegram alerts have been successfully connected! 🚀\n"
        "You will receive instant alerts for executed trades, target hits, and risk limits.",
        cfg
    )
    return jsonify({
        "ok": True,
        "delivered": delivered,
        "message": "Verification alert dispatched to Telegram." if delivered else "Could not dispatch alert. Check token and chat ID."
    })


@paper_bp.get("/api/paper/profiles")
def paper_list_profiles():
    """Returns all registered trader profiles with performance metrics and settings."""
    profiles = srv.paper_manager.list_profiles()
    return jsonify({"profiles": profiles, "count": len(profiles)})


@paper_bp.post("/api/paper/profiles/create")
def paper_create_profile():
    """Creates a new user profile with custom name, initial capital, and instrument configuration."""
    data = request.get_json(silent=True) or {}
    user_name = (data.get("user_name") or "").strip()
    if not user_name:
        return jsonify({"error": "Profile name is required."}), 400

    capital = float(data.get("initial_capital", 100000.0))
    instruments = data.get("instruments", ["EQUITY"])
    style = data.get("trading_style", "HIGH_WINRATE")
    risk = data.get("risk_profile", "MODERATE")
    holding_mins = int(data.get("holding_duration_mins", 15))

    cfg = {
        "initial_capital": capital,
        "instruments": instruments,
        "trading_style": style,
        "risk_profile": risk,
        "holding_duration_mins": holding_mins,
    }

    try:
        sess, msg = srv.paper_manager.create_profile(user_name, cfg)
        if not sess:
            return jsonify({"error": msg}), 409 if "already exists" in msg else 400

        return jsonify({"ok": True, "message": msg, "profile": sess.get_state()})
    except Exception as exc:
        srv.app.logger.exception("Failed to create profile %s", user_name)
        try:
            sess, _ = srv.paper_manager.get_session(user_name)
            return jsonify({"ok": True, "message": f"Profile [{user_name}] ready.", "profile": sess.get_state()})
        except Exception:
            return jsonify({"error": f"Failed to create profile: {str(exc)}"}), 500


@paper_bp.get("/api/paper/leaderboard")
def paper_get_leaderboard():
    """Returns the trader profiles leaderboard ranked by net profit, returns, and win rate across 3 modes: mix, ai_only, manual_only."""
    active_param = request.args.get("active_only") or request.args.get("only_active")
    only_active = str(active_param).strip().lower() in ("true", "1", "yes") if active_param is not None else False
    mode = request.args.get("mode") or request.args.get("filter_mode") or "mix"
    leaderboard = srv.paper_manager.get_leaderboard(only_active=only_active, mode=mode)
    return jsonify({
        "ok": True,
        "leaderboard": leaderboard,
        "total_traders": len(leaderboard),
        "only_active": only_active,
        "mode": mode,
        "generated_at": srv.get_ist_str()
    })


@paper_bp.post("/api/paper/backtest")
def paper_run_backtest():
    """Runs deterministic strategy backtest on historical candles with realistic transaction costs."""
    data = request.get_json(silent=True) or {}
    sym = srv.normalize_symbol(data.get("symbol", "NIFTY 50"))
    strat = data.get("strategy", "🎯 80%+ Smart Money Pullback & Breakeven")
    cap = float(data.get("initial_capital", 100000.0))
    risk_prof = data.get("risk_profile", "MODERATE")
    years = int(data.get("years", 5))

    # Fetch historical daily candles (e.g. 5-year data span)
    ticker = srv.yahoo_ticker(sym)
    candles = None
    try:
        range_str = f"{years}y" if years in (1, 2, 3, 5) else "5y"
        rows, meta = srv.fetch_yahoo_chart(ticker, "1d", range_str)
        if rows and len(rows) >= 30:
            candles = rows
    except Exception as exc:
        srv.logger.warning("Could not fetch Yahoo historical candles for %s: %s", sym, exc)

    results = pe.PaperTradingEngine.run_backtest(
        symbol=sym,
        strategy=strat,
        initial_capital=cap,
        candles=candles,
        risk_profile=risk_prof,
        years=years,
    )
    return jsonify(results)
