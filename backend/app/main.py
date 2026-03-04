"""Orbis API — 3-D globe news explorer backend."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.routers.news import router as news_router
from app.services.cache import close_redis, get_redis, invalidate
from app.services.database import close_pool, get_pool

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
        "http://localhost:3000",
        "https://*.vercel.app",
        "https://orbisapp.co",
        "https://www.orbisapp.co",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers.
app.include_router(news_router)


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup() -> None:
    """Warm up Redis, database, and GDELT cache on startup."""
    logger.info("Starting Orbis API …")
    await get_redis()
    await get_pool()

    # Flush old AI summaries so updated prompt takes effect
    await invalidate("summary:*")
    # Flush stale globe cache so improved fallback query runs fresh
    await invalidate("gdelt:geo:*")

    # Pre-warm the globe news cache so first request is instant
    import asyncio
    from app.services.gdelt import fetch_geo_points

    async def _warm_cache():
        try:
            points = await fetch_geo_points(query="sourcelang:english", timespan="24h")
            logger.info("Cache warm-up complete: %d globe points loaded.", len(points))
        except Exception:
            logger.warning("Cache warm-up failed — first request will be slower.", exc_info=True)

    asyncio.create_task(_warm_cache())


@app.on_event("shutdown")
async def shutdown() -> None:
    """Release Redis and database connections on shutdown."""
    logger.info("Shutting down Orbis API …")
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
