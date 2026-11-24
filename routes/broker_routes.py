"""
FinGroww Trading Intelligence — Real Broker API Routes Blueprint.
=================================================================
Exposes REST endpoints for Zerodha Kite Connect, Angel One SmartAPI,
DhanHQ, and Upstox API v2 live trading, margin checks, real position books, and panic square-offs.
"""

from flask import Blueprint, request, jsonify
import logging
from brokers import broker_manager

logger = logging.getLogger("FinGroww.Routes.Broker")

broker_bp = Blueprint("broker_bp", __name__)


def _extract_user(req) -> str:
    user = None
    try:
        if req.is_json and req.get_json(silent=True):
            j = req.get_json(silent=True)
            user = j.get("user_name") or j.get("user") or j.get("user_id")
    except Exception:
        pass
    if not user:
        user = req.args.get("user") or req.args.get("user_name") or req.args.get("user_id")
    if not user:
        user = req.headers.get("X-User-Name") or req.cookies.get("fingroww_user")
    if not user:
        user = "Akshay"
    return str(user).strip()


@broker_bp.get("/api/broker/status")
def broker_status():
    """Returns active broker connection status and current trading mode (PAPER vs REAL)."""
    user = _extract_user(request)
    status = broker_manager.get_status(user)
    is_conn = bool(status.get("is_connected"))
    return jsonify({
        "ok": True,
        "success": True,
        "connected": is_conn,
        "user_name": user,
        "broker": status.get("broker_name"),
        "broker_name": status.get("broker_name"),
        "client_id": status.get("client_id"),
        "mode": status.get("mode", "PAPER"),
        "status": status,
    })


@broker_bp.post("/api/broker/connect")
def broker_connect():
    """Connects to Zerodha Kite Connect, Angel One, DhanHQ, or Upstox with user API credentials."""
    data = request.get_json(silent=True) or {}
    user = _extract_user(request)
    broker_name = data.get("broker_name") or data.get("broker")

    if not broker_name:
        return jsonify({"ok": False, "success": False, "error": "Broker name is required (e.g. ZERODHA_KITE, ANGEL_ONE, DHAN, UPSTOX)."}), 400

    credentials = data.get("credentials") or {
        "api_key": data.get("api_key"),
        "access_token": data.get("access_token") or data.get("token"),
        "client_id": data.get("client_id") or data.get("clientcode"),
        "password": data.get("password") or data.get("mpin"),
        "totp": data.get("totp"),
        "jwt_token": data.get("jwt_token"),
    }

    success, msg, profile = broker_manager.connect_broker(user, broker_name, credentials)
    if success:
        return jsonify({
            "ok": True,
            "success": True,
            "connected": True,
            "message": msg,
            "broker": profile.get("broker"),
            "broker_name": profile.get("broker"),
            "client_id": profile.get("client_id"),
            "user_name": profile.get("user_name"),
            "profile": profile,
        })
    return jsonify({"ok": False, "success": False, "error": msg}), 400


@broker_bp.post("/api/broker/disconnect")
def broker_disconnect():
    """Disconnects the current active broker and safely reverts to Paper Trading."""
    user = _extract_user(request)
    success, msg = broker_manager.disconnect_broker(user)
    return jsonify({"ok": success, "success": success, "connected": False, "message": msg})


@broker_bp.post("/api/broker/mode/toggle")
def broker_toggle_mode():
    """Switches active engine execution target between 'PAPER' and 'REAL'."""
    data = request.get_json(silent=True) or {}
    user = _extract_user(request)
    target_mode = data.get("mode") or "PAPER"

    success, msg = broker_manager.set_trading_mode(user, target_mode)
    if success:
        return jsonify({"ok": True, "success": True, "message": msg, "mode": target_mode.upper()})
    return jsonify({"ok": False, "success": False, "error": msg}), 400


