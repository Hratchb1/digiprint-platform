from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from uuid import UUID
import asyncio

from app.core.database import get_db
from app.core.auth import get_current_user, effective_store_id, assert_can_access
from app.core.timeutils import utcnow
from app.models.schemas import (
    OrderCreate, OrderRead, OrderSummary, OrderStatusUpdate,
    OrderMarkBlank, OrderSetDriveLink, RollsAddPayload, OrderDiscardRequest
)
from app.models.orm import Order, Roll, Store, OrderActivity
from app.services.order_service import order_service

router = APIRouter(prefix="/orders", tags=["orders"])

# Default visibility: active pipeline states. Terminal states (cancelled,
# discarded) are hidden unless explicitly requested.
ACTIVE_STATUSES = ("inbound", "booked_in", "scanning", "delivered")
TERMINAL_STATUSES = ("cancelled", "discarded")
VALID_STATUSES = set(ACTIVE_STATUSES) | set(TERMINAL_STATUSES)

DISCARDABLE_STATUSES = ("inbound", "booked_in", "scanning")


def _actor(current_user: dict) -> str:
    return current_user.get("initials") or current_user.get("email", "staff")


@router.post("", response_model=OrderRead, status_code=201)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Book in a new film order (manual intake)."""
    if not payload.operator_initials:
        payload.operator_initials = current_user.get("initials", "")
    try:
        order = await order_service.create_order(db, payload, actor_label=_actor(current_user))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    order = await order_service.get_order(db, order.id)
    return _enrich(order)


@router.get("", response_model=List[OrderRead])
async def list_orders(
    store_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None, description="Comma-separated statuses, e.g. inbound,booked_in"),
    include_terminal: bool = Query(False, description="Include cancelled and discarded orders"),
    film_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    twin: Optional[str] = Query(None, description="Exact twin check match (zero-padded to 4 digits)"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    store_scope: Optional[UUID] = Depends(effective_store_id),
):
    """List orders. Store staff are limited to their own store.

    Defaults to active statuses (inbound, booked_in, scanning, delivered).
    An explicit ?status= list overrides the default and include_terminal.

    Store scoping: non-admins always get store_scope (derived from their
    token) — any client-supplied ?store_id= is ignored, it cannot be used
    to widen access. master_admin has store_scope=None (all stores) and
    may optionally pass ?store_id= to filter to a single store.
    """
    if store_scope is not None:
        store_id = store_scope

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        invalid = [s for s in statuses if s not in VALID_STATUSES]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status value(s): {', '.join(invalid)}. "
                       f"Valid: {', '.join(sorted(VALID_STATUSES))}",
            )
    else:
        statuses = list(ACTIVE_STATUSES)
        if include_terminal:
            statuses += list(TERMINAL_STATUSES)

    orders = await order_service.list_orders(
        db, store_id, statuses, search, limit, offset, film_type=film_type, twin=twin
    )
    return [_enrich(o) for o in orders]


@router.get("/check/twin")
async def check_twin(
    store_id: UUID = Query(...),
    twin_check: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    store_scope: Optional[UUID] = Depends(effective_store_id),
):
    """Check if a twin check number already exists in this store.

    Non-admins: the token's store always wins over the client-supplied
    ?store_id=, so a store login can't probe another store's twin space.
    """
    if store_scope is not None:
        store_id = store_scope
    padded = twin_check.strip().zfill(4)
    exists = await order_service.check_twin_exists(db, store_id, padded)
    return {"exists": exists, "twin_check": padded}


@router.get("/check/order-number")
async def check_order_number(
    order_number: str = Query(...),
    store_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    store_scope: Optional[UUID] = Depends(effective_store_id),
):
    """Check if an order number already exists at a store."""
    if store_scope is not None:
        store_id = store_scope
    existing = await order_service.get_order_by_number(db, order_number.strip(), store_id)
    if not existing:
        return {"exists": False}
    existing = await order_service.get_order(db, existing.id)
    return {"exists": True, "order": _enrich(existing)}


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    order = await order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(order, current_user)
    return _enrich(order)


@router.patch("/{order_id}/status", response_model=OrderRead)
async def update_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    existing = await order_service.get_order(db, order_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(existing, current_user)
    try:
        order = await order_service.update_order_status(
            db, order_id, payload, actor_label=_actor(current_user)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _enrich(order)


@router.patch("/{order_id}/drive-link", response_model=OrderRead)
async def set_drive_link(
    order_id: UUID,
    payload: OrderSetDriveLink,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Set the Google Drive folder URL for a delivered order."""
    existing = await order_service.get_order(db, order_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(existing, current_user)
    try:
        order = await order_service.set_drive_link(
            db, order_id, payload.drive_order_folder_url, actor_label=_actor(current_user)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _enrich(order)


@router.post("/{order_id}/mark-blank", response_model=OrderRead)
async def mark_blank(
    order_id: UUID,
    payload: OrderMarkBlank,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark specific rolls as blank."""
    existing = await order_service.get_order(db, order_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(existing, current_user)
    try:
        order = await order_service.mark_blanks(
            db, order_id, payload.roll_ids, actor_label=_actor(current_user)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _enrich(order)


@router.post("/{order_id}/add-rolls", response_model=OrderRead)
async def add_rolls_to_order(
    order_id: UUID,
    payload: RollsAddPayload,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Add additional rolls to an existing order."""
    order = await order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(order, current_user)

    existing_twins = await order_service._get_existing_twins(db, order.store_id)
    new_twins = [r.twin_check for r in payload.rolls]
    dups = [t for t in new_twins if t in existing_twins]
    if dups:
        raise HTTPException(
            status_code=409,
            detail=f"Twin check(s) already in use: {', '.join(dups)}"
        )

    for roll_payload in payload.rolls:
        roll = Roll(
            order_id=order.id,
            store_id=order.store_id,
            twin_check=roll_payload.twin_check,
            service_type=roll_payload.service_type,
            status="booked",
        )
        db.add(roll)

    await order_service._log_event(
        db, order.id,
        event_type="rolls_added",
        description=f"{len(payload.rolls)} roll(s) added to order",
        actor_label=_actor(current_user),
    )

    # Primary promotion trigger — staff hit this path via the Intake dup-modal
    # "Add rolls" choice when an inbound order already exists.
    if order.status == "inbound":
        await order_service._promote_inbound_to_booked_in(
            db, order, actor_label=_actor(current_user),
            roll_count=len(payload.rolls), source="add_rolls_dup_modal",
        )

    await db.commit()
    order = await order_service.get_order(db, order.id)
    return _enrich(order)


@router.post("/{order_id}/reset-twins", response_model=OrderRead)
async def reset_twin_checks(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Admin only: manually re-lock archived twin checks on an order."""
    role = current_user.get("role", "")
    if role not in ("master_admin", "store_admin"):
        raise HTTPException(status_code=403, detail="Admin access required to reset twin checks")

    existing = await order_service.get_order(db, order_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(existing, current_user)

    try:
        order = await order_service.reset_twin_checks(
            db, order_id, actor_label=_actor(current_user)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _enrich(order)


@router.post("/{order_id}/retry-border")
async def retry_border_processing(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Retry border processing for an order that previously failed."""
    order = await order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(order, current_user)

    if not order.border_scan:
        raise HTTPException(status_code=400, detail="Order does not have border scan enabled")

    if order.border_scan_status == "processing":
        raise HTTPException(status_code=400, detail="Border processing is already in progress")

    scanned_rolls = [r for r in (order.rolls or []) if r.drive_folder_url]
    if not scanned_rolls:
        raise HTTPException(status_code=400, detail="No scanned rolls found — cannot locate source images")

    roll = scanned_rolls[0]

    from supabase import create_client
    from app.core.config import settings
    from app.services.drive_watcher import _get_drive_service, _build_prefix

    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    config_result = client.table("drive_config").select("*").eq(
        "store_id", str(order.store_id)
    ).execute()

    if not config_result.data:
        raise HTTPException(status_code=500, detail="No Drive config found for this store")

    client.table("orders").update({
        "border_scan_status": None,
        "bordered_scans_drive_url": None,
    }).eq("id", str(order_id)).execute()

    client.table("order_events").insert({
        "order_id": str(order_id),
        "event_type": "border_scan_retry",
        "description": f"Border processing retry requested by {_actor(current_user)}",
        "actor_label": _actor(current_user),
        "metadata": {},
    }).execute()

    drive_url = order.drive_order_folder_url or ""
    order_folder_id = drive_url.rstrip("/").split("/")[-1] if drive_url else None

    if not order_folder_id:
        raise HTTPException(status_code=400, detail="Cannot determine Drive folder ID from order")

    folder_name = _build_prefix(roll.twin_check, str(order.store_id))

    from app.services.drive_watcher import _run_border_processing
    from pathlib import Path
    config = config_result.data[0]
    film_scans_root = Path(config.get("film_scans_root") or "D:/Film Scans")
    border_processing_root = Path(config.get("border_processing_root") or "D:/Border Processing")

    service = _get_drive_service()
    asyncio.create_task(
        _run_border_processing(
            client=client,
            service=service,
            order_id=str(order_id),
            order_number=order.order_number,
            order_folder_id=order_folder_id,
            folder_name=folder_name,
            twin_check=roll.twin_check,
            film_scans_root=film_scans_root,
            border_processing_root=border_processing_root,
        )
    )

    return {"status": "queued", "message": "Border processing has been re-queued"}


@router.get("/{order_id}/events")
async def get_events(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Full audit trail for an order."""
    from app.models.orm import OrderEvent
    order = await order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(order, current_user)

    result = await db.execute(
        select(OrderEvent)
        .where(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.created_at.desc())
    )
    events = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "description": e.description,
            "actor_label": e.actor_label,
            "metadata": e.event_data,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


@router.post("/{order_id}/discard", response_model=OrderRead)
async def discard_order(
    order_id: UUID,
    payload: OrderDiscardRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Discard an order that should never have entered the pipeline.

    Only inbound, booked_in and scanning orders can be discarded.
    Reason validation (422 on invalid) is handled by the DiscardReason enum.
    """
    order = await order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(order, current_user)

    if order.status not in DISCARDABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot discard an order in status '{order.status}' — "
                   f"only {', '.join(DISCARDABLE_STATUSES)} orders can be discarded",
        )

    operator = payload.operator_id or _actor(current_user)
    order.status = "discarded"
    order.discarded_at = utcnow()
    order.discarded_by = operator
    order.discard_reason = payload.reason.value
    order.discard_notes = payload.notes

    db.add(OrderActivity(
        order_id=order.id,
        event_type="order_discarded",
        event_data={"reason": payload.reason.value, "notes": payload.notes},
        operator_id=operator,
    ))

    await db.commit()
    order = await order_service.get_order(db, order.id)
    return _enrich(order)


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _enrich(order: Order) -> dict:
    """Serialize order to dict for frontend."""
    # "Sale date" on the Orders list (see OrdersPage.tsx) is the Pronto
    # order date — order_date is not a column on Order, only
    # pronto_order_date is (orm.py), so hasattr(order, "order_date") was
    # always False here and this silently rendered "—" for every order
    # regardless of whether pronto_order_date had a real value. Confirmed
    # against live data: 5,591 of 5,607 orders (99.7%) have a
    # pronto_order_date that was never reaching the frontend.
    order_date = _iso(order.pronto_order_date)

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "order_type": order.order_type,
        "order_date": order_date,
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "phone_number": order.phone_number,
        "account": order.account,
        "store_id": str(order.store_id),
        "store_name": order.store.name if order.store else str(order.store_id),
        "operator_initials": order.operator_initials,
        "email_status": order.email_status or "",
        "blank_email_status": order.blank_email_status or "",
        "print_ready_email_status": order.print_ready_email_status or "",
        "drive_order_folder_url": order.drive_order_folder_url,
        "is_print_only": order.is_print_only,
        "has_blanks": order.has_blanks,
        "manual_entry": order.manual_entry or False,
        # Border scan fields
        "border_scan": order.border_scan or False,
        "contact_sheet": order.contact_sheet or False,
        "rebate_scan": order.rebate_scan or False,
        "border_scan_status": order.border_scan_status,
        "bordered_scans_drive_url": order.bordered_scans_drive_url,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "date_scanned": order.date_scanned.isoformat() if order.date_scanned else None,
        "date_delivered": order.date_delivered.isoformat() if order.date_delivered else None,
        # Inbound pipeline fields (migration 003)
        "pronto_order_number": order.pronto_order_number,
        "pronto_account_number": order.pronto_account_number,
        "pronto_order_date": _iso(order.pronto_order_date),
        "booked_in_at": _iso(order.booked_in_at),
        "scanning_at": _iso(order.scanning_at),
        "delivered_at": _iso(order.delivered_at),
        "cancelled_at": _iso(order.cancelled_at),
        "discarded_at": _iso(order.discarded_at),
        "discarded_by": order.discarded_by,
        "discard_reason": order.discard_reason,
        "discard_notes": order.discard_notes,
        "refund_status": order.refund_status,
        "refund_amount": order.refund_amount,
        "notes": order.notes,
        # Set by order_service._attach_film_types() on list_orders — not an
        # ORM column, so getattr with a default handles single-order fetches
        # (get_order) that don't attach it.
        "film_type": getattr(order, "film_type", None),
        "rolls": [
            {
                "id": str(r.id),
                "order_id": str(r.order_id),
                "twin_check": r.twin_check,
                "service_type": r.service_type,
                "status": r.status,
                "is_blank": r.is_blank,
                "drive_folder_url": r.drive_folder_url,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "date_scanned": r.date_scanned.isoformat() if r.date_scanned else None,
                "date_delivered": r.date_delivered.isoformat() if r.date_delivered else None,
                "operator_initials": r.operator_initials,
            }
            for r in (order.rolls or [])
        ]
    }
