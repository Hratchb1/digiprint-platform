"""
routers/rolls.py — Film roll intake, status updates, and queries
Mirrors all existing Sheet operations as REST endpoints.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from pydantic import BaseModel

from ..db.database import get_db
from ..models import Roll, RollEvent, Store, RollStatus

router = APIRouter(prefix="/rolls", tags=["Film Rolls"])


# ─────────────────────────────────────────
# PYDANTIC SCHEMAS
# ─────────────────────────────────────────

class RollCreate(BaseModel):
    store_id: int
    order_number: str
    twin_check: str
    customer_name: str
    customer_email: Optional[str] = None
    account: Optional[str] = None
    service_type: str = "Dev+Scan"
    operator: Optional[str] = None
    force_dup: bool = False


class RollBatchCreate(BaseModel):
    store_id: int
    order_number: str
    twin_checks: list[str]
    customer_name: str
    customer_email: Optional[str] = None
    account: Optional[str] = None
    service_type: str = "Dev+Scan"
    operator: Optional[str] = None
    force_dup: bool = False


class RollStatusUpdate(BaseModel):
    status: str
    operator: Optional[str] = None
    detail: Optional[str] = None


class RollUpdate(BaseModel):
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    service_type: Optional[str] = None
    operator: Optional[str] = None
    account: Optional[str] = None
    drive_order_folder_url: Optional[str] = None
    blank_flag: Optional[bool] = None
    print_only_flag: Optional[bool] = None
    email_status: Optional[str] = None
    blank_email_status: Optional[str] = None
    print_ready_email_status: Optional[str] = None


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def pad4(s: str) -> str:
    digits = "".join(c for c in str(s) if c.isdigit())
    return digits.zfill(4)


def log_event(db: Session, roll_id: int, event_type: str, detail: str = None, operator: str = None):
    event = RollEvent(roll_id=roll_id, event_type=event_type, detail=detail, operator=operator)
    db.add(event)


def roll_to_dict(r: Roll) -> dict:
    return {
        "id": r.id,
        "store_id": r.store_id,
        "store_name": r.store.name if r.store else None,
        "order_number": r.order_number,
        "twin_check": r.twin_check,
        "customer_name": r.customer_name,
        "customer_email": r.customer_email,
        "account": r.account,
        "service_type": r.service_type,
        "operator": r.operator,
        "status": r.status,
        "blank_flag": r.blank_flag,
        "print_only_flag": r.print_only_flag,
        "drive_order_folder_url": r.drive_order_folder_url,
        "email_status": r.email_status,
        "blank_email_status": r.blank_email_status,
        "print_ready_email_status": r.print_ready_email_status,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "date_scanned": r.date_scanned.isoformat() if r.date_scanned else None,
        "date_delivered": r.date_delivered.isoformat() if r.date_delivered else None,
        "date_print_ready_notified": r.date_print_ready_notified.isoformat() if r.date_print_ready_notified else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ─────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────

@router.get("/")
def list_rolls(
    store_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """List rolls with optional filtering. Used by the main dashboard table."""
    q = db.query(Roll)
    if store_id:
        q = q.filter(Roll.store_id == store_id)
    if status:
        q = q.filter(Roll.status == status)
    if search:
        term = f"%{search}%"
        q = q.filter(or_(
            Roll.order_number.ilike(term),
            Roll.customer_name.ilike(term),
            Roll.customer_email.ilike(term),
            Roll.twin_check.ilike(term),
        ))
    total = q.count()
    rolls = q.order_by(desc(Roll.timestamp)).offset(offset).limit(limit).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "rolls": [roll_to_dict(r) for r in rolls]
    }


@router.post("/")
def create_roll(payload: RollCreate, db: Session = Depends(get_db)):
    """Add a single roll — equivalent to intake_addRollRow in Sheets."""
    store = db.query(Store).filter(Store.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    twin = pad4(payload.twin_check)

    if not payload.force_dup:
        existing = db.query(Roll).filter(
            Roll.store_id == payload.store_id,
            Roll.twin_check == twin
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Twin {twin} already exists for this store")

    roll = Roll(
        store_id=payload.store_id,
        order_number=payload.order_number.strip().replace(" ", ""),
        twin_check=twin,
        customer_name=payload.customer_name.strip(),
        customer_email=(payload.customer_email or "").strip() or None,
        account=(payload.account or "").strip() or None,
        service_type=payload.service_type,
        operator=(payload.operator or "").strip() or None,
        status=RollStatus.booked,
        timestamp=datetime.utcnow(),
    )
    db.add(roll)
    db.flush()
    log_event(db, roll.id, "intake", f"Manual intake by {payload.operator or 'unknown'}", payload.operator)
    db.commit()
    db.refresh(roll)
    return roll_to_dict(roll)


@router.post("/batch")
def create_roll_batch(payload: RollBatchCreate, db: Session = Depends(get_db)):
    """Add multiple rolls for one order — equivalent to intake_addRollBatch."""
    store = db.query(Store).filter(Store.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    twins = [pad4(t) for t in payload.twin_checks if t.strip()]
    if not twins:
        raise HTTPException(status_code=400, detail="No twin checks provided")

    skipped = []
    saved = []

    for twin in twins:
        if not payload.force_dup:
            existing = db.query(Roll).filter(
                Roll.store_id == payload.store_id,
                Roll.twin_check == twin
            ).first()
            if existing:
                skipped.append(twin)
                continue

        roll = Roll(
            store_id=payload.store_id,
            order_number=payload.order_number.strip().replace(" ", ""),
            twin_check=twin,
            customer_name=payload.customer_name.strip(),
            customer_email=(payload.customer_email or "").strip() or None,
            account=(payload.account or "").strip() or None,
            service_type=payload.service_type,
            operator=(payload.operator or "").strip() or None,
            status=RollStatus.booked,
            timestamp=datetime.utcnow(),
        )
        db.add(roll)
        db.flush()
        log_event(db, roll.id, "intake_batch", f"Batch intake", payload.operator)
        saved.append(twin)

    db.commit()
    return {"saved": len(saved), "twins_saved": saved, "skipped": skipped}


@router.get("/check-twin")
def check_twin(store_id: int, twin: str, db: Session = Depends(get_db)):
    """Check if a twin already exists — used by intake form before saving."""
    existing = db.query(Roll).filter(
        Roll.store_id == store_id,
        Roll.twin_check == pad4(twin)
    ).first()
    return {"exists": existing is not None, "twin": pad4(twin)}


@router.get("/check-order")
def check_order(store_id: int, order_number: str, db: Session = Depends(get_db)):
    """Check if an order number already exists in this store."""
    existing = db.query(Roll).filter(
        Roll.store_id == store_id,
        Roll.order_number == order_number.strip().replace(" ", "")
    ).first()
    return {"exists": existing is not None}


@router.get("/{roll_id}")
def get_roll(roll_id: int, db: Session = Depends(get_db)):
    roll = db.query(Roll).filter(Roll.id == roll_id).first()
    if not roll:
        raise HTTPException(status_code=404, detail="Roll not found")
    return roll_to_dict(roll)


@router.patch("/{roll_id}/status")
def update_roll_status(roll_id: int, payload: RollStatusUpdate, db: Session = Depends(get_db)):
    """Update status + log event. Used by dashboard action buttons."""
    roll = db.query(Roll).filter(Roll.id == roll_id).first()
    if not roll:
        raise HTTPException(status_code=404, detail="Roll not found")

    old_status = roll.status
    roll.status = payload.status
    roll.updated_at = datetime.utcnow()

    # Auto-stamp dates based on status transition
    if payload.status == RollStatus.delivered and not roll.date_delivered:
        roll.date_delivered = datetime.utcnow()
    if payload.status in (RollStatus.scanned, RollStatus.delivered) and not roll.date_scanned:
        roll.date_scanned = datetime.utcnow()
    if payload.status == RollStatus.blank:
        roll.blank_flag = True
    if payload.status == RollStatus.print_ready:
        roll.print_only_flag = True

    log_event(
        db, roll.id, "status_change",
        f"{old_status} → {payload.status}" + (f" | {payload.detail}" if payload.detail else ""),
        payload.operator
    )
    db.commit()
    db.refresh(roll)
    return roll_to_dict(roll)


@router.patch("/{roll_id}")
def update_roll(roll_id: int, payload: RollUpdate, db: Session = Depends(get_db)):
    """General field update — used for editing customer details, drive links, etc."""
    roll = db.query(Roll).filter(Roll.id == roll_id).first()
    if not roll:
        raise HTTPException(status_code=404, detail="Roll not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(roll, field, value)
    roll.updated_at = datetime.utcnow()

    log_event(db, roll.id, "edited", str(payload.model_dump(exclude_none=True)))
    db.commit()
    db.refresh(roll)
    return roll_to_dict(roll)


@router.get("/{roll_id}/events")
def get_roll_events(roll_id: int, db: Session = Depends(get_db)):
    """Get full audit trail for a roll."""
    events = db.query(RollEvent).filter(RollEvent.roll_id == roll_id).order_by(desc(RollEvent.created_at)).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "detail": e.detail,
            "operator": e.operator,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
