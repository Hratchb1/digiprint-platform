import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import Optional, List
from jinja2 import Environment, FileSystemLoader, select_autoescape
from supabase import create_client
from app.core.config import settings
from app.core.timeutils import utcnow

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
# v4 templates live (Phase 5, 15 Jul 2026). Instant rollback: point any
# entry back at the original filename — the pre-v4 files are kept in place.
TEMPLATE_MAP = {
    "scans_ready":            "scans_ready_v4.html",
    "prints_and_scans_ready": "prints_and_scans_ready_v4.html",
    "prints_ready":           "prints_ready_v4.html",
    "negatives_ready":        "negatives_ready_v4.html",
    "blank_notification":     "blank_notification_v4.html",
}

SUBJECT_MAP = {
    "scans_ready":            "{first_name}, your film scans are ready | Order {order_number}",
    "prints_and_scans_ready": "{first_name}, your prints and scans are ready | Order {order_number}",
    "prints_ready":           "{first_name}, your prints are ready for collection | Order {order_number}",
    "negatives_ready":        "{first_name}, your negatives are ready | Order {order_number}",
    "blank_notification":     "{first_name}, an update on your recent order | Order {order_number}",
}

# ---------------------------------------------------------------------------
# Frames-per-roll assumption
# ---------------------------------------------------------------------------
# NOTE: schema currently has no per-roll frame count column. We default to 36
# because 35mm 36-exp is by far the dominant lab format. If/when a `frame_count`
# column is added to the rolls table, replace _compute_frames_count below.
DEFAULT_FRAMES_PER_ROLL = 36


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
def _format_date_long(dt: datetime) -> str:
    """Format a date as e.g. '3 April 2026'. %-d is not portable (crashes on Windows)."""
    return f"{dt.day} {dt.strftime('%B %Y')}"


def _expiry_str(base_date: datetime, days: int) -> str:
    """Return a human-readable expiry date string."""
    return _format_date_long(base_date + timedelta(days=days))


# ---------------------------------------------------------------------------
# Helper — fetch store settings (storage policy + branding)
# ---------------------------------------------------------------------------
def _get_store_settings(store_id: str) -> dict:
    """
    Fetch storage policy, review URL, and email branding fields from store_settings.
    Branding fields (address_line, reply_email, hours_label, instagram_url) are
    optional — the template falls back gracefully when they're absent.
    """
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
        "negative_storage_days": 14,
        "drive_storage_days": 90,
        "google_review_url": None,
        "address_line": None,
        "reply_email": None,
        "hours_label": None,
        "instagram_url": None,
    }


# ---------------------------------------------------------------------------
# Helper — fetch active promotions
# ---------------------------------------------------------------------------
def _get_active_promotions() -> list:
    """Fetch all active promotions from the promotions table."""
    try:
        sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        today = utcnow().date().isoformat()
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
# Helper — comma-separated service list for the "Bring this when you
# collect" card, e.g. "Hi-Res Scans, Bordered Scans, Negatives"
# ---------------------------------------------------------------------------
def _compute_service_list(
    has_scans: bool, has_prints: bool, has_border: bool,
    has_contact: bool, has_hires: bool,
) -> str:
    parts: List[str] = []
    if has_hires:
        parts.append("Hi-Res Scans")
    elif has_scans:
        parts.append("Scans")
    if has_prints:
        parts.append("Prints")
    if has_border:
        parts.append("Bordered Scans")
    if has_contact:
        parts.append("Contact Sheet")
    # Every developed roll produces negatives regardless of what else was
    # ordered — always listed last.
    parts.append("Negatives")
    return ", ".join(parts)


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
# Helper — fetch rolls for an order (lazy — only when not already on order dict)
# ---------------------------------------------------------------------------
def _get_order_rolls(order: dict) -> List[dict]:
    """
    Returns the rolls list for an order. Prefers the rolls already on the
    order dict (when called from the FastAPI router with _enrich()), falls
    back to a Supabase fetch by order_id (when called from drive_watcher
    or send_manual_email).
    """
    rolls = order.get("rolls")
    if rolls:
        return rolls

    order_id = order.get("id")
    if not order_id:
        return []

    try:
        sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        result = (
            sb.table("rolls")
            .select("id, twin_check, service_type, status, is_blank")
            .eq("order_id", order_id)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"Could not fetch rolls for order {order_id}: {e}")
        return []


