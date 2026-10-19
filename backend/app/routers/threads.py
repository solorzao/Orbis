"""API routes for story threads: the same developing story across outlets and places."""

from __future__ import annotations

import asyncio
import functools
import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.models.threads import ThreadDetail, ThreadSummary
from app.routers.http_cache import edge_cached
from app.routers.news import _globe_topic_tag
from app.services.cache import cycle_ttl, get_cached, set_cached
from app.services.thread_reads import LIST_HOURS, list_threads, thread_detail

router = APIRouter(prefix="/api", tags=["threads"])

# How long thread answers stay cached: at least until the next cycle ends
# (cycle_ttl). Each ingestion reassigns threads and invalidates db:*, and
# app.warm refills the default list.
_THREADS_TTL = 300

# The timeline's live presets (frontend LiveHours, thread_reads.LIST_HOURS); any
# other timespan is a 422.
_LIVE_HOURS = frozenset(LIST_HOURS)

# The threads rail's first request.
DEFAULT_HOURS = 24
DEFAULT_LIMIT = 20

# The furthest a detail pages: 50 pages of 20 stories.
_MAX_OFFSET = 1000

# Seconds the shared list query may take: the pool sets no command timeout,
# so a hung query would otherwise hold every later miss for its key.
_LIST_QUERY_TIMEOUT = 15

# The list query running for each cache key: misses that arrive while it runs
# wait for it rather than run their own.
_list_in_flight: dict[str, asyncio.Task[list[ThreadSummary]]] = {}

Timespan = Annotated[str, Query(description="A live window: 1h, 6h, 24h or 168h")]
Topic = Annotated[
    str | None,
    Query(
        description="Topic pill: Politics, Conflict, Technology, Climate, Economy, Health or All"
    ),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hours(timespan: str) -> int:
    match = re.fullmatch(r"(\d{1,3})h", timespan.strip().lower())
    hours = int(match.group(1)) if match else 0
    if hours not in _LIVE_HOURS:
        raise HTTPException(status_code=422, detail="timespan must be 1h, 6h, 24h or 168h.")
    return hours


@router.get("/threads", response_model=list[ThreadSummary], dependencies=[Depends(edge_cached)])
async def get_threads(
    timespan: Timespan = "24h",
    topic: Topic = None,
    limit: Annotated[int, Query(ge=1, le=50, description="Most threads to return")] = DEFAULT_LIMIT,
) -> list[ThreadSummary]:
    """Developing stories: threads seen in the window with at least 3 stories from at
    least 3 outlets, fastest first (stories in the last 6 hours), then the biggest.

    A thread is one story's coverage across outlets and places, assigned at
    ingestion from the headlines' embeddings: its status is emerging (first
    seen within 6 hours), developing (2 or more stories in the last 6 hours)
    or fading.
    """
    hours = _hours(timespan)
    tag = _globe_topic_tag(topic)
    return await cached_threads(hours, tag, limit)


async def cached_threads(hours: int, tag: str | None, limit: int) -> list[ThreadSummary]:
    """/api/threads' answer: cached, else computed once (concurrent misses share the
    query, and its error: nothing is cached then) and cached until the next cycle.

    The request and the warmer both come here, so a warmed entry has the key
    and the bytes a request would have stored.
    """
    cache_k = f"db:threads:list:v1:{hours}h:{tag or ''}:{limit}"
    cached = await get_cached(cache_k)
    if cached is not None:  # [] is a cached answer too
        return [ThreadSummary.model_validate(t) for t in cached]

    task = _list_in_flight.get(cache_k)
    if task is None:
        task = asyncio.create_task(_load_threads(cache_k, hours, tag, limit))
        _list_in_flight[cache_k] = task
        task.add_done_callback(functools.partial(_landed, cache_k))
    return await asyncio.shield(task)


async def _load_threads(
    cache_k: str, hours: int, tag: str | None, limit: int
) -> list[ThreadSummary]:
    async with asyncio.timeout(_LIST_QUERY_TIMEOUT):
        rows = await list_threads(_now(), hours, tag, limit)
    threads = [ThreadSummary.model_validate(r) for r in rows]
    await set_cached(cache_k, [t.model_dump(mode="json") for t in threads], cycle_ttl(_THREADS_TTL))
    return threads


def _landed(cache_k: str, task: asyncio.Task) -> None:
    """Forget a finished list query, so the next miss runs a new one."""
    if _list_in_flight.get(cache_k) is task:
        del _list_in_flight[cache_k]


async def warm_threads() -> None:
    """Cache the threads rail's first request: 24 hours, all topics, 20 (app.warm)."""
    await cached_threads(DEFAULT_HOURS, None, DEFAULT_LIMIT)


@router.get(
    "/threads/{thread_id}", response_model=ThreadDetail, dependencies=[Depends(edge_cached)]
)
async def get_thread(
    thread_id: Annotated[int, Path(ge=1, le=2**63 - 1, description="A thread's id")],
    offset: Annotated[
        int, Query(ge=0, le=_MAX_OFFSET, description="Stories to skip, 20 a page")
    ] = 0,
) -> ThreadDetail:
    """One thread: its list fields, its top people and organisations (counted per
    story), every place it reached in first-report order, its hourly stories and
    tone, and its stories newest first, 20 a page. 404 for an unknown id."""
    cache_k = f"db:threads:detail:v1:{thread_id}:{offset}"
    cached = await get_cached(cache_k)
    if cached is not None:
        return ThreadDetail.model_validate(cached)

    detail = await thread_detail(thread_id, offset, _now())
    if detail is None:
        raise HTTPException(status_code=404, detail="No such thread.")
    result = ThreadDetail.model_validate(detail)
    await set_cached(cache_k, result.model_dump(mode="json"), cycle_ttl(_THREADS_TTL))
    return result
