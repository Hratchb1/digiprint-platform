# app/api/pronto.py
# ============================================================
# Pronto lookup endpoints consumed by the intake form.
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import get_current_user
from app.services.pronto_sync import sync_pronto_cache
from app.services.twin_check_service import compute_process_mix

router = APIRouter(prefix="/pronto", tags=["pronto"])

# ── GET /api/pronto/lookup/{order_number} ───────────────────
@router.get("/lookup/{order_number}")
async def lookup_order(
    order_number: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Look up a Pronto order number in the cache.
    Returns customer details + aggregated SKU summary for intake form auto-fill.
    """
    order_number = order_number.strip()

    result = await db.execute(
        text("SELECT * FROM pronto_order_summary WHERE sales_order_number = :order_num"),
        {"order_num": order_number},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_number} not found in Pronto cache.",
        )

    # Build the SKU summary lines for display in the intake form
    sku_lines = row.sku_lines or []

    # Separate dev / scan / print lines for the order summary panel
    dev_lines   = [l for l in sku_lines if l.get("category") == "Developing"]
    scan_lines  = [l for l in sku_lines if l.get("category") == "Scanning"]
    print_lines = [l for l in sku_lines if l.get("category") == "Film Printing"]

    # Build human-readable roll summary  e.g. ["C41 35mm × 2", "B&W 120mm × 1"]
    roll_summary = []
    for line in dev_lines:
        film  = line.get("film_type") or "Unknown"
        units = line.get("shipped_units", 1)
        roll_summary.append({"label": film, "qty": units})

    # Scan resolution summary  e.g. ["Standard Scan × 2"]
    scan_summary = []
    for line in scan_lines:
        res   = line.get("scan_resolution") or "Standard"
        units = line.get("shipped_units", 1)
        scan_summary.append({"label": f"{res} Scan", "qty": units})

    # Print summary
    print_summary = []
    for line in print_lines:
        name  = line.get("product_name") or "Prints"
        units = line.get("shipped_units", 1)
        print_summary.append({"label": name, "qty": units})

    # Twin check process mix — a LIVE join of this order's pronto_cache
    # lines to sku_map, not the cached pronto_cache.service_type/film_type
    # columns (those predate — and are unrelated to — sku_map's new
    # requires_twin_check/process_code columns, and are null for a store
    # whose enrichment lapsed; see twin_check_service module docstring).
    # Purely additive field — every existing field above is unchanged.
    mix_rows = await db.execute(
        text(
            "SELECT pc.sku_code, pc.shipped_units, "
            "sm.requires_twin_check, sm.process_code "
            "FROM pronto_cache pc "
            "LEFT JOIN sku_map sm ON sm.sku_code = pc.sku_code "
            "WHERE pc.sales_order_number = :order_num"
        ),
        {"order_num": order_number},
    )
    sku_lookup: dict = {}
    mix_lines = []
    for r in mix_rows.mappings():
        mix_lines.append({"sku_code": r["sku_code"], "shipped_units": r["shipped_units"]})
        sku_lookup[r["sku_code"]] = {
            "requires_twin_check": bool(r["requires_twin_check"]),
            "process_code": r["process_code"],
        }
    process_mix = compute_process_mix(mix_lines, sku_lookup)

    return {
        "found":                True,
        "sales_order_number":   row.sales_order_number,
        "territory":            row.territory,
        "customer_name":        row.customer_name,
        "email_address":        row.email_address,
        "phone_number":         row.phone_number,
        "pronto_account":       row.pronto_account,
        "inferred_service_type":row.inferred_service_type,
        "total_rolls":          int(row.total_rolls or 0),
        "roll_summary":         roll_summary,
        "scan_summary":         scan_summary,
        "print_summary":        print_summary,
        "sku_lines":            sku_lines,
        "synced_at":            row.synced_at.isoformat() if row.synced_at else None,
        "process_mix":          process_mix,
    }


# ── GET /api/pronto/status ───────────────────────────────────
@router.get("/status")
async def sync_status(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns cache row count and last sync time. Useful for admin dashboards."""
    result = await db.execute(
        text("SELECT COUNT(*) as total, MAX(synced_at) as last_sync FROM pronto_cache")
    )
    row = result.fetchone()
    return {
        "total_rows": row.total,
        "last_sync":  row.last_sync.isoformat() if row.last_sync else None,
    }


# ── POST /api/pronto/sync ────────────────────────────────────
@router.post("/sync")
async def manual_sync(current_user=Depends(get_current_user)):
    """
    Manually trigger a Pronto cache sync.
    Useful for admins when they need fresh data immediately.
    Only accessible to store_admin and master_admin roles.
    """
    if current_user.get("role") not in ("store_admin", "master_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to trigger manual sync.",
        )
    result = await sync_pronto_cache()
    return result