# ---------------------------------------------------------------------------
# Helper — derived counts and labels for v4 templates
# ---------------------------------------------------------------------------
def _compute_rolls_count(rolls: List[dict]) -> int:
    """Count of non-blank rolls — what the customer is actually receiving."""
    return sum(1 for r in rolls if not r.get("is_blank"))


def _compute_blank_roll_count(rolls: List[dict]) -> int:
    """Count of rolls confirmed blank on this order."""
    return sum(1 for r in rolls if r.get("is_blank"))


def _compute_frames_count(rolls_count: int) -> int:
    """
    Estimated frame count. See DEFAULT_FRAMES_PER_ROLL note above —
    swap to a real per-roll column when schema supports it.
    """
    return rolls_count * DEFAULT_FRAMES_PER_ROLL if rolls_count else 0


def _compute_twin_check_range(rolls: List[dict]) -> Optional[str]:
    """
    Compress the order's twin checks into a single human label:
      one twin           -> "0042"
      multiple, in range -> "0042-0045"
      no rolls           -> None
    Twin checks are zero-padded text so lexicographic order == numeric order.
    """
    twins = sorted({(r.get("twin_check") or "").strip() for r in rolls if r.get("twin_check")})
    if not twins:
        return None
    if len(twins) == 1 or twins[0] == twins[-1]:
        return twins[0]
    return f"{twins[0]}-{twins[-1]}"


