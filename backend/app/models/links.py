"""Pydantic models for co-coverage links between countries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.news import NewsArticle


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


class LinkEntity(BaseModel):
    """A person or organisation in several of a link's stories."""

    name: str
    type: Literal["person", "org"]
    n: int = Field(..., description="The link's stories that name it")


class LinkDetail(BaseModel):
    """What the link inspector shows for one pair of countries."""

    a: LinkCountry
    b: LinkCountry
    n: int
    lift: float
    topic_mix: dict[str, int] = Field(..., description="Stories per topic tag (may count twice)")
    tone: float
    shared: list[LinkEntity] = Field(..., description="Names in 2 or more of the stories, top 8")
    themes: list[str] = Field(..., description="The stories' top 5 GDELT themes, as words")
    articles: list[NewsArticle] = Field(..., description="The 10 newest distinct stories")


class LinkExplainRequest(BaseModel):
    """Which link to explain: two ISO codes and the window. Names are never taken from here."""

    a: str = Field(..., max_length=8)
    b: str = Field(..., max_length=8)
    start_time: str | None = Field(None, max_length=40)
    end_time: str | None = Field(None, max_length=40)
    topic: str | None = Field(None, max_length=20)


class LinkExplanation(BaseModel):
    """2-3 sentences on what a link's stories are about, or a message saying why not."""

    text: str
