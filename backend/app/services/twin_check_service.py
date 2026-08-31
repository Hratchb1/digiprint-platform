# app/services/twin_check_service.py
# ============================================================
# Twin check allocation, manual-entry recording, print job building,
# void/reprint, and rescan creation.
#
# See backend/migrations/009_twin_check_allocation.sql for the full
# design rationale. The short version, repeated here because it drives
# every function in this file:
#
#   A twin check is one concept regardless of provenance — same
#   storage, display, and downstream operations, whether RollCall
#   allocated it or a staff member typed it off pre-printed stock.
#   TwinCheck.source ('auto'|'manual') is the entire distinction:
#     - Both write a TwinCheck row and set Roll.twin_check_id.
#     - Only 'auto' rows are drawn from TwinCheckSequence and carry a
#       real cycle; 'manual' rows never advance current_value.
#     - Both run the same collision check before insert.
#
#   Collision detection reads Roll.twin_check (status <> 'archived'),
#   NOT the twin_checks table — historical rolls that predate this
#   feature have no TwinCheck row and are deliberately not backfilled.
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Roll, Order, TwinCheck, TwinCheckSequence, PrintJob, OrderEvent, Store
from app.core.timeutils import utcnow

logger = logging.getLogger(__name__)

# Rescan display suffixes start at B (the original delivered order is
# implicitly "A" / unsuffixed) and stop at Z — 25 rescans of the same
# order is well past any real-world case.
RESCAN_LETTERS = [chr(c) for c in range(ord("B"), ord("Z") + 1)]


# ── Pure logic — no DB, unit-testable directly (see tests/test_twin_check_service.py) ──

def compute_process_mix(sku_lines: list[dict], sku_map: dict[str, dict]) -> dict:
    """
    Given an order's Pronto SKU lines (pronto_order_summary.sku_lines shape —
    see api/pronto.py) and a sku_code -> {requires_twin_check, process_code}
    lookup, return how many twin checks this order needs and their process
    mix.

    THIS IS THE FIX FOR THE DOUBLE-COUNT BUG. Only lines whose SKU is
    flagged requires_twin_check=True contribute. A Dev+Scan order booked as
    two line items — e.g. a Dev SKU x5 and its accompanying Scan SKU x5 for
    the *same five physical rolls* — sums to 5, not 10, because the Scan SKU
    is never flagged. Summing every line regardless of category is the
    obvious approach and it is wrong; this function exists specifically so
    that mistake can't be made at any call site.

    Returns:
        {
          "total": int,                                  # rolls needed
          "mix": [{"process_code": str|None, "count": int}, ...],
          "unmapped": bool,   # True if any flagged line has no process_code —
                               # callers must block and prompt, never default
                               # to C41 (criterion #11c).
        }
    """
    mix: dict[Optional[str], int] = {}
    total = 0
    unmapped = False

    for line in sku_lines or []:
        sku_code = str(line.get("sku_code") or "").strip()
        info = sku_map.get(sku_code)
        if not info or not info.get("requires_twin_check"):
            continue

        qty = int(line.get("shipped_units") or 0)
        if qty <= 0:
            continue

        code = info.get("process_code")
        if code is None:
            unmapped = True

        total += qty
        mix[code] = mix.get(code, 0) + qty

    return {
        "total": total,
        "mix": [{"process_code": k, "count": v} for k, v in mix.items()],
        "unmapped": unmapped,
    }


def _pad(number: int) -> str:
    return str(number).zfill(4)


# ── Store config (raw SQL — store_settings has no ORM model, matching the
#    existing convention where non-core-request tables like sku_map/
#    pronto_cache are queried via text() through the same AsyncSession
#    rather than given a full ORM mapping; see api/pronto.py) ──

async def _get_store_settings(db: AsyncSession, store_id: UUID) -> dict:
    result = await db.execute(
        text(
            "SELECT label_printer_ip, label_printer_dpi, label_width_mm, "
            "label_height_mm, label_copies, print_agent_token "
            "FROM store_settings WHERE store_id = :sid"
        ),
        {"sid": str(store_id)},
    )
    row = result.mappings().first()
    if not row:
        raise ValueError(
            f"No store_settings row for store {store_id} — run migration 009's "
            f"seed step (store_settings had 0 rows before this feature)."
        )
    return dict(row)


# ── Collision detection ──────────────────────────────────────────────────

