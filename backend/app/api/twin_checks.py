# app/api/twin_checks.py
# ============================================================
# Twin check allocation, reprint/void, rescan, print queue, and the
# per-store auto_enabled admin toggle.
#
# See backend/migrations/009_twin_check_allocation.sql and
# app/services/twin_check_service.py for the full design — a twin check
# is one concept regardless of provenance (source='auto'|'manual' is the
# entire distinction); every endpoint here works identically for both.
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Optional, List
from uuid import UUID

from app.core.database import get_db
from app.core.auth import get_current_user, effective_store_id, assert_can_access, require_admin
from app.core.timeutils import utcnow
from app.models.orm import TwinCheck, TwinCheckSequence, PrintJob
from app.models.schemas import (
    AllocateResponse, TwinCheckRead, VoidTwinCheckRequest, AddRollPayload,
    RescanRequest, PrintQueueJobRead, PrintQueueAckRequest,
    TwinCheckSequenceRead, TwinCheckSequenceUpdate,
)
from app.services import twin_check_service
from app.services.order_service import order_service

router = APIRouter(tags=["twin_checks"])


def _actor(current_user: dict) -> str:
    return current_user.get("initials") or current_user.get("email", "staff")


def _pad(n: int) -> str:
    return str(n).zfill(4)


def _to_read(tc: TwinCheck) -> TwinCheckRead:
    return TwinCheckRead(
        id=tc.id, store_id=tc.store_id, number=tc.number, twin_check=_pad(tc.number),
        cycle=tc.cycle, source=tc.source, order_id=tc.order_id, roll_id=tc.roll_id,
        status=tc.status, collision_warning=tc.collision_warning,
        allocated_at=tc.allocated_at, allocated_by=tc.allocated_by,
        printed_at=tc.printed_at, voided_at=tc.voided_at, void_reason=tc.void_reason,
    )


def _range_label(twin_checks: List[TwinCheck]) -> Optional[str]:
    """'4821-4830' for a contiguous same-cycle block, the single padded
    number for a block of one, else None (e.g. a mixed-cycle set pulled
    together after a wrap — still valid, just not a clean range to print)."""
    if not twin_checks:
        return None
    numbers = sorted(tc.number for tc in twin_checks)
    cycles = {tc.cycle for tc in twin_checks}
    contiguous = numbers[-1] - numbers[0] + 1 == len(numbers)
    if contiguous and len(cycles) <= 1:
        return _pad(numbers[0]) if len(numbers) == 1 else f"{_pad(numbers[0])}-{_pad(numbers[-1])}"
    return None


async def _get_order_or_404(db: AsyncSession, order_id: UUID, current_user: dict):
    order = await order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_can_access(order, current_user)
    return order


async def _get_twin_check_or_404(db: AsyncSession, twin_check_id: UUID, current_user: dict) -> TwinCheck:
    tc = await db.get(TwinCheck, twin_check_id)
    if not tc:
        raise HTTPException(status_code=404, detail="Twin check not found")
    assert_can_access(tc, current_user)
    return tc


# ── Allocate / print / add-roll (order-scoped) ──────────────────────────────

