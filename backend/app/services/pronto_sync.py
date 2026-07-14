# app/services/pronto_sync.py
# ============================================================
# Fetches the Pronto master Google Sheet (CSV export) every
# 10 minutes and syncs it into the pronto_cache table via
# append-only / upsert-only semantics (never deletes rows).
#
# New behaviour (migration 003+):
#   - Groups rows by Sales Order Number
#   - Classifies each group as 'new' or 'refund'
#   - Creates Inbound orders in the orders table for new groups
#   - Matches refunds and applies status flips / refund_status tags
#   - Unmatched refunds go to refund_warnings table
# ============================================================

import asyncio
import csv
import io
import logging
from datetime import datetime
from typing import Literal, Optional

import httpx
from supabase import create_client

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Google Sheet config ──────────────────────────────────────
SHEET_ID = "1t2zijvvjqSlzVPOjkTSTDmGgpxrH2vaT8x4xbVJXfsg"
TAB_NAME = "RawData"
CSV_URL  = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/gviz/tq?tqx=out:csv&sheet={TAB_NAME}"
)

# ── SKUs that set add-on service flags on orders ─────────────
ADDON_SKU_FLAGS = {
    "177426": "border_scan",
    "177427": "contact_sheet",
    "177428": "rebate_scan",
}

ADDON_SKUS = set(ADDON_SKU_FLAGS.keys())

# ── Statuses that are eligible for cancellation via refund ───
REFUNDABLE_PRE_DELIVERED = ("inbound", "booked_in", "scanning")
ACTIVE_STATUSES          = ("inbound", "booked_in", "scanning", "delivered")

# ── Column name normalisers ──────────────────────────────────
COLUMN_MAP = {
    "territory":             "territory",
    "order date":            "order_date",
    "shipped date":          "shipped_date",
    "sales order number":    "sales_order_number",
    "sales order bo suffix": "bo_suffix",
    "customer name":         "customer_name",
    "email address":         "email_address",
    "sales rep name":        "sales_rep_name",
    "sku code":              "sku_code",
    "product name":          "product_name",
    "category":              "category",
    "class":                 "class",
    "group":                 "group_name",
    "shipped units":         "shipped_units",
    "shipped value inc gst": "shipped_value",
    "data updated on":       "data_updated_on",
    "pronto account number": "pronto_account",
    "phone number":          "phone_number",
}


# ── Parsers ──────────────────────────────────────────────────

def _normalise_header(raw: str) -> str:
    return raw.strip().lower()