def _compute_service_label(order_type: Optional[str]) -> Optional[str]:
    """
    Map the internal order_type code to a customer-facing label.
    Falls back to a Title-Case version of the input for unknown codes.
    """
    if not order_type:
        return None

    key = order_type.strip()
    label_map = {
        "Dev only":        "Develop only",
        "Dev+Scan":        "Develop & Scan",
        "Dev+Scan+Print":  "Develop, Scan & Print",
        "Dev+Print":       "Develop & Print",
        "Scan only":       "Scan only",
        "Print only":      "Print only",
    }
    return label_map.get(key, key.title())


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
        order:        Enriched order dict (from _enrich() in orders.py,
                      or from a Supabase fetch in send_manual_email).
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
            base_date = raw_date or utcnow()
    except Exception:
        base_date = utcnow()

    invoice_date_str = _format_date_long(base_date)

    # --- Store settings (storage policy + review URL + email branding) ---
    store_settings = _get_store_settings(store_id) if store_id else {}
    print_days        = store_settings.get("print_storage_days", 30)
    negative_days     = store_settings.get("negative_storage_days", 14)
    drive_days        = store_settings.get("drive_storage_days", 90)
    google_review_url = store_settings.get("google_review_url")

    # New (v4) branding fields — all optional, template falls back gracefully
    store_address_line  = store_settings.get("address_line")
    store_reply_email   = store_settings.get("reply_email")
    store_hours_label   = store_settings.get("hours_label")
    store_instagram_url = store_settings.get("instagram_url")

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
    # hires_scan has no backing DB column yet — this flag is forward-compatible
    # and will simply stay False until that SKU/column is added.
    has_hires    = "hires" in service_type or bool(order.get("hires_scan"))

    # --- Service list for the "Bring this when you collect" card ---
    service_list = _compute_service_list(has_scans, has_prints, has_border, has_contact, has_hires)

    # --- Rolls-derived stats (rolls_count, frames_count, twin_check_range) ---
    rolls = _get_order_rolls(order)
    rolls_count       = _compute_rolls_count(rolls)
    frames_count      = _compute_frames_count(rolls_count)
    twin_check_range  = _compute_twin_check_range(rolls)
    blank_roll_count  = _compute_blank_roll_count(rolls)

    # --- Service label (customer-facing version of order_type) ---
    service_label = _compute_service_label(order.get("order_type"))

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
            has_hires=has_hires,
            service_list=service_list,
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
            blank_roll_count=blank_roll_count,
            # ── v4 additions ──
            # Order-level derived stats
            rolls_count=rolls_count or None,
            frames_count=frames_count or None,
            service_label=service_label,
            twin_check_range=twin_check_range,
            # Per-store branding
            store_address_line=store_address_line,
            store_reply_email=store_reply_email,
            store_hours_label=store_hours_label,
            store_instagram_url=store_instagram_url,
        )
    except Exception as e:
        logger.error(f"Template render failed for {template_key}: {e}")
        return False

    # --- Send via Gmail SMTP ---
    if not customer_email:
        logger.warning(f"No customer email for order {order_number} — skipping send")
        return False

    # PAUSE_EMAILS=1 suppresses real SMTP sends (dev/testing) but reports
    # success so downstream status flows behave exactly as a real send.
    if settings.PAUSE_EMAILS:
        logger.warning(
            f"[PAUSE_EMAILS] Send suppressed: {template_key} → {customer_email} "
            f"(order {order_number}) — treating as success"
        )
        return True

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
    Pick the appropriate email template from the order's ROLLS, not
    order_type. order_type is a coarse category ('film'/'b2b'/'print_only'/
    'passport') set once at intake/Pronto-sync — it never carries service
    info like "Dev+Scan", so keying off it silently defaulted almost every
    order to blank_notification (see order 3939686: order_type='film').

    blank_notification fires only when every roll on the order is confirmed
    blank (is_blank=True). A mix of blank and good rolls still gets the
    normal scans/prints template — that template renders its own blank-roll
    notice via blank_roll_count, it doesn't need the standalone one.

    Otherwise, derive from each roll's service_type. An order can carry
    rolls with different service types; the richest combination present
    wins (prints_and_scans > scans > prints > negatives):
      Dev+Scan+Print          -> prints_and_scans_ready
      Dev+Scan / Scan only    -> scans_ready
      Dev+Print / Print only  -> prints_ready
      Dev only                -> negatives_ready

    Unknown/empty service_type on every roll (or no rolls at all) never
    falls back to blank_notification — defaults to scans_ready and logs a
    warning, so a data gap is visible instead of silently mis-sent.
    """
    rolls = _get_order_rolls(order)

    if rolls and all(r.get("is_blank") for r in rolls):
        return "blank_notification"

    has_scan = has_print = has_dev_only = False
    for r in rolls:
        service = (r.get("service_type") or "").strip().lower()
        if "scan" in service:
            has_scan = True
        if "print" in service:
            has_print = True
        if service == "dev only":
            has_dev_only = True

    if has_scan and has_print:
        return "prints_and_scans_ready"
    if has_scan:
        return "scans_ready"
    if has_print:
        return "prints_ready"
    if has_dev_only:
        return "negatives_ready"

    logger.warning(
        f"[_derive_template_key] Could not determine service type from rolls "
        f"for order {order.get('order_number') or order.get('id')} "
        f"({len(rolls)} roll(s)) — defaulting to scans_ready"
    )
    return "scans_ready"


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
                "id, order_number, order_type, pronto_order_date, created_at, status, "
                "customer_name, customer_email, account, store_id, "
                "drive_order_folder_url, border_scan, contact_sheet, rebate_scan, "
                "has_blanks, email_status"
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
    # send_order_email reads order_date for the invoice date line
    order["order_date"] = order.get("pronto_order_date")

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

    # Send (rolls are fetched lazily inside send_order_email via _get_order_rolls)
    success = send_order_email(order=order, template_key=template_key)

    # Log result to email_log
    try:
        customer_name = _title_name(order.get("customer_name"))
        first_name = customer_name.split()[0] if customer_name != "there" else "there"
        subject = SUBJECT_MAP.get(template_key, "An update on your order").format(
            first_name=first_name,
            order_number=order.get("order_number") or "—",
        )
        sb.table("email_log").insert({
            "order_id": order_id,
            "email_type": template_key,
            "recipient": order.get("customer_email") or "unknown",
            "subject": subject,
            "status": "sent" if success else "failed",
        }).execute()
    except Exception as e:
        logger.warning(f"[send_manual_email] Could not write to email_log: {e}")

    # Update order email_status on success
    if success:
        try:
            sb.table("orders").update({"email_status": "sent"}).eq("id", order_id).execute()
        except Exception as e:
            logger.warning(f"[send_manual_email] Could not update email_status: {e}")

        # Advance status to delivered on any successful manual send (Dev only /
        # Print only / blank notification / negatives-ready flows that don't go
        # through the Drive watcher). Guarded so it never regresses a terminal status.
        if order.get("status") not in ("delivered", "cancelled", "discarded"):
            try:
                sb.table("orders").update({
                    "status": "delivered",
                    "delivered_at": utcnow().isoformat(),
                }).eq("id", order_id).execute()
                sb.table("order_events").insert({
                    "order_id": order_id,
                    "event_type": "delivered",
                    "description": "Order delivered — manual email sent",
                    "actor_label": "manual_email",
                    "metadata": {"template_key": template_key},
                }).execute()
            except Exception as e:
                logger.warning(f"[send_manual_email] Could not update status to delivered: {e}")

    return success
