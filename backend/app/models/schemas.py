from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────

class ServiceType(str, Enum):
    dev_only        = "Dev only"
    dev_scan        = "Dev+Scan"
    dev_scan_print  = "Dev+Scan+Print"
    dev_print       = "Dev+Print"
    scan_only       = "Scan only"
    print_only      = "Print only"


class OrderStatus(str, Enum):
    inbound     = "inbound"
    booked_in   = "booked_in"
    scanning    = "scanning"
    delivered   = "delivered"
    cancelled   = "cancelled"
    discarded   = "discarded"
    # NOTE: "archived" is intentionally excluded — internal roll-level status only


class OrderType(str, Enum):
    film        = "film"
    b2b         = "b2b"
    print_only  = "print_only"
    passport    = "passport"


class DiscardReason(str, Enum):
    charge_correction = "charge_correction"
    add_on_existing   = "add_on_existing"
    not_film_related  = "not_film_related"
    duplicate_sale    = "duplicate_sale"
    other             = "other"


class UserRole(str, Enum):
    staff        = "staff"
    store_admin  = "store_admin"
    master_admin = "master_admin"


# ── Auth ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ── Stores ─────────────────────────────────────────────────────────────────

class StoreBase(BaseModel):
    name: str
    label: str
    email: str


class StoreRead(StoreBase):
    id: UUID
    drive_root_folder_id: Optional[str] = None
    drive_inbox_folder_id: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Users ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    initials: Optional[str] = None
    role: UserRole = UserRole.staff
    store_id: Optional[UUID] = None


class UserRead(BaseModel):
    id: UUID
    email: str
    full_name: str
    initials: Optional[str]
    role: str
    store_id: Optional[UUID]
    is_active: bool

    class Config:
        from_attributes = True


# ── Roll intake ────────────────────────────────────────────────────────────

class RollIntake(BaseModel):
    # Optional (migration 009): a store with twin_check_sequences.auto_enabled
    # submits rolls with no twin_check at all — the roll is created pending
    # (twin_check/twin_check_id both NULL) and filled in by a follow-up call
    # to POST /orders/{id}/twin-checks/allocate. Manual-mode bookings (and
    # any booking in a store where auto_enabled is off) still provide a real
    # value here, exactly as before.
    twin_check: Optional[str] = None
    service_type: ServiceType = ServiceType.dev_scan
    # Process/chemistry code (C41/BW/RSC) — see sku_map.process_code. Only
    # meaningful once a real twin_check exists; ignored for pending rolls
    # (auto mode sets it from the SKU-derived mix at allocate time instead).
    process_code: Optional[str] = None

    @field_validator("twin_check")
    @classmethod
    def pad_twin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        digits = "".join(c for c in v if c.isdigit())
        if not digits or len(digits) > 4:
            raise ValueError("Twin check must be 1-4 digits")
        return digits.zfill(4)


class RollRead(BaseModel):
    id: UUID
    order_id: UUID
    twin_check: Optional[str] = None
    service_type: str
    status: str
    is_blank: bool
    drive_folder_url: Optional[str]
    created_at: datetime
    date_scanned: Optional[datetime]
    date_delivered: Optional[datetime]
    operator_initials: Optional[str]
    # Twin check allocation fields (migration 009) — see TwinCheckRead below
    # for the full record; these are the roll-list-friendly subset.
    twin_check_id: Optional[UUID] = None
    process_code: Optional[str] = None
    collision_warning: bool = False

    class Config:
        from_attributes = True


# ── Twin check allocation ────────────────────────────────────────────────

class TwinCheckRead(BaseModel):
    id: UUID
    store_id: UUID
    number: int
    twin_check: str  # zero-padded 4-digit display form
    cycle: Optional[int] = None
    source: str  # 'auto' | 'manual'
    order_id: Optional[UUID] = None
    roll_id: Optional[UUID] = None
    status: str  # allocated | printed | voided
    collision_warning: bool
    allocated_at: datetime
    allocated_by: Optional[str] = None
    printed_at: Optional[datetime] = None
    voided_at: Optional[datetime] = None
    void_reason: Optional[str] = None

    class Config:
        from_attributes = True


class AllocateResponse(BaseModel):
    order_id: UUID
    twin_checks: List[TwinCheckRead]
    range_label: Optional[str] = None  # e.g. "4821-4830", None if non-contiguous/empty


class VoidTwinCheckRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("A void reason is required")
        return v.strip()


class AddRollPayload(BaseModel):
    service_type: ServiceType = ServiceType.dev_scan
    process_code: Optional[str] = None


class RescanRequest(BaseModel):
    roll_ids: List[UUID]

    @field_validator("roll_ids")
    @classmethod
    def at_least_one(cls, v: List[UUID]) -> List[UUID]:
        if not v:
            raise ValueError("Select at least one roll to rescan")
        return v


class ProcessMixEntry(BaseModel):
    process_code: Optional[str]
    count: int


class ProcessMixResponse(BaseModel):
    total: int
    mix: List[ProcessMixEntry]
    unmapped: bool


class PrintQueueJobRead(BaseModel):
    id: UUID
    store_id: UUID
    zpl: str
    status: str
    created_at: datetime
    sent_at: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class PrintQueueAckRequest(BaseModel):
    status: str  # 'sent' | 'failed'
    error: Optional[str] = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in ("sent", "failed"):
            raise ValueError("status must be 'sent' or 'failed'")
        return v


