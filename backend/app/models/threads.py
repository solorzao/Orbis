"""Story threads (/api/threads): the same developing story across outlets and places."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.news import GlobeLead


class ThreadPlace(BaseModel):
    """A 1-degree cell the thread reached: its first report there."""

    lat: float
    lng: float
    place: str  # display_place of that report's region and country_code
    country_code: str = ""
    first_seen: datetime  # the cell's first report
    n: int  # distinct stories in the cell


class ThreadSummary(BaseModel):
    """A listed thread (/api/threads)."""

    id: int
    title: str  # the AI title (PR 15c), else the lead story's headline
    synopsis: str | None = None  # null until PR 15c
    # emerging: first seen within 6 hours; developing: 2+ stories in the last
    # 6 hours; otherwise fading.
    status: Literal["emerging", "developing", "fading"]
    first_seen: datetime
    last_seen: datetime
    n_stories: int
    n_sources: int
    velocity: int  # distinct stories in the last 6 hours
    countries: list[str] = Field(default_factory=list)
    places: list[ThreadPlace] = Field(default_factory=list)  # up to 20, first report first
    topic: str  # the dominant topic among its stories ("general" if none)
    lead: GlobeLead | None = None  # null when its article is no longer kept


class ThreadEntity(BaseModel):
    name: str
    n: int  # distinct stories naming it


class ThreadHour(BaseModel):
    hour: datetime  # the UTC hour's start
    n: int  # distinct stories first filed in it
    tone: float | None = None  # their mean tone


class ThreadArticle(BaseModel):
    title: str  # display_title: one clean headline
    source_name: str
    published_at: datetime
    source_url: str
    place: str


class ThreadDetail(ThreadSummary):
    """One thread (/api/threads/{id}): the list item, plus its people and spread."""

    entities: list[ThreadEntity] = Field(default_factory=list)  # top 12
    spread: list[ThreadPlace] = Field(default_factory=list)  # every place kept (up to 30)
    timeline: list[ThreadHour] = Field(default_factory=list)  # hours with stories, in order
    articles: list[ThreadArticle] = Field(default_factory=list)  # 20 stories, newest first