async def _collision_check(
    db: AsyncSession,
    store_id: UUID,
    twin_check: str,
    exclude_roll_id: Optional[UUID] = None,
) -> bool:
    """
    True if `twin_check` is already held by another active roll in this
    store. Reads Roll.twin_check, not the twin_checks table — see module
    docstring. Mirrors order_service._get_existing_twins's status filter.
    """
    conditions = [
        Roll.store_id == store_id,
        Roll.twin_check == twin_check,
        Roll.status != "archived",
    ]
    if exclude_roll_id:
        conditions.append(Roll.id != exclude_roll_id)

    result = await db.execute(select(Roll.id).where(and_(*conditions)).limit(1))
    return result.scalar_one_or_none() is not None


# ── Manual entry — writes a twin_checks row, never touches the sequence ──

async def record_manual_twin(
    db: AsyncSession, roll: Roll, twin_check: str, actor: str
) -> TwinCheck:
    """
    Called from order_service.create_order() / api.orders.add_rolls_to_order()
    for every roll that already carries a typed twin_check — i.e. every
    manual-mode booking, and every booking in a store where auto_enabled is
    off. Writes a TwinCheck row (source='manual') in the SAME transaction as
    the roll insert (does not commit — caller commits). Never touches
    TwinCheckSequence: a mistyped 9500 must never advance the sequence to
    dodge a future collision (§3.3 relies on log-and-warn only, identically
    for auto and manual).

    Every current caller already validated twin_check via a Pydantic field
    validator (RollIntake.pad_twin / TwinCheckUpdate.validate_twin) before it
    gets here, but this function doesn't get to assume that forever — a
    future call site that skips Pydantic would otherwise hit an unhandled
    int() ValueError and 500 the whole request. Re-checking here costs
    nothing and turns that into the same clean 400 every other bad-input
    path in this service already produces.
    """
    if not twin_check or not twin_check.isdigit() or len(twin_check) != 4:
        raise ValueError(f"Invalid twin check {twin_check!r} — must be exactly 4 digits")

    collision = await _collision_check(db, roll.store_id, twin_check, exclude_roll_id=roll.id)

    tc = TwinCheck(
        store_id=roll.store_id,
        number=int(twin_check),
        cycle=None,
        source="manual",
        order_id=roll.order_id,
        roll_id=roll.id,
        collision_warning=collision,
        allocated_by=actor,
    )
    db.add(tc)
    await db.flush()
    roll.twin_check_id = tc.id

    if collision:
        logger.warning(
            f"[twin_check_service] Collision (manual entry): store={roll.store_id} "
            f"number={twin_check} order={roll.order_id} roll={roll.id} — flagged, not skipped."
        )

    return tc


# ── Auto allocation ──────────────────────────────────────────────────────