@broker_bp.get("/api/broker/funds")
def broker_funds():
    """Fetches live margins and funds directly from the connected broker."""
    user = _extract_user(request)
    client = broker_manager.get_client(user)
    if not client or not client.is_connected:
        return jsonify({"ok": False, "success": False, "error": "No broker connected. Please connect a broker first."}), 400

    success, funds, err = client.get_funds()
    if success:
        return jsonify({"ok": True, "success": True, "funds": funds})
    return jsonify({"ok": False, "success": False, "error": err}), 502


@broker_bp.get("/api/broker/positions")
def broker_positions():
    """Fetches real open market positions from the connected broker."""
    user = _extract_user(request)
    client = broker_manager.get_client(user)
    if not client or not client.is_connected:
        return jsonify({"ok": False, "success": False, "error": "No broker connected."}), 400

    success, positions, err = client.get_positions()
    if success:
        return jsonify({"ok": True, "success": True, "positions": positions, "count": len(positions)})
    return jsonify({"ok": False, "success": False, "error": err}), 502


@broker_bp.get("/api/broker/orders")
def broker_orders():
    """Fetches today's real broker order book."""
    user = _extract_user(request)
    client = broker_manager.get_client(user)
    if not client or not client.is_connected:
        return jsonify({"ok": False, "success": False, "error": "No broker connected."}), 400

    success, orders, err = client.get_orders()
    if success:
        return jsonify({"ok": True, "success": True, "orders": orders, "count": len(orders)})
    return jsonify({"ok": False, "success": False, "error": err}), 502


@broker_bp.post("/api/broker/order/place")
def broker_place_order():
    """Places an immediate live real order on the connected broker terminal."""
    data = request.get_json(silent=True) or {}
    user = _extract_user(request)
    client = broker_manager.get_client(user)
    if not client or not client.is_connected:
        return jsonify({"ok": False, "error": "Cannot execute real order: No active broker connected."}), 400

    symbol = data.get("symbol")
    qty = int(data.get("quantity") or data.get("qty") or 0)
    side = str(data.get("side") or "BUY").upper()

    if not symbol or qty <= 0:
        return jsonify({"ok": False, "error": "Valid symbol and quantity > 0 are required."}), 400

    # Mandatory Stop-Loss enforcement even for real live manual trades!
    stop_loss = data.get("stop_loss")
    if stop_loss is None or float(stop_loss) <= 0:
        return jsonify({"ok": False, "error": "Stop-Loss is strictly mandatory to protect real broker capital."}), 400

    success, order_res, err = client.place_order(
        symbol=symbol,
        quantity=qty,
        side=side,
        order_type=data.get("order_type", "MARKET"),
        price=float(data.get("price") or 0.0),
        trigger_price=float(data.get("trigger_price") or 0.0),
        product=data.get("product", "MIS"),
        exchange=data.get("exchange", "NSE"),
        tag=data.get("tag", "FINGROWW_REAL"),
        stop_loss=float(stop_loss),
        target_price=float(data.get("target_price") or 0.0) if data.get("target_price") else None,
    )
    if success:
        return jsonify({"ok": True, "order": order_res, "message": err})
    return jsonify({"ok": False, "error": err}), 400


@broker_bp.post("/api/broker/order/cancel")
def broker_cancel_order():
    """Cancels a pending real broker order."""
    data = request.get_json(silent=True) or {}
    user = _extract_user(request)
    client = broker_manager.get_client(user)
    if not client or not client.is_connected:
        return jsonify({"ok": False, "error": "No broker connected."}), 400

    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"ok": False, "error": "Missing order_id."}), 400

    success, msg = client.cancel_order(str(order_id))
    if success:
        return jsonify({"ok": True, "message": msg})
    return jsonify({"ok": False, "error": msg}), 400


@broker_bp.post("/api/broker/square-off-all")
def broker_square_off_all():
    """Panic Button: Instantly squares off all real open positions on the broker."""
    user = _extract_user(request)
    client = broker_manager.get_client(user)
    if not client or not client.is_connected:
        return jsonify({"ok": False, "error": "No broker connected."}), 400

    success, closed_count, logs = client.square_off_all()
    return jsonify({
        "ok": success,
        "closed_count": closed_count,
        "logs": logs,
        "message": f"Squared off {closed_count} positions on {client.broker_name}."
    })
