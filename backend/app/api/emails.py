# app/api/emails.py
# ============================================================
# Email API endpoints — manual send + email log
# ============================================================

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.email_service import send_manual_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


class ManualEmailPayload(BaseModel):
    template_override: Optional[str] = None
    # Required when the order has an unvoided collision_warning — see
    # _has_unacknowledged_collision below. This is the point the brief
    # calls out as the one that matters: a collision at book-in is
    # harmless, a collision at the point of emailing someone's scans is
    # the incident.
    acknowledge_collision: bool = False


def _has_unacknowledged_collision(order_id: str) -> bool:
    """True if this order has any non-voided twin_checks row flagged
    collision_warning — the delivery-time gate from migration 009 /
    twin_check_service. Uses the Supabase client directly, matching this
    file's existing convention (no SQLAlchemy session in emails.py today)."""
    try:
        from supabase import create_client
        from app.core.config import settings
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        result = (
            client.table("twin_checks")
            .select("id")
            .eq("order_id", order_id)
            .eq("collision_warning", True)
            .neq("status", "voided")
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.warning(f"[emails_api] Could not check collision_warning for order {order_id}: {e}")
        return False


@router.post("/send/{order_id}")
async def send_email(order_id: UUID, payload: ManualEmailPayload = ManualEmailPayload()):
    """
    Manually trigger an email for an order.
    Used for Dev only and Print only orders where email is not automatic.
    """
    if _has_unacknowledged_collision(str(order_id)) and not payload.acknowledge_collision:
        raise HTTPException(
            status_code=409,
            detail="This order has a twin check collision warning — acknowledge before sending scans.",
        )
    try:
        success = await send_manual_email(
            order_id=str(order_id),
            template_override=payload.template_override,
        )
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Email failed to send — check email_log for details"
            )
        return {"message": "Email sent successfully", "order_id": str(order_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[emails_api] Send failed for order {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/log/{order_id}")
async def get_email_log(order_id: UUID):
    """Get email send history for a specific order."""
    try:
        from supabase import create_client
        from app.core.config import settings
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

        result = client.table("email_log").select("*").eq(
            "order_id", str(order_id)
        ).order("sent_at", desc=True).execute()

        return {"order_id": str(order_id), "emails": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/log")
async def get_all_email_logs(
    status: Optional[str] = None,
    limit: int = 50
):
    """Get recent email log entries across all orders."""
    try:
        from supabase import create_client
        from app.core.config import settings
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

        query = client.table("email_log").select("*").order(
            "sent_at", desc=True
        ).limit(limit)

        if status:
            query = query.eq("status", status)

        result = query.execute()
        return {"emails": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resend/{order_id}")
async def resend_email(order_id: UUID, payload: ManualEmailPayload = ManualEmailPayload()):
    """
    Resend the email for an order regardless of previous send status.
    Staff-triggered resend. Gated by the same collision acknowledgement as
    a first send — a resend still transmits scans to the customer.
    """
    if _has_unacknowledged_collision(str(order_id)) and not payload.acknowledge_collision:
        raise HTTPException(
            status_code=409,
            detail="This order has a twin check collision warning — acknowledge before sending scans.",
        )
    try:
        success = await send_manual_email(order_id=str(order_id))
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Resend failed — check email_log for details"
            )
        return {"message": "Email resent successfully", "order_id": str(order_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[emails_api] Resend failed for order {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))