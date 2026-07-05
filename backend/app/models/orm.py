from sqlalchemy import (
    Column, String, Boolean, Text, DateTime, ForeignKey,
    Integer, Float, ARRAY, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.core.database import Base


class Store(Base):
    __tablename__ = "stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False, unique=True)
    label = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    drive_root_folder_id = Column(Text)
    drive_inbox_folder_id = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    orders = relationship("Order", back_populates="store")
    users = relationship("User", back_populates="store")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    full_name = Column(Text, nullable=False)
    initials = Column(Text)
    role = Column(Text, nullable=False, default="staff")
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True))

    store = relationship("Store", back_populates="users")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    email = Column(Text)
    phone = Column(Text)
    account = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number = Column(Text, nullable=False)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"))

    customer_name = Column(Text, nullable=False)
    customer_email = Column(Text)
    phone_number = Column(Text)
    account = Column(Text)

    order_type = Column(Text, nullable=False, default="film")
    status = Column(Text, nullable=False, default="booked_in")

    drive_order_folder_url = Column(Text)
    scan_link = Column(Text)

    email_status = Column(Text, default="")
    blank_email_status = Column(Text, default="")
    print_ready_email_status = Column(Text, default="")

    is_print_only = Column(Boolean, default=False)
    has_blanks = Column(Boolean, default=False)

    # --- Manual entry flag ---
    # True when order was booked manually (Pronto not available)
    # False (default) for all Pronto-synced orders
    manual_entry = Column(Boolean, default=False)

    # --- Border / add-on scan flags ---
    border_scan = Column(Boolean, default=False)
    contact_sheet = Column(Boolean, default=False)
    rebate_scan = Column(Boolean, default=False)
    border_scan_status = Column(Text, default=None)
    bordered_scans_drive_url = Column(Text, default=None)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    date_scanned = Column(DateTime(timezone=True))
    date_delivered = Column(DateTime(timezone=True))
    date_print_ready_notified = Column(DateTime(timezone=True))

    # --- Inbound pipeline status timestamps (migration 003) ---
    booked_in_at = Column(DateTime(timezone=True))

    operator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    operator_initials = Column(Text)
    notes = Column(Text)

    store = relationship("Store", back_populates="orders")
    rolls = relationship("Roll", back_populates="order", cascade="all, delete-orphan")
    events = relationship("OrderEvent", back_populates="order", cascade="all, delete-orphan")


class Roll(Base):
    __tablename__ = "rolls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)

    twin_check = Column(Text, nullable=False)
    service_type = Column(Text, nullable=False, default="Dev+Scan")
    status = Column(Text, nullable=False, default="booked")

    is_blank = Column(Boolean, default=False)
    blank_confirmed_at = Column(DateTime(timezone=True))
    blank_notified_at = Column(DateTime(timezone=True))

    drive_folder_name = Column(Text)
    drive_folder_url = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    date_scanned = Column(DateTime(timezone=True))
    date_delivered = Column(DateTime(timezone=True))

    operator_initials = Column(Text)

    order = relationship("Order", back_populates="rolls")


class OrderEvent(Base):
    __tablename__ = "order_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    roll_id = Column(UUID(as_uuid=True), ForeignKey("rolls.id"))
    event_type = Column(Text, nullable=False)
    description = Column(Text)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    actor_label = Column(Text)
    event_data = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="events")


class RollAuditLog(Base):
    __tablename__ = "roll_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    roll_id = Column(UUID(as_uuid=True), ForeignKey("rolls.id", ondelete="CASCADE"), nullable=False)
    field_name = Column(Text, nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False, unique=True)
    contact_name = Column(Text)
    email = Column(Text)
    phone = Column(Text)
    pixieset_gallery_url = Column(Text)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    releases = relationship("VendorRelease", back_populates="vendor")


class VendorRelease(Base):
    __tablename__ = "vendor_releases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    release_name = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    pixieset_gallery_url = Column(Text)
    total_items = Column(Integer, default=0)
    completed_items = Column(Integer, default=0)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    due_date = Column(DateTime(timezone=True))
    dispatched_at = Column(DateTime(timezone=True))

    vendor = relationship("Vendor", back_populates="releases")
