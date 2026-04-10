import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
from supabase import create_client
from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------
jinja_env = Environment(
    loader=FileSystemLoader("app/templates/email"),
    autoescape=select_autoescape(["html"])
)

# ---------------------------------------------------------------------------
# Template routing
# ---------------------------------------------------------------------------
TEMPLATE_MAP = {
    "scans_ready":           "scans_ready.html",
    "prints_and_scans_ready": "prints_and_scans_ready.html",
    "prints_ready":          "prints_ready.html",
    "negatives_ready":       "negatives_ready.html",
    "blank_notification":    "blank_notification.html",
}

SUBJECT_MAP = {
    "scans_ready":            "Your film scans are ready, {first_name} | Order {order_number}",
    "prints_and_scans_ready": "Your prints and scans are ready, {first_name} | Order {order_number}",
    "prints_ready":           "Your prints are ready for collection | Order {order_number}",
    "negatives_ready":        "Your negatives are ready — Order {order_number}",
    "blank_notification":     "{first_name}, an update on your recent order {order_number}",
}

# ---------------------------------------------------------------------------
# Helper — name formatting
# ---------------------------------------------------------------------------
def _title_name(name: Optional[str]) -> str:
    """Always render customer name in Title Case regardless of source format."""
    if not name:
        return "there"
    return name.strip().title()


# ---------------------------------------------------------------------------
# Helper — expiry date string
# ---------------------------------------------------------------------------
def _expiry_str(base_date: datetime, days: int) -> str:
    """Return a human-readable expiry date string."""
    expiry = base_date + timedelta(days=days)
    return expiry.strftime("%-d %B %Y")  # e.g. 3 April 2026


# ---------------------------------------------------------------------------
# Helper — fetch store settings
# ---------------------------------------------------------------------------
def _get_store_settings(store_id: str) -> dict:
    """Fetch storage policy and review URL from store_settings."""
    try:
        sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        result = sb.table("store_settings").select("*").eq("store_id", store_id).single().execute()
        if result.data:
            return result.data
    except Exception as e:
        logger.warning(f"Could not fetch store_settings for {store_id}: {e}")
    # Safe fallback defaults
    return {
        "print_storage_days": 30,
        "negative_storage_days": 30,
        "drive_storage_days": 90,
        "google_review_url": None,
    }


# ---------------------------------------------------------------------------
# Helper — fetch active promotions
# ---------------------------------------------------------------------------
def _get_active_promotions() -> list:
    """Fetch all active promotions from the promotions table."""
    try:
        sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        today = datetime.utcnow().date().isoformat()
        result = (
            sb.table("promotions")
            .select("*")
            .eq("active", True)
            .or_(f"valid_until.is.null,valid_until.gte.{today}")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"Could not fetch promotions: {e}")
        return []


# ---------------------------------------------------------------------------
# Helper — cross-sell flags
# ---------------------------------------------------------------------------
def _get_crosssell_flags(order: dict) -> dict:
    """
    Determine which services the order did NOT include.
    These drive the More To Explore cross-sell tiles.
    """
    service_type = (order.get("service_type") or "").lower()
    has_scans  = "scan" in service_type
    has_prints = "print" in service_type
    has_border = bool(order.get("border_scan"))
    has_contact = bool(order.get("contact_sheet"))

    return {
        "crosssell_scans":   not has_scans,
        "crosssell_prints":  not has_prints,
        "crosssell_border":  not has_border,
        "crosssell_contact": not has_contact,
    }


