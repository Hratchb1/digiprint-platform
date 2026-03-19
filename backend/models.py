"""
models.py — SQLAlchemy ORM models for digiPrint platform
Mirrors the existing Google Sheet schema exactly, plus adds multi-store and B2B support.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text,
    ForeignKey, Enum as SAEnum, func
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────

class ServiceType(str, enum.Enum):
    dev_only        = "Dev only"
    dev_scan        = "Dev+Scan"
    dev_scan_print  = "Dev+Scan+Print"
    dev_print       = "Dev+Print"
    scan_only       = "Scan only"
    print_only      = "Print only"


class RollStatus(str, enum.Enum):
    booked      = "Booked"
    processing  = "Processing"
    scanned     = "Scanned"
    delivered   = "Delivered"
    blank       = "Blank"
    print_ready = "PrintReady"
    archived    = "Archived"


class EmailStatus(str, enum.Enum):
    pending         = "Pending"
    sent            = "Sent"
    resent          = "Resent"
    paused          = "Paused"
    missing_email   = "Missing Email"
    missing_order   = "Missing Order"
    skipped         = "Skipped"


# ─────────────────────────────────────────
# STORES
# ─────────────────────────────────────────

class Store(Base):
    """One row per physical store. Config lives here, not hardcoded."""
    __tablename__ = "stores"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    name            = Column(String(100), nullable=False, unique=True)   # e.g. "Bondi"
    label           = Column(String(150), nullable=False)                # e.g. "digiDirect Bondi"
    reply_to        = Column(String(200))                                # lab.bondi@digidirect.com.au
    drive_root_id   = Column(String(200))                                # Google Drive root folder ID
    drive_inbox_id  = Column(String(200))                                # Inbox folder ID
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=func.now())

    rolls           = relationship("Roll", back_populates="store")
    b2b_orders      = relationship("B2BOrder", back_populates="store")


# ─────────────────────────────────────────
# ROLLS (Film orders — mirrors Sheets schema)
# ─────────────────────────────────────────

class Roll(Base):
    """
    One row = one film roll/twin.
    Multiple rolls can share the same order_number (batch orders).
    """
    __tablename__ = "rolls"

    id              = Column(Integer, primary_key=True, autoincrement=True)

    # ── Identifiers ──
    store_id        = Column(Integer, ForeignKey("stores.id"), nullable=False)
    order_number    = Column(String(100), nullable=False, index=True)
    twin_check      = Column(String(10), nullable=False)    # 4-digit padded e.g. "0042"

    # ── Customer ──
    customer_name   = Column(String(200), nullable=False)
    customer_email  = Column(String(200))
    account         = Column(String(200))                   # B2B account name from Pronto

    # ── Service ──
    service_type    = Column(String(50), default=ServiceType.dev_scan)
    operator        = Column(String(50))

    # ── Status ──
    status          = Column(String(50), default=RollStatus.booked)
    blank_flag      = Column(Boolean, default=False)
    print_only_flag = Column(Boolean, default=False)

    # ── Drive ──
    drive_order_folder_url = Column(Text)

    # ── Email tracking ──
    email_status                = Column(String(100))
    blank_email_status          = Column(String(100))
    print_ready_email_status    = Column(String(100))

    # ── Timestamps ──
    timestamp               = Column(DateTime, default=func.now())
    date_scanned            = Column(DateTime)
    date_delivered          = Column(DateTime)
    date_print_ready_notified = Column(DateTime)
    updated_at              = Column(DateTime, default=func.now(), onupdate=func.now())

    # ── Relationships ──
    store           = relationship("Store", back_populates="rolls")
    events          = relationship("RollEvent", back_populates="roll", cascade="all, delete-orphan")


class RollEvent(Base):
    """Audit trail — every status change or email send is logged here."""
    __tablename__ = "roll_events"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    roll_id     = Column(Integer, ForeignKey("rolls.id"), nullable=False)
    event_type  = Column(String(100), nullable=False)   # e.g. "status_change", "email_sent"
    detail      = Column(Text)                          # JSON or free text
    operator    = Column(String(50))
    created_at  = Column(DateTime, default=func.now())

    roll        = relationship("Roll", back_populates="events")


# ─────────────────────────────────────────
# B2B ORDERS
# ─────────────────────────────────────────

class Vendor(Base):
    """Photographers, galleries, studios — B2B clients."""
    __tablename__ = "vendors"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    name            = Column(String(200), nullable=False)
    email           = Column(String(200))
    phone           = Column(String(50))
    pixieset_id     = Column(String(200))               # Pixieset vendor/client ID
    notes           = Column(Text)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=func.now())

    orders          = relationship("B2BOrder", back_populates="vendor")


class B2BOrder(Base):
    """A vendor/gallery order — flows into same production queue."""
    __tablename__ = "b2b_orders"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    store_id        = Column(Integer, ForeignKey("stores.id"), nullable=False)
    vendor_id       = Column(Integer, ForeignKey("vendors.id"))

    # ── Reference ──
    order_reference = Column(String(200), nullable=False, index=True)
    pixieset_order_id = Column(String(200))             # from Pixieset webhook

    # ── Status ──
    status          = Column(String(50), default="Received")   # Received, Batched, In Production, QC, Fulfilled
    priority        = Column(String(20), default="Normal")     # Normal, Rush, Scheduled

    # ── Product / fulfilment ──
    product_type    = Column(String(100))               # e.g. "Fine Art Print", "Canvas", "Photo Book"
    quantity        = Column(Integer, default=1)
    notes           = Column(Text)

    # ── Tracking ──
    received_at     = Column(DateTime, default=func.now())
    batched_at      = Column(DateTime)
    fulfilled_at    = Column(DateTime)
    updated_at      = Column(DateTime, default=func.now(), onupdate=func.now())

    store           = relationship("Store", back_populates="b2b_orders")
    vendor          = relationship("Vendor", back_populates="orders")
