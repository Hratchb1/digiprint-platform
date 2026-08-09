# app/services/drive_watcher.py
# ============================================================
# Google Drive watcher — polls per-store Inbox folders every
# 5 minutes, matches folders to rolls via twin check, moves
# them to Delivered, updates order status, triggers email.
# ============================================================

import asyncio
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
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

# ── Fallback paths — used only if drive_config has no paths set for a store ──
DEFAULT_FILM_SCANS_ROOT        = Path("D:/Film Scans")
DEFAULT_BORDER_PROCESSING_ROOT = Path("D:/Border Processing")
# ─────────────────────────────────────────────────────────────────────────────

# Module-level prefix cache — populated once per watcher cycle
# Maps store_id (str) -> prefix (str or None)
_prefix_cache: dict[str, Optional[str]] = {}


def _load_store_prefixes(client) -> dict[str, Optional[str]]:
    """
    Load twin folder prefix rules from store_settings table.
    Called once per watcher cycle and cached for that cycle.
    Returns a dict mapping store_id -> prefix (or None for raw twin).
    """
    try:
        result = client.table("store_settings").select(
            "store_id, twin_folder_prefix"
        ).execute()

        prefixes = {}
        for row in result.data:
            store_id = row["store_id"]
            prefix = row.get("twin_folder_prefix")  # None = raw 4-digit twin
            prefixes[store_id] = prefix

        logger.info(f"[drive_watcher] Loaded prefix rules for {len(prefixes)} store(s) from store_settings")
        return prefixes

    except Exception as e:
        logger.error(f"[drive_watcher] Failed to load store prefixes from store_settings: {e}")
        # Hard fallback — known rules in case DB is unreachable
        return {
            "a90c273e-49ff-4733-b709-31066f2ec503": "0000",   # Bondi
            "ff8bdc2e-966b-4a49-80b2-af5030148095": "0000",   # Miranda
            "8a525dc4-c1c2-48a0-a315-c03082b63f3e": "0000",   # Cannington
            "87ed3978-0d69-4acd-89f5-8e60dd121165": None,     # Parramatta
            "f2635a53-93ca-499f-aad4-4eb5e7f9128c": None,     # Melbourne
            "514d0eee-b807-45bd-96bd-eda630be1fba": "A00",    # Brisbane
        }


def _get_prefix(store_id: str) -> Optional[str]:
    """Return the prefix for a store from the cycle cache."""
    return _prefix_cache.get(store_id)


def _get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _get_store_paths(config: dict) -> tuple[Path, Path]:
    film_scans = config.get("film_scans_root")
    border_proc = config.get("border_processing_root")
    film_scans_path  = Path(film_scans)  if film_scans  else DEFAULT_FILM_SCANS_ROOT
    border_proc_path = Path(border_proc) if border_proc else DEFAULT_BORDER_PROCESSING_ROOT
    return film_scans_path, border_proc_path


def _strip_prefix(folder_name: str, store_id: str) -> Optional[str]:
    """
    Extract the twin check from a Drive folder name.

    Store-aware: if store_settings.twin_folder_prefix is set for this store,
    that literal prefix is stripped first — a store convention is only
    matched against folders that actually carry it. Stores with no prefix
    configured match the folder name as-is.

    Whatever remains is then normalized numerically rather than matched by
    exact string shape: non-digit characters are discarded, the digits are
    parsed as an int, and re-padded to the canonical 4-digit twin_check
    format. This is what makes "00000001" resolve to "0001" — Bondi and
    Miranda's scanning app emits a fixed 0000 pad ahead of the twin, so the
    literal folder name is 4 digits longer than the stored twin_check. A
    strict "exactly 4 digits" match (the old behaviour) rejects that outright;
    int-normalizing accepts any amount of leading-zero padding.
    """
    prefix = _get_prefix(store_id)
    remainder = folder_name

    if prefix:
        if not folder_name.startswith(prefix):
            return None
        remainder = folder_name[len(prefix):]

    digits = re.sub(r"\D", "", remainder)
    if not digits:
        return None

    twin = str(int(digits)).zfill(4)
    if len(twin) != 4:
        # More significant digits than a real twin check can have (max
        # 9999) — don't guess, treat as unparseable rather than risk a
        # false match.
        return None
    return twin


def _build_prefix(twin: str, store_id: str) -> str:
    prefix = _get_prefix(store_id)
    return f"{prefix}{twin}" if prefix else twin


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
            body={"role": "reader", "type": "anyone"},
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


# ── Border processing helpers ─────────────────────────────────────────────────

def _find_local_scan_folder(film_scans_root: Path, folder_name: str) -> Optional[Path]:
    if not film_scans_root.exists():
        logger.warning(f"[border] Film Scans root not found: {film_scans_root}")
        return None

    for date_folder in sorted(film_scans_root.iterdir(), reverse=True):
        if not date_folder.is_dir():
            continue
        candidate = date_folder / folder_name
        if candidate.exists() and candidate.is_dir():
            logger.info(f"[border] Found local scan folder: {candidate}")
            return candidate

    logger.warning(f"[border] Could not find local scan folder for: {folder_name}")
    return None


def _upload_folder_to_drive(service, local_folder: Path, parent_drive_id: str,
                              folder_name: str) -> Optional[str]:
    try:
        drive_folder_id = _get_or_create_folder(service, parent_drive_id, folder_name)
        image_files = [
            f for f in local_folder.iterdir()
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".tif", ".tiff")
        ]
        logger.info(f"[border] Uploading {len(image_files)} file(s) to Drive folder '{folder_name}'")
        for img_file in image_files:
            mime_type = "image/tiff" if img_file.suffix.lower() in (".tif", ".tiff") else "image/jpeg"
            media = MediaFileUpload(str(img_file), mimetype=mime_type, resumable=True)
            service.files().create(
                body={"name": img_file.name, "parents": [drive_folder_id]},
                media_body=media,
                fields="id",
            ).execute()
            logger.info(f"[border]   ✓ Uploaded: {img_file.name}")
        return drive_folder_id
    except Exception as e:
        logger.error(f"[border] Upload failed: {e}")
        return None


async def _run_border_processing(
    client,
    service,
    order_id: str,
    order_number: str,
    order_folder_id: str,
    folder_name: str,
    twin_check: str,
    film_scans_root: Path,
    border_processing_root: Path,
):
    logger.info(f"[border] Starting border processing for order {order_number}")

    client.table("orders").update({
        "border_scan_status": "processing"
    }).eq("id", order_id).execute()

    work_dir   = border_processing_root / order_number
    source_dir = work_dir / "source"
    output_dir = work_dir / "output"

    try:
        local_scan_folder = _find_local_scan_folder(film_scans_root, folder_name)
        if not local_scan_folder:
            raise FileNotFoundError(
                f"Local scan folder not found for twin {twin_check} / folder {folder_name}"
            )

        source_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        image_extensions = {".jpg", ".jpeg", ".tif", ".tiff"}
        copied = 0
        for f in local_scan_folder.iterdir():
            if f.is_file() and f.suffix.lower() in image_extensions:
                shutil.copy2(f, source_dir / f.name)
                copied += 1

        if copied == 0:
            raise ValueError(f"No image files found in {local_scan_folder}")

        logger.info(f"[border] Copied {copied} image(s) to {source_dir}")

        from app.services.image_processors.border_processor import process_folder
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, process_folder, str(source_dir), str(output_dir),
        )

        if result["failed"]:
            logger.warning(f"[border] {len(result['failed'])} image(s) failed")

        if not result["processed"]:
            raise ValueError("Border processor produced no output files")

        logger.info(f"[border] Processed {len(result['processed'])} image(s) successfully")

        bordered_folder_id = _upload_folder_to_drive(
            service, output_dir, order_folder_id, "Bordered Scans"
        )
        if not bordered_folder_id:
            raise RuntimeError("Drive upload failed — no folder ID returned")

        _set_folder_public(service, bordered_folder_id)

        bordered_url = _get_folder_drive_url(bordered_folder_id)
        client.table("orders").update({
            "border_scan_status": "complete",
            "bordered_scans_drive_url": bordered_url,
        }).eq("id", order_id).execute()

        client.table("order_events").insert({
            "order_id": order_id,
            "event_type": "border_scan_complete",
            "description": f"Border processing complete. {len(result['processed'])} image(s) processed.",
            "actor_label": "border_processor",
            "metadata": {
                "bordered_scans_drive_url": bordered_url,
                "processed_count": len(result["processed"]),
                "failed_count": len(result["failed"]),
            },
        }).execute()

        logger.info(f"[border] ✓ Complete for order {order_number}. Drive: {bordered_url}")

    except Exception as e:
        logger.error(f"[border] ✗ Failed for order {order_number}: {e}")
        client.table("orders").update({
            "border_scan_status": "failed",
        }).eq("id", order_id).execute()
        client.table("order_events").insert({
            "order_id": order_id,
            "event_type": "border_scan_failed",
            "description": f"Border processing failed: {e}",
            "actor_label": "border_processor",
            "metadata": {"error": str(e)},
        }).execute()

    finally:
        try:
            if work_dir.exists():
                shutil.rmtree(work_dir)
                logger.info(f"[border] Cleaned up working dir: {work_dir}")
        except Exception as cleanup_err:
            logger.warning(f"[border] Cleanup failed for {work_dir}: {cleanup_err}")