# ---------------------------------------------------------------------------
# Helper — fetch drive config for store (Gmail credentials)
# ---------------------------------------------------------------------------
def _get_drive_config(store_id: str) -> Optional[dict]:
    try:
        sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        result = (
            sb.table("drive_config")
            .select("*")
            .eq("store_id", store_id)
            .single()
            .execute()
        )
        return result.data
    except Exception as e:
        logger.error(f"Could not fetch drive_config for store {store_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------
def send_order_email(
    order: dict,
    template_key: str,
    drive_url: Optional[str] = None,
) -> bool:
    """
    Render and send a customer email for an order.

    Args:
        order:        Enriched order dict (from _enrich() in orders.py)
        template_key: One of the keys in TEMPLATE_MAP
        drive_url:    Optional — Drive folder URL injected by watcher

    Returns:
        True on success, False on failure
    """

    # --- Resolve template ---
    template_file = TEMPLATE_MAP.get(template_key)
    if not template_file:
        logger.error(f"Unknown template key: {template_key}")
        return False

    # --- Customer details ---
    customer_name  = _title_name(order.get("customer_name"))
    first_name     = customer_name.split()[0] if customer_name != "there" else "there"
    order_number   = order.get("order_number") or order.get("pronto_order_number") or "—"
    customer_email = order.get("customer_email")
    store_name     = order.get("store_name") or "digiDirect"
    store_id       = order.get("store_id")
    account_number = order.get("customer_account") or order.get("account_number") or None

    # Invoice date — formatted
    raw_date = order.get("order_date") or order.get("created_at")
    try:
        if isinstance(raw_date, str):
            base_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        else:
            base_date = raw_date or datetime.utcnow()
    except Exception:
        base_date = datetime.utcnow()

    invoice_date_str = base_date.strftime("%-d %B %Y")

    # --- Store settings (storage policy + review URL) ---
    store_settings = _get_store_settings(store_id) if store_id else {}
    print_days    = store_settings.get("print_storage_days", 30)
    negative_days = store_settings.get("negative_storage_days", 30)
    drive_days    = store_settings.get("drive_storage_days", 90)
    google_review_url = store_settings.get("google_review_url")

    # --- Expiry dates ---
    drive_expiry    = _expiry_str(base_date, drive_days)
    print_expiry    = _expiry_str(base_date, print_days)
    negative_expiry = _expiry_str(base_date, negative_days)

    # --- Service flags ---
    service_type = (order.get("service_type") or "").lower()
    has_scans    = "scan" in service_type
    has_prints   = "print" in service_type
    has_border   = bool(order.get("border_scan"))
    has_contact  = bool(order.get("contact_sheet"))

    # --- Promotions ---
    promotions = _get_active_promotions()

    # --- Cross-sell flags ---
    crosssell = _get_crosssell_flags(order)

    # --- Subject line ---
    subject_template = SUBJECT_MAP.get(template_key, "An update on your order")
    subject = subject_template.format(
        first_name=first_name,
        order_number=order_number,
    )

    # --- Render template ---
    try:
        template = jinja_env.get_template(template_file)
        html_body = template.render(
            # Customer
            customer_name=customer_name,
            first_name=first_name,
            order_number=order_number,
            account_number=account_number,
            invoice_date=invoice_date_str,
            store_name=store_name,
            # Drive
            drive_url=drive_url or order.get("drive_order_folder_url"),
            # Service flags
            has_scans=has_scans,
            has_prints=has_prints,
            has_border=has_border,
            has_contact=has_contact,
            # Storage expiry
            drive_expiry=drive_expiry,
            print_expiry=print_expiry,
            negative_expiry=negative_expiry,
            # Promotions
            promotions=promotions,
            # Cross-sell
            **crosssell,
            # Review
            google_review_url=google_review_url,
            # Blank roll
            blank_roll_count=order.get("blank_roll_count") or 0,
        )
    except Exception as e:
        logger.error(f"Template render failed for {template_key}: {e}")
        return False

    # --- Send via Gmail SMTP ---
    if not customer_email:
        logger.warning(f"No customer email for order {order_number} — skipping send")
        return False

    drive_config = _get_drive_config(store_id) if store_id else None
    if not drive_config:
        logger.error(f"No drive_config for store {store_id} — cannot send email")
        return False

    gmail_address  = drive_config.get("gmail_address")
    gmail_password = drive_config.get("gmail_app_password")

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"digiDirect {store_name} Lab <{gmail_address}>"
        msg["To"]      = customer_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, customer_email, msg.as_string())

        logger.info(f"Email sent: {template_key} → {customer_email} (order {order_number})")
        return True

    except Exception as e:
        logger.error(f"SMTP send failed for order {order_number}: {e}")
        return False


# ---------------------------------------------------------------------------
# Template key derivation
# ---------------------------------------------------------------------------
def _derive_template_key(order: dict) -> str:
    """
    Pick the appropriate email template based on order_type.
    Falls back to blank_notification when no match is found.
    """
    order_type = (order.get("order_type") or "").lower()
    has_scan  = "scan" in order_type
    has_print = "print" in order_type
    has_neg   = "neg" in order_type or "negative" in order_type

    if has_scan and has_print:
        return "prints_and_scans_ready"
    if has_scan:
        return "scans_ready"
    if has_print:
        return "prints_ready"
    if has_neg:
        return "negatives_ready"
    return "blank_notification"


# ---------------------------------------------------------------------------
# Manual / staff-triggered send
# ---------------------------------------------------------------------------
async def send_manual_email(
    order_id: str,
    template_override: Optional[str] = None,
) -> bool:
    """
    Fetch an order from Supabase, choose the right template, send the email,
    and write the result to the email_log table.

    Args:
        order_id:          UUID string of the order.
        template_override: If supplied and a valid TEMPLATE_MAP key, use it
                           instead of the auto-derived template.

    Returns:
        True on success, False on any failure.
    """
    sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

    # Fetch order
    try:
        result = (
            sb.table("orders")
            .select(
                "id, order_number, order_type, order_date, created_at, status, "
                "customer_name, customer_email, account, store_id, "
                "drive_order_folder_url, border_scan, contact_sheet, rebate_scan, "
                "has_blanks, blank_roll_count, email_status"
            )
            .eq("id", order_id)
            .single()
            .execute()
        )
    except Exception as e:
        logger.error(f"[send_manual_email] Failed to fetch order {order_id}: {e}")
        return False

    if not result.data:
        logger.error(f"[send_manual_email] Order {order_id} not found")
        return False

    order = result.data

    # Fetch store name
    store_id = order.get("store_id")
    if store_id:
        try:
            store_result = sb.table("stores").select("name").eq("id", store_id).single().execute()
            order["store_name"] = store_result.data.get("name") if store_result.data else None
        except Exception:
            order["store_name"] = None

    # service_type shim — send_order_email uses this for has_scans / has_prints flags
    order["service_type"] = order.get("order_type") or ""

    # Resolve template key
    template_key = template_override if template_override in TEMPLATE_MAP else _derive_template_key(order)

    # Send
    success = send_order_email(order=order, template_key=template_key)

    # Log result to email_log
    try:
        sb.table("email_log").insert({
            "order_id": order_id,
            "template_key": template_key,
            "recipient": order.get("customer_email"),
            "status": "sent" if success else "failed",
            "triggered_by": "manual",
        }).execute()
    except Exception as e:
        logger.warning(f"[send_manual_email] Could not write to email_log: {e}")

    # Update order email_status on success
    if success:
        try:
            sb.table("orders").update({"email_status": "sent"}).eq("id", order_id).execute()
        except Exception as e:
            logger.warning(f"[send_manual_email] Could not update email_status: {e}")

    return success