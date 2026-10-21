"""API route for entity dossiers: a person or organisation in the news."""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.middleware.security import strip_invisible
from app.models.entities import EntityDossier, EntityType
from app.routers.http_cache import edge_cached
from app.services.cache import cached_model, cycle_ttl, get_cached, set_cached
from app.services.entities import get_entity_dossier, resolve_entity

router = APIRouter(prefix="/api", tags=["entities"])

# Dossiers stay at least until the next cycle ends (cycle_ttl): ingestion
# invalidates db:* as each cycle ends.
_ENTITY_TTL = 300

_MAX_NAME = 200

# The dossier being computed for each cache key: misses that arrive while it
# runs (the same name in any case, say) wait for it rather than run their own.
_dossier_in_flight: dict[str, asyncio.Task[EntityDossier | None]] = {}

# Seconds the shared computation may take (the pool sets no command timeout).
_DOSSIER_QUERY_TIMEOUT = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get(
    "/entities/{entity_type}/{name:path}",
    response_model=EntityDossier,
    dependencies=[Depends(edge_cached)],
)
async def get_entity(
    entity_type: EntityType,
    name: str,
    timespan: Literal["24h", "168h"] = Query("168h", description="24h or 168h"),
) -> EntityDossier:
    """Where and how a person or organisation is in the news over the window.

    *name* matches a graph name of that type exactly, in any case (404
    otherwise), and its stored spelling is used from then on. Stories are
    read from thread members, up to a cap, newest first; ``capped`` says when
    the window holds more. See services/entities.py.
    """
    name = " ".join(strip_invisible(name).split())
    if not 1 <= len(name) <= _MAX_NAME:
        raise HTTPException(status_code=422, detail="name must be 1 to 200 characters")

    cache_k = f"db:entity:v1:{entity_type}:{name.lower()}:{timespan}"
    cached = await get_cached(cache_k)
    found = None if cached is None else cached_model(cache_k, cached, EntityDossier.model_validate)
    if found is not None:
        return found

    task = _dossier_in_flight.get(cache_k)
    if task is None:
        task = asyncio.create_task(_load_dossier(cache_k, entity_type, name, timespan))
        _dossier_in_flight[cache_k] = task
        task.add_done_callback(functools.partial(_landed, cache_k))
    dossier = await asyncio.shield(task)
    if dossier is None:
        raise HTTPException(status_code=404, detail="No person or organisation of that name")
    return dossier


async def _load_dossier(
    cache_k: str, entity_type: str, name: str, timespan: str
) -> EntityDossier | None:
    """Resolve the name, then compute and cache its dossier; None (uncached) if unknown."""
    now = _now()
    async with asyncio.timeout(_DOSSIER_QUERY_TIMEOUT):
        stored = await resolve_entity(entity_type, name, now)
        if stored is None:
            return None
        raw = await get_entity_dossier(stored, entity_type, timespan, now)
    dossier = EntityDossier(**raw)
    await set_cached(cache_k, dossier.model_dump(mode="json"), cycle_ttl(_ENTITY_TTL))
    return dossier


def _landed(cache_k: str, task: asyncio.Task) -> None:
    """Forget a finished dossier computation, so the next miss runs a new one."""
    if _dossier_in_flight.get(cache_k) is task:
        del _dossier_in_flight[cache_k]
