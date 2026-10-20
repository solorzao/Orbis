"""API routes for the investigation board: pins resolved, edges between them, a memo.

The board lives in the visitor's browser (localStorage); these routes only
read. Every item id is parsed strictly before any query (services/board.py),
and a malformed or repeated one is a 422.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models.board import BoardEdge, BoardItems, BoardLinks, BoardResolution, ResolvedItem
from app.routers.links import cached_links_7d
from app.services.board import EDGE_KINDS, BoardItem, board_edges, parse_items, resolve_items
from app.services.cache import get_cached, set_cached

router = APIRouter(prefix="/api/board", tags=["board"])

# Edges stay cached this long per set of pins. Under db:*, so the end of each
# ingestion cycle clears them with the threads they're made of.
LINKS_TTL = 600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(raws: list[str]) -> list[BoardItem]:
    try:
        return parse_items(raws)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _digest(ids: list[str]) -> str:
    """A short cache-key part for a list of ids (they never hold a newline)."""
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


@router.post("/resolve", response_model=BoardResolution)
async def resolve(body: BoardItems) -> BoardResolution:
    """What each pin is now, from server data, in the request's order: a snapshot
    (title, place, lat/lng, time, http(s) url, as each kind has them), or null
    for an unknown or expired item. For share links and refreshing pins."""
    items = _parse(body.items)
    snapshots = await resolve_items(items, _now())
    return BoardResolution(
        items=[ResolvedItem(item=i.id, snapshot=s) for i, s in zip(items, snapshots)]
    )


@router.post("/links", response_model=BoardLinks)
async def links(body: BoardItems) -> BoardLinks:
    """The typed edges between pins: same_thread, shared_entity, same_place and
    co_covered (countries in a pair the 7-day /api/links list has). Each runs
    from the earlier pin in board order; they sort by pins, then kind.

    Cached for 10 minutes by the set of pins, whatever their order. When the
    7-day links list isn't cached, co_covered edges are skipped (never
    recomputed here), ``co_coverage_checked`` is false and nothing is cached.
    """
    items = _parse(body.items)
    by_id = sorted(items, key=lambda item: item.id)
    cache_k = "db:board:links:v1:" + _digest([item.id for item in by_id])
    cached = await get_cached(cache_k)
    if cached is not None:
        return BoardLinks(edges=_in_board_order(cached["edges"], items), co_coverage_checked=True)

    listed_links = await cached_links_7d()
    listed = (
        None
        if listed_links is None
        else {frozenset((link.a.iso, link.b.iso)) for link in listed_links}
    )
    edges = await board_edges(by_id, listed, _now())
    if listed is not None:
        await set_cached(cache_k, {"edges": edges}, LINKS_TTL)
    return BoardLinks(edges=_in_board_order(edges, items), co_coverage_checked=listed is not None)


def _in_board_order(edges: list[dict], items: list[BoardItem]) -> list[BoardEdge]:
    """*edges* turned to run from the earlier pin in board order, sorted by pins, then kind."""
    index = {item.id: n for n, item in enumerate(items)}
    turned = [
        edge if index[edge["a"]] < index[edge["b"]] else {**edge, "a": edge["b"], "b": edge["a"]}
        for edge in edges
    ]
    turned.sort(key=lambda e: (index[e["a"]], index[e["b"]], EDGE_KINDS.index(e["kind"])))
    return [BoardEdge(**edge) for edge in turned]
