"""
FinGroww SaaS Platform — FastAPI v2 User Dashboard, Watchlists, Saved Signals & Notifications Router.
All routes strictly require JWT Bearer authentication and isolate data by user_id.
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies import get_current_user
from backend.schemas import (
    NotificationReadRequest,
    SaveSignalRequest,
    WatchlistAddItemRequest,
    WatchlistRemoveItemRequest,
)
from backend.services import dashboard_service

router = APIRouter(prefix="/api/v2", tags=["User Dashboard v2"])


@router.get("/dashboard/overview")
def get_dashboard_overview(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return dashboard_service.get_dashboard_overview(user["user_id"], user["username"])


@router.get("/watchlists")
def list_watchlists(
    live: bool = Query(default=True),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    lists = dashboard_service.get_watchlists(user["user_id"], include_live_quotes=live)
    return {"ok": True, "watchlists": lists}


@router.post("/watchlists/items")
def add_watchlist_item(
    payload: WatchlistAddItemRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return dashboard_service.add_watchlist_item(
        user_id=user["user_id"],
        watchlist_name=payload.watchlist_name,
        symbol=payload.symbol,
        alert_above=payload.alert_above,
        alert_below=payload.alert_below,
        notes=payload.notes,
    )


@router.delete("/watchlists/items")
def remove_watchlist_item(
    payload: WatchlistRemoveItemRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return dashboard_service.remove_watchlist_item(
        user_id=user["user_id"],
        watchlist_name=payload.watchlist_name,
        symbol=payload.symbol,
    )


@router.get("/signals/saved")
def list_saved_signals(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    items = dashboard_service.get_saved_signals(user["user_id"])
    return {"ok": True, "count": len(items), "signals": items}


@router.post("/signals/saved", status_code=201)
def save_signal(
    payload: SaveSignalRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return dashboard_service.save_signal_for_user(user["user_id"], payload.model_dump())


@router.delete("/signals/saved/{saved_id}")
def delete_saved_signal(
    saved_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    ok = dashboard_service.delete_saved_signal(user["user_id"], saved_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved signal not found")
    return {"ok": True, "message": "Signal removed"}


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(default=False),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return dashboard_service.get_notifications(user["user_id"], unread_only=unread_only)


@router.post("/notifications/read")
def mark_notifications_read(
    payload: NotificationReadRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return dashboard_service.mark_notifications_read(
        user_id=user["user_id"],
        notification_id=payload.notification_id,
        mark_all=payload.mark_all,
    )
