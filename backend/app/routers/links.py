"""API routes for co-coverage links between countries."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.links import Link
from app.routers.http_cache import edge_cached
from app.routers.news import _globe_topic_tag, _parse_iso
from app.services.ai_summary import _window_key
from app.services.cache import get_cached, set_cached
from app.services.links import get_link_pairs, rank_links

router = APIRouter(prefix="/api", tags=["links"])

# How long links stay cached: ingestion invalidates db:* keys every cycle anyway.
_LINKS_TTL = 600
# An empty window is cached briefly, so new stories show soon.
_EMPTY_LINKS_TTL = 60

# The timeline's live presets (frontend LiveHours); any other timespan is a 422.
_LIVE_HOURS = frozenset({1, 6, 24, 168})

# The longest range: the timeline's 7 days straddle 8 UTC days.
_MAX_RANGE = timedelta(days=8)

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


@router.get("/links", response_model=list[Link], dependencies=[Depends(edge_cached)])
async def get_links(
    timespan: Timespan = "24h",
    start_time: StartTime = None,
    end_time: EndTime = None,
    topic: Topic = None,
    rank: Annotated[
        Literal["lift", "count"],
        Query(description="lift: surprisingly often together; count: most stories"),
    ] = "lift",
    limit: Annotated[int, Query(ge=1, le=60, description="Most links to return")] = 40,
) -> list[Link]:
    """Pairs of countries the window's stories cover together, for arcs on the globe.

    A story links its own country with each other country it mentions. At
    most 6 links per country, so hubs do not take every slot.
    """
    tag = _globe_topic_tag(topic)
    window = _window(timespan, start_time, end_time)

    cache_k = f"db:links:v1:{window.key}:{tag or ''}:{rank}:{limit}"
    cached = await get_cached(cache_k)
    if cached is not None:  # [] is a cached empty window
        return [Link.model_validate(link) for link in cached]

    rows = await get_link_pairs(window.start, window.end, tag)
    links = [Link.model_validate(link) for link in rank_links(rows, rank, limit, tag)]

    ttl = _LINKS_TTL if links else _EMPTY_LINKS_TTL
    await set_cached(cache_k, [link.model_dump(by_alias=True) for link in links], ttl)
    return links
