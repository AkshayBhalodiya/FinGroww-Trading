"""
FinGroww Trading Intelligence — FastAPI SaaS Master Application (ASGI).
Run directly via: uvicorn backend.app:app --host 127.0.0.1 --port 8787
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import db_manager
from backend.routers import admin, auth, billing_academy, dashboard, journal, paper_v2, users
from backend.wsgi_bridge import WSGIToASGI


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_manager.init()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/v2/docs",
    redoc_url="/api/v2/redoc",
    openapi_url="/api/v2/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register FastAPI v2 Routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(dashboard.router)
app.include_router(paper_v2.router)
app.include_router(journal.router)
app.include_router(admin.router)
app.include_router(billing_academy.router)


@app.get("/api/v2/health", tags=["System"])
def v2_health():
    return {
        "ok": True,
        "engine": "FastAPI + Pydantic v2",
        "version": settings.APP_VERSION,
        "db_mode": db_manager.mode,
        "collections_registered": len(db_manager._local_store),
    }


# Mount existing Flask WSGI app for zero-breakage legacy endpoints & static HTML files
try:
    import fingroww_market_server as legacy_srv
    app.mount("/", WSGIToASGI(legacy_srv.app))
except Exception:
    pass
