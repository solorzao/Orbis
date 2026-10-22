"""API routes for relations between countries, from GDELT's reported events.

Every answer is the 7-day lens (the last 7 UTC days), whatever window the
timeline shows: there are no window parameters, and any sent are ignored. The
answers read only the daily rollups, which each cycle's events step adds to,
so they live under db:*, which the cycle invalidates as it ends: the list and
every pair's detail refresh together, and app.warm refills the default list.
Their TTL (cache.WEEK_TTL) is only a backstop. The days in the keys move them
at UTC midnight.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.relations import Relation, RelationDetail, Relations
from app.routers.http_cache import edge_cached, retry_shortly
from app.routers.links import Country, _pair
from app.services.cache import (
    WEEK_TTL,
    FlightCancelled,
    cached_model,
    get_cached,
    set_cached,
    single_flight,
)
from app.services.relations import (
    get_relation_detail,
    get_relation_pairs,
    get_since,
    lens_days,
    rank_relations,
)

router = APIRouter(prefix="/api", tags=["relations"])

# The layer's first request (frontend useRelations: every class, RELATIONS_LIMIT),
# the one warm_relations caches.
DEFAULT_KIND = "all"
DEFAULT_LIMIT = 40
# An empty list briefly, as #108's links do (_EMPTY_LINKS_TTL), so new rollups show soon.
_EMPTY_TTL = 60
NOT_FOUND = "No reported events between them in the last 7 days."
Kind = Annotated[
    Literal["all", "cooperation", "conflict"],
    Query(description="Which reported events: all, cooperation (quad 1-2) or conflict (3-4)"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days(first: date, last: date) -> str:
    return f"{first:%Y%m%d}-{last:%Y%m%d}"


@router.get("/relations", response_model=Relations, dependencies=[Depends(edge_cached)])
async def get_relations(
    kind: Kind = DEFAULT_KIND,
    limit: Annotated[
        int, Query(ge=1, le=60, description="Most relations to return")
    ] = DEFAULT_LIMIT,
) -> Relations:
    """Pairs of countries in GDELT's reported events over the last 7 UTC days.

    Machine-coded from news reports (not verified): who did what to whom, as
    reported.
    """
    return await cached_relations(kind, limit)


async def cached_relations(kind: str, limit: int) -> Relations:
    """/api/relations' answer: cached, else computed once for concurrent callers
    and cached.

    The request and warm_relations both come here, so a warmed entry has the
    key and the bytes a request would have stored. An entry that no longer
    fits Relations is a miss.
    """
    first, last = lens_days(_now())
    key = f"db:relations:v1:{_days(first, last)}:{kind}:{limit}"
    cached = await get_cached(key)
    if cached is not None:
        found = cached_model(key, cached, Relations.model_validate)
        if found is not None:
            return found

    async def load() -> Relations:
        rows = await get_relation_pairs(first, last, kind)
        result = Relations(
            first_day=first,
            last_day=last,
            since=await get_since(first, last),
            relations=[Relation.model_validate(r) for r in rank_relations(rows, kind, limit)],
        )
        ttl = WEEK_TTL if result.relations else _EMPTY_TTL
        await set_cached(key, result.model_dump(mode="json", by_alias=True), ttl)
        return result

    try:
        return await single_flight(key, load)
    except FlightCancelled as stopped:  # at shutdown: a 503 to retry
        raise retry_shortly(stopped) from None


async def warm_relations() -> None:
    """Cache the Relations layer's first request: every class, 40 (app.warm, after
    each ingestion cycle)."""
    await cached_relations(DEFAULT_KIND, DEFAULT_LIMIT)


@router.get("/relations/detail", response_model=RelationDetail, dependencies=[Depends(edge_cached)])
async def get_relation(a: Country, b: Country) -> RelationDetail:
    """One pair's reported events over the last 7 UTC days, for the inspector.

    Every class and both directions, whatever the list's class switch says,
    each of the lens's days, and sample first reports. No thresholds: a pair
    with any events has a detail. The pair comes back in code order, so
    either order shares one cache entry. A pair with no events is a 404, not
    cached.
    """
    a, b = sorted(_pair(a, b))
    first, last = lens_days(_now())
    key = f"db:relations:detail:v1:{a}:{b}:{_days(first, last)}"
    cached = await get_cached(key)
    if cached is not None:
        found = cached_model(key, cached, RelationDetail.model_validate)
        if found is not None:
            return found

    async def load() -> RelationDetail:
        detail = await get_relation_detail(a, b, first, last)
        if detail is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        result = RelationDetail.model_validate(detail)
        await set_cached(key, result.model_dump(mode="json", by_alias=True), WEEK_TTL)
        return result

    try:
        return await single_flight(key, load)
    except FlightCancelled as stopped:  # at shutdown: a 503 to retry
        raise retry_shortly(stopped) from None
