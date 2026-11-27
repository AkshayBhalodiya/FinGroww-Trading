"""
FinGroww SaaS Platform — Flask Parity Blueprint for Phase 2 Dashboard, Watchlists, Saved Signals & Notifications.
"""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from backend.schemas import (
    NotificationReadRequest,
    SaveSignalRequest,
    WatchlistAddItemRequest,
    WatchlistRemoveItemRequest,
)
from backend.services import dashboard_service
from routes.auth_v2_routes import _validation_error_response, require_jwt_auth

dashboard_v2_bp = Blueprint("dashboard_v2_api", __name__)


@dashboard_v2_bp.get("/api/v2/dashboard/overview")
@require_jwt_auth
def v2_dashboard_overview(user):
    return jsonify(dashboard_service.get_dashboard_overview(user["user_id"], user["username"]))


@dashboard_v2_bp.get("/api/v2/watchlists")
@require_jwt_auth
def v2_list_watchlists(user):
    live = request.args.get("live", "true").lower() != "false"
    lists = dashboard_service.get_watchlists(user["user_id"], include_live_quotes=live)
    return jsonify({"ok": True, "watchlists": lists})


@dashboard_v2_bp.post("/api/v2/watchlists/items")
@require_jwt_auth
def v2_add_watchlist_item(user):
    try:
        payload = WatchlistAddItemRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            dashboard_service.add_watchlist_item(
                user_id=user["user_id"],
                watchlist_name=payload.watchlist_name,
                symbol=payload.symbol,
                alert_above=payload.alert_above,
                alert_below=payload.alert_below,
                notes=payload.notes,
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)


@dashboard_v2_bp.delete("/api/v2/watchlists/items")
@require_jwt_auth
def v2_remove_watchlist_item(user):
    try:
        payload = WatchlistRemoveItemRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            dashboard_service.remove_watchlist_item(
                user_id=user["user_id"],
                watchlist_name=payload.watchlist_name,
                symbol=payload.symbol,
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)


@dashboard_v2_bp.get("/api/v2/signals/saved")
@require_jwt_auth
def v2_list_saved_signals(user):
    items = dashboard_service.get_saved_signals(user["user_id"])
    return jsonify({"ok": True, "count": len(items), "signals": items})


@dashboard_v2_bp.post("/api/v2/signals/saved")
@require_jwt_auth
def v2_save_signal(user):
    try:
        payload = SaveSignalRequest.model_validate(request.get_json(silent=True) or {})
        res = dashboard_service.save_signal_for_user(user["user_id"], payload.model_dump())
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)


@dashboard_v2_bp.delete("/api/v2/signals/saved/<saved_id>")
@require_jwt_auth
def v2_delete_saved_signal(user, saved_id):
    ok = dashboard_service.delete_saved_signal(user["user_id"], saved_id)
    if not ok:
        return jsonify({"ok": False, "error": "Saved signal not found"}), 404
    return jsonify({"ok": True, "message": "Signal removed"})


@dashboard_v2_bp.get("/api/v2/notifications")
@require_jwt_auth
def v2_list_notifications(user):
    unread_only = request.args.get("unread_only", "false").lower() == "true"
    return jsonify(dashboard_service.get_notifications(user["user_id"], unread_only=unread_only))


@dashboard_v2_bp.post("/api/v2/notifications/read")
@require_jwt_auth
def v2_mark_notifications_read(user):
    try:
        payload = NotificationReadRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            dashboard_service.mark_notifications_read(
                user_id=user["user_id"],
                notification_id=payload.notification_id,
                mark_all=payload.mark_all,
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
