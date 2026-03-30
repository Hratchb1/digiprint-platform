# app/services/drive_watcher.py
# ============================================================
# Google Drive watcher — polls per-store Inbox folders every
# 5 minutes, matches folders to rolls via twin check, moves
# them to Delivered, updates order status, triggers email.
# ============================================================

import logging
import os
import re
from datetime import datetime
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import create_client

from app.core.config import settings

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

SERVICE_ACCOUNT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "service_account.json"
)

STORE_PREFIXES = {
    "a90c273e-49ff-4733-b709-31066f2ec503": "0000",   # Bondi
    "ff8bdc2e-966b-4a49-80b2-af5030148095": "0000",   # Miranda
    "8a525dc4-c1c2-48a0-a315-c03082b63f3e": "0000",   # Cannington
    "87ed3978-0d69-4acd-89f5-8e60dd121165": "",        # Parramatta (raw)
    "f2635a53-93ca-499f-aad4-4eb5e7f9128c": "",        # Melbourne (raw)
    "514d0eee-b807-45bd-96bd-eda630be1fba": "A00",     # Brisbane
}


def _get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _strip_prefix(folder_name: str, store_id: str) -> Optional[str]:
    prefix = STORE_PREFIXES.get(store_id, "")
    if prefix:
        if folder_name.startswith(prefix):
            raw = folder_name[len(prefix):]
            if re.fullmatch(r"\d{4}", raw):
                return raw
        return None
    else:
        if re.fullmatch(r"\d{4}", folder_name):
            return folder_name
        return None


def _build_prefix(twin: str, store_id: str) -> str:
    prefix = STORE_PREFIXES.get(store_id, "")
    return f"{prefix}{twin}"


def _list_inbox_folders(service, inbox_folder_id: str) -> list[dict]:
    try:
        result = service.files().list(
            q=f"'{inbox_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name, modifiedTime)",
            pageSize=100,
        ).execute()
        return result.get("files", [])
    except HttpError as e:
        logger.error(f"[drive_watcher] Error listing inbox: {e}")
        return []


def _get_or_create_folder(service, parent_id: str, folder_name: str) -> str:
    result = service.files().list(
        q=f"'{parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id)",
        pageSize=1,
    ).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(
        body={
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        },
        fields="id",
    ).execute()
    return folder["id"]


def _move_folder(service, folder_id: str, new_parent_id: str, old_parent_id: str):
    service.files().update(
        fileId=folder_id,
        addParents=new_parent_id,
        removeParents=old_parent_id,
        fields="id, parents",
    ).execute()


def _set_folder_public(service, folder_id: str):
    try:
        service.permissions().create(
            fileId=folder_id,
            body={
                "role": "reader",
                "type": "anyone",
            },
        ).execute()
        logger.info(f"[drive_watcher] Folder {folder_id} set to public viewer")
    except HttpError as e:
        logger.error(f"[drive_watcher] Failed to set folder permissions: {e}")


def _is_stable(modified_time_str: str, stabilise_seconds: int) -> bool:
    try:
        modified = datetime.fromisoformat(modified_time_str.replace("Z", "+00:00"))
        now = datetime.now(modified.tzinfo)
        age_seconds = (now - modified).total_seconds()
        return age_seconds >= stabilise_seconds
    except Exception:
        return True


def _log_watcher_event(client, store_id: str, folder_id: str, folder_name: str,
                        status: str, detail: str = None,
                        roll_id: str = None, order_id: str = None):
    try:
        record = {
            "store_id": store_id,
            "folder_id": folder_id,
            "folder_name": folder_name,
            "status": status,
            "detail": detail,
        }
        if roll_id:
            record["roll_id"] = roll_id
        if order_id:
            record["order_id"] = order_id

        client.table("drive_watcher_log").upsert(
            record, on_conflict="folder_id"
        ).execute()
    except Exception as e:
        logger.error(f"[drive_watcher] Failed to log event: {e}")


def _get_folder_drive_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


async def run_drive_watcher():
    logger.info("[drive_watcher] ---- Starting Drive watcher cycle ----")

    try:
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        logger.info("[drive_watcher] Supabase client created")

        configs = client.table("drive_config").select("*").eq("enabled", True).execute()
        logger.info(f"[drive_watcher] Found {len(configs.data)} enabled store config(s)")

        if not configs.data:
            logger.info("[drive_watcher] No enabled store configs found.")
            return

        service = _get_drive_service()
        logger.info("[drive_watcher] Drive service authenticated")

        for config in configs.data:
            try:
                await _process_store(client, service, config)
            except Exception as e:
                logger.error(f"[drive_watcher] Error processing store {config.get('store_id')}: {e}")

    except Exception as e:
        logger.error(f"[drive_watcher] Fatal error in watcher: {e}")

    logger.info("[drive_watcher] ---- Watcher cycle complete ----")


