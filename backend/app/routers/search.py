"""API route for global search: people, organisations and story threads."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.middleware.security import strip_invisible
from app.models.search import SearchResults
from app.routers.http_cache import edge_cached
from app.services.cache import cached_model, get_cached, set_cached
from app.services.search import search

router = APIRouter(prefix="/api", tags=["search"])

# Results stay five minutes: counts move with each cycle, names rarely.
_SEARCH_TTL = 300

_MIN_Q, _MAX_Q = 2, 80


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/search", response_model=SearchResults, dependencies=[Depends(edge_cached)])
async def get_search(
    q: str = Query(..., max_length=400, description="2 to 80 characters"),
) -> SearchResults:
    """People and organisations named like *q*, by mentions this week, and story
    threads whose title or lead headline contains it: up to five of each.

    *q* is trimmed and its invisible characters dropped; it is matched as
    text (LIKE wildcards included). Places are searched client-side.
    """
    q = " ".join(strip_invisible(q).split())
    if not _MIN_Q <= len(q) <= _MAX_Q:
        raise HTTPException(status_code=422, detail="q must be 2 to 80 characters")

    cache_k = f"db:search:v1:{q.lower()}"
    cached = await get_cached(cache_k)
    found = None if cached is None else cached_model(cache_k, cached, SearchResults.model_validate)
    if found is not None:
        return found

    results = SearchResults(**await search(q, _now()))
    await set_cached(cache_k, results.model_dump(), _SEARCH_TTL)
    return results
