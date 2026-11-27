"""
FinGroww SaaS Platform — FastAPI v2 Multi-Account Paper Trading & Confluence Router.
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.dependencies import get_current_user
from backend.schemas import (
    PaperAccountCloseRequest,
    PaperAccountCreateRequest,
    PaperAccountOrderRequest,
    PaperAccountResetRequest,
)
from backend.services import intelligence_service, paper_v2_service

router = APIRouter(prefix="/api/v2", tags=["Multi-Account Paper Trading v2"])


@router.get("/paper/accounts")
def list_paper_accounts(
    include_archived: bool = Query(default=False),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    accounts = paper_v2_service.list_accounts(user["user_id"], include_archived=include_archived)
    return {"ok": True, "count": len(accounts), "accounts": accounts}


@router.post("/paper/accounts", status_code=201)
def create_paper_account(
    payload: PaperAccountCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return paper_v2_service.create_account(
            user_id=user["user_id"],
            name=payload.name,
            virtual_capital=payload.virtual_capital,
            trading_style=payload.trading_style,
        )
    except paper_v2_service.PaperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/paper/accounts/{account_id}")
def get_paper_account_details(
    account_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return paper_v2_service.get_account_details(user["user_id"], account_id)
    except paper_v2_service.PaperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/paper/accounts/{account_id}/reset")
def reset_paper_account(
    account_id: str,
    payload: PaperAccountResetRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return paper_v2_service.reset_account(user["user_id"], account_id, payload.virtual_capital)
    except paper_v2_service.PaperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/paper/accounts/{account_id}/archive")
def archive_paper_account(
    account_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return paper_v2_service.archive_account(user["user_id"], account_id)
    except paper_v2_service.PaperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/paper/accounts/{account_id}/orders", status_code=201)
def place_paper_account_order(
    account_id: str,
    payload: PaperAccountOrderRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return paper_v2_service.place_account_order(user["user_id"], account_id, payload.model_dump())
    except paper_v2_service.PaperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/paper/accounts/{account_id}/close")
def close_paper_account_position(
    account_id: str,
    payload: PaperAccountCloseRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return paper_v2_service.close_account_position(
            user_id=user["user_id"],
            account_id=account_id,
            position_id=payload.position_id,
            exit_price=payload.exit_price,
            exit_reason=payload.exit_reason,
        )
    except paper_v2_service.PaperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/paper/accounts/{account_id}/export.csv")
def export_paper_account_csv(
    account_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        csv_body = paper_v2_service.export_account_trades_csv(user["user_id"], account_id)
        return Response(
            content=csv_body,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=fingroww_{account_id}_trades.csv"},
        )
    except paper_v2_service.PaperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/intelligence/confluence")
def get_three_timeframe_confluence(
    symbol: str = Query(default="NIFTY 50"),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return intelligence_service.evaluate_three_timeframe_confluence(symbol)
