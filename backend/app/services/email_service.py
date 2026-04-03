# app/services/email_service.py
# ============================================================
# Gmail SMTP email service — renders Jinja2 templates and
# sends customer notification emails per store credentials.
# Logs all sends to the email_log table.
# ============================================================

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
import os

from supabase import create_client
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Template directory ───────────────────────────────────────
TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "app", "templates", "email"
)

jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
)


def _first_name(full_name: str) -> str:
    """Extract first name from full name."""
    if not full_name:
        return "there"
    return full_name.strip().split()[0]


def _select_template(order_type: str, has_blanks: bool, all_blank: bool) -> str:
    """
    Select the correct email template based on order service type.
    Returns template filename.
    """
    if all_blank:
        return "blank_notification.html"

    order_type = (order_type or "").strip()

    if order_type == "Dev+Scan+Print":
        return "prints_and_scans_ready.html"
    elif order_type == "Dev+Scan":
        return "scans_ready.html"
    elif order_type == "Dev only":
        return "negatives_ready.html"
    elif order_type == "Print only":
        return "prints_ready.html"
    elif order_type == "Scan only":
        return "scans_ready.html"
    else:
        return "scans_ready.html"


def _select_subject(order_type: str, order_number: str, has_blanks: bool, all_blank: bool) -> str:
    """Select email subject line based on order type."""
    if all_blank:
        return f"Update on your film order | {order_number} | digiDirect"

    order_type = (order_type or "").strip()

    if order_type == "Dev+Scan+Print":
        return f"Your prints and scans are ready | {order_number} | digiDirect"
    elif order_type == "Dev+Scan":
        return f"Your scans are ready | {order_number} | digiDirect"
    elif order_type == "Dev only":
        return f"Your negatives are ready to collect | {order_number} | digiDirect"
    elif order_type == "Print only":
        return f"Your prints are ready to collect | {order_number} | digiDirect"
    elif order_type == "Scan only":
        return f"Your scans are ready | {order_number} | digiDirect"
    else:
        return f"Your order is ready | {order_number} | digiDirect"


def _render_template(template_name: str, context: dict) -> str:
    """Render a Jinja2 HTML template with the given context."""
    template = jinja_env.get_template(template_name)
    return template.render(**context)


def _send_smtp(
    gmail_address: str,
    gmail_app_password: str,
    to_email: str,
    subject: str,
    html_body: str,
):
    """Send an email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = to_email

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, to_email, msg.as_string())


def _log_email(
    client,
    order_id: str,
    to_email: str,
    subject: str,
    template_name: str,
    status: str,
    error_message: Optional[str] = None,
):
    """Log email send attempt to email_log table."""
    try:
        client.table("email_log").insert({
            "order_id": order_id,
            "to_email": to_email,
            "subject": subject,
            "template_name": template_name,
            "status": status,
            "error_message": error_message,
            "sent_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"[email_service] Failed to log email: {e}")


async def send_order_email(
    client,
    config: dict,
    order: dict,
    rolls: list,
) -> bool:
    """
    Send the appropriate customer email for a completed order.
    Called automatically by the drive watcher when all rolls are scanned.
    Returns True if sent successfully.

    If the order has border_scan enabled, the bordered_scans_drive_url will
    be None at this point (processing runs async after email). The template
    receives bordered_scans_url=None and gracefully omits the bordered link.
    """
    to_email = order.get("customer_email")
    if not to_email:
        logger.warning(f"[email_service] No customer email for order {order.get('order_number')}")
        return False

    order_type = order.get("order_type", "")
    order_number = order.get("order_number", "")
    customer_name = order.get("customer_name", "")
    drive_url = order.get("drive_order_folder_url", "")

    # Border scans — will be None if processing hasn't completed yet
    bordered_scans_url = order.get("bordered_scans_drive_url") or None
    has_border_scan = bool(order.get("border_scan", False))

    # Determine blank status
    blank_rolls = [r for r in rolls if r.get("is_blank") or r.get("status") == "blank"]
    all_blank = len(blank_rolls) == len(rolls)
    has_blanks = len(blank_rolls) > 0

    template_name = _select_template(order_type, has_blanks, all_blank)
    subject = _select_subject(order_type, order_number, has_blanks, all_blank)

    # Build blank twins list for blank notification
    blank_twins = [r.get("twin_check", "") for r in blank_rolls]

    context = {
        "first_name": _first_name(customer_name),
        "customer_name": customer_name,
        "order_number": order_number,
        "drive_url": drive_url,
        "has_blanks": has_blanks,
        "all_blank": all_blank,
        "blank_twins": blank_twins,
        "blank_count": len(blank_rolls),
        "total_rolls": len(rolls),
        "store_name": "digiDirect",
        # Border scan context — templates check has_border_scan and bordered_scans_url
        "has_border_scan": has_border_scan,
        "bordered_scans_url": bordered_scans_url,
    }

    try:
        html_body = _render_template(template_name, context)
    except Exception as e:
        logger.error(f"[email_service] Template render failed: {e}")
        _log_email(client, order["id"], to_email, subject,
                   template_name, "failed", str(e))
        return False

    gmail_address = config.get("gmail_address")
    gmail_app_password = config.get("gmail_app_password")

    try:
        _send_smtp(gmail_address, gmail_app_password, to_email, subject, html_body)
        logger.info(f"[email_service] Email sent to {to_email} for order {order_number}")
        _log_email(client, order["id"], to_email, subject, template_name, "sent")
        return True
    except Exception as e:
        logger.error(f"[email_service] SMTP failed for order {order_number}: {e}")
        _log_email(client, order["id"], to_email, subject,
                   template_name, "failed", str(e))
        return False


async def send_manual_email(
    order_id: str,
    template_override: Optional[str] = None,
) -> bool:
    """
    Send a manual email for an order — used for Dev only and Print only templates
    which require staff to trigger manually.
    """
    try:
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

        # Fetch order
        order_result = client.table("orders").select("*").eq("id", order_id).execute()
        if not order_result.data:
            logger.error(f"[email_service] Order {order_id} not found")
            return False
        order = order_result.data[0]

        # Fetch store drive config for SMTP credentials
        config_result = client.table("drive_config").select("*").eq(
            "store_id", order["store_id"]
        ).execute()
        if not config_result.data:
            logger.error(f"[email_service] No drive config for store {order['store_id']}")
            return False
        config = config_result.data[0]

        # Fetch rolls
        rolls_result = client.table("rolls").select("*").eq("order_id", order_id).execute()
        rolls = rolls_result.data or []

        return await send_order_email(client, config, order, rolls)

    except Exception as e:
        logger.error(f"[email_service] Manual email failed: {e}")
        return False