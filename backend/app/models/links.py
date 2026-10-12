"""Pydantic models for co-coverage links between countries."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LinkCountry(BaseModel):
    """One end of a link: a country and its label point."""

    iso: str = Field(..., description="ISO 3166-1 alpha-2")
    name: str
    lat: float
    lng: float


class Link(BaseModel):
    """Two countries covered together by the window's stories."""

    model_config = ConfigDict(populate_by_name=True)

    a: LinkCountry
    b: LinkCountry
    n: int = Field(..., description="Stories from one country that mention the other")
    lift: float = Field(..., description="How much more often than chance: n * N / (n_a * n_b)")
    topic: str = Field(..., description="The stories' most common topic tag, or the filter's")
    tone: float = Field(..., description="Mean sentiment of the stories, -1 to 1")
    from_: str = Field(..., alias="from", description="The country most of them come from")
