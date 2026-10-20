"""API routes for the investigation board: pins resolved, edges between them, a memo.

The board lives in the visitor's browser (localStorage); these routes only
read. Every item id is parsed strictly before any query (services/board.py),
and a malformed or repeated one is a 422.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models.board import BoardItems, BoardResolution, ResolvedItem
from app.services.board import BoardItem, parse_items, resolve_items

router = APIRouter(prefix="/api/board", tags=["board"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(raws: list[str]) -> list[BoardItem]:
    try:
        return parse_items(raws)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


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