def _parse_date(val: str) -> Optional[str]:
    if not val or not val.strip():
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(val.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_int(val) -> int:
    try:
        return int(float(str(val).strip()))
    except (ValueError, AttributeError):
        return 0


def _parse_decimal(val) -> Optional[float]:
    try:
        return float(str(val).strip().replace(",", "").replace("$", ""))
    except (ValueError, AttributeError):
        return None


# ── Sheet fetcher ────────────────────────────────────────────

async def fetch_sheet_rows() -> list[dict]:
    """Download the Google Sheet as CSV and parse into row dicts."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(CSV_URL)
        resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    raw_headers  = reader.fieldnames or []
    header_index = {_normalise_header(h): h for h in raw_headers}

    rows = []
    for raw_row in reader:
        row: dict = {}
        for norm_col, internal_key in COLUMN_MAP.items():
            raw_header = header_index.get(norm_col)
            row[internal_key] = raw_row.get(raw_header, "").strip() if raw_header else ""
        rows.append(row)

    logger.info(f"[pronto_sync] Fetched {len(rows)} rows from Google Sheet")
    return rows


# ── Supabase lookups ─────────────────────────────────────────

def _get_sku_map(client) -> dict[str, dict]:
    result = client.table("sku_map").select(
        "sku_code, service_type, film_type, scan_resolution, category"
    ).execute()
    return {
        row["sku_code"]: {
            "service_type":    row.get("service_type"),
            "film_type":       row.get("film_type"),
            "scan_resolution": row.get("scan_resolution"),
            "category":        row.get("category"),
        }
        for row in result.data
    }


def _load_store_map(client) -> dict[str, str]:
    """Returns {territory_code: store_id} for all stores with a territory_code set."""
    result = client.table("stores").select("id, territory_code").execute()
    return {
        r["territory_code"]: r["id"]
        for r in result.data
        if r.get("territory_code")
    }


# ── Cache key ────────────────────────────────────────────────

def _build_cache_key(order_num: str, bo_suffix: Optional[str], sku_code: Optional[str]) -> str:
    return f"{order_num}|{bo_suffix or ''}|{sku_code or ''}"


# ── Sales order classification ───────────────────────────────

def _classify_sales_order(rows: list[dict]) -> Literal["new", "refund"]:
    """Any negative shipped_units in the group → refund."""
    for row in rows:
        if _parse_int(row.get("shipped_units", "0")) < 0:
            return "refund"
    return "new"


# ── Refund matching ──────────────────────────────────────────

def _refund_sku_signature(refund_lines: list[dict]) -> dict[str, int]:
    """Build {sku_code: abs_qty} for non-addon SKUs in a refund group."""
    sig: dict[str, int] = {}
    for row in refund_lines:
        sku = row.get("sku_code") or ""
        if not sku or sku in ADDON_SKUS:
            continue
        qty = abs(_parse_int(row.get("shipped_units", "0")))
        if qty > 0:
            sig[sku] = sig.get(sku, 0) + qty
    return sig


def _order_cache_sku_signature(order_number: str, client) -> dict[str, int]:
    """Load the original SKU signature for an order from pronto_cache."""
    result = client.table("pronto_cache").select(
        "sku_code, shipped_units"
    ).eq("sales_order_number", order_number).execute()

    sig: dict[str, int] = {}
    for row in result.data or []:
        sku = row.get("sku_code") or ""
        if not sku or sku in ADDON_SKUS:
            continue
        qty = _parse_int(row.get("shipped_units", 0))
        if qty > 0:
            sig[sku] = sig.get(sku, 0) + qty
    return sig


def _refund_is_full(original_sig: dict[str, int], refund_sig: dict[str, int]) -> bool:
    """Full refund = refund covers 100% of each non-addon SKU in the original."""
    if not original_sig:
        return False
    return all(refund_sig.get(sku, 0) >= qty for sku, qty in original_sig.items())


def _match_refund(
    refund_lines: list[dict], client
) -> tuple[Optional[dict], str]:
    """
    Try to find the order this refund belongs to.
    Returns (order_dict | None, confidence).
    confidence is 'exact', 'cash_fallback', or 'unmatched'.
    """
    account   = next((r.get("pronto_account", "") for r in refund_lines if r.get("pronto_account")), "")
    territory = next((r.get("territory", "") for r in refund_lines if r.get("territory")), "")
    refund_sig = _refund_sku_signature(refund_lines)

    # Primary: account number + SKU + qty
    if account and not account.upper().startswith("CASH"):
        candidates = client.table("orders").select(
            "id, pronto_order_number, status, pronto_order_date, refund_status, store_id"
        ).eq(
            "pronto_account_number", account
        ).in_(
            "status", list(ACTIVE_STATUSES)
        ).neq(
            "refund_status", "full"
        ).order("pronto_order_date", desc=False).execute()

        for order in (candidates.data or []):
            original_sig = _order_cache_sku_signature(order["pronto_order_number"], client)
            if original_sig and all(
                original_sig.get(sku, 0) == qty for sku, qty in refund_sig.items()
            ):
                return (order, "exact")

    # Cash fallback: territory + SKU + qty + closest prior date
    if not account or account.upper().startswith("CASH"):
        store_map   = _load_store_map(client)
        store_id    = store_map.get(territory)
        if store_id:
            candidates = client.table("orders").select(
                "id, pronto_order_number, status, pronto_order_date, refund_status, store_id"
            ).eq(
                "store_id", store_id
            ).in_(
                "status", list(ACTIVE_STATUSES)
            ).neq(
                "refund_status", "full"
            ).order("pronto_order_date", desc=False).execute()

            for order in (candidates.data or []):
                original_sig = _order_cache_sku_signature(order["pronto_order_number"], client)
                if original_sig and all(
                    original_sig.get(sku, 0) == qty for sku, qty in refund_sig.items()
                ):
                    return (order, "cash_fallback")

    return (None, "unmatched")


# ── Refund application ───────────────────────────────────────

def _apply_refund(matched_order: dict, refund_lines: list[dict], client) -> None:
    order_id           = matched_order["id"]
    order_status       = matched_order["status"]
    orig_order_number  = matched_order["pronto_order_number"]
    refund_order_number = refund_lines[0].get("sales_order_number", "")
    now                = datetime.utcnow().isoformat()

    refund_amount = abs(sum(
        _parse_decimal(r.get("shipped_value") or "0") or 0.0
        for r in refund_lines
    ))

    refund_sig   = _refund_sku_signature(refund_lines)
    original_sig = _order_cache_sku_signature(orig_order_number, client)
    full         = _refund_is_full(original_sig, refund_sig)

    base_refund_fields = {
        "refund_pronto_order_number": refund_order_number,
        "refund_amount":              refund_amount,
    }

    if full and order_status in REFUNDABLE_PRE_DELIVERED:
        client.table("orders").update({
            **base_refund_fields,
            "status":       "cancelled",
            "cancelled_at": now,
            "refund_status": "full",
        }).eq("id", order_id).execute()
        _log_activity(client, order_id, "order_cancelled", {
            "reason":               "full_refund",
            "refund_order_number":  refund_order_number,
            "refund_amount":        refund_amount,
        })

    elif full and order_status == "delivered":
        client.table("orders").update({
            **base_refund_fields,
            "refund_status": "full",
        }).eq("id", order_id).execute()
        _log_activity(client, order_id, "refund_processed", {
            "refund_order_number": refund_order_number,
            "refund_amount":       refund_amount,
        })

    else:
        client.table("orders").update({
            **base_refund_fields,
            "refund_status": "partial",
        }).eq("id", order_id).execute()
        _log_activity(client, order_id, "partial_refund_processed", {
            "refund_order_number": refund_order_number,
            "refund_amount":       refund_amount,
            "refunded_skus":       refund_sig,
        })


# ── Activity logging ─────────────────────────────────────────

def _log_activity(client, order_id: str, event_type: str, event_data: dict) -> None:
    try:
        client.table("order_activity").insert({
            "order_id":   order_id,
            "event_type": event_type,
            "event_data": event_data,
            "operator_id": "system",
        }).execute()
    except Exception as exc:
        logger.warning(
            f"[pronto_sync] Failed to log activity '{event_type}' for order {order_id}: {exc}"
        )


# ── Addon flag helpers (unchanged from prior version) ────────

def _build_addon_flag_map(rows: list[dict]) -> dict[str, dict]:
    addon_map: dict[str, dict] = {}
    for row in rows:
        order_num = row.get("sales_order_number", "").strip()
        sku_code  = row.get("sku_code", "").strip()
        if not order_num or sku_code not in ADDON_SKU_FLAGS:
            continue
        flag_name = ADDON_SKU_FLAGS[sku_code]
        if order_num not in addon_map:
            addon_map[order_num] = {
                "border_scan":   False,
                "contact_sheet": False,
                "rebate_scan":   False,
            }
        addon_map[order_num][flag_name] = True
    return addon_map


def _apply_addon_flags(client, addon_map: dict[str, dict]) -> int:
    if not addon_map:
        return 0
    updated      = 0
    order_numbers = list(addon_map.keys())
    result = client.table("orders").select("id, order_number").in_(
        "order_number", order_numbers
    ).execute()
    for order_row in result.data or []:
        order_id     = order_row["id"]
        order_number = order_row["order_number"]
        flags        = addon_map.get(order_number)
        if not flags:
            continue
        client.table("orders").update(flags).eq("id", order_id).execute()
        updated += 1
        logger.info(
            f"[pronto_sync] Order {order_number} addon flags: "
            f"border={flags['border_scan']} contact={flags['contact_sheet']} rebate={flags['rebate_scan']}"
        )
    return updated


# ── Main sync job ─────────────────────────────────────────────

async def sync_pronto_cache() -> dict:
    """
    Main sync job (called by APScheduler every 10 minutes).

    1. Fetch CSV rows from Google Sheet.
    2. Group rows by Sales Order Number.
    3. Upsert every row into pronto_cache (append-only, never deletes).
       - first_seen_at and order_created are NOT in the upsert payload,
         so they are set once on INSERT by DB DEFAULT and never overwritten.
    4. For each sales order group:
       - 'new'    → create Inbound order if not already in orders table
       - 'refund' → match to existing order and apply refund logic;
                    unmatched refunds go to refund_warnings
    5. Apply addon SKU flags to any booked orders.
    """
    logger.info("[pronto_sync] Starting Pronto cache sync...")

    try:
        rows = await fetch_sheet_rows()
    except Exception as exc:
        logger.error(f"[pronto_sync] Failed to fetch sheet: {exc}")
        return {"status": "error", "message": str(exc)}

    # supabase-py is a synchronous client — its .execute() calls are blocking
    # network I/O. Running them directly on the event loop would freeze every
    # other request (including this one's own scheduler-triggered re-entry)
    # for the full duration of the sync, so push the blocking work to a thread.
    try:
        return await asyncio.to_thread(_sync_pronto_cache_blocking, rows)
    except Exception as exc:
        logger.error(f"[pronto_sync] Sync failed: {exc}", exc_info=True)
        return {"status": "error", "message": str(exc)}


def _sync_pronto_cache_blocking(rows: list[dict]) -> dict:
    """Synchronous body of the sync job — runs off the event loop via asyncio.to_thread."""
    client    = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    sku_map   = _get_sku_map(client)
    store_map = _load_store_map(client)

    # ── Group rows by sales order number ────────────────
    orders_by_number: dict[str, list[dict]] = {}
    for row in rows:
        order_num = row.get("sales_order_number", "").strip()
        if not order_num:
            continue
        orders_by_number.setdefault(order_num, []).append(row)

    # ── Build pronto_cache upsert records ────────────────
    # NOTE: first_seen_at and order_created are intentionally absent from
    # this payload. PostgREST only updates columns present in the body,
    # so they are preserved for existing rows and set by DB DEFAULT for new rows.
    cache_records = []
    skipped       = 0
    seen_keys: set[str] = set()  # defensive duplicate tracking

    for row in rows:
        order_num = row.get("sales_order_number", "").strip()
        if not order_num:
            skipped += 1
            continue

        sku_code  = row.get("sku_code", "").strip()
        bo_suffix = row.get("bo_suffix", "").strip() or None
        sku_data  = sku_map.get(sku_code, {})
        cache_key = _build_cache_key(order_num, bo_suffix, sku_code)

        if cache_key in seen_keys:
            logger.warning(
                f"[pronto_sync] Duplicate cache key in CSV: {cache_key} — keeping latest"
            )
        seen_keys.add(cache_key)

        record = {
            "cache_key":          cache_key,
            "territory":          row.get("territory") or None,
            "order_date":         _parse_date(row.get("order_date", "")),
            "shipped_date":       _parse_date(row.get("shipped_date", "")),
            "sales_order_number": order_num,
            "bo_suffix":          bo_suffix,
            "customer_name":      row.get("customer_name") or None,
            "email_address":      row.get("email_address") or None,
            "phone_number":       row.get("phone_number") or None,
            "pronto_account":     row.get("pronto_account") or None,
            "sales_rep_name":     row.get("sales_rep_name") or None,
            "sku_code":           sku_code or None,
            "product_name":       row.get("product_name") or None,
            "category":           row.get("category") or None,
            "class":              row.get("class") or None,
            "group_name":         row.get("group_name") or None,
            "shipped_units":      _parse_int(row.get("shipped_units", "1")),
            "shipped_value":      _parse_decimal(row.get("shipped_value", "")),
            "data_updated_on":    _parse_date(row.get("data_updated_on", "")),
            "service_type":       sku_data.get("service_type"),
            "film_type":          sku_data.get("film_type"),
            "scan_resolution":    sku_data.get("scan_resolution"),
            "last_seen_at":       datetime.utcnow().isoformat(),
            "synced_at":          datetime.utcnow().isoformat(),
        }
        cache_records.append(record)

    # Upsert in batches of 500
    BATCH = 500
    for i in range(0, len(cache_records), BATCH):
        client.table("pronto_cache").upsert(
            cache_records[i : i + BATCH],
            on_conflict="cache_key",
        ).execute()

    logger.info(f"[pronto_sync] Upserted {len(cache_records)} pronto_cache rows ({skipped} skipped)")

    # ── Process each sales order group ───────────────────
    inbound_created        = 0
    refund_warnings_created = 0

    for order_num, order_rows in orders_by_number.items():
        classification = _classify_sales_order(order_rows)
        header         = order_rows[0]
        territory      = header.get("territory", "").strip()

        if classification == "new":
            store_id = store_map.get(territory)
            if not store_id:
                logger.warning(
                    f"[pronto_sync] Unknown territory '{territory}' for order "
                    f"{order_num} — skipping order creation"
                )
                continue

            # No-op if order already in RollCall. Match on order_number too:
            # intake-created orders may predate this sale appearing in the
            # sheet, and older rows have no pronto_order_number at all —
            # matching only pronto_order_number created duplicate inbound rows.
            existing = client.table("orders").select("id").or_(
                f"pronto_order_number.eq.{order_num},order_number.eq.{order_num}"
            ).execute()
            if existing.data:
                continue

            now = datetime.utcnow().isoformat()
            customer_name = header.get("customer_name") or "Unknown"

            insert_result = client.table("orders").insert({
                "order_number":        order_num,
                "pronto_order_number": order_num,
                "pronto_account_number": header.get("pronto_account") or None,
                "store_id":            store_id,
                "customer_name":       customer_name,
                "customer_email":      header.get("email_address") or None,
                "phone_number":        header.get("phone_number") or None,
                "account":             header.get("pronto_account") or None,
                "status":              "inbound",
                "order_type":          "film",
                "pronto_order_date":   _parse_date(header.get("order_date", "")),
                "pronto_shipped_date": _parse_date(header.get("shipped_date", "")),
            }).execute()

            if not insert_result.data:
                logger.error(f"[pronto_sync] Insert returned no data for order {order_num}")
                continue

            new_order_id = insert_result.data[0]["id"]
            inbound_created += 1

            # Mark cache rows as having produced an order
            cache_keys = [
                _build_cache_key(order_num, r.get("bo_suffix") or None, r.get("sku_code") or "")
                for r in order_rows
            ]
            client.table("pronto_cache").update(
                {"order_created": True}
            ).in_("cache_key", cache_keys).execute()

            _log_activity(client, new_order_id, "order_created", {
                "source":              "pronto_sync",
                "territory":           territory,
                "pronto_order_number": order_num,
                "customer_name":       customer_name,
            })
            logger.info(f"[pronto_sync] Created inbound order {order_num} (territory: {territory})")

        elif classification == "refund":
            cache_keys = [
                _build_cache_key(order_num, r.get("bo_suffix") or None, r.get("sku_code") or "")
                for r in order_rows
            ]
            client.table("pronto_cache").update(
                {"is_refund": True}
            ).in_("cache_key", cache_keys).execute()

            matched_order, confidence = _match_refund(order_rows, client)

            if matched_order:
                client.table("pronto_cache").update({
                    "refund_matched_to_order_id": matched_order["id"],
                    "refund_match_confidence":    confidence,
                }).in_("cache_key", cache_keys).execute()

                _apply_refund(matched_order, order_rows, client)
                logger.info(
                    f"[pronto_sync] Refund {order_num} matched to "
                    f"{matched_order['pronto_order_number']} ({confidence})"
                )
            else:
                client.table("pronto_cache").update({
                    "refund_match_confidence": "unmatched",
                }).in_("cache_key", cache_keys).execute()

                # The same refund rows stay in the sheet forever — only warn once
                # per refund order, and never resurrect resolved/ignored warnings.
                already_warned = client.table("refund_warnings").select("id").eq(
                    "refund_pronto_order_number", order_num
                ).limit(1).execute()
                if already_warned.data:
                    continue

                refund_amount = abs(sum(
                    _parse_decimal(r.get("shipped_value") or "0") or 0.0
                    for r in order_rows
                ))
                client.table("refund_warnings").insert({
                    "refund_pronto_order_number": order_num,
                    "pronto_account_number":      header.get("pronto_account") or None,
                    "territory":                  territory or None,
                    "refund_amount":              refund_amount,
                    "refund_lines": [
                        {
                            "sku_code":     r.get("sku_code"),
                            "product_name": r.get("product_name"),
                            "shipped_units": _parse_int(r.get("shipped_units", "0")),
                            "shipped_value": _parse_decimal(r.get("shipped_value", "")),
                        }
                        for r in order_rows
                    ],
                }).execute()
                refund_warnings_created += 1
                logger.warning(
                    f"[pronto_sync] Unmatched refund {order_num} — added to refund_warnings"
                )

    # ── Addon flags (unchanged behaviour) ────────────────
    addon_map      = _build_addon_flag_map(rows)
    orders_updated = _apply_addon_flags(client, addon_map)
    if orders_updated:
        logger.info(f"[pronto_sync] Addon flags updated on {orders_updated} order(s)")

    summary = {
        "status":                   "ok",
        "cache_rows_synced":        len(cache_records),
        "skipped":                  skipped,
        "inbound_orders_created":   inbound_created,
        "refund_warnings_created":  refund_warnings_created,
        "orders_addon_updated":     orders_updated,
        "synced_at":                datetime.utcnow().isoformat(),
    }
    logger.info(
        f"[pronto_sync] Complete — {inbound_created} inbound created, "
        f"{refund_warnings_created} refund warnings"
    )
    return summary
