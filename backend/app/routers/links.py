"""API routes for co-coverage links between countries."""

from __future__ import annotations

import functools
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.links import Link, LinkDetail, LinkExplainRequest, LinkExplanation
from app.routers.http_cache import edge_cached, retry_shortly
from app.routers.news import _deduplicate_articles, _globe_topic_tag, _parse_iso, _row_to_article
from app.services.ai_summary import _window_key
from app.services.cache import (
    WEEK_TTL,
    FlightCancelled,
    cached_model,
    cycle_ttl,
    get_cached,
    set_cached,
    single_flight,
    week_fresh,
)
from app.services.country_centroids import centroid
from app.services.links import explain_link, get_link_detail, get_link_pairs, rank_links

router = APIRouter(prefix="/api", tags=["links"])

# How long links stay cached: ingestion invalidates db:* keys every cycle anyway.
_LINKS_TTL = 600
# An empty window is cached briefly, so new stories show soon.
_EMPTY_LINKS_TTL = 60

# The timeline's live presets (frontend LiveHours); any other timespan is a 422.
_LIVE_HOURS = frozenset({1, 6, 24, 168})

# The longest range: the timeline's 7 days straddle 8 UTC days.
_MAX_RANGE = timedelta(days=8)

# Stories the link inspector lists.
_DETAIL_ARTICLES = 10

Timespan = Annotated[str, Query(description="A live window: 1h, 6h, 24h or 168h")]
StartTime = Annotated[str | None, Query(description="A range's ISO start, with end_time")]
EndTime = Annotated[str | None, Query(description="A range's ISO end, with start_time")]
Topic = Annotated[
    str | None,
    Query(
        description="Topic pill: Politics, Conflict, Technology, Climate, Economy, Health or All"
    ),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Window(NamedTuple):
    start: datetime
    end: datetime
    key: str  # for cache keys: live:{hours}, or the range floored to the hour


def _window(timespan: str, start_time: str | None, end_time: str | None) -> Window:
    """The window's bounds and cache-key part, as the frontend's TimeWindow allows them.

    A range needs both bounds, as ISO 8601 times, in order and at most 8 days
    apart. Otherwise the window is live: one of the timeline's presets, the
    last that many hours up to now. Anything else is a 422.
    """
    if start_time is not None or end_time is not None:
        start, end = _parse_iso(start_time), _parse_iso(end_time)
        if start is None or end is None:
            raise HTTPException(
                status_code=422,
                detail="A range needs start_time and end_time, both ISO 8601 times.",
            )
        if start >= end:
            raise HTTPException(status_code=422, detail="start_time must be before end_time.")
        if end - start > _MAX_RANGE:
            raise HTTPException(status_code=422, detail="A range spans at most 8 days.")
        return Window(start, end, _window_key(start, end))
    match = re.fullmatch(r"(\d{1,3})h", timespan.strip().lower())
    hours = int(match.group(1)) if match else 0
    if hours not in _LIVE_HOURS:
        raise HTTPException(status_code=422, detail="timespan must be 1h, 6h, 24h or 168h.")
    now = _now()
    return Window(now - timedelta(hours=hours), now, f"live:{hours}")


def _pair(a: str, b: str) -> tuple[str, str]:
    """Two different ISO codes (any case) that have label points, uppercased, or a 422."""
    codes = []
    for code in (a, b):
        iso = code.strip().upper()
        if centroid(iso) is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown country {code!r}: an ISO 3166-1 alpha-2 code with a label point.",
            )
        codes.append(iso)
    if codes[0] == codes[1]:
        raise HTTPException(status_code=422, detail="a and b must be different countries.")
    return codes[0], codes[1]


# What /api/links ranks by and returns when the request does not say.
DEFAULT_RANK = "lift"
DEFAULT_LIMIT = 40


@router.get("/links", response_model=list[Link], dependencies=[Depends(edge_cached)])
async def get_links(
    timespan: Timespan = "24h",
    start_time: StartTime = None,
    end_time: EndTime = None,
    topic: Topic = None,
    rank: Annotated[
        Literal["lift", "count"],
        Query(description="lift: surprisingly often together; count: most stories"),
    ] = DEFAULT_RANK,
    limit: Annotated[int, Query(ge=1, le=60, description="Most links to return")] = DEFAULT_LIMIT,
) -> list[Link]:
    """Pairs of countries the window's stories cover together, for arcs on the globe.

    A story links its own country with each other country it mentions. At
    most 6 links per country, so hubs do not take every slot.
    """
    tag = _globe_topic_tag(topic)
    window = _window(timespan, start_time, end_time)
    return await cached_links(window, tag, rank, limit)


# The 7-day window's cache-key part: its answers are week-long entries.
_WEEK_WINDOW = "live:168"


def _links_key(window: Window, tag: str | None, rank: str, limit: int) -> str:
    """The 7-day window's under wk:, which no cycle invalidates (see
    cache.WEEK_TTL), the others under db:."""
    return _key_for(window.key, tag, rank, limit)


def _key_for(window_key: str, tag: str | None, rank: str, limit: int) -> str:
    prefix = "wk" if window_key == _WEEK_WINDOW else "db"
    return f"{prefix}:links:v5:{window_key}:{tag or ''}:{rank}:{limit}"


# The default 7-day answer's key: its age gates warm_links_7d (cache.week_fresh).
_LINKS_WEEK_GATE = _key_for(_WEEK_WINDOW, None, DEFAULT_RANK, DEFAULT_LIMIT)


def _parse_links(cached: list) -> list[Link]:
    return [Link.model_validate(link) for link in cached]


