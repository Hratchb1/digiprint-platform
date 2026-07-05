#!/usr/bin/env python3
"""
backfill_inbound_orders.py
==========================
One-off script: seeds Inbound orders from pronto_cache rows that have
no matching order in the orders table.

Run AFTER migrations 003, 004, 005 have been applied to Supabase.
Run BEFORE the next scheduled pronto_sync fires (or stop the scheduler
temporarily while running this).

Usage (from digiprint/backend/ with venv activated):
    python scripts/backfill_inbound_orders.py [--dry-run]

Flags:
    --dry-run   Print what would be created without writing to the DB.
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# Allow imports from app/ when run from the backend directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_date(val: str):
    if not val or not str(val).strip():
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(val).strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_int(val) -> int:
    try:
        return int(float(str(val).strip()))
    except (ValueError, AttributeError):
        return 0


def main(dry_run: bool = False) -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        logger.error(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in the environment or .env file."
        )
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    logger.info("=== Backfill: Inbound Orders from pronto_cache ===")
    if dry_run:
        logger.info("DRY RUN — no writes will occur")

    # Load territory → store_id map
    stores_result = client.table("stores").select("id, territory_code, name").execute()
    store_map = {
        r["territory_code"]: r["id"]
        for r in stores_result.data
        if r.get("territory_code")
    }
    logger.info(f"Loaded {len(store_map)} territory codes: {list(store_map.keys())}")

    # Load all positive-qty pronto_cache rows (skip refunds)
    logger.info("Loading pronto_cache rows (positive shipped_units only)...")
    cache_result = client.table("pronto_cache").select(
        "sales_order_number, bo_suffix, territory, order_date, shipped_date, "
        "customer_name, email_address, phone_number, pronto_account, shipped_units, "
        "order_created"
    ).gt("shipped_units", 0).execute()

    all_cache_rows = cache_result.data or []
    logger.info(f"Loaded {len(all_cache_rows)} positive-qty cache rows")

    # Group by sales_order_number (take first row as header per group)
    groups: dict[str, dict] = {}
    for row in all_cache_rows:
        order_num = (row.get("sales_order_number") or "").strip()
        if not order_num:
            continue
        if order_num not in groups:
            groups[order_num] = row  # first row = header

    logger.info(f"Found {len(groups)} distinct sales order numbers in pronto_cache")

    # Load existing pronto_order_numbers from orders table
    logger.info("Loading existing orders (pronto_order_number)...")
    orders_result = client.table("orders").select("pronto_order_number, order_number").execute()
    existing_pronto_numbers: set[str] = set()
    for o in orders_result.data or []:
        if o.get("pronto_order_number"):
            existing_pronto_numbers.add(o["pronto_order_number"])
        if o.get("order_number"):
            existing_pronto_numbers.add(o["order_number"])

    logger.info(f"Found {len(existing_pronto_numbers)} existing orders in RollCall")

    # Determine which orders need backfilling
    to_create = {
        order_num: header
        for order_num, header in groups.items()
        if order_num not in existing_pronto_numbers
    }

    logger.info(f"Orders to backfill: {len(to_create)}")
    if not to_create:
        logger.info("Nothing to backfill — all pronto_cache orders already exist in RollCall.")
        return

    created  = 0
    skipped  = 0
    errors   = 0

    for order_num, header in to_create.items():
        territory = (header.get("territory") or "").strip()
        store_id  = store_map.get(territory)

        if not store_id:
            logger.warning(
                f"  SKIP {order_num} — unknown territory '{territory}'"
            )
            skipped += 1
            continue

        customer_name = header.get("customer_name") or "Unknown"
        order_date    = _parse_date(header.get("order_date", ""))
        shipped_date  = _parse_date(header.get("shipped_date", ""))

        logger.info(
            f"  {'[DRY RUN] Would create' if dry_run else 'Creating'} "
            f"INBOUND {order_num} — {customer_name} ({territory})"
        )

        if dry_run:
            created += 1
            continue

        try:
            insert_result = client.table("orders").insert({
                "order_number":          order_num,
                "pronto_order_number":   order_num,
                "pronto_account_number": header.get("pronto_account") or None,
                "store_id":              store_id,
                "customer_name":         customer_name,
                "customer_email":        header.get("email_address") or None,
                "phone_number":          header.get("phone_number") or None,
                "account":               header.get("pronto_account") or None,
                "status":                "inbound",
                "order_type":            "film",
                "pronto_order_date":     order_date,
                "pronto_shipped_date":   shipped_date,
            }).execute()

            if not insert_result.data:
                logger.error(f"  ERROR {order_num} — insert returned no data")
                errors += 1
                continue

            new_order_id = insert_result.data[0]["id"]

            # Log activity event
            client.table("order_activity").insert({
                "order_id":   new_order_id,
                "event_type": "order_created",
                "event_data": {
                    "source":              "backfill_script",
                    "territory":           territory,
                    "pronto_order_number": order_num,
                },
                "operator_id": "system",
            }).execute()

            # Mark pronto_cache rows as order_created = true
            client.table("pronto_cache").update(
                {"order_created": True}
            ).eq("sales_order_number", order_num).execute()

            created += 1

        except Exception as exc:
            logger.error(f"  ERROR {order_num} — {exc}")
            errors += 1

    logger.info("=== Backfill complete ===")
    logger.info(f"  Created : {created}")
    logger.info(f"  Skipped : {skipped}  (unknown territory)")
    logger.info(f"  Errors  : {errors}")

    if dry_run:
        logger.info("(DRY RUN — nothing was actually written)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill inbound orders from pronto_cache")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
