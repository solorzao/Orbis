"""Orbis API — 3-D globe news explorer backend."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.middleware.security import SecurityMiddleware
from app.routers.agent import router as agent_router
from app.routers.links import router as links_router
from app.routers.news import router as news_router
from app.services.cache import close_redis, get_redis
from app.services.database import close_pool, get_pool
from app.services.ingestion import run_ingestion_cycle, stop_background_tasks
from app.services.scheduler import start_scheduler, stop_scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger("orbis")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Orbis API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://orbisapp.co",
        "https://www.orbisapp.co",
    ],
    allow_origin_regex=r"https://orbis[a-z0-9-]*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security middleware (API key + rate limiting).
# Added after CORS so preflight responses include CORS headers.
app.add_middleware(SecurityMiddleware)

# Register routers.
app.include_router(news_router)
app.include_router(links_router)
app.include_router(agent_router)


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup() -> None:
    """Warm up connections and kick off the GDELT ingestion pipeline."""
    logger.info("Starting Orbis API …")
    logger.info("Daily Claude budget: $%.2f (UTC day).", settings.llm_daily_budget_usd)
    await get_redis()
    await get_pool()

    # Run one immediate ingestion so the DB has data, then start the
    # periodic scheduler.  Fire-and-forget so startup isn't blocked.
    import asyncio

    async def _initial_ingest():
        count = await run_ingestion_cycle()
        logger.info("Initial ingestion complete: %d articles.", count)

    asyncio.create_task(_initial_ingest())
    start_scheduler()


@app.on_event("shutdown")
async def shutdown() -> None:
    """Stop scheduler and release connections on shutdown."""
    logger.info("Shutting down Orbis API …")
    await stop_scheduler()
    # A cache warm still running would reopen Redis or the pool once closed.
    await stop_background_tasks()
    await close_redis()
    await close_pool()


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, path, and response time for every request."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Liveness / readiness probe — checks downstream services."""
    checks = {"api": "ok"}

    # Check database
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    # Check Redis
    try:
        r = await get_redis()
        if r:
            await r.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_configured"
    except Exception:
        checks["redis"] = "unavailable"

    all_ok = all(v in ("ok", "not_configured") for v in checks.values())
    status = "ok" if all_ok else "degraded"

    return JSONResponse(
        content={"status": status, "version": app.version, "checks": checks},
        status_code=200 if all_ok else 503,
    )