async def cached_links(window: Window, tag: str | None, rank: str, limit: int) -> list[Link]:
    """/api/links' answer for the window: cached, else computed and cached.

    The request and the cache warmers both come here, so a warmed entry has
    the key and the bytes a request would have stored. An entry that no
    longer fits Link is a miss. The 7-day window's answers are week-long
    entries (wk:*, refreshed hourly by warm_links_7d); a miss there is
    computed once for concurrent requests.
    """
    cache_k = _links_key(window, tag, rank, limit)
    cached = await get_cached(cache_k)
    if cached is not None:  # [] is a cached empty window
        links = cached_model(cache_k, cached, _parse_links)
        if links is not None:
            return links

    load = functools.partial(_load_links, cache_k, window, tag, rank, limit)
    if window.key != _WEEK_WINDOW:
        return await load()
    try:
        return await single_flight(cache_k, load)
    except FlightCancelled as stopped:  # at a cycle's boundary: a 503 to retry
        raise retry_shortly(stopped) from None


async def _load_links(
    cache_k: str, window: Window, tag: str | None, rank: str, limit: int
) -> list[Link]:
    """Compute the window's links and cache them: a week's for WEEK_TTL, others
    until the next cycle ends. An empty answer briefly, so new stories show soon;
    but an empty week other than the default's (the warm's gate, which must not
    read as fresh) for WEEK_TTL, or each request for it would read the week."""
    rows = await get_link_pairs(window.start, window.end, tag)
    links = [Link.model_validate(link) for link in rank_links(rows, rank, limit, tag)]

    week = window.key == _WEEK_WINDOW
    if links:
        ttl = WEEK_TTL if week else cycle_ttl(_LINKS_TTL)
    elif week and cache_k != _LINKS_WEEK_GATE:
        ttl = WEEK_TTL
    else:
        ttl = _EMPTY_LINKS_TTL
    await set_cached(cache_k, [link.model_dump(by_alias=True) for link in links], ttl)
    return links


async def warm_links_24h() -> None:
    """Cache the default 24-hour /api/links answer (app.warm, after each ingestion cycle)."""
    await cached_links(_window("24h", None, None), None, DEFAULT_RANK, DEFAULT_LIMIT)


def _default_7d() -> tuple[Window, None, str, int]:
    """The default 7-day /api/links request: the one warm_links_7d caches and
    cached_links_7d reads, so the two always name the same key."""
    return _window("168h", None, None), None, DEFAULT_RANK, DEFAULT_LIMIT


async def warm_links_7d() -> None:
    """Refresh the default 7-day /api/links answer about hourly (app.warm).

    Nothing while it is fresh (cache.week_fresh: under 55 minutes old), so most
    cycles skip it: each refresh reads the week's stories (12-27 s, and past
    30 s, on production). Joins a computation a request's miss has started; the
    warm's timeout, or a stop (stop_background_tasks), cancels it.
    """
    window, tag, rank, limit = _default_7d()
    cache_k = _links_key(window, tag, rank, limit)
    if await week_fresh(cache_k):
        return
    load = functools.partial(_load_links, cache_k, window, tag, rank, limit)
    await single_flight(cache_k, load, cancel_with_caller=True)


async def cached_links_7d() -> list[Link] | None:
    """The default 7-day /api/links answer when it is cached (warm_links_7d refreshes
    it hourly), else None. Never computed here: the board's co-coverage edges read
    it, and skip themselves rather than run the 7-day query."""
    cache_k = _links_key(*_default_7d())
    cached = await get_cached(cache_k)
    return None if cached is None else cached_model(cache_k, cached, _parse_links)


Country = Annotated[str, Query(max_length=8, description="ISO 3166-1 alpha-2 code")]


@router.get("/links/detail", response_model=LinkDetail, dependencies=[Depends(edge_cached)])
async def get_link(
    a: Country,
    b: Country,
    timespan: Timespan = "24h",
    start_time: StartTime = None,
    end_time: EndTime = None,
    topic: Topic = None,
) -> LinkDetail:
    """One link for the inspector: its numbers, shared names, themes and newest stories.

    The window and topic are validated as for /api/links, so the inspector's
    n and lift match the arc's. The pair comes back in code order, as
    /api/links has it, so either order shares one cache entry.
    """
    a, b = sorted(_pair(a, b))
    tag = _globe_topic_tag(topic)
    window = _window(timespan, start_time, end_time)

    cache_k = f"db:links:detail:v11:{a}:{b}:{window.key}:{tag or ''}"
    cached = await get_cached(cache_k)
    found = None if cached is None else cached_model(cache_k, cached, LinkDetail.model_validate)
    if found is not None:
        return found

    detail = await get_link_detail(a, b, window.start, window.end, tag)
    # One row per story already; this merges what story_key cannot: copies
    # written before ingestion stored it, whose outlet suffixes differ.
    stories = _deduplicate_articles([_row_to_article(r) for r in detail["articles"]])
    result = LinkDetail(**{**detail, "articles": stories[:_DETAIL_ARTICLES]})
    await set_cached(cache_k, result.model_dump(mode="json"), _LINKS_TTL)
    return result


@router.post("/links/explain", response_model=LinkExplanation)
async def explain(body: LinkExplainRequest) -> LinkExplanation:
    """2-3 sentences from Claude on what the stories linking two countries are about.

    The window is validated as for /api/links: a range (both bounds), else
    the live timespan (24h by default), so an arc explains its own window.
    Only the codes, window and topic are read from the request; the prompt
    is built from server-side data.
    """
    a, b = _pair(body.a, body.b)
    tag = _globe_topic_tag(body.topic)
    window = _window(body.timespan, body.start_time, body.end_time)
    return LinkExplanation(text=await explain_link(a, b, window.start, window.end, tag))
