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
    twin_check: str
    service_type: ServiceType = ServiceType.dev_scan

    @field_validator("twin_check")
    @classmethod
    def pad_twin(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if not digits or len(digits) > 4:
            raise ValueError("Twin check must be 1-4 digits")
        return digits.zfill(4)


class RollRead(BaseModel):
    id: UUID
    order_id: UUID
    twin_check: str
    service_type: str
    status: str
    is_blank: bool
    drive_folder_url: Optional[str]
    created_at: datetime
    date_scanned: Optional[datetime]
    date_delivered: Optional[datetime]
    operator_initials: Optional[str]

    class Config:
        from_attributes = True


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
    rolls: List[RollRead] = []
    notes: Optional[str]

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
