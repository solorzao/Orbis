"""Pydantic models for the investigation board (/api/board): see services/board.py."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.services.board import MAX_ITEMS, MAX_NAME

# The longest id: "entity:person:" and a 200-character name.
ItemId = Annotated[str, StringConstraints(max_length=len("entity:person:") + MAX_NAME)]


class BoardItems(BaseModel):
    """Pins, in board order: 1 to 20 distinct item ids."""

    items: list[ItemId] = Field(..., min_length=1, max_length=MAX_ITEMS)


class BoardSnapshot(BaseModel):
    """What a pin is, from server data: enough to show it once its data has expired."""

    title: str  # a headline, place, "A and B", thread title or name
    place: str | None = None  # where: the story's place, a thread's first, a name's top
    lat: float | None = None
    lng: float | None = None
    time: datetime | None = None  # a story's; a place's newest; a thread's last
    url: str | None = None  # an article's link: http(s) only


class ResolvedItem(BaseModel):
    item: str
    snapshot: BoardSnapshot | None  # null: unknown, or expired (purged after 7 days)


class BoardResolution(BaseModel):
    items: list[ResolvedItem]  # in the request's order
