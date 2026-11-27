"""
FinGroww SaaS Platform — FastAPI v2 Trading Journal & AI Trading Coach Router.
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies import get_current_user
from backend.schemas import JournalEntryCreateRequest, JournalEntryUpdateRequest
from backend.services import journal_service

router = APIRouter(prefix="/api/v2", tags=["Trading Journal & AI Coach v2"])


@router.get("/journal")
def list_journal_entries(
    limit: int = Query(default=50, ge=1, le=200),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    items = journal_service.list_journals(user["user_id"], limit=limit)
    return {"ok": True, "count": len(items), "entries": items}


@router.post("/journal", status_code=201)
def create_journal_entry(
    payload: JournalEntryCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return journal_service.create_journal_entry(user["user_id"], payload.model_dump())


@router.put("/journal/{journal_id}")
def update_journal_entry(
    journal_id: str,
    payload: JournalEntryUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return journal_service.update_journal_entry(user["user_id"], journal_id, payload.model_dump(exclude_none=True))
    except journal_service.JournalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.delete("/journal/{journal_id}")
def delete_journal_entry(
    journal_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not journal_service.delete_journal_entry(user["user_id"], journal_id):
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return {"ok": True, "message": "Journal entry deleted"}


@router.get("/coach/insights")
def get_coach_insights(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return journal_service.get_ai_coach_insights(user["user_id"])
