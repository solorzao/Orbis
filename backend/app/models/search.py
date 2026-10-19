"""Pydantic models for global search (/api/search): see services/search.py."""

from __future__ import annotations

from pydantic import BaseModel

from app.models.entities import EntityType


class EntityResult(BaseModel):
    type: EntityType
    name: str
    n: int  # distinct stories in the last 7 days, among the members read
    capped: bool  # the member cap was reached: more stories than n ("{n}+")


class ThreadResult(BaseModel):
    id: int
    title: str  # the AI title, else the lead story's headline


class SearchResults(BaseModel):
    """People, organisations and threads; places are searched client-side."""

    people: list[EntityResult]  # at most 5, most mentioned first
    orgs: list[EntityResult]
    threads: list[ThreadResult]  # at most 5, fastest first
