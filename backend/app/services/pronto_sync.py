# app/services/pronto_sync.py
# ============================================================
# Fetches the Pronto master Google Sheet (CSV export) every
# 10 minutes and syncs it into the pronto_cache table.
# Uses Supabase HTTP client instead of direct DB connection.
# ============================================================

import csv
import io
import logging
from datetime import datetime, date
from typing import Optional

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


def _parse_int(val: str) -> int:
    try:
        return int(float(val.strip()))
    except (ValueError, AttributeError):
        return 1


def _parse_decimal(val: str) -> Optional[float]:
    try:
        return float(val.strip().replace(",", "").replace("$", ""))
    except (ValueError, AttributeError):
        return None


async def fetch_sheet_rows() -> list[dict]:
    """Download the Google Sheet as CSV and parse into row dicts."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(CSV_URL)
        resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))

    raw_headers  = reader.fieldnames or []
    header_index = {
        _normalise_header(h): h
        for h in raw_headers
    }

    rows = []
    for raw_row in reader:
        row: dict = {}
        for norm_col, internal_key in COLUMN_MAP.items():
            raw_header = header_index.get(norm_col)
            row[internal_key] = raw_row.get(raw_header, "").strip() if raw_header else ""
        rows.append(row)

    logger.info(f"[pronto_sync] Fetched {len(rows)} rows from Google Sheet")
    return rows


def get_sku_map() -> dict[str, dict]:
    """Load the sku_map table via Supabase HTTP client."""
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
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


async def sync_pronto_cache() -> dict:
    """
    Main sync job.
    1. Fetch rows from Google Sheet
    2. Clear pronto_cache via Supabase client
    3. Re-insert all rows with resolved SKU data
    """
    logger.info("[pronto_sync] Starting Pronto cache sync...")

    try:
        rows = await fetch_sheet_rows()
    except Exception as exc:
        logger.error(f"[pronto_sync] Failed to fetch sheet: {exc}")
        return {"status": "error", "message": str(exc)}

    try:
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        sku_map = get_sku_map()

        # Clear existing cache
        client.table("pronto_cache").delete().neq("id", 0).execute()

        # Build insert rows in batches of 500
        inserted = 0
        skipped  = 0
        batch    = []

        for row in rows:
            order_num = row.get("sales_order_number", "").strip()
            if not order_num:
                skipped += 1
                continue

            sku_code = row.get("sku_code", "").strip()
            sku_data = sku_map.get(sku_code, {})

            record = {
                "territory":          row.get("territory") or None,
                "order_date":         _parse_date(row.get("order_date", "")),
                "shipped_date":       _parse_date(row.get("shipped_date", "")),
                "sales_order_number": order_num,
                "bo_suffix":          row.get("bo_suffix") or None,
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
            }
            batch.append(record)
            inserted += 1

            # Insert in batches of 500
            if len(batch) >= 500:
                client.table("pronto_cache").insert(batch).execute()
                batch = []

        # Insert remaining rows
        if batch:
            client.table("pronto_cache").insert(batch).execute()

    except Exception as exc:
        logger.error(f"[pronto_sync] Database error: {exc}")
        return {"status": "error", "message": str(exc)}

    summary = {
        "status":    "ok",
        "inserted":  inserted,
        "skipped":   skipped,
        "synced_at": datetime.utcnow().isoformat(),
    }
    logger.info(f"[pronto_sync] Complete — {inserted} rows inserted, {skipped} skipped")
    return summary