class TwinCheckSequenceRead(BaseModel):
    store_id: UUID
    current_value: int
    cycle: int
    min_value: int
    max_value: int
    auto_enabled: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class TwinCheckSequenceUpdate(BaseModel):
    auto_enabled: bool


class RollsAddPayload(BaseModel):
    """Payload for adding rolls to an existing order"""
    rolls: List[RollIntake]
    operator_initials: Optional[str] = None


# ── Orders ─────────────────────────────────────────────────────────────────

class OrderCreate(BaseModel):
    """Manual intake - staff types customer details"""
    order_number: str
    store_id: UUID
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    account: Optional[str] = None
    order_type: OrderType = OrderType.film
    rolls: List[RollIntake]
    operator_initials: Optional[str] = None
    notes: Optional[str] = None
    manual_entry: bool = False  # True when booked without Pronto lookup

    @field_validator("order_number")
    @classmethod
    def clean_order_number(cls, v: str) -> str:
        return v.strip().replace(" ", "")


class OrderCreateFromPronto(BaseModel):
    """Pronto lookup intake - customer data pulled from RawData"""
    order_number: str
    store_id: UUID
    rolls: List[RollIntake]
    operator_initials: Optional[str] = None
    customer_name: str
    customer_email: Optional[str] = None
    account: Optional[str] = None
    service_type: Optional[ServiceType] = None


class TwinCheckUpdate(BaseModel):
    twin_check: str

    @field_validator("twin_check")
    @classmethod
    def validate_twin(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 4:
            raise ValueError("Twin check must be exactly 4 numeric digits")
        return v


class OrderRead(BaseModel):
    id: UUID
    order_number: str
    order_type: str
    order_date: Optional[str] = None
    status: str
    customer_name: str
    customer_email: Optional[str]
    phone_number: Optional[str] = None
    account: Optional[str]
    store_id: UUID
    store_name: Optional[str] = None
    operator_initials: Optional[str]
    email_status: str
    blank_email_status: str
    print_ready_email_status: str
    drive_order_folder_url: Optional[str]
    is_print_only: bool
    has_blanks: bool
    manual_entry: bool = False
    # Border / addon scan flags
    border_scan: bool = False
    contact_sheet: bool = False
    rebate_scan: bool = False
    border_scan_status: Optional[str] = None
    bordered_scans_drive_url: Optional[str] = None
    created_at: datetime
    date_scanned: Optional[datetime]
    date_delivered: Optional[datetime]
    # Inbound pipeline fields (migration 003)
    pronto_order_number: Optional[str] = None
    pronto_account_number: Optional[str] = None
    pronto_order_date: Optional[datetime] = None
    booked_in_at: Optional[datetime] = None
    scanning_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    discarded_at: Optional[datetime] = None
    discarded_by: Optional[str] = None
    discard_reason: Optional[str] = None
    discard_notes: Optional[str] = None
    refund_status: Optional[str] = None
    refund_amount: Optional[float] = None
    rolls: List[RollRead] = []
    notes: Optional[str]
    # Live-joined from pronto_cache for OrdersPage colour-coding — see
    # order_service._attach_film_types(). None for manual entries or any
    # order without a matching Pronto sales order.
    film_type: Optional[str] = None

    class Config:
        from_attributes = True


class OrderSummary(BaseModel):
    """Lightweight version for list views"""
    id: UUID
    order_number: str
    order_type: str
    status: str
    customer_name: str
    customer_email: Optional[str]
    store_name: str
    operator_initials: Optional[str]
    email_status: str
    total_rolls: int
    blank_rolls: int
    delivered_rolls: int
    has_blanks: bool
    is_print_only: bool
    manual_entry: bool = False
    drive_order_folder_url: Optional[str]
    created_at: datetime
    date_delivered: Optional[datetime]
    turnaround_hours: Optional[float]


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    notes: Optional[str] = None


class OrderMarkBlank(BaseModel):
    roll_ids: List[UUID]
    send_email: bool = False


class OrderSetDriveLink(BaseModel):
    drive_order_folder_url: str


class OrderDiscardRequest(BaseModel):
    reason: DiscardReason
    notes: Optional[str] = None
    operator_id: Optional[str] = None


# ── Refund warnings ────────────────────────────────────────────────────────

class RefundWarningResolveRequest(BaseModel):
    order_id: UUID
    notes: Optional[str] = None
    operator_id: Optional[str] = None


class RefundWarningIgnoreRequest(BaseModel):
    notes: Optional[str] = None
    operator_id: Optional[str] = None


# ── Dashboard / stats ──────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    store_id: Optional[UUID]
    store_name: Optional[str]
    period_days: int
    total_orders: int
    delivered_orders: int
    pending_orders: int
    overdue_orders: int
    blank_orders: int
    avg_turnaround_hours: Optional[float]
    orders_today: int
    rolls_today: int


# ── Pronto lookup ──────────────────────────────────────────────────────────

class ProntoLookupResult(BaseModel):
    found: bool
    order_number: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    service_type: Optional[str] = None
    account: Optional[str] = None


# ── Events ─────────────────────────────────────────────────────────────────

class EventRead(BaseModel):
    id: UUID
    order_id: UUID
    roll_id: Optional[UUID]
    event_type: str
    description: Optional[str]
    actor_label: Optional[str]
    metadata: dict
    created_at: datetime

    class Config:
        from_attributes = True
