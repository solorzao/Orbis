"""Orbis API — 3-D globe news explorer backend."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.middleware.security import AccessLogPathFilter, SecurityMiddleware, route_template
from app.routers.agent import router as agent_router
from app.routers.board import router as board_router
from app.routers.entities import router as entities_router
from app.routers.http_cache import RETRY_AFTER_SECONDS
from app.routers.links import router as links_router
from app.routers.news import router as news_router
from app.routers.relations import router as relations_router
from app.routers.search import router as search_router
from app.routers.threads import router as threads_router
from app.services.cache import close_redis, get_redis, open_redis
from app.services.database import close_pool, get_pool, open_pool
from app.services.ingestion import run_ingestion_cycle, stop_background_tasks, stop_cycle_task
from app.services.scheduler import start_scheduler, stop_scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger("orbis")
# Uvicorn's access log, where a launch keeps it on (the container turns it off;
# log_requests below logs each request): no query string, no entity name.
logging.getLogger("uvicorn.access").addFilter(AccessLogPathFilter())
# httpx logs each outbound request's URL whole at INFO, query string included,
# and the scraper's URLs can come from a visitor's question (read_article).
# httpx2, the anthropic and openai SDKs' client, logs its requests the same way.
# httpcore and httpcore2 log at DEBUG only, connection details: kept quiet too.
for _name in ("httpx", "httpcore", "httpx2", "httpcore2"):
    logging.getLogger(_name).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run startup as the server starts and shutdown as it stops (both below),
    also when the server's lifespan task is cancelled instead."""
    await startup()
    try:
        yield
    finally:
        await shutdown()


app = FastAPI(title="Orbis API", version="0.1.0", lifespan=lifespan)

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
app.include_router(relations_router)
app.include_router(threads_router)
app.include_router(agent_router)
app.include_router(search_router)
app.include_router(entities_router)
app.include_router(board_router)


# ---------------------------------------------------------------------------
# Lifecycle events (run by lifespan, above)
# ---------------------------------------------------------------------------
# Startup's ingestion cycle, held so shutdown can stop it (stop_initial_ingest).
_initial_ingest_task: asyncio.Task | None = None


async def startup() -> None:
    """Warm up connections and kick off the GDELT ingestion pipeline."""
    global _initial_ingest_task
    logger.info("Starting Orbis API …")
    logger.info("Daily Claude budget: $%.2f (UTC day).", settings.llm_daily_budget_usd)
    # Open: also after a shutdown closed them, the app started again in one process.
    await open_redis()
    await open_pool()

    # Run one immediate ingestion so the DB has data, then start the
    # periodic scheduler.  In a task of its own so startup isn't blocked.
    async def _initial_ingest():
        count = await run_ingestion_cycle()
        logger.info("Initial ingestion complete: %d articles.", count)

    _initial_ingest_task = asyncio.create_task(_initial_ingest())
    start_scheduler()


async def stop_initial_ingest() -> None:
    """Cancel startup's ingestion cycle if it is still running, and wait until it stops,
    a bounded time (stop_cycle_task); a cancel of the caller propagates.

    A replica shut down during its first cycle ran it on past close_pool, to fail
    there ("Ingestion cycle failed." at ERROR) with its closing db:* invalidation a
    no-op. Cancelled, the cycle's transactions roll back (the events step's advisory
    lock, a transaction's, with them), its connections go back to the pool before
    close_pool, and it starts no cache warm.
    """
    global _initial_ingest_task
    task, _initial_ingest_task = _initial_ingest_task, None
    if task is not None and not task.done():
        await stop_cycle_task(task, "Initial ingestion")


async def shutdown() -> None:
    """Stop ingestion and background work, then release connections on shutdown."""
    logger.info("Shutting down Orbis API …")
    # A cycle still running (the scheduler's, or startup's first) would reach Redis
    # and the pool once closed: both stop first, so neither starts a cache warm
    # after the background tasks have stopped.
    await stop_scheduler()
    await stop_initial_ingest()
    # A cache warm or a week read still running would reach Redis or the pool once
    # closed: every one stops here. One that lands later still (breaking's query,
    # shielded, runs on for its requests) finds them closed, and never opens them again.
    await stop_background_tasks(shutdown=True)
    await close_redis()
    await close_pool()


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, route, status and response time for every request. The route as
    declared (``/api/entities/{entity_type}/{name:path}``), or ``unmatched``, never
    the path as sent: no query string, entity name or forged newline (route_template)."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1f ms)",
        request.method,
        route_template(request),
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
def raised_at(exc: BaseException) -> str:
    """Where *exc* was raised, as ``module:line``: the innermost frame of the app's own
    code in its traceback (an asyncio.timeout's innermost is asyncio's, the same for
    every route), else the innermost of all. The code's place, never data."""
    frames = [
        (frame.f_globals.get("__name__") or os.path.basename(frame.f_code.co_filename), line)
        for frame, line in traceback.walk_tb(exc.__traceback__)
    ]
    ours = [(module, line) for module, line in frames if module.split(".")[0] == "app"]
    module, line = (ours or frames or [("unknown", 0)])[-1]
    return f"{module}:{line}"


@app.exception_handler(TimeoutError)
async def timed_out(request: Request, exc: TimeoutError) -> JSONResponse:
    """A route's query or call that ran out of time, unhandled there: a 503 the client
    retries after Retry-After, not a 500 and a traceback (the breaking query's, 110
    in four days before its route answered 503 itself). Answered inside the
    middleware, so log_requests logs the 503; nothing of the error in the body.
    One line names the route as declared (route_template), never the path or query
    as sent, and where the timeout came from: the error's type and the code's
    place (raised_at), never its message. A CancelledError is no TimeoutError: a
    cancelled request stays one."""
    logger.warning(
        "%s %s timed out (%s at %s); answered 503.",
        request.method,
        route_template(request),
        type(exc).__name__,
        raised_at(exc),
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Timed out; retry shortly."},
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )


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