async def allocate_for_order(db: AsyncSession, order_id: UUID, actor: str) -> list[TwinCheck]:
    """
    Allocates numbers for every pending (twin_check_id IS NULL) roll on this
    order, in one contiguous block. Idempotent: if no rolls are pending
    (either because a prior call already allocated them, or none exist),
    returns the order's existing block instead of allocating again — a
    double-click on Book In must not consume two blocks (criterion #3).

    `.with_for_update()` on the pending-rolls query closes the race a plain
    idempotency check would miss: two near-simultaneous calls for the same
    order must not both see the same pending rolls and both allocate — the
    second blocks until the first commits, then finds nothing pending.
    """
    order = await db.get(Order, order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")

    pending = (
        await db.execute(
            select(Roll)
            .where(and_(Roll.order_id == order_id, Roll.twin_check_id.is_(None)))
            .order_by(Roll.created_at)
            .with_for_update()
        )
    ).scalars().all()

    if not pending:
        existing = (
            await db.execute(
                select(TwinCheck)
                .where(TwinCheck.order_id == order_id)
                .order_by(TwinCheck.number)
            )
        ).scalars().all()
        return existing

    count = len(pending)
    allocations = (
        await db.execute(
            text("SELECT number, cycle FROM allocate_twin_checks(:sid, :n)"),
            {"sid": str(order.store_id), "n": count},
        )
    ).fetchall()

    # allocate_twin_checks() always returns exactly p_count rows by
    # construction (generate_series(start_at, start_at + p_count - 1)), but
    # this loop would silently under-allocate — stranding the tail of
    # `pending` at twin_check_id=NULL with no error raised — if that were
    # ever violated by a future change to the function or an unexpected
    # driver/result-set quirk. zip() truncates to the shorter sequence
    # rather than erroring, so the mismatch has to be checked explicitly.
    if len(allocations) != count:
        raise ValueError(
            f"allocate_twin_checks returned {len(allocations)} row(s) for a "
            f"request of {count} — refusing to partially allocate order {order_id}"
        )

    created: list[TwinCheck] = []
    for roll, row in zip(pending, allocations):
        number, cycle = row.number, row.cycle
        padded = _pad(number)
        collision = await _collision_check(db, order.store_id, padded)

        tc = TwinCheck(
            store_id=order.store_id,
            number=number,
            cycle=cycle,
            source="auto",
            order_id=order_id,
            roll_id=roll.id,
            collision_warning=collision,
            allocated_by=actor,
        )
        db.add(tc)
        await db.flush()

        roll.twin_check = padded
        roll.twin_check_id = tc.id
        created.append(tc)

        if collision:
            logger.warning(
                f"[twin_check_service] Collision (auto allocate): store={order.store_id} "
                f"number={padded} new order={order_id} roll={roll.id} — flagged, not skipped."
            )

    await db.commit()
    for tc in created:
        await db.refresh(tc)
    return created


async def add_roll(
    db: AsyncSession, order_id: UUID, service_type: str,
    process_code: Optional[str], actor: str,
) -> list[TwinCheck]:
    """Allocate one more twin check mid-job — creates a pending roll, then
    delegates to allocate_for_order (which only ever allocates for rolls
    still pending, so this never touches already-allocated rolls on the
    same order)."""
    order = await db.get(Order, order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")

    roll = Roll(
        order_id=order_id,
        store_id=order.store_id,
        service_type=service_type,
        process_code=process_code,
        status="booked",
        operator_initials=actor,
    )
    db.add(roll)
    await db.flush()

    db.add(OrderEvent(
        order_id=order_id,
        roll_id=roll.id,
        event_type="roll_added_mid_job",
        description="Roll added mid-job — pending twin check allocation",
        actor_label=actor,
    ))

    return await allocate_for_order(db, order_id, actor)


# ── Void / reprint ────────────────────────────────────────────────────────

async def void_twin_check(db: AsyncSession, twin_check_id: UUID, reason: str, actor: str) -> TwinCheck:
    """
    Burns the number — never reissued (TwinCheckSequence is untouched, the
    sequence only ever moves forward). Re-opens the linked roll
    (twin_check/twin_check_id -> NULL) so it can be picked up by a follow-up
    allocate or manual re-entry; the roll itself is not deleted.
    """
    tc = await db.get(TwinCheck, twin_check_id)
    if not tc:
        raise ValueError(f"Twin check {twin_check_id} not found")
    if tc.status == "voided":
        raise ValueError("Twin check is already voided")
    if not reason or not reason.strip():
        raise ValueError("A void reason is required")

    tc.status = "voided"
    tc.voided_at = utcnow()
    tc.void_reason = reason

    if tc.roll_id:
        roll = await db.get(Roll, tc.roll_id)
        if roll and roll.twin_check_id == tc.id:
            roll.twin_check = None
            roll.twin_check_id = None

    db.add(OrderEvent(
        order_id=tc.order_id,
        roll_id=tc.roll_id,
        event_type="twin_check_voided",
        description=f"Twin check {_pad(tc.number)} voided — {reason}",
        actor_label=actor,
        event_data={"twin_check_id": str(tc.id), "number": tc.number, "reason": reason},
    ))

    await db.commit()
    await db.refresh(tc)
    return tc


async def reprint_twin_check(db: AsyncSession, twin_check_id: UUID, actor: str) -> PrintJob:
    """Re-enqueues the identical number — never allocates (criterion #4).

    Auto-only. A manual twin check has no digital label in the first place
    — the physical sticker was already pre-printed before it was typed in —
    so there is nothing to reprint. Void is deliberately NOT restricted this
    way (burning a wrongly-entered number is meaningful regardless of
    provenance); this asymmetry is intentional, not an oversight."""
    tc = await db.get(TwinCheck, twin_check_id)
    if not tc:
        raise ValueError(f"Twin check {twin_check_id} not found")
    if tc.status == "voided":
        raise ValueError("Cannot reprint a voided twin check")
    if tc.source == "manual":
        raise ValueError(
            "Manual twin checks have no digital label to reprint — the "
            "physical sticker was already pre-printed."
        )
    if not tc.roll_id:
        raise ValueError("Twin check has no associated roll")

    roll = await db.get(Roll, tc.roll_id)
    if not roll:
        raise ValueError("Associated roll no longer exists")
    if not roll.process_code:
        raise ValueError(
            "Roll has no process code set — select a process before printing "
            "(never defaults to C41)."
        )
    order = await db.get(Order, tc.order_id) if tc.order_id else None

    return await _build_print_job(db, store_id=tc.store_id, pairs=[(roll, tc)], order=order, actor=actor)


# ── Print job building ───────────────────────────────────────────────────

async def build_print_job_for_order(db: AsyncSession, order_id: UUID, actor: str) -> PrintJob:
    """Prints every non-voided, auto-allocated roll on the order —
    re-clickable without reallocating (it never touches TwinCheckSequence or
    creates new TwinCheck rows, only reads existing ones).

    Auto-only. An order can genuinely mix auto and manual rolls (e.g.
    auto-booked, then a roll added manually via add-rolls) — manual rolls
    are silently excluded here rather than blocking the whole batch, since
    there's nothing to print for them (see reprint_twin_check's docstring).
    """
    order = await db.get(Order, order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")

    pairs = (
        await db.execute(
            select(Roll, TwinCheck)
            .join(TwinCheck, Roll.twin_check_id == TwinCheck.id)
            .where(and_(
                Roll.order_id == order_id,
                TwinCheck.status != "voided",
                TwinCheck.source == "auto",
            ))
            .order_by(TwinCheck.number)
        )
    ).all()
    pairs = [(row[0], row[1]) for row in pairs]

    if not pairs:
        raise ValueError(
            "No auto-allocated twin checks on this order to print — manual "
            "entries have no digital label to generate."
        )

    missing_process = [str(roll.id) for roll, _ in pairs if not roll.process_code]
    if missing_process:
        raise ValueError(
            f"{len(missing_process)} roll(s) have no process code set — select a "
            f"process before printing (never defaults to C41): {', '.join(missing_process)}"
        )

    return await _build_print_job(db, store_id=order.store_id, pairs=pairs, order=order, actor=actor)


async def _build_print_job(
    db: AsyncSession, store_id: UUID, pairs: list[tuple[Roll, TwinCheck]],
    order: Optional[Order], actor: str,
) -> PrintJob:
    # Imported, not rewritten — see backend/twincheck/twincheck_label.py.
    from twincheck.twincheck_label import LabelSpec, build_job

    settings_row = await _get_store_settings(db, store_id)
    store = await db.get(Store, store_id)
    sequence = await db.get(TwinCheckSequence, store_id)

    spec = LabelSpec(
        dpi=int(settings_row.get("label_printer_dpi") or 203),
        width_mm=float(settings_row.get("label_width_mm") or 23),
        height_mm=float(settings_row.get("label_height_mm") or 15),
    )
    copies = int(settings_row.get("label_copies") or 2)
    order_number = order.order_number if order else "?"
    if order and order.rescan_display_suffix:
        order_number = f"{order_number}-{order.rescan_display_suffix}"

    label_rolls = [
        {
            "order": order_number,
            # Short process code only (C41/BW/RSC) — never film format or
            # brand, see §3.5b. roll_index/roll_total are computed by
            # build_job itself from the list position — do not pass them here.
            "film_type": roll.process_code,
            "twin_check": tc.number,
        }
        for roll, tc in pairs
    ]

    zpl = build_job(
        rolls=label_rolls,
        spec=spec,
        store=store.territory_code if store else "",
        # Cosmetic only under the default code128 barcode (only the
        # datamatrix variant encodes cycle) — the store's current cycle is
        # a harmless, always-defined choice for a job that may mix auto
        # (real cycle) and manual (cycle=None) rows.
        cycle=(sequence.cycle if sequence else 1),
        copies=copies,
    )

    job = PrintJob(store_id=store_id, zpl=zpl, status="pending")
    db.add(job)

    now = utcnow()
    for _, tc in pairs:
        if tc.status == "allocated":
            tc.status = "printed"
        tc.printed_at = now

    db.add(OrderEvent(
        order_id=order.id if order else None,
        event_type="labels_printed",
        description=f"{len(pairs)} label(s) enqueued for printing",
        actor_label=actor,
        event_data={"twin_checks": [tc.number for _, tc in pairs]},
    ))

    await db.commit()
    await db.refresh(job)
    return job


# ── Rescan ────────────────────────────────────────────────────────────────

async def _next_rescan_suffix(db: AsyncSession, root_order: Order) -> str:
    """
    Union of two sources of taken letters on this root order number + store:
      1. rescan_display_suffix on existing rescan children of the root.
      2. Literal order_number values matching '{root}-[A-Z]' in the same
         store — the pre-existing duplicate-order-modal mechanism in
         IntakePage.tsx, which writes "{order_number}-B" directly into
         order_number for an unrelated case (the same Pronto order booked
         twice). Without this check, a first rescan would also compute "B"
         and display identically to an unrelated real order already named
         "{order_number}-B".
    Returns the smallest unused letter starting at B.
    """
    children = (
        await db.execute(
            select(Order.rescan_display_suffix).where(Order.rescan_of_order_id == root_order.id)
        )
    ).all()
    taken = {s for (s,) in children if s}

    pattern = f"^{re.escape(root_order.order_number)}-[A-Z]$"
    dup_modal_rows = (
        await db.execute(
            text("SELECT order_number FROM orders WHERE store_id = :sid AND order_number ~ :pattern"),
            {"sid": str(root_order.store_id), "pattern": pattern},
        )
    ).all()
    for (order_number,) in dup_modal_rows:
        taken.add(order_number.rsplit("-", 1)[-1])

    for letter in RESCAN_LETTERS:
        if letter not in taken:
            return letter
    raise ValueError("Exhausted rescan suffix letters (B-Z) for this order")


async def create_rescan(
    db: AsyncSession, order_id: UUID, roll_ids: list[UUID], actor: str,
) -> Order:
    """
    Creates a linked rescan order for a subset of rolls on a delivered
    order. Does not allocate — the caller (api/twin_checks.py) calls
    allocate_for_order() on the returned order right after, matching the
    two-step allocate pattern used everywhere else.
    """
    order = await db.get(Order, order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")
    if order.status != "delivered":
        raise ValueError("Rescan is only available on a delivered order")
    if not roll_ids:
        raise ValueError("Select at least one roll to rescan")

    # Resolve the ultimate root — a rescan of a rescan still displays off
    # the original order number, not the intermediate one.
    root = order
    while root.rescan_of_order_id:
        parent = await db.get(Order, root.rescan_of_order_id)
        if not parent:
            break
        root = parent

    rolls_to_rescan = (
        await db.execute(
            select(Roll).where(and_(Roll.id.in_(roll_ids), Roll.order_id == order_id))
        )
    ).scalars().all()
    if len(rolls_to_rescan) != len(set(str(r) for r in roll_ids)):
        raise ValueError("Some roll_ids were not found on this order")

    suffix = await _next_rescan_suffix(db, root)

    new_order = Order(
        order_number=root.order_number,  # unchanged — suffix is display-only
        pronto_order_number=order.pronto_order_number,
        store_id=order.store_id,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        customer_email=order.customer_email,
        phone_number=order.phone_number,
        account=order.account,
        order_type=order.order_type,
        status="booked_in",
        booked_in_at=utcnow(),
        manual_entry=order.manual_entry,
        operator_initials=actor,
        rescan_of_order_id=root.id,
        rescan_display_suffix=suffix,
    )
    db.add(new_order)
    await db.flush()

    for _old_roll in rolls_to_rescan:
        db.add(Roll(
            order_id=new_order.id,
            store_id=new_order.store_id,
            service_type="Scan only",
            process_code="RSC",
            status="booked",
            operator_initials=actor,
        ))

    display = f"{root.order_number}-{suffix}"
    db.add(OrderEvent(
        order_id=new_order.id,
        event_type="rescan_created",
        description=f"Rescan of order {root.order_number} ({len(rolls_to_rescan)} roll(s)) — {display}",
        actor_label=actor,
        event_data={
            "original_order_id": str(order_id),
            "root_order_id": str(root.id),
            "roll_ids": [str(r) for r in roll_ids],
        },
    ))
    db.add(OrderEvent(
        order_id=order_id,
        event_type="rescanned",
        description=f"{len(rolls_to_rescan)} roll(s) sent for rescan as {display}",
        actor_label=actor,
        event_data={"rescan_order_id": str(new_order.id)},
    ))

    # Deliberately does not commit — the caller (api/twin_checks.py's
    # rescan() endpoint) immediately calls allocate_for_order() on this same
    # order within the same request/session, and that call's own commit is
    # the single terminal commit for the whole operation. Committing here
    # first would split "create the rescan order" and "allocate its twin
    # checks" into two transactions with no atomicity between them — if
    # allocate_for_order failed after this commit, the rescan order would be
    # left permanently stranded with pending rolls and no numbers, and
    # nothing in the UI offers a way to retry just the allocation step for
    # an already-created order. flush() below is enough to populate
    # new_order.id and make the new rolls visible to allocate_for_order's
    # own query within this same uncommitted transaction.
    await db.flush()
    return new_order


twin_check_service_functions = (
    "compute_process_mix", "record_manual_twin", "allocate_for_order", "add_roll",
    "void_twin_check", "reprint_twin_check", "build_print_job_for_order", "create_rescan",
)
