"""API routes for news data, clusters, summaries, and topics."""

from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import APIRouter, Query

from app.models.news import (
    ClusterSummaryResponse,
    GlobeDataPoint,
    NewsArticle,
    TopicCount,
)
from app.services.ai_summary import summarise_cluster
from app.services.clustering import articles_near
from app.services.country_centroids import normalize_country
from app.services.gdelt import fetch_articles, fetch_geo_points

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["news"])

# Frontend sends "Climate" but classifier uses "environment"
_TOPIC_ALIASES = {"climate": "environment"}

# Map frontend topic names to GDELT search keywords for server-side filtering
_TOPIC_TO_GDELT_QUERY: dict[str, str] = {
    "conflict": "war OR attack OR military OR conflict",
    "politics": "president OR election OR government OR parliament",
    "economy": "economy OR market OR trade OR financial",
    "technology": "tech OR ai OR cyber OR digital",
    "health": "health OR virus OR hospital OR vaccine",
    "environment": "climate OR pollution OR energy OR wildfire",
}


def _resolve_topic(topic: str | None) -> str | None:
    if not topic:
        return None
    lower = topic.lower()
    return _TOPIC_ALIASES.get(lower, lower)


def _extract_country_from_location(location_name: str) -> str | None:
    """Extract country code from a GEO API location name.

    Examples: "Tehran, Tehran, Iran" -> "IR", "United Kingdom" -> "GB"
    """
    parts = [p.strip() for p in location_name.split(",")]
    for part in reversed(parts):
        code = normalize_country(part)
        if code and len(code) == 2:
            return code
    return None


@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    topic: str | None = Query(None, description="Optional topic filter"),
    timespan: str = Query("24h", description="GDELT timespan, e.g. 24h, 48h"),
    limit: int = Query(100, ge=1, le=500, description="Max data points"),
) -> list[GlobeDataPoint]:
    """Return globe data points from the GDELT GEO 2.0 API.

    Uses city-level geographic data for worldwide coverage.
    Topic filtering is passed to the GDELT query for server-side filtering.
    """
    resolved = _resolve_topic(topic)
    gdelt_query = "sourcelang:english"
    if resolved and resolved in _TOPIC_TO_GDELT_QUERY:
        gdelt_query = f"({_TOPIC_TO_GDELT_QUERY[resolved]}) sourcelang:english"

    points = await fetch_geo_points(query=gdelt_query, timespan=timespan)
    points.sort(key=lambda p: p.article_count, reverse=True)
    return points[:limit]


@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(5.0, description="Search radius in degrees"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name from GEO API"),
) -> list[NewsArticle]:
    """Return full articles near a given lat/lng point.

    Used when a user clicks a dot on the globe.
    """
    articles = await fetch_articles()
    resolved = _resolve_topic(topic)
    if resolved:
        articles = [a for a in articles if resolved in a.topic_tags]

    # Try country-based filtering first (more reliable than proximity with centroids)
    if location_name:
        country_code = _extract_country_from_location(location_name)
        if country_code:
            by_country = [a for a in articles if a.country_code == country_code]
            if by_country:
                return by_country

    # Fallback: proximity search
    nearby = articles_near(articles, lat, lng, radius)
    return nearby


@router.get("/news/summary", response_model=ClusterSummaryResponse)
async def get_cluster_summary(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(5.0, description="Search radius in degrees"),
    location_name: str | None = Query(None, description="Location name from GEO API"),
) -> ClusterSummaryResponse:
    """Return an AI-generated summary for the cluster at a location."""
    articles = await fetch_articles()

    if location_name:
        country_code = _extract_country_from_location(location_name)
        if country_code:
            nearby = [a for a in articles if a.country_code == country_code]
        else:
            nearby = articles_near(articles, lat, lng, radius)
    else:
        nearby = articles_near(articles, lat, lng, radius)

    summary_text = await summarise_cluster(nearby, lat, lng)
    return ClusterSummaryResponse(
        lat=lat,
        lng=lng,
        article_count=len(nearby),
        summary=summary_text,
    )


@router.get("/topics", response_model=list[TopicCount])
async def get_topics() -> list[TopicCount]:
    """Return available topic categories with article counts."""
    articles = await fetch_articles()
    counts: dict[str, int] = defaultdict(int)
    for a in articles:
        if a.topic_tags:
            for tag in a.topic_tags:
                counts[tag] += 1
        else:
            counts["general"] += 1
    result = [TopicCount(topic=t, count=c) for t, c in counts.items()]
    result.sort(key=lambda t: t.count, reverse=True)
    return result
