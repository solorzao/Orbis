"""Caches refilled after each ingestion cycle, so visitors get hits, not cold queries.

Each cycle invalidates every ``db:*`` key, and on a quiet site the edge
entry has usually expired too, so the first visitor after a cycle waited
for whatever they asked for: 3.9 s for the globe, 4.7 s for the links
layer's 7-day window, on production. ``WARMERS`` ask for those answers the
way the frontend's first visit does (the same code path and cache key),
one at a time to spare the database, each within WARM_TIMEOUT seconds. A
warmer that fails or times out is logged and skipped.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.routers.links import warm_links_7d, warm_links_24h
from app.routers.news import warm_breaking, warm_globe, warm_volume
from app.routers.threads import warm_threads
from app.services.cache import get_redis

logger = logging.getLogger("orbis.warm")

Warmer = Callable[[], Awaitable[object]]

# Run in order: the first visit's globe and timeline (24 hours, all topics),
# then the links layer's default windows, then breaking stories (one list for
# every topic: the ticker's, and the delta's count), then the threads rail's
# default list (24 hours, all topics, 20). Another endpoint's warmer joins here.
WARMERS: tuple[Warmer, ...] = (
    warm_globe,
    warm_volume,
    warm_links_24h,
    warm_links_7d,
    warm_breaking,
    warm_threads,
)

# Seconds each warmer may take.
WARM_TIMEOUT = 30


async def warm_caches(warmers: tuple[Warmer, ...] = WARMERS, timeout: float = WARM_TIMEOUT) -> None:
    """Run each warmer in turn, logging how long each and all took. Never raises.

    Without Redis (none configured, or unreachable) there is nothing to
    fill, so nothing runs.
    """
    if await get_redis() is None:
        logger.info("Cache warm skipped: no Redis.")
        return
    began = time.monotonic()
    warmed = 0
    for warmer in warmers:
        name = getattr(warmer, "__name__", repr(warmer))
        started = time.monotonic()
        try:
            await asyncio.wait_for(warmer(), timeout)
        except TimeoutError:
            logger.warning("Cache warm %s timed out after %s s; continuing.", name, timeout)
        except Exception:
            logger.warning(
                "Cache warm %s failed after %.2f s; continuing.",
                name,
                time.monotonic() - started,
                exc_info=True,
            )
        else:
            warmed += 1
            logger.info("Cache warm %s took %.2f s.", name, time.monotonic() - started)
    logger.info("Cache warm: %d of %d in %.2f s.", warmed, len(warmers), time.monotonic() - began)
