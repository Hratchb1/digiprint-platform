"""
main.py — digiPrint Platform API
Run locally: uvicorn backend.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .routers import rolls, stores, b2b
from .db.database import engine
from .models import Base

# Create all tables on startup (safe to run multiple times)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="digiPrint Platform",
    description="Film processing & B2B order management for digiDirect",
    version="1.0.0",
)

# CORS — allow the frontend (React dev server or same-origin in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(rolls.router, prefix="/api")
app.include_router(stores.router, prefix="/api")
app.include_router(b2b.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "digiPrint Platform"}


# Serve the built frontend (for production / when running without a separate dev server)
frontend_build = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_build):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_build, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        return FileResponse(os.path.join(frontend_build, "index.html"))