# ── Main watcher ──────────────────────────────────────────────────────────────

async def run_drive_watcher():
    global _prefix_cache

    logger.info("[drive_watcher] ---- Starting Drive watcher cycle ----")
    try:
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

        # Load prefix rules from store_settings once per cycle
        _prefix_cache = _load_store_prefixes(client)

        configs = client.table("drive_config").select("*").eq("enabled", True).execute()
        logger.info(f"[drive_watcher] Found {len(configs.data)} enabled store config(s)")
        if not configs.data:
            return
        service = _get_drive_service()
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
    folders = _list_inbox_folders(service, inbox_folder_id)
    logger.info(f"[drive_watcher] Found {len(folders)} folder(s) in inbox")

    if not folders:
        return

    for folder in folders:
        await _process_folder(
            client, service, config,
            folder, inbox_folder_id, delivered_folder_id,
            store_id, stabilise_seconds
        )


async def _process_folder(client, service, config, folder, inbox_folder_id,
                           delivered_folder_id, store_id, stabilise_seconds):
    folder_id   = folder["id"]
    folder_name = folder["name"]
    modified_time = folder.get("modifiedTime", "")

    logger.info(f"[drive_watcher] --- Processing folder: {folder_name} ---")

    existing = client.table("drive_watcher_log").select("status").eq("folder_id", folder_id).execute()
    if existing.data:
        existing_status = existing.data[0]["status"]
        if existing_status in ("moved", "emailed", "skipped"):
            return
        if existing_status == "processing":
            return

    if not _is_stable(modified_time, stabilise_seconds):
        logger.info(f"[drive_watcher] Folder not stable yet: {folder_name}")
        return

    twin = _strip_prefix(folder_name, store_id)
    if not twin:
        logger.warning(f"[drive_watcher] Cannot parse twin from folder: {folder_name}")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "skipped", "Could not parse twin check from folder name")
        return

    _log_watcher_event(client, store_id, folder_id, folder_name, "processing",
                       f"Parsed twin: {twin}")

    rolls = client.table("rolls").select(
        "id, twin_check, order_id, status, date_scanned, drive_folder_url, store_id"
    ).eq("twin_check", twin).eq("store_id", store_id).execute()

    if not rolls.data:
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "skipped", f"No roll found for twin {twin}")
        return

    candidates = [
        r for r in rolls.data
        if r.get("date_scanned") is None
        and r.get("drive_folder_url") is None
        and r.get("status") not in ("delivered", "blank", "archived")
    ]

    if len(candidates) > 1:
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "ambiguous", f"{len(candidates)} matching rolls found for twin {twin}")
        return

    if len(candidates) == 0:
        already_scanned = [r for r in rolls.data if r.get("date_scanned") is not None]
        if already_scanned:
            _log_watcher_event(client, store_id, folder_id, folder_name,
                               "rescan_detected", "Roll already scanned.")
        else:
            _log_watcher_event(client, store_id, folder_id, folder_name,
                               "skipped", f"No eligible roll for twin {twin}")
        return

    roll = candidates[0]
    roll_id  = roll["id"]
    order_id = roll["order_id"]

    order_result = client.table("orders").select(
        "id, order_number, customer_name, customer_email, status, order_type, "
        "store_id, drive_order_folder_url, border_scan, bordered_scans_drive_url"
    ).eq("id", order_id).execute()

    if not order_result.data:
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "error", f"Order {order_id} not found", roll_id=roll_id)
        return

    order = order_result.data[0]
    film_scans_root, border_processing_root = _get_store_paths(config)

    now = datetime.now()
    order_folder_name = f"{order['order_number']} {order['customer_name']}"
    year_folder_id  = _get_or_create_folder(service, delivered_folder_id, str(now.year))
    month_folder_id = _get_or_create_folder(service, year_folder_id, str(now.month))
    order_folder_id = _get_or_create_folder(service, month_folder_id, order_folder_name)

    try:
        _move_folder(service, folder_id, order_folder_id, inbox_folder_id)
        logger.info(f"[drive_watcher] Moved {folder_name} → {order_folder_name}")
    except HttpError as e:
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "error", f"Move failed: {e}", roll_id=roll_id, order_id=order_id)
        return

    drive_url = _get_folder_drive_url(order_folder_id)
    _set_folder_public(service, order_folder_id)

    client.table("rolls").update({
        "date_scanned": datetime.utcnow().isoformat(),
        "drive_folder_url": drive_url,
        "status": "scanned",
    }).eq("id", roll_id).execute()

    _log_watcher_event(client, store_id, folder_id, folder_name,
                       "moved", f"Moved to {order_folder_name}",
                       roll_id=roll_id, order_id=order_id)

    # First scan detected for this order — advance booked_in -> scanning.
    # Guarded so a later roll on the same order doesn't re-fire this or
    # downgrade an order that's already past this stage.
    if order.get("status") == "booked_in":
        client.table("orders").update({
            "status": "scanning",
            "scanning_at": datetime.utcnow().isoformat(),
        }).eq("id", order_id).execute()
        order["status"] = "scanning"

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

    if unscanned:
        logger.info(f"[drive_watcher] Order {order['order_number']} waiting for {len(unscanned)} more roll(s)")
        return

    # All rolls scanned — record the Drive link, but do NOT advance to
    # delivered yet. Status stays on scanning until the email actually
    # sends successfully (see below).
    client.table("orders").update({
        "drive_order_folder_url": drive_url,
        "date_scanned": datetime.utcnow().isoformat(),
    }).eq("id", order_id).execute()

    client.table("order_events").insert({
        "order_id": order_id,
        "event_type": "scans_complete",
        "description": f"All rolls scanned. Drive: {drive_url}",
        "actor_label": "drive_watcher",
        "metadata": {"drive_url": drive_url, "roll_id": roll_id},
    }).execute()

    try:
        from app.services.email_service import send_order_email, _derive_template_key
        order["drive_order_folder_url"] = drive_url
        order["service_type"] = order.get("order_type") or ""
        template_key = _derive_template_key(order)
        sent = send_order_email(order, template_key, drive_url=drive_url)

        if sent:
            client.table("orders").update({
                "status": "delivered",
                "delivered_at": datetime.utcnow().isoformat(),
            }).eq("id", order_id).execute()

            client.table("order_events").insert({
                "order_id": order_id,
                "event_type": "delivered",
                "description": f"Order delivered — email sent. Drive: {drive_url}",
                "actor_label": "drive_watcher",
                "metadata": {"drive_url": drive_url, "roll_id": roll_id},
            }).execute()

            _log_watcher_event(client, store_id, folder_id, folder_name,
                               "emailed", "Email sent successfully",
                               roll_id=roll_id, order_id=order_id)
        else:
            logger.error(
                f"[drive_watcher] Email send returned False for order {order['order_number']} "
                f"— leaving status on scanning"
            )
            _log_watcher_event(client, store_id, folder_id, folder_name,
                               "error", "Email send returned False",
                               roll_id=roll_id, order_id=order_id)
    except Exception as e:
        logger.error(f"[drive_watcher] Email failed for order {order['order_number']}: {e}")
        _log_watcher_event(client, store_id, folder_id, folder_name,
                           "error", f"Email failed: {e}",
                           roll_id=roll_id, order_id=order_id)

    if order.get("border_scan"):
        logger.info(f"[drive_watcher] Border scan enabled — queuing job for order {order['order_number']}")
        asyncio.create_task(
            _run_border_processing(
                client=client,
                service=service,
                order_id=order_id,
                order_number=order["order_number"],
                order_folder_id=order_folder_id,
                folder_name=folder_name,
                twin_check=twin,
                film_scans_root=film_scans_root,
                border_processing_root=border_processing_root,
            )
        )