async def _process_store(client, service, config: dict):
    store_id = config["store_id"]
    inbox_folder_id = config["inbox_folder_id"]
    delivered_folder_id = config["delivered_folder_id"]
    stabilise_seconds = config.get("stabilise_seconds", 30)

    logger.info(f"[drive_watcher] Processing store {store_id}")
    logger.info(f"[drive_watcher] Checking inbox folder: {inbox_folder_id}")

    folders = _list_inbox_folders(service, inbox_folder_id)
    logger.info(f"[drive_watcher] Found {len(folders)} folder(s) in inbox")

    if not folders:
        logger.info(f"[drive_watcher] No folders in inbox for store {store_id}")
        return

    for folder in folders:
        logger.info(f"[drive_watcher] Processing folder: {folder['name']} (id: {folder['id']})")
        await _process_folder(
            client, service, config,
            folder, inbox_folder_id, delivered_folder_id,
            store_id, stabilise_seconds
        )


async def _process_folder(client, service, config, folder, inbox_folder_id,
                           delivered_folder_id, store_id, stabilise_seconds):
    folder_id = folder["id"]
    folder_name = folder["name"]
    modified_time = folder.get("modifiedTime", "")

    logger.info(f"[drive_watcher] --- Processing folder: {folder_name} ---")

    # ── Rule 5: Idempotency ──
    existing = client.table("drive_watcher_log").select("status").eq(
        "folder_id", folder_id
    ).execute()

    if existing.data:
        existing_status = existing.data[0]["status"]
        logger.info(f"[drive_watcher] Existing log status: {existing_status}")
        if existing_status in ("moved", "emailed", "skipped"):
            logger.info(f"[drive_watcher] Skipping already processed folder: {folder_name}")
            return
        if existing_status == "processing":
            logger.info(f"[drive_watcher] Folder already being processed: {folder_name}")
            return
    else:
        logger.info(f"[drive_watcher] No existing log entry — proceeding")

    # ── Rule 4: Stabilisation ──
    stable = _is_stable(modified_time, stabilise_seconds)
    logger.info(f"[drive_watcher] Folder stable: {stable} (modified: {modified_time}, required wait: {stabilise_seconds}s)")
    if not stable:
        logger.info(f"[drive_watcher] Folder not stable yet: {folder_name}")
        return

    # ── Parse twin check ──
    twin = _strip_prefix(folder_name, store_id)
    logger.info(f"[drive_watcher] Parsed twin: {twin} from folder: {folder_name}")
    if not twin:
        logger.warning(f"[drive_watcher] Cannot parse twin from folder: {folder_name}")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "skipped", "Could not parse twin check from folder name")
        return

    # ── Lock ──
    _log_watcher_event(client, store_id, folder_id, folder_name, "processing",
                       f"Parsed twin: {twin}")

    # ── Find matching roll ──
    logger.info(f"[drive_watcher] Looking up twin {twin} for store {store_id}")
    rolls = client.table("rolls").select(
        "id, twin_check, order_id, status, date_scanned, drive_folder_url, store_id"
    ).eq("twin_check", twin).eq("store_id", store_id).execute()

    logger.info(f"[drive_watcher] Roll lookup returned {len(rolls.data) if rolls.data else 0} result(s)")

    if not rolls.data:
        logger.warning(f"[drive_watcher] No roll found for twin {twin} at store {store_id}")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "skipped", f"No roll found for twin {twin}")
        return

    candidates = [
        r for r in rolls.data
        if r.get("date_scanned") is None
        and r.get("drive_folder_url") is None
        and r.get("status") not in ("delivered", "blank", "archived")
    ]

    logger.info(f"[drive_watcher] Eligible candidates: {len(candidates)}")

    if len(candidates) > 1:
        logger.error(f"[drive_watcher] AMBIGUOUS: {len(candidates)} candidates for twin {twin}")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "ambiguous", f"{len(candidates)} matching rolls found for twin {twin}")
        return

    if len(candidates) == 0:
        already_scanned = [r for r in rolls.data if r.get("date_scanned") is not None]
        if already_scanned:
            logger.warning(f"[drive_watcher] RESCAN_DETECTED for twin {twin}")
            _log_watcher_event(client, store_id, folder_id, folder_name,
                               "rescan_detected",
                               "Roll already scanned. Staff must approve rescan in RollCall.")
        else:
            logger.warning(f"[drive_watcher] No eligible roll for twin {twin}")
            _log_watcher_event(client, store_id, folder_id, folder_name,
                               "skipped", f"No eligible roll for twin {twin}")
        return

    roll = candidates[0]
    roll_id = roll["id"]
    order_id = roll["order_id"]
    logger.info(f"[drive_watcher] Matched roll {roll_id} to order {order_id}")

    # ── Fetch the order ──
    order_result = client.table("orders").select(
        "id, order_number, customer_name, customer_email, status, order_type, store_id, drive_order_folder_url"
    ).eq("id", order_id).execute()

    if not order_result.data:
        logger.error(f"[drive_watcher] Order {order_id} not found")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "error", f"Order {order_id} not found", roll_id=roll_id)
        return

    order = order_result.data[0]
    logger.info(f"[drive_watcher] Found order: {order['order_number']} for {order['customer_name']}")

    # ── Build Delivered folder path ──
    now = datetime.now()
    year_str = str(now.year)
    month_str = str(now.month)
    order_folder_name = f"{order['order_number']} {order['customer_name']}"
    logger.info(f"[drive_watcher] Creating folder path: Delivered/{year_str}/{month_str}/{order_folder_name}")

    year_folder_id = _get_or_create_folder(service, delivered_folder_id, year_str)
    month_folder_id = _get_or_create_folder(service, year_folder_id, month_str)
    order_folder_id = _get_or_create_folder(service, month_folder_id, order_folder_name)
    logger.info(f"[drive_watcher] Order folder ID: {order_folder_id}")

    # ── Move roll folder ──
    try:
        _move_folder(service, folder_id, order_folder_id, inbox_folder_id)
        logger.info(f"[drive_watcher] Moved {folder_name} → {order_folder_name}")
    except HttpError as e:
        logger.error(f"[drive_watcher] Failed to move folder: {e}")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "error", f"Move failed: {e}", roll_id=roll_id, order_id=order_id)
        return

    # ── Set folder public ──
    drive_url = _get_folder_drive_url(order_folder_id)
    _set_folder_public(service, order_folder_id)
    logger.info(f"[drive_watcher] Drive URL: {drive_url}")

    # ── Update roll ──
    client.table("rolls").update({
        "date_scanned": datetime.utcnow().isoformat(),
        "drive_folder_url": drive_url,
        "status": "scanned",
    }).eq("id", roll_id).execute()
    logger.info(f"[drive_watcher] Roll {roll_id} marked as scanned")

    _log_watcher_event(client, store_id, folder_id, folder_name,
                       "moved", f"Moved to {order_folder_name}",
                       roll_id=roll_id, order_id=order_id)

    # ── Check if all rolls scanned ──
    all_rolls = client.table("rolls").select(
        "id, status, date_scanned, is_blank"
    ).eq("order_id", order_id).execute()

    total_rolls = all_rolls.data
    unscanned = [
        r for r in total_rolls
        if r.get("date_scanned") is None
        and not r.get("is_blank", False)
        and r.get("status") not in ("blank", "delivered", "archived")
    ]

    logger.info(f"[drive_watcher] Unscanned rolls remaining: {len(unscanned)}")

    if unscanned:
        logger.info(f"[drive_watcher] Order {order['order_number']} waiting for {len(unscanned)} more roll(s)")
        return

    # ── All rolls done ──
    logger.info(f"[drive_watcher] All rolls complete for order {order['order_number']} — sending email")

    client.table("orders").update({
        "status": "delivered",
        "date_delivered": datetime.utcnow().isoformat(),
        "drive_order_folder_url": drive_url,
        "date_scanned": datetime.utcnow().isoformat(),
    }).eq("id", order_id).execute()

    client.table("order_events").insert({
        "order_id": order_id,
        "event_type": "delivered",
        "description": f"All rolls scanned and delivered. Drive: {drive_url}",
        "actor_label": "drive_watcher",
        "metadata": {"drive_url": drive_url, "roll_id": roll_id},
    }).execute()

    # ── Send email ──
    try:
        from app.services.email_service import send_order_email
        # Inject drive URL into order dict so template receives it
        order["drive_order_folder_url"] = drive_url
        logger.info(f"[drive_watcher] Sending email to {order['customer_email']}")
        await send_order_email(client, config, order, total_rolls)
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "emailed", "Email sent successfully",
                           roll_id=roll_id, order_id=order_id)
        logger.info(f"[drive_watcher] Email sent successfully")
    except Exception as e:
        logger.error(f"[drive_watcher] Email failed for order {order['order_number']}: {e}")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "error", f"Email failed: {e}",
                           roll_id=roll_id, order_id=order_id)