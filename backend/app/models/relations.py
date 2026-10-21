"""Pydantic models for relations between countries, from GDELT's reported events.

Events are machine-coded from news reports, not verified facts, and one report
can yield several events. Every answer is the 7-day lens: the last 7 UTC days.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.links import LinkCountry


class QuadCounts(BaseModel):
    """Reported events by QuadClass: all four, zeros included."""

    verbal_cooperation: int = Field(..., description="Reported events coded verbal cooperation")
    material_cooperation: int = Field(..., description="Reported events coded material cooperation")
    verbal_conflict: int = Field(..., description="Reported events coded verbal conflict")
    material_conflict: int = Field(..., description="Reported events coded material conflict")


class Relation(BaseModel):
    """Two countries in the lens's reported events (machine-coded, not verified)."""

    model_config = ConfigDict(populate_by_name=True)

    a: LinkCountry = Field(..., description="The pair's first country, in code order")
    b: LinkCountry = Field(..., description="The pair's second country, in code order")
    n: int = Field(..., description="Reported events between them, either direction")
    outlets: int = Field(..., description="Distinct outlets among the events' first reports")
    mentions: int = Field(..., description="Mentions in the 15 minutes each event was first seen")
    quad: QuadCounts
    kind: Literal["cooperation", "conflict"] = Field(
        ..., description="The class most of the reported events fall in, or the class filter's"
    )
    goldstein: float = Field(
        ..., description="Mean Goldstein scale, -10 to 10: an event-type score, not a magnitude"
    )
    tone: float = Field(..., description="Mean tone of the first reports, -100 to 100")
    from_: str = Field(
        ...,
        alias="from",
        description="The country whose actors act in most of the reported events (the arc's start)",
    )


class Relations(BaseModel):
    """/api/relations: the pairs over the 7-day lens."""

    first_day: date = Field(..., description="The lens's first UTC day (today - 6)")
    last_day: date = Field(..., description="The lens's last UTC day (today)")
    since: date | None = Field(
        ...,
        description="The earliest day the lens has reported events for; later than first_day "
        "only while the rollups are newer than a week; null with none",
    )
    relations: list[Relation]


class RelationDirection(BaseModel):
    """One direction of a pair: the reported events in which *from*'s actors act on *to*."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(..., alias="from", description="The acting country")
    to: str = Field(..., description="The country acted upon")
    n: int = Field(..., description="Reported events in this direction")
    quad: QuadCounts


class RelationDay(BaseModel):
    """One UTC day of the lens: reported events by class."""

    day: date
    cooperation: int = Field(..., description="Reported events coded cooperation (quad 1-2)")
    conflict: int = Field(..., description="Reported events coded conflict (quad 3-4)")


class RelationReport(BaseModel):
    """A first report some of the pair's events were coded from."""

    model_config = ConfigDict(populate_by_name=True)

    url: str = Field(..., description="The first report's address (http(s) only)")
    outlet: str = Field(..., description="The outlet's host")
    title: str | None = Field(..., description="Its headline, when we hold that article; else null")
    day: date = Field(..., description="The UTC day GDELT added the events")
    quad_class: int = Field(
        ...,
        ge=1,
        le=4,
        description="1 verbal cooperation, 2 material cooperation, 3 verbal conflict, "
        "4 material conflict",
    )
    from_: str = Field(..., alias="from", description="The acting country in those events")


class RelationDetail(Relation):
    """/api/relations/detail: one pair over the lens, every class, both directions."""

    first_day: date = Field(..., description="The lens's first UTC day (today - 6)")
    last_day: date = Field(..., description="The lens's last UTC day (today)")
    since: date | None = Field(
        ..., description="The earliest day the lens has reported events for, as in the list"
    )
    directions: list[RelationDirection] = Field(
        ..., description="a to b first, then b to a: only those with reported events"
    )
    daily: list[RelationDay] = Field(..., description="Each of the lens's 7 days, zeros included")
    samples: list[RelationReport] = Field(
        ..., description="Up to 10 distinct first reports, newest day first"
    )
