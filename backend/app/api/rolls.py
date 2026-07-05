from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.orm import Roll, RollAuditLog, OrderEvent, Order
from app.models.schemas import TwinCheckUpdate

router = APIRouter(prefix="/rolls", tags=["rolls"])

# Statuses considered "active" — twins held by these rolls block new assignments
ACTIVE_STATUSES = {"booked", "processing", "scanned", "print_ready", "devready", "printready"}


@router.patch("/{roll_id}/twin-check")
async def update_twin_check(
    roll_id: UUID,
    payload: TwinCheckUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Edit the twin check number on a roll.
    Allowed on any status (including delivered/archived) to support fixing mix-ups.
    Blocked only if the new twin is already held by an active (non-delivered) roll in the same store.
    """
    result = await db.execute(select(Roll).where(Roll.id == roll_id))
    roll = result.scalar_one_or_none()
    if not roll:
        raise HTTPException(status_code=404, detail="Roll not found")

    old_twin = roll.twin_check

    # No-op if twin unchanged
    if old_twin == payload.twin_check:
        return {
            "id": str(roll.id),
            "order_id": str(roll.order_id),
            "twin_check": roll.twin_check,
            "service_type": roll.service_type,
            "status": roll.status,
            "is_blank": roll.is_blank,
            "drive_folder_url": roll.drive_folder_url,
            "created_at": roll.created_at.isoformat() if roll.created_at else None,
            "date_scanned": roll.date_scanned.isoformat() if roll.date_scanned else None,
            "date_delivered": roll.date_delivered.isoformat() if roll.date_delivered else None,
            "operator_initials": roll.operator_initials,
        }

    # Collision check — only block if an ACTIVE roll in this store already holds the new twin
    collision_result = await db.execute(
        select(Roll, Order)
        .join(Order, Roll.order_id == Order.id)
        .where(
            and_(
                Roll.store_id == roll.store_id,
                Roll.twin_check == payload.twin_check,
                Roll.id != roll.id,
                Roll.status.in_(ACTIVE_STATUSES),
            )
        )
        .limit(1)
    )
    collision = collision_result.first()
    if collision:
        conflicting_roll, conflicting_order = collision
        raise HTTPException(
            status_code=409,
            detail=f"Twin {payload.twin_check} is already in use by order {conflicting_order.order_number} — choose a different number."
        )

    roll.twin_check = payload.twin_check

    actor = current_user.get("initials") or current_user.get("email", "staff")
    user_id = current_user.get("id") or current_user.get("user_id")

    audit = RollAuditLog(
        roll_id=roll.id,
        field_name="twin_check",
        old_value=old_twin,
        new_value=payload.twin_check,
        changed_by_user_id=UUID(str(user_id)) if user_id else None,
        changed_at=datetime.utcnow(),
    )
    db.add(audit)

    event = OrderEvent(
        order_id=roll.order_id,
        roll_id=roll.id,
        event_type="twin_check_edited",
        description=f"Twin check changed: {old_twin} → {payload.twin_check}",
        actor_label=actor,
        event_data={"old_twin": old_twin, "new_twin": payload.twin_check},
    )
    db.add(event)

    await db.commit()
    await db.refresh(roll)

    return {
        "id": str(roll.id),
        "order_id": str(roll.order_id),
        "twin_check": roll.twin_check,
        "service_type": roll.service_type,
        "status": roll.status,
        "is_blank": roll.is_blank,
        "drive_folder_url": roll.drive_folder_url,
        "created_at": roll.created_at.isoformat() if roll.created_at else None,
        "date_scanned": roll.date_scanned.isoformat() if roll.date_scanned else None,
        "date_delivered": roll.date_delivered.isoformat() if roll.date_delivered else None,
        "operator_initials": roll.operator_initials,
    }
