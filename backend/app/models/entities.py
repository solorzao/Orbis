"""Pydantic models for entity dossiers (/api/entities): see services/entities.py."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["person", "org"]


class EntityCounts(BaseModel):
    """Distinct stories naming the entity, among every match (never capped)."""

    h24: int
    d7: int


class EntityCountry(BaseModel):
    country_code: str  # ISO 3166-1 alpha-2
    n: int  # distinct stories


class EntityPlace(BaseModel):
    """A 1° cell the entity's stories come from."""

    lat: float  # the cell's newest story's
    lng: float
    place: str  # display_place of that story's region and country_code
    country_code: str
    n: int  # distinct stories in the cell
    tone: float  # their mean sentiment, -1 to 1


class TimelineBucket(BaseModel):
    t: datetime  # the bucket's start: an hour (24h) or a day (168h)
    n: int  # distinct stories published in it


class CoMention(BaseModel):
    """A person or organisation that appears in the same coverage (untyped: thread
    members record names only)."""

    name: str
    n: int  # stories naming both, among the capped members


class EntityHeadline(BaseModel):
    title: str  # display_title
    source_name: str
    published_at: datetime
    source_url: str
    place: str


class EntityDossier(BaseModel):
    """A person or organisation in the news over a window (24h or 168h)."""

    name: str  # as the graph spells it
    type: EntityType
    counts: EntityCounts
    trend: float | None = Field(
        ..., description="Stories in the last 24 h over the 24 h before; null if none before"
    )
    capped: bool = Field(
        ...,
        description="The window has more members than the cap: places, timeline, co-mentions "
        "and headlines are from the newest",
    )
    cap: int
    countries: list[EntityCountry]  # most stories first, among every match in the window
    places: list[EntityPlace]  # at most 12, most stories first
    timeline: list[TimelineBucket]  # 24 hourly or 7 daily buckets, oldest first
    co_mentions: list[CoMention]  # at most 15
    headlines: list[EntityHeadline]  # the 10 newest stories
    since: datetime | None = Field(
        ..., description="The earliest thread member of all: data starts here (the ramp)"
    )
