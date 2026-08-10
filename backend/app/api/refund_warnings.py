# app/api/refund_warnings.py
# ============================================================
# Manual resolution of unmatched refund warnings (Phase 3).
#
# The pronto_sync job parks refunds it can't match in the
# refund_warnings table. Staff resolve them here: either match
# to an order (re-using pronto_sync._apply_refund) or ignore.
#
# Uses the Supabase client (refund_warnings has no ORM model);
# blocking bodies run via asyncio.to_thread like pronto_sync.
# ============================================================

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from supabase import create_client

from app.core.config import settings
from app.core.auth import get_current_user
from app.core.timeutils import utcnow
from app.models.schemas import RefundWarningResolveRequest, RefundWarningIgnoreRequest
from app.services.pronto_sync import _apply_refund

router = APIRouter()


def _client():
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def _get_pending_warning(client, warning_id: str) -> dict:
    result = client.table("refund_warnings").select("*").eq("id", warning_id).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Refund warning not found")
    warning = result.data[0]
    if warning.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Refund warning is '{warning.get('status')}' — only pending warnings can be actioned",
        )
    return warning


def _close_warning(client, warning_id: str, status: str, operator_id: str, notes) -> dict:
    result = client.table("refund_warnings").update({
        "status": status,
        "resolved_by": operator_id,
        "resolved_at": utcnow().isoformat(),
        "resolution_notes": notes,
    }).eq("id", warning_id).execute()
    return result.data[0] if result.data else {}


# ── GET /api/refund-warnings ─────────────────────────────────

@router.get("")
async def list_refund_warnings(current_user: dict = Depends(get_current_user)):
    """All pending refund warnings, newest first."""
    return await asyncio.to_thread(_list_pending_blocking)


def _list_pending_blocking() -> list[dict]:
    client = _client()
    result = client.table("refund_warnings").select("*").eq(
        "status", "pending"
    ).order("created_at", desc=True).execute()
    return result.data or []


# ── POST /api/refund-warnings/{id}/resolve ───────────────────

@router.post("/{warning_id}/resolve")
async def resolve_refund_warning(
    warning_id: str,
    payload: RefundWarningResolveRequest,
    current_user: dict = Depends(get_current_user),
):
    """Apply the refund to a manually matched order, then close the warning."""
    operator = payload.operator_id or current_user.get("initials") or current_user.get("email", "staff")
    return await asyncio.to_thread(
        _resolve_blocking, warning_id, str(payload.order_id), payload.notes, operator
    )


def _resolve_blocking(warning_id: str, order_id: str, notes, operator: str) -> dict:
    client = _client()
    warning = _get_pending_warning(client, warning_id)

    order_result = client.table("orders").select(
        "id, status, pronto_order_number, pronto_order_date, refund_status, store_id"
    ).eq("id", order_id).execute()
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    matched_order = order_result.data[0]

    # Stored refund_lines lack sales_order_number, which _apply_refund reads
    # off the first line — re-attach it from the warning row.
    refund_lines = [
        {**line, "sales_order_number": warning["refund_pronto_order_number"]}
        for line in (warning.get("refund_lines") or [])
    ]
    if not refund_lines:
        raise HTTPException(status_code=400, detail="Refund warning has no refund lines to apply")

    _apply_refund(matched_order, refund_lines, client)

    return _close_warning(client, warning_id, "manually_resolved", operator, notes)


# ── POST /api/refund-warnings/{id}/ignore ────────────────────

@router.post("/{warning_id}/ignore")
async def ignore_refund_warning(
    warning_id: str,
    payload: RefundWarningIgnoreRequest,
    current_user: dict = Depends(get_current_user),
):
    """Dismiss a warning without applying any refund."""
    operator = payload.operator_id or current_user.get("initials") or current_user.get("email", "staff")
    return await asyncio.to_thread(_ignore_blocking, warning_id, payload.notes, operator)


def _ignore_blocking(warning_id: str, notes, operator: str) -> dict:
    client = _client()
    _get_pending_warning(client, warning_id)
    return _close_warning(client, warning_id, "ignored", operator, notes)
