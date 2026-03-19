from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.orm import Store
from app.models.schemas import StoreRead, DashboardStats
from app.services.order_service import order_service

router = APIRouter(tags=["stores & dashboard"])


@router.get("/stores", response_model=list[StoreRead])
async def list_stores(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Store).where(Store.is_active == True).order_by(Store.name))
    return result.scalars().all()


@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(
    store_id: Optional[UUID] = Query(None),
    period_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get stats for dashboard. Master admins can query all stores or a specific one.
    Store staff/admins always see their own store.
    """
    if current_user.get("role") != "master_admin":
        store_id = UUID(current_user["store_id"]) if current_user.get("store_id") else store_id

    return await order_service.get_dashboard_stats(db, store_id, period_days)
