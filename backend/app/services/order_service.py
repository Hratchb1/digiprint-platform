from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, table, column
from sqlalchemy.orm import selectinload
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timedelta
import logging

from app.models.orm import Order, Roll, OrderEvent, Store
from app.models.schemas import (
    OrderCreate, OrderStatusUpdate, DashboardStats
)

logger = logging.getLogger(__name__)

# Statuses that free up twin checks for reuse — terminal order states only
TWIN_EXPIRY_STATUSES = {"delivered", "cancelled", "discarded"}

# Order statuses considered "in progress" for dashboard pending/overdue counts
PENDING_STATUSES = ["booked_in", "scanning"]

# SKUs that set addon service flags on orders
ADDON_SKU_FLAGS = {
    "177426": "border_scan",
    "177427": "contact_sheet",
    "177428": "rebate_scan",
}


class OrderService:

    async def create_order(self, db: AsyncSession, payload: OrderCreate, actor_label: str = "system") -> Order:
        existing_twins = await self._get_existing_twins(db, payload.store_id)
        new_twins = [r.twin_check for r in payload.rolls]
        dups = [t for t in new_twins if t in existing_twins]
        if dups:
            raise ValueError(f"Twin checks already exist in this store: {', '.join(dups)}")

        # Guard: if an inbound order already exists with this order_number, promote
        # it instead of inserting a duplicate. Covers any caller that doesn't go
        # through the dup-modal/add-rolls path in the Intake UI.
        existing_inbound = await self._get_inbound_order_by_number(db, payload.order_number, payload.store_id)
        if existing_inbound:
            for roll_data in payload.rolls:
                roll = Roll(
                    order_id=existing_inbound.id,
                    store_id=payload.store_id,
                    twin_check=roll_data.twin_check,
                    service_type=roll_data.service_type.value,
                    operator_initials=payload.operator_initials,
                )
                db.add(roll)

            await self._promote_inbound_to_booked_in(
                db, existing_inbound, actor_label=actor_label,
                roll_count=len(payload.rolls), source="create_order_guard",
            )
            await db.commit()
            await db.refresh(existing_inbound)
            return existing_inbound

        # Check pronto_cache for addon SKUs BEFORE creating the order
        # so the flags are set correctly in the initial API response
        addon_flags = self._get_addon_flags_from_pronto(payload.order_number)

        order = Order(
            order_number=payload.order_number,
            # Stamp the Pronto link so pronto_sync's dedup recognises this
            # sale and doesn't create a duplicate inbound row for it.
            pronto_order_number=payload.order_number,
            store_id=payload.store_id,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            phone_number=getattr(payload, "customer_phone", None),
            account=payload.account,
            order_type=payload.order_type.value,
            operator_initials=payload.operator_initials,
            notes=payload.notes,
            status="booked_in",
            booked_in_at=datetime.utcnow(),
            # Set addon flags directly on the ORM object
            border_scan=addon_flags.get("border_scan", False),
            contact_sheet=addon_flags.get("contact_sheet", False),
            rebate_scan=addon_flags.get("rebate_scan", False),
        )
        db.add(order)
        await db.flush()

        for roll_data in payload.rolls:
            roll = Roll(
                order_id=order.id,
                store_id=payload.store_id,
                twin_check=roll_data.twin_check,
                service_type=roll_data.service_type.value,
                operator_initials=payload.operator_initials,
            )
            db.add(roll)

        if any(addon_flags.values()):
            logger.info(
                f"[order_service] Order {payload.order_number} — addon flags set from Pronto: "
                f"border_scan={addon_flags.get('border_scan')}, "
                f"contact_sheet={addon_flags.get('contact_sheet')}, "
                f"rebate_scan={addon_flags.get('rebate_scan')}"
            )

        await self._log_event(db, order.id, "booked_in",
                              f"Order booked in with {len(payload.rolls)} roll(s)",
                              actor_label=actor_label,
                              metadata={"roll_count": len(payload.rolls), "twins": new_twins})
        await db.commit()
        await db.refresh(order)
        return order

    def _get_addon_flags_from_pronto(self, order_number: str) -> dict:
        """
        Synchronously check pronto_cache for addon SKUs (177426/177427/177428).
        Returns a dict of flag names to booleans.
        Called before order creation so flags are set in the initial response.
        """
        flags = {"border_scan": False, "contact_sheet": False, "rebate_scan": False}
        try:
            from supabase import create_client
            from app.core.config import settings

            client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
            result = client.table("pronto_cache").select(
                "sku_code"
            ).eq("sales_order_number", order_number).execute()

            if result.data:
                skus = {row["sku_code"] for row in result.data if row.get("sku_code")}
                flags["border_scan"]   = "177426" in skus
                flags["contact_sheet"] = "177427" in skus
                flags["rebate_scan"]   = "177428" in skus

        except Exception as e:
            logger.warning(f"[order_service] Could not check addon flags for {order_number}: {e}")

        return flags

    async def get_order(self, db: AsyncSession, order_id: UUID) -> Optional[Order]:
        result = await db.execute(
            select(Order)
            .options(selectinload(Order.rolls), selectinload(Order.events), selectinload(Order.store))
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_order_by_number(self, db: AsyncSession, order_number: str, store_id: Optional[UUID] = None) -> Optional[Order]:
        q = select(Order).where(Order.order_number == order_number)
        if store_id:
            q = q.where(Order.store_id == store_id)
        q = q.options(selectinload(Order.rolls), selectinload(Order.store))
        result = await db.execute(q)
        return result.scalar_one_or_none()

    async def _get_inbound_order_by_number(self, db: AsyncSession, order_number: str, store_id: UUID) -> Optional[Order]:
        result = await db.execute(
            select(Order)
            .options(selectinload(Order.rolls))
            .where(and_(
                Order.order_number == order_number,
                Order.store_id == store_id,
                Order.status == "inbound",
            ))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _promote_inbound_to_booked_in(
        self, db: AsyncSession, order: Order, actor_label: str = "system",
        roll_count: Optional[int] = None, source: str = "intake_form",
    ) -> None:
        """Promote an inbound order to booked_in and log the activity event."""
        order.status = "booked_in"
        order.booked_in_at = datetime.utcnow()
        await self._log_event(
            db, order.id, "order_booked_in",
            f"Inbound order promoted to booked_in"
            + (f" — {roll_count} roll(s) added" if roll_count else ""),
            actor_label=actor_label,
            metadata={"source": source, "roll_count": roll_count},
        )

    async def list_orders(
        self,
        db: AsyncSession,
        store_id: Optional[UUID] = None,
        statuses: Optional[List[str]] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        film_type: Optional[str] = None,
        twin: Optional[str] = None,
    ) -> List[Order]:
        q = (
            select(Order)
            .options(selectinload(Order.rolls), selectinload(Order.store))
            .order_by(Order.created_at.desc())
        )
        if store_id:
            q = q.where(Order.store_id == store_id)
        if statuses:
            q = q.where(Order.status.in_(statuses))
        if twin:
            q = q.where(Order.rolls.any(Roll.twin_check == twin.strip().zfill(4)))
        if film_type:
            # film_type lives on pronto_cache lines, not on orders —
            # match orders whose Pronto sales order contains that film type
            pronto_cache = table("pronto_cache", column("sales_order_number"), column("film_type"))
            subq = select(pronto_cache.c.sales_order_number).where(
                pronto_cache.c.film_type == film_type
            )
            q = q.where(Order.pronto_order_number.in_(subq))
        if search:
            q = q.where(or_(
                Order.order_number.ilike(f"%{search}%"),
                Order.pronto_order_number.ilike(f"%{search}%"),
                Order.customer_name.ilike(f"%{search}%"),
                Order.customer_email.ilike(f"%{search}%"),
            ))
        q = q.limit(limit).offset(offset)
        result = await db.execute(q)
        return result.scalars().all()

    async def _get_existing_twins(self, db: AsyncSession, store_id: UUID) -> set:
        result = await db.execute(
            select(Roll.twin_check).where(and_(Roll.store_id == store_id, Roll.status != "archived"))
        )
        return {row[0] for row in result.fetchall()}

    async def check_twin_exists(self, db: AsyncSession, store_id: UUID, twin_check: str) -> bool:
        result = await db.execute(
            select(Roll.id).where(and_(Roll.store_id == store_id, Roll.twin_check == twin_check, Roll.status != "archived")).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def update_order_status(self, db: AsyncSession, order_id: UUID, update: OrderStatusUpdate, actor_label: str = "system") -> Order:
        order = await self.get_order(db, order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        old_status = order.status
        new_status = update.status.value
        order.status = new_status

        if new_status == "delivered":
            order.date_delivered = datetime.utcnow()
            for roll in order.rolls:
                if roll.status not in ("blank", "archived"):
                    roll.status = "delivered"
                    roll.date_delivered = datetime.utcnow()

        # --- Twin check expiry ---
        if new_status in TWIN_EXPIRY_STATUSES:
            archived_twins = []
            for roll in order.rolls:
                if roll.status != "archived":
                    roll.status = "archived"
                    archived_twins.append(roll.twin_check)

            if archived_twins:
                await self._log_event(
                    db, order_id,
                    event_type="twin_checks_expired",
                    description=f"{len(archived_twins)} twin check(s) released for reuse (order reached '{new_status}')",
                    actor_label="system",
                    metadata={"released_twins": archived_twins, "triggered_by_status": new_status},
                )

        await self._log_event(db, order_id, "status_change",
                              f"Status changed: {old_status} to {new_status}",
                              actor_label=actor_label,
                              metadata={"from": old_status, "to": new_status})
        await db.commit()
        await db.refresh(order)
        return order

    async def reset_twin_checks(self, db: AsyncSession, order_id: UUID, actor_label: str = "system") -> Order:
        """Manually re-lock archived twin checks on an order. Admin only."""
        order = await self.get_order(db, order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        reset_twins = []
        for roll in order.rolls:
            if roll.status == "archived":
                roll.status = "booked"
                reset_twins.append(roll.twin_check)

        if not reset_twins:
            raise ValueError("No archived twin checks found on this order to reset")

        await self._log_event(
            db, order_id,
            event_type="twin_checks_reset",
            description=f"{len(reset_twins)} twin check(s) manually reset by admin",
            actor_label=actor_label,
            metadata={"reset_twins": reset_twins},
        )
        await db.commit()
        await db.refresh(order)
        return order

    async def mark_blanks(self, db: AsyncSession, order_id: UUID, roll_ids: List[UUID], actor_label: str = "system") -> Order:
        order = await self.get_order(db, order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        blank_twins = []
        for roll in order.rolls:
            if roll.id in roll_ids:
                roll.is_blank = True
                roll.status = "blank"
                roll.blank_confirmed_at = datetime.utcnow()
                blank_twins.append(roll.twin_check)

        order.has_blanks = True
        if all(r.is_blank for r in order.rolls):
            # "blank" is no longer a valid order-level status (migration 003) —
            # an all-blank order is terminal, so it maps to delivered.
            order.status = "delivered"
            order.date_delivered = datetime.utcnow()

        await self._log_event(db, order_id, "blanks_marked",
                              f"{len(blank_twins)} roll(s) marked blank",
                              actor_label=actor_label,
                              metadata={"blank_twins": blank_twins})
        await db.commit()
        await db.refresh(order)
        return order

    async def set_drive_link(self, db: AsyncSession, order_id: UUID, drive_url: str, actor_label: str = "system") -> Order:
        order = await self.get_order(db, order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        order.drive_order_folder_url = drive_url
        order.date_scanned = datetime.utcnow()
        if order.status == "booked_in":
            order.status = "scanning"

        await self._log_event(db, order_id, "drive_link_set", "Drive folder link set",
                              actor_label=actor_label, metadata={"url": drive_url})
        await db.commit()
        await db.refresh(order)
        return order

    async def get_dashboard_stats(self, db: AsyncSession, store_id: Optional[UUID] = None, period_days: int = 30) -> DashboardStats:
        since = datetime.utcnow() - timedelta(days=period_days)
        base_filter = [Order.created_at >= since]
        if store_id:
            base_filter.append(Order.store_id == store_id)

        total = await db.scalar(select(func.count(Order.id)).where(and_(*base_filter)))
        delivered = await db.scalar(select(func.count(Order.id)).where(and_(*base_filter, Order.status == "delivered")))
        pending = await db.scalar(select(func.count(Order.id)).where(and_(*base_filter, Order.status.in_(PENDING_STATUSES))))
        blanks = await db.scalar(select(func.count(Order.id)).where(and_(*base_filter, Order.has_blanks == True)))

        overdue_cutoff = datetime.utcnow() - timedelta(hours=48)
        overdue_filter = [Order.created_at < overdue_cutoff, Order.status.in_(PENDING_STATUSES)]
        if store_id:
            overdue_filter.append(Order.store_id == store_id)
        overdue = await db.scalar(select(func.count(Order.id)).where(and_(*overdue_filter)))

        avg_result = await db.scalar(
            select(func.avg(func.extract("epoch", Order.date_delivered - Order.created_at) / 3600))
            .where(and_(*base_filter, Order.date_delivered.isnot(None)))
        )

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_filter = [Order.created_at >= today_start]
        if store_id:
            today_filter.append(Order.store_id == store_id)
        orders_today = await db.scalar(select(func.count(Order.id)).where(and_(*today_filter)))
        rolls_today = await db.scalar(select(func.count(Roll.id)).join(Order).where(and_(*today_filter)))

        store_name = None
        if store_id:
            store = await db.get(Store, store_id)
            store_name = store.name if store else None

        return DashboardStats(
            store_id=store_id,
            store_name=store_name,
            period_days=period_days,
            total_orders=total or 0,
            delivered_orders=delivered or 0,
            pending_orders=pending or 0,
            overdue_orders=overdue or 0,
            blank_orders=blanks or 0,
            avg_turnaround_hours=float(avg_result) if avg_result else None,
            orders_today=orders_today or 0,
            rolls_today=rolls_today or 0,
        )

    async def _log_event(self, db: AsyncSession, order_id: UUID, event_type: str, description: str, actor_label: str = "system", metadata: dict = None):
        event = OrderEvent(
            order_id=order_id,
            event_type=event_type,
            description=description,
            actor_label=actor_label,
            event_data=metadata or {}
        )
        db.add(event)


order_service = OrderService()
