# app/api/dashboard.py
# ============================================================
# RollCall dashboard metrics (Phase 3).
#
# Uses the Supabase client (same pattern as pronto_sync.py /
# drive_watcher.py) rather than the ORM — these are aggregation
# queries over pipeline state. supabase-py is synchronous, so
# every handler pushes its blocking body to a thread via
# asyncio.to_thread, mirroring pronto_sync.
# ============================================================

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from supabase import create_client

from app.core.config import settings
from app.core.auth import get_current_user

router = APIRouter()

PENDING_STATUSES = ("inbound", "booked_in", "scanning")

# All DB timestamps are stored as naive UTC. "Today" is the AEST
# (UTC+10, no DST — matches the PRD definition) calendar day.
AEST_OFFSET = timedelta(hours=10)


def _client():
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def _today_aest_utc_window() -> tuple[str, str]:
    """UTC [start, end) ISO strings covering the current AEST calendar day."""
    now_aest = datetime.utcnow() + AEST_OFFSET
    start_aest = now_aest.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_aest - AEST_OFFSET
    return start_utc.isoformat(), (start_utc + timedelta(days=1)).isoformat()


def _parse_ts(val) -> Optional[datetime]:
    """Parse a PostgREST timestamp string to a naive UTC datetime."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        return None


def _count_orders(client, status) -> int:
    q = client.table("orders").select("id", count="exact")
    if isinstance(status, (list, tuple)):
        q = q.in_("status", list(status))
    else:
        q = q.eq("status", status)
    return q.execute().count or 0


# PostgREST caps responses at 1000 rows — every "fetch rows" query must
# paginate or large states (thousands of inbound orders) get silently clipped.
PAGE_SIZE = 1000


def _fetch_all(build_query) -> list[dict]:
    """Exhaustively page through a query. build_query() must return a fresh
    filtered select builder each call (builders can't be re-executed)."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = build_query().range(offset, offset + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _apply_order_filters(q, status=None, **filters):
    if isinstance(status, (list, tuple)):
        q = q.in_("status", list(status))
    elif status:
        q = q.eq("status", status)
    for col, (op, val) in filters.items():
        q = getattr(q, op)(col, val)
    return q


def _order_ids(client, **filters) -> list[str]:
    rows = _fetch_all(
        lambda: _apply_order_filters(client.table("orders").select("id"), **filters)
    )
    return [r["id"] for r in rows]


def _count_rolls_for_orders(client, order_ids: list[str]) -> int:
    """Count rolls linked to the given orders, chunked to keep URLs short."""
    if not order_ids:
        return 0
    total = 0
    CHUNK = 100
    for i in range(0, len(order_ids), CHUNK):
        result = client.table("rolls").select("id", count="exact").in_(
            "order_id", order_ids[i : i + CHUNK]
        ).execute()
        total += result.count or 0
    return total


# ── GET /api/dashboard/counts ────────────────────────────────

@router.get("/counts")
async def dashboard_counts(current_user: dict = Depends(get_current_user)):
    return await asyncio.to_thread(_counts_blocking)


def _counts_blocking() -> dict:
    client = _client()
    inbound_ids = _order_ids(client, status="inbound")
    booked_ids = _order_ids(client, status="booked_in")
    return {
        "inbound_orders": len(inbound_ids),
        "booked_orders": len(booked_ids),
        "inbound_rolls": _count_rolls_for_orders(client, inbound_ids),
        "booked_rolls": _count_rolls_for_orders(client, booked_ids),
    }


# ── GET /api/dashboard/needs_attention ───────────────────────

@router.get("/needs_attention")
async def dashboard_needs_attention(current_user: dict = Depends(get_current_user)):
    return await asyncio.to_thread(_needs_attention_blocking)


def _missing_email_ids(client) -> list[str]:
    rows = _fetch_all(
        lambda: client.table("orders").select("id, customer_email").eq("status", "delivered")
    )
    return [r["id"] for r in rows if not (r.get("customer_email") or "").strip()]


def _overdue_ids(client) -> list[str]:
    cutoff = (datetime.utcnow() - timedelta(hours=48)).isoformat()
    return _order_ids(client, status="booked_in", booked_in_at=("lt", cutoff))


def _needs_attention_blocking() -> dict:
    client = _client()
    cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    overdue = _overdue_ids(client)
    stuck = _order_ids(client, status="scanning", scanning_at=("lt", cutoff_24h))
    missing_email = _missing_email_ids(client)
    inbound_aging = _order_ids(client, status="inbound", pronto_order_date=("lt", cutoff_24h))

    return {
        "overdue_count": len(overdue),
        "overdue_order_ids": overdue,
        "stuck_in_scanning_count": len(stuck),
        "stuck_in_scanning_order_ids": stuck,
        "missing_email_count": len(missing_email),
        "missing_email_order_ids": missing_email,
        "inbound_aging_count": len(inbound_aging),
        "inbound_aging_order_ids": inbound_aging,
    }


# ── GET /api/dashboard/today_activity ────────────────────────

@router.get("/today_activity")
async def dashboard_today_activity(current_user: dict = Depends(get_current_user)):
    return await asyncio.to_thread(_today_activity_blocking)


def _count_in_window(client, ts_column: str, start: str, end: str) -> int:
    return client.table("orders").select("id", count="exact").gte(
        ts_column, start
    ).lt(ts_column, end).execute().count or 0


def _today_activity_blocking() -> dict:
    client = _client()
    start, end = _today_aest_utc_window()
    return {
        "orders_received": _count_in_window(client, "pronto_order_date", start, end),
        "orders_booked_in": _count_in_window(client, "booked_in_at", start, end),
        "orders_delivered": _count_in_window(client, "delivered_at", start, end),
    }


# ── GET /api/dashboard/performance ───────────────────────────

@router.get("/performance")
async def dashboard_performance(current_user: dict = Depends(get_current_user)):
    return await asyncio.to_thread(_performance_blocking)


def _performance_blocking() -> dict:
    client = _client()
    start, end = _today_aest_utc_window()

    # Average turnaround over the last 30 days of deliveries
    cutoff_30d = (datetime.utcnow() - timedelta(days=30)).isoformat()
    delivered = _fetch_all(
        lambda: client.table("orders").select("booked_in_at, delivered_at")
        .eq("status", "delivered").gte("delivered_at", cutoff_30d)
    )

    turnarounds = []
    for row in delivered:
        booked = _parse_ts(row.get("booked_in_at"))
        done = _parse_ts(row.get("delivered_at"))
        if booked and done and done >= booked:
            turnarounds.append((done - booked).total_seconds() / 86400)
    avg_turnaround = round(sum(turnarounds) / len(turnarounds), 1) if turnarounds else 0.0

    today_delivered_ids = [
        r["id"] for r in _fetch_all(
            lambda: client.table("orders").select("id")
            .gte("delivered_at", start).lt("delivered_at", end)
        )
    ]
    pending_ids = _order_ids(client, status=PENDING_STATUSES)

    return {
        "avg_turnaround_days": avg_turnaround,
        "rolls_today": _count_rolls_for_orders(client, today_delivered_ids),
        "pending_rolls": _count_rolls_for_orders(client, pending_ids),
        "pending_orders": len(pending_ids),
        "overdue_count": len(_overdue_ids(client)),
    }


# ── GET /api/dashboard/workload ──────────────────────────────

@router.get("/workload")
async def dashboard_workload(current_user: dict = Depends(get_current_user)):
    return await asyncio.to_thread(_workload_blocking)


def _workload_blocking() -> dict:
    client = _client()
    now = datetime.utcnow()

    pending = _fetch_all(
        lambda: client.table("orders").select("id, pronto_order_date, created_at")
        .in_("status", list(PENDING_STATUSES))
    )

    ages = []
    for row in pending:
        # pronto_order_date per spec; manual orders have none — fall back
        # to created_at so they still count toward workload
        anchor = _parse_ts(row.get("pronto_order_date")) or _parse_ts(row.get("created_at"))
        if anchor:
            ages.append(max((now - anchor).total_seconds() / 86400, 0.0))

    return {
        "avg_pending_age_days": round(sum(ages) / len(ages), 1) if ages else 0.0,
        "oldest_pending_days": int(max(ages)) if ages else 0,
        "missing_email_count": len(_missing_email_ids(client)),
    }
