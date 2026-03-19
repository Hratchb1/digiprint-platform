"""
routers/b2b.py — B2B vendor/Pixieset order endpoints
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel

from ..db.database import get_db
from ..models import B2BOrder, Vendor, Store

router = APIRouter(prefix="/b2b", tags=["B2B Orders"])


# ─────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────

class VendorCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    pixieset_id: Optional[str] = None
    notes: Optional[str] = None


class B2BOrderCreate(BaseModel):
    store_id: int
    vendor_id: Optional[int] = None
    order_reference: str
    pixieset_order_id: Optional[str] = None
    product_type: Optional[str] = None
    quantity: int = 1
    priority: str = "Normal"
    notes: Optional[str] = None


class B2BStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def order_to_dict(o: B2BOrder) -> dict:
    return {
        "id": o.id,
        "store_id": o.store_id,
        "store_name": o.store.name if o.store else None,
        "vendor_id": o.vendor_id,
        "vendor_name": o.vendor.name if o.vendor else None,
        "order_reference": o.order_reference,
        "pixieset_order_id": o.pixieset_order_id,
        "status": o.status,
        "priority": o.priority,
        "product_type": o.product_type,
        "quantity": o.quantity,
        "notes": o.notes,
        "received_at": o.received_at.isoformat() if o.received_at else None,
        "batched_at": o.batched_at.isoformat() if o.batched_at else None,
        "fulfilled_at": o.fulfilled_at.isoformat() if o.fulfilled_at else None,
    }


def vendor_to_dict(v: Vendor) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "email": v.email,
        "phone": v.phone,
        "pixieset_id": v.pixieset_id,
        "notes": v.notes,
        "is_active": v.is_active,
    }


# ─────────────────────────────────────────
# VENDOR ENDPOINTS
# ─────────────────────────────────────────

@router.get("/vendors")
def list_vendors(db: Session = Depends(get_db)):
    vendors = db.query(Vendor).filter(Vendor.is_active == True).all()
    return [vendor_to_dict(v) for v in vendors]


@router.post("/vendors")
def create_vendor(payload: VendorCreate, db: Session = Depends(get_db)):
    vendor = Vendor(**payload.model_dump())
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor_to_dict(vendor)


# ─────────────────────────────────────────
# ORDER ENDPOINTS
# ─────────────────────────────────────────

@router.get("/orders")
def list_b2b_orders(
    store_id: Optional[int] = None,
    status: Optional[str] = None,
    vendor_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    q = db.query(B2BOrder)
    if store_id:
        q = q.filter(B2BOrder.store_id == store_id)
    if status:
        q = q.filter(B2BOrder.status == status)
    if vendor_id:
        q = q.filter(B2BOrder.vendor_id == vendor_id)
    orders = q.order_by(desc(B2BOrder.received_at)).all()
    return [order_to_dict(o) for o in orders]


@router.post("/orders")
def create_b2b_order(payload: B2BOrderCreate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    order = B2BOrder(**payload.model_dump(), received_at=datetime.utcnow())
    db.add(order)
    db.commit()
    db.refresh(order)
    return order_to_dict(order)


@router.patch("/orders/{order_id}/status")
def update_b2b_order_status(order_id: int, payload: B2BStatusUpdate, db: Session = Depends(get_db)):
    order = db.query(B2BOrder).filter(B2BOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = payload.status
    order.updated_at = datetime.utcnow()

    if payload.status == "Batched":
        order.batched_at = datetime.utcnow()
    if payload.status == "Fulfilled":
        order.fulfilled_at = datetime.utcnow()
    if payload.notes:
        order.notes = payload.notes

    db.commit()
    db.refresh(order)
    return order_to_dict(order)


# ─────────────────────────────────────────
# PIXIESET WEBHOOK (Phase 2)
# ─────────────────────────────────────────

@router.post("/pixieset/webhook")
async def pixieset_webhook(payload: dict, db: Session = Depends(get_db)):
    """
    Receive Pixieset order webhooks and create B2B orders automatically.
    Phase 2 — wire up when Pixieset integration is ready.
    """
    # Log the raw payload for now
    print(f"[Pixieset webhook] {payload}")

    # TODO: parse payload, match vendor, create B2BOrder
    return {"received": True}
