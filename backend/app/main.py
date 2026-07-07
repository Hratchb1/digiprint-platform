# app/main.py
import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.core.config import get_settings
from app.api import auth, orders, stores, dashboard, refund_warnings
from app.api.rolls import router as rolls_router
from app.api.pronto import router as pronto_router
from app.api.drive import router as drive_router
from app.api.emails import router as emails_router
from app.services.pronto_sync import sync_pronto_cache
from app.services.drive_watcher import run_drive_watcher

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="digiPrint Operations API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(rolls_router, prefix="/api")
app.include_router(stores.router, prefix="/api")
app.include_router(pronto_router, prefix="/api")
app.include_router(drive_router, prefix="/api")
app.include_router(emails_router, prefix="/api")
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(refund_warnings.router, prefix="/api/refund-warnings", tags=["refund_warnings"])
# Underscore alias — the Phase 3 spec references both spellings
app.include_router(refund_warnings.router, prefix="/api/refund_warnings", include_in_schema=False)

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    # Run Pronto sync immediately on startup
    asyncio.create_task(sync_pronto_cache())

    # Pronto sync every 10 minutes
    scheduler.add_job(
        sync_pronto_cache,
        trigger=IntervalTrigger(minutes=10),
        id="pronto_sync",
        name="Pronto cache sync",
        replace_existing=True,
    )

    # Drive watcher every 5 minutes
    scheduler.add_job(
        run_drive_watcher,
        trigger=IntervalTrigger(minutes=5),
        id="drive_watcher",
        name="Drive folder watcher",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[startup] Scheduler started — Pronto sync every 10min, Drive watcher every 5min")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)

@app.get("/")
async def root():
    return {"service": "digiPrint Operations API", "version": "1.0.0", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "ok"}