@router.post("/orders/{order_id}/twin-checks/allocate", response_model=AllocateResponse)
async def allocate(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Allocate a block for every pending roll on this order. Idempotent —
    a double-click / retry finds nothing pending and returns the existing
    block instead of allocating twice."""
    await _get_order_or_404(db, order_id, current_user)
    try:
        twin_checks = await twin_check_service.allocate_for_order(db, order_id, _actor(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AllocateResponse(
        order_id=order_id,
        twin_checks=[_to_read(tc) for tc in twin_checks],
        range_label=_range_label(twin_checks),
    )


@router.post("/orders/{order_id}/twin-checks/print")
async def print_labels(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Render ZPL for every allocated, non-voided roll on the order and
    enqueue a print_jobs row. Re-clickable without reallocating."""
    await _get_order_or_404(db, order_id, current_user)
    try:
        job = await twin_check_service.build_print_job_for_order(db, order_id, _actor(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"print_job_id": str(job.id), "status": job.status}


@router.post("/orders/{order_id}/twin-checks/add-roll", response_model=AllocateResponse)
async def add_roll(
    order_id: UUID,
    payload: AddRollPayload,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Allocate one more twin check mid-job, logged."""
    await _get_order_or_404(db, order_id, current_user)
    try:
        twin_checks = await twin_check_service.add_roll(
            db, order_id, payload.service_type.value, payload.process_code, _actor(current_user)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AllocateResponse(
        order_id=order_id,
        twin_checks=[_to_read(tc) for tc in twin_checks],
        range_label=_range_label(twin_checks),
    )


# ── Reprint / void (twin-check-scoped) ──────────────────────────────────────

@router.post("/twin-checks/{twin_check_id}/reprint")
async def reprint(
    twin_check_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Re-enqueue the identical number. Never allocates."""
    await _get_twin_check_or_404(db, twin_check_id, current_user)
    try:
        job = await twin_check_service.reprint_twin_check(db, twin_check_id, _actor(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"print_job_id": str(job.id), "status": job.status}


@router.post("/twin-checks/{twin_check_id}/void", response_model=TwinCheckRead)
async def void(
    twin_check_id: UUID,
    payload: VoidTwinCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Burn the number — reason required. The linked roll is reset to
    pending so it can be reallocated or retyped; the number itself is
    never reissued."""
    await _get_twin_check_or_404(db, twin_check_id, current_user)
    try:
        tc = await twin_check_service.void_twin_check(db, twin_check_id, payload.reason, _actor(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_read(tc)


# ── Rescan ────────────────────────────────────────────────────────────────

@router.post("/orders/{order_id}/rescan", response_model=AllocateResponse)
async def rescan(
    order_id: UUID,
    payload: RescanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a linked rescan order for a subset of rolls on a delivered
    order, and allocate fresh twin checks for it immediately."""
    await _get_order_or_404(db, order_id, current_user)
    try:
        new_order = await twin_check_service.create_rescan(db, order_id, payload.roll_ids, _actor(current_user))
        twin_checks = await twin_check_service.allocate_for_order(db, new_order.id, _actor(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AllocateResponse(
        order_id=new_order.id,
        twin_checks=[_to_read(tc) for tc in twin_checks],
        range_label=_range_label(twin_checks),
    )


# ── Print queue — store print agent auth (token, not JWT) ─────────────────
# An always-on background poller is a poor fit for an 8h-expiry JWT — see
# migration 009 / the build plan. store_settings.print_agent_token is
# admin-set (random default on seed), checked via this header on exactly
# these two endpoints; everything else keeps using the normal JWT flow.

async def _verify_print_agent(db: AsyncSession, store_id: UUID, x_print_agent_token: Optional[str]) -> None:
    if not x_print_agent_token:
        raise HTTPException(status_code=401, detail="Missing X-Print-Agent-Token header")
    result = await db.execute(
        text("SELECT print_agent_token FROM store_settings WHERE store_id = :sid"),
        {"sid": str(store_id)},
    )
    row = result.first()
    if not row or not row[0] or row[0] != x_print_agent_token:
        raise HTTPException(status_code=401, detail="Invalid print agent token")


@router.get("/print-queue", response_model=List[PrintQueueJobRead])
async def get_print_queue(
    store_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    x_print_agent_token: Optional[str] = Header(None),
):
    await _verify_print_agent(db, store_id, x_print_agent_token)
    result = await db.execute(
        select(PrintJob)
        .where(PrintJob.store_id == store_id, PrintJob.status == "pending")
        .order_by(PrintJob.created_at)
    )
    return result.scalars().all()


@router.post("/print-queue/{job_id}/ack")
async def ack_print_job(
    job_id: UUID,
    payload: PrintQueueAckRequest,
    db: AsyncSession = Depends(get_db),
    x_print_agent_token: Optional[str] = Header(None),
):
    job = await db.get(PrintJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Print job not found")
    await _verify_print_agent(db, job.store_id, x_print_agent_token)

    job.status = payload.status
    if payload.status == "sent":
        job.sent_at = utcnow()
        job.error = None
    else:
        job.error = payload.error
        # Left as 'failed' for the agent's own retry/backoff — not
        # re-enqueued server-side (§6 of the brief).

    await db.commit()
    return {"id": str(job.id), "status": job.status}


# ── Store-scoped mode check (any authenticated user, not admin-only) ──────
# The full TwinCheckSequenceRead (current_value/cycle) below is admin-only —
# but the intake flow needs to know whether to show the auto or manual
# twin-check UI, and that decision has to be available to every staff
# member booking an order, not just admins.

@router.get("/twin-check-sequences/{store_id}/mode")
async def get_sequence_mode(
    store_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    store_scope: Optional[UUID] = Depends(effective_store_id),
):
    if store_scope is not None and store_scope != store_id:
        raise HTTPException(status_code=404, detail="Not found")
    seq = await db.get(TwinCheckSequence, store_id)
    if not seq:
        raise HTTPException(status_code=404, detail="No sequence configured for this store")
    return {"store_id": str(store_id), "auto_enabled": seq.auto_enabled}


# ── Admin — per-store auto_enabled toggle, current_value/cycle visibility ──

@router.get("/twin-check-sequences", response_model=List[TwinCheckSequenceRead])
async def list_sequences(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
    store_scope: Optional[UUID] = Depends(effective_store_id),
):
    q = select(TwinCheckSequence)
    if store_scope is not None:
        q = q.where(TwinCheckSequence.store_id == store_scope)
    result = await db.execute(q)
    return result.scalars().all()


@router.patch("/twin-check-sequences/{store_id}", response_model=TwinCheckSequenceRead)
async def update_sequence(
    store_id: UUID,
    payload: TwinCheckSequenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
    store_scope: Optional[UUID] = Depends(effective_store_id),
):
    if store_scope is not None and store_scope != store_id:
        raise HTTPException(status_code=404, detail="Not found")
    seq = await db.get(TwinCheckSequence, store_id)
    if not seq:
        raise HTTPException(status_code=404, detail="No sequence configured for this store")
    seq.auto_enabled = payload.auto_enabled
    seq.updated_at = utcnow()
    await db.commit()
    await db.refresh(seq)
    return seq
