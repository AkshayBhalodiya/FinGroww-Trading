"""
FinGroww SaaS Platform — Flask Parity Blueprint for Phase 3 (Multi-Account Paper, Journal, AI Coach & Confluence).
"""

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from backend.schemas import (
    JournalEntryCreateRequest,
    JournalEntryUpdateRequest,
    PaperAccountCloseRequest,
    PaperAccountCreateRequest,
    PaperAccountOrderRequest,
    PaperAccountResetRequest,
)
from backend.services import intelligence_service, journal_service, paper_v2_service
from routes.auth_v2_routes import _validation_error_response, require_jwt_auth

phase3_v2_bp = Blueprint("phase3_v2_api", __name__)


@phase3_v2_bp.get("/api/v2/paper/accounts")
@require_jwt_auth
def v2_list_paper_accounts(user):
    inc = request.args.get("include_archived", "false").lower() == "true"
    accounts = paper_v2_service.list_accounts(user["user_id"], include_archived=inc)
    return jsonify({"ok": True, "count": len(accounts), "accounts": accounts})


@phase3_v2_bp.post("/api/v2/paper/accounts")
@require_jwt_auth
def v2_create_paper_account(user):
    try:
        payload = PaperAccountCreateRequest.model_validate(request.get_json(silent=True) or {})
        res = paper_v2_service.create_account(
            user_id=user["user_id"],
            name=payload.name,
            virtual_capital=payload.virtual_capital,
            trading_style=payload.trading_style,
        )
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)
    except paper_v2_service.PaperServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.get("/api/v2/paper/accounts/<account_id>")
@require_jwt_auth
def v2_get_paper_account_details(user, account_id):
    try:
        return jsonify(paper_v2_service.get_account_details(user["user_id"], account_id))
    except paper_v2_service.PaperServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.post("/api/v2/paper/accounts/<account_id>/reset")
@require_jwt_auth
def v2_reset_paper_account(user, account_id):
    try:
        payload = PaperAccountResetRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(paper_v2_service.reset_account(user["user_id"], account_id, payload.virtual_capital))
    except ValidationError as exc:
        return _validation_error_response(exc)
    except paper_v2_service.PaperServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.post("/api/v2/paper/accounts/<account_id>/archive")
@require_jwt_auth
def v2_archive_paper_account(user, account_id):
    try:
        return jsonify(paper_v2_service.archive_account(user["user_id"], account_id))
    except paper_v2_service.PaperServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.post("/api/v2/paper/accounts/<account_id>/orders")
@require_jwt_auth
def v2_place_paper_account_order(user, account_id):
    try:
        payload = PaperAccountOrderRequest.model_validate(request.get_json(silent=True) or {})
        res = paper_v2_service.place_account_order(user["user_id"], account_id, payload.model_dump())
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)
    except paper_v2_service.PaperServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.post("/api/v2/paper/accounts/<account_id>/close")
@require_jwt_auth
def v2_close_paper_account_position(user, account_id):
    try:
        payload = PaperAccountCloseRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(
            paper_v2_service.close_account_position(
                user_id=user["user_id"],
                account_id=account_id,
                position_id=payload.position_id,
                exit_price=payload.exit_price,
                exit_reason=payload.exit_reason,
            )
        )
    except ValidationError as exc:
        return _validation_error_response(exc)
    except paper_v2_service.PaperServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.get("/api/v2/paper/accounts/<account_id>/export.csv")
@require_jwt_auth
def v2_export_paper_csv(user, account_id):
    try:
        csv_body = paper_v2_service.export_account_trades_csv(user["user_id"], account_id)
        return Response(
            csv_body,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=fingroww_{account_id}_trades.csv"},
        )
    except paper_v2_service.PaperServiceError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.get("/api/v2/intelligence/confluence")
@require_jwt_auth
def v2_three_timeframe_confluence(user):
    sym = request.args.get("symbol", "NIFTY 50")
    return jsonify(intelligence_service.evaluate_three_timeframe_confluence(sym))


@phase3_v2_bp.get("/api/v2/journal")
@require_jwt_auth
def v2_list_journal(user):
    limit = int(request.args.get("limit", 50))
    items = journal_service.list_journals(user["user_id"], limit=limit)
    return jsonify({"ok": True, "count": len(items), "entries": items})


@phase3_v2_bp.post("/api/v2/journal")
@require_jwt_auth
def v2_create_journal(user):
    try:
        payload = JournalEntryCreateRequest.model_validate(request.get_json(silent=True) or {})
        res = journal_service.create_journal_entry(user["user_id"], payload.model_dump())
        return jsonify(res), 201
    except ValidationError as exc:
        return _validation_error_response(exc)


@phase3_v2_bp.put("/api/v2/journal/<journal_id>")
@require_jwt_auth
def v2_update_journal(user, journal_id):
    try:
        payload = JournalEntryUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return jsonify(journal_service.update_journal_entry(user["user_id"], journal_id, payload.model_dump(exclude_none=True)))
    except ValidationError as exc:
        return _validation_error_response(exc)
    except journal_service.JournalError as exc:
        return jsonify({"ok": False, "error": exc.message}), exc.status_code


@phase3_v2_bp.delete("/api/v2/journal/<journal_id>")
@require_jwt_auth
def v2_delete_journal(user, journal_id):
    if not journal_service.delete_journal_entry(user["user_id"], journal_id):
        return jsonify({"ok": False, "error": "Journal entry not found"}), 404
    return jsonify({"ok": True, "message": "Journal entry deleted"})


@phase3_v2_bp.get("/api/v2/coach/insights")
@require_jwt_auth
def v2_coach_insights(user):
    return jsonify(journal_service.get_ai_coach_insights(user["user_id"]))
