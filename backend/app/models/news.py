"""Pydantic models for news articles, clusters, and globe data points."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """A single geolocated news article."""

    id: str
    title: str
    summary: str | None = None
    source_url: str
    source_name: str
    source_language: str = "en"
    published_at: datetime
    ingested_at: datetime
    latitude: float
    longitude: float
    country_code: str = ""
    region: str = ""
    topic_tags: list[str] = Field(default_factory=list)
    sentiment_score: float = 0.0
    entities: dict = Field(default_factory=dict)


class NewsCluster(BaseModel):
    """A spatial cluster of related articles."""

    center_lat: float
    center_lng: float
    articles: list[NewsArticle]
    topic: str
    avg_sentiment: float


class GlobeDataPoint(BaseModel):
    """Lightweight point for rendering on the 3-D globe."""

    lat: float
    lng: float
    weight: float
    article_count: int
    top_headline: str
    topic: str
    location_name: str = ""


class ClusterSummaryResponse(BaseModel):
    """Response payload for the /api/news/summary endpoint."""

    lat: float
    lng: float
    article_count: int
    summary: str


class TopicCount(BaseModel):
    """A topic with its article count."""

    topic: str
    count: int


class HourlyDensity(BaseModel):
    """Article count for a single hour bucket."""

    hour: int
    count: int


class SelectionSummaryRequest(BaseModel):
    """Request body for summarizing a user-selected set of articles."""

    headlines: list[str] = Field(..., min_length=1, max_length=10)
    location_name: str | None = Field(None, max_length=100)


class SelectionSummaryResponse(BaseModel):
    """Response payload for the selection summary endpoint."""

    summary: str
    article_count: int
