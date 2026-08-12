# app/api/drive.py
# ============================================================
# Drive watcher API endpoints — config management + manual trigger
# ============================================================

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from supabase import create_client

from app.core.config import settings
from app.services.drive_watcher import run_drive_watcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drive", tags=["drive"])


def get_supabase():
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("/config")
async def list_drive_configs():
    """List all store Drive configurations."""
    try:
        client = get_supabase()
        result = client.table("drive_config").select(
            "id, store_id, inbox_folder_id, delivered_folder_id, "
            "gmail_address, stabilise_seconds, enabled, updated_at"
        ).execute()
        return {"configs": result.data}
    except Exception as e:
        logger.error(f"[drive_api] Error listing configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/{store_id}")
async def get_drive_config(store_id: UUID):
    """Get Drive config for a specific store."""
    try:
        client = get_supabase()
        result = client.table("drive_config").select(
            "id, store_id, inbox_folder_id, delivered_folder_id, "
            "gmail_address, stabilise_seconds, enabled, updated_at"
        ).eq("store_id", str(store_id)).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="No Drive config found for this store")

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/{store_id}")
async def update_drive_config(store_id: UUID, payload: dict):
    """Update Drive config for a specific store."""
    try:
        client = get_supabase()

        allowed_fields = {
            "inbox_folder_id", "delivered_folder_id",
            "gmail_address", "gmail_app_password",
            "stabilise_seconds", "enabled"
        }
        update_data = {k: v for k, v in payload.items() if k in allowed_fields}

        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        result = client.table("drive_config").update(update_data).eq(
            "store_id", str(store_id)
        ).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="No Drive config found for this store")

        return {"message": "Drive config updated", "store_id": str(store_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def manual_drive_sync():
    """Manually trigger the Drive watcher cycle (admin only)."""
    try:
        logger.info("[drive_api] Manual Drive sync triggered")
        result = await run_drive_watcher()

        if result and result.get("status") == "already_running":
            return {
                "status": "already_running",
                "message": "Drive watcher is already running — try again shortly",
            }

        return {"status": "completed", "message": "Drive watcher cycle complete"}
    except Exception as e:
        logger.error(f"[drive_api] Manual sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/log")
async def get_watcher_log(
    store_id: Optional[UUID] = None,
    status: Optional[str] = None,
    limit: int = 50
):
    """Get recent drive watcher log entries."""
    try:
        client = get_supabase()
        query = client.table("drive_watcher_log").select("*").order(
            "created_at", desc=True
        ).limit(limit)

        if store_id:
            query = query.eq("store_id", str(store_id))
        if status:
            query = query.eq("status", status)

        result = query.execute()
        return {"log": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/log/order/{order_id}")
async def get_watcher_log_for_order(order_id: UUID):
    """
    Get drive watcher log entries for a specific order.
    Used by the Order Detail page to show rescan alerts.
    Returns only rescan_detected entries so the UI can prompt staff to approve.
    """
    try:
        client = get_supabase()
        result = client.table("drive_watcher_log").select("*").eq(
            "order_id", str(order_id)
        ).eq(
            "status", "rescan_detected"
        ).order(
            "created_at", desc=True
        ).execute()

        return {"order_id": str(order_id), "rescans": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/log/{folder_id}")
async def clear_watcher_log_entry(folder_id: str):
    """
    Clear a specific watcher log entry by folder_id.
    Used to allow reprocessing of a rescan-detected folder.
    """
    try:
        client = get_supabase()
        result = client.table("drive_watcher_log").delete().eq(
            "folder_id", folder_id
        ).execute()
        return {"message": f"Log entry cleared for folder {folder_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))