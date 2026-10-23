"""Caches refilled after each ingestion cycle, so visitors get hits, not cold queries.

Each cycle invalidates every ``db:*`` key, and on a quiet site the edge
entry has usually expired too, so the first visitor after a cycle waited
for whatever they asked for: 3.9 s for the globe, 4.7 s for the links
layer's 7-day window, on production. ``WARMERS`` ask for those answers the
way the frontend's first visit does (the same code path and cache key; the
7-day globe's seven topics come from one pass, under their requests' keys),
one at a time to spare the database, each within WARM_TIMEOUT seconds or its
own WARMER_TIMEOUTS. A warmer that fails or times out is logged and skipped.
The 7-day window's globe and links are kept under ``wk:*`` instead, which no
cycle invalidates, and their warmers refresh them about hourly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping

from app.routers.links import warm_links_7d, warm_links_24h
from app.routers.news import warm_breaking, warm_globe, warm_globe_week, warm_volume
from app.routers.relations import warm_relations
from app.routers.threads import warm_threads
from app.services.cache import get_redis

logger = logging.getLogger("orbis.warm")

Warmer = Callable[[], Awaitable[object]]

# Run in order: the first visit's globe and timeline (24 hours, all topics),
# then the links layer's 24-hour window, then breaking stories (one list for
# every topic: the ticker's, and the delta's count; a miss before this refill
# gets the last good list, and the globe has no such fallback, so it stays
# first and breaking's 11-14 s query never holds it up), then the threads rail's
# default list (24 hours, all topics, 20), then the Relations layer's (every
# class, 40: its 7-day lens reads only the daily rollups, so it is under db:*
# and refilled each cycle, as the events step adds to them). Another
# endpoint's warmer joins there. Last, the two week reads: the 7-day links
# list and the 7-day globe for every topic pill. They refresh their wk:*
# entries (which no cycle invalidates) only once those are 55 minutes old
# (cache.week_fresh), so one cycle an hour runs them and the others skip them;
# run last, they never hold up the cycle's own warmers (links-7d's 26.5 s ran
# breaking past its 30 s on production, 2026-10-21).
WARMERS: tuple[Warmer, ...] = (
    warm_globe,
    warm_volume,
    warm_links_24h,
    warm_breaking,
    warm_threads,
    warm_relations,
    warm_links_7d,
    warm_globe_week,
)

# Seconds each warmer may take.
WARM_TIMEOUT = 30

# Warmers allowed longer, both reading the week's stories on a slow disk, about
# once an hour: the 7-day globe's one pass took 25-33 s on production, and the
# 7-day links warm 12-27 s, once past 30 s (2026-10-21). One cut off is
# cancelled, read and all; its entry, stored for 80 minutes and refreshed at
# 55, serves on for up to 25 more, and the next cycle's warm retries it.
WARMER_TIMEOUTS: dict[Warmer, float] = {warm_globe_week: 90, warm_links_7d: 90}


async def warm_caches(
    warmers: tuple[Warmer, ...] = WARMERS,
    timeout: float = WARM_TIMEOUT,
    timeouts: Mapping[Warmer, float] = WARMER_TIMEOUTS,
) -> None:
    """Run each warmer in turn, logging how long each and all took. Never raises.

    Each may take *timeout* seconds, or its own in *timeouts*.

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
        limit = timeouts.get(warmer, timeout)
        try:
            await asyncio.wait_for(warmer(), limit)
        except TimeoutError:
            logger.warning("Cache warm %s timed out after %s s; continuing.", name, limit)
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
