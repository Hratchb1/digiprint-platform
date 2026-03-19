"""
routers/stores.py — Store management endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from ..db.database import get_db
from ..models import Store

router = APIRouter(prefix="/stores", tags=["Stores"])


class StoreCreate(BaseModel):
    name: str
    label: str
    reply_to: Optional[str] = None
    drive_root_id: Optional[str] = None
    drive_inbox_id: Optional[str] = None


def store_to_dict(s: Store) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "label": s.label,
        "reply_to": s.reply_to,
        "drive_root_id": s.drive_root_id,
        "drive_inbox_id": s.drive_inbox_id,
        "is_active": s.is_active,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/")
def list_stores(db: Session = Depends(get_db)):
    stores = db.query(Store).filter(Store.is_active == True).all()
    return [store_to_dict(s) for s in stores]


@router.post("/")
def create_store(payload: StoreCreate, db: Session = Depends(get_db)):
    existing = db.query(Store).filter(Store.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Store '{payload.name}' already exists")
    store = Store(**payload.model_dump())
    db.add(store)
    db.commit()
    db.refresh(store)
    return store_to_dict(store)


@router.get("/{store_id}/stats")
def store_stats(store_id: int, db: Session = Depends(get_db)):
    """Dashboard stats for a single store."""
    from ..models import Roll
    from sqlalchemy import func

    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    total = db.query(Roll).filter(Roll.store_id == store_id).count()
    booked = db.query(Roll).filter(Roll.store_id == store_id, Roll.status == "Booked").count()
    delivered = db.query(Roll).filter(Roll.store_id == store_id, Roll.status == "Delivered").count()
    blanks = db.query(Roll).filter(Roll.store_id == store_id, Roll.status == "Blank").count()
    print_ready = db.query(Roll).filter(Roll.store_id == store_id, Roll.status == "PrintReady").count()

    return {
        "store_id": store_id,
        "store_name": store.name,
        "total_rolls": total,
        "booked": booked,
        "delivered": delivered,
        "blanks": blanks,
        "print_ready": print_ready,
        "in_progress": total - delivered - blanks,
    }
