from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from uuid import UUID

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.schemas import (
    OrderCreate, OrderRead, OrderSummary, OrderStatusUpdate,
    OrderMarkBlank, OrderSetDriveLink
)
from app.models.orm import Order, Roll, Store
from app.services.order_service import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


def _actor(current_user: dict) -> str:
    return current_user.get("initials") or current_user.get("email", "staff")


@router.post("", response_model=OrderRead, status_code=201)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Book in a new film order (manual intake)."""
    # If operator not provided, use logged-in user's initials
    if not payload.operator_initials:
        payload.operator_initials = current_user.get("initials", "")
    try:
        order = await order_service.create_order(db, payload, actor_label=_actor(current_user))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Reload with relationships
    order = await order_service.get_order(db, order.id)
    return _enrich(order)


@router.get("", response_model=List[OrderRead])
async def list_orders(
    store_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List orders. Store staff are limited to their own store."""
    # Enforce store restriction for non-master-admins
    if current_user.get("role") != "master_admin" and not store_id:
        store_id = UUID(current_user["store_id"]) if current_user.get("store_id") else None

    orders = await order_service.list_orders(db, store_id, status, search, limit, offset)
    return [_enrich(o) for o in orders]


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    order = await order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _enrich(order)


@router.patch("/{order_id}/status", response_model=OrderRead)
async def update_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    try:
        order = await order_service.mark_blanks(
            db, order_id, payload.roll_ids, actor_label=_actor(current_user)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _enrich(order)


@router.get("/{order_id}/events")
async def get_events(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Full audit trail for an order."""
    from app.models.orm import OrderEvent
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
            "metadata": e.metadata,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


@router.get("/check/twin")
async def check_twin(
    store_id: UUID = Query(...),
    twin_check: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Check if a twin check number already exists in this store."""
    padded = twin_check.strip().zfill(4)
    exists = await order_service.check_twin_exists(db, store_id, padded)
    return {"exists": exists, "twin_check": padded}


def _enrich(order: Order) -> dict:
    """Add store_name to order dict for frontend convenience."""
    d = {
        "id": str(order.id),
        "order_number": order.order_number,
        "order_type": order.order_type,
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
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
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "date_scanned": order.date_scanned.isoformat() if order.date_scanned else None,
        "date_delivered": order.date_delivered.isoformat() if order.date_delivered else None,
        "notes": order.notes,
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
    return d
