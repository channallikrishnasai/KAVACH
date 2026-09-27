"""
CrisisFlow Backend — Unified server.
Runs STGCN Digital Twin (from api.py) + MongoDB CRUD on a SINGLE port.

Start with:  python main.py
"""
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import connect_db, close_db, create_indexes, get_db
from seed import seed_database

# Import the STGCN router (this triggers model loading at import time)
from api import stgcn_router
from kavach_core import kavach_router

from routers import (
    resources,
    zones,
    dispatches,
    alerts,
    citizen_reports,
    incidents,
    hospitals,
    road_blocks,
    dashboard,
    triage,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the local KAVACH demo even when optional MongoDB is unavailable."""
    import traceback
    demo_mode = os.getenv("KAVACH_DEMO_MODE", "true").lower() in {"1", "true", "yes", "on"}
    app.state.database_status = "starting"
    try:
        await connect_db()
        await create_indexes()
        from database import db
        await seed_database(db)
        app.state.database_status = "connected"
        print("[KAVACH] MongoDB connected and legacy collections initialized")
    except Exception as e:
        if not demo_mode:
            print(f"[KAVACH] Required MongoDB startup failed: {e}")
            traceback.print_exc()
            raise
        print(f"[KAVACH] MongoDB unavailable; opening local in-memory persistence for demo mode: {e}")
        import database
        if database.client:
            database.client.close()
        try:
            from mongomock_motor import AsyncMongoMockClient
            database.client = AsyncMongoMockClient()
            database.db = database.client[database.DATABASE_NAME]
            await create_indexes()
            await seed_database(database.db)
            app.state.database_status = "simulated_memory"
            print("[KAVACH] In-memory Mongo-compatible demo store ready (resets on restart; not production data)")
        except Exception as fallback_error:
            database.client = None
            database.db = None
            app.state.database_status = "unavailable"
            print(f"[KAVACH] Memory persistence unavailable; core command service remains active: {fallback_error}")
    try:
        print("[KAVACH] Command service ready; external actions remain local and approval-gated")
        yield
    finally:
        if app.state.database_status == "connected":
            await close_db()


app = FastAPI(
    title="KAVACH City Guardian API",
    description="Local-first emergency coordination for Bengaluru with explicit provider provenance.",
    version="1.0.0-demo",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("KAVACH_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── STGCN Digital Twin routes (from api.py) ──
app.include_router(stgcn_router)
app.include_router(kavach_router)

# ── MongoDB CRUD routes ──
app.include_router(resources.router)
app.include_router(zones.router)
app.include_router(dispatches.router)
app.include_router(alerts.router)
app.include_router(citizen_reports.router)
app.include_router(incidents.router)
app.include_router(hospitals.router)
app.include_router(road_blocks.router)
app.include_router(dashboard.router)
app.include_router(triage.router)

# ── Dashboard HTML ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"), media_type="text/html")

@app.get("/dashboard.js")
async def serve_dashboard_js():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.js"), media_type="application/javascript")

@app.get("/dashboard_app.js")
async def serve_dashboard_app_js():
    return FileResponse(os.path.join(BASE_DIR, "dashboard_app.js"), media_type="application/javascript")


@app.get("/")
async def root():
    return {
        "service": "KAVACH City Guardian",
        "version": "1.0.0",
        "docs": "/docs",
        "stgcn_endpoints": {
            "simulate": "/simulate",
            "route": "/route",
            "route_nearest": "/route/nearest",
            "weather": "/weather",
            "geojson_buildings": "/geojson/buildings",
            "geojson_water": "/geojson/water",
        },
        "mongodb_endpoints": {
            "resources": "/api/resources",
            "zones": "/api/zones",
            "dispatches": "/api/dispatches",
            "alerts": "/api/alerts",
            "citizen_reports": "/api/citizen-reports",
            "incidents": "/api/incidents",
            "hospitals": "/api/hospitals",
            "road_blocks": "/api/road-blocks",
            "dashboards": "/api/dashboard/{role}",
            "triage": "/api/triage/run",
        },
    }


@app.get("/health")
async def health():
    from api import STGCN_STATUS
    database_status = getattr(app.state, "database_status", "starting")
    return {
        "status": "healthy" if database_status in {"connected", "simulated_memory"} else "degraded",
        "database": database_status,
        "stgcn": STGCN_STATUS,
        "prediction_provider": "STGCN" if STGCN_STATUS == "available" else "SIMULATION",
        "demo_mode": os.getenv("KAVACH_DEMO_MODE", "true").lower() in {"1", "true", "yes", "on"},
    }


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    print(f"[KAVACH] Starting local server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
# trigger reload
