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


def _build_location_query(location_name: str | None) -> str:
    """Build a GDELT DOC query scoped to a location name.

    Uses the first part of the location (city/region) as a search keyword
    so GDELT returns articles mentioning that place.
    """
    if not location_name:
        return "sourcelang:english"
    # Use the first component (city/region) — most specific part
    city = location_name.split(",")[0].strip()
    if city:
        return f'"{city}" sourcelang:english'
    return "sourcelang:english"


@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    timespan: str = Query("24h", description="GDELT timespan, e.g. 24h, 48h"),
    limit: int = Query(500, ge=1, le=500, description="Max data points"),
) -> list[GlobeDataPoint]:
    """Return all globe data points from the GDELT GEO 2.0 API.

    Returns all topics — filtering is done client-side for instant switching.
    """
    points = await fetch_geo_points(query="sourcelang:english", timespan=timespan)
    points.sort(key=lambda p: p.article_count, reverse=True)
    return points[:limit]


_MAX_CLUSTER_ARTICLES = 10


@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(5.0, description="Search radius in degrees"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name from GEO API"),
) -> list[NewsArticle]:
    """Return full articles near a given lat/lng point.

    Used when a user clicks a dot on the globe.  Searches GDELT with the
    location name so articles are relevant to the specific city/region.
    """
    # Build a location-specific GDELT query for relevant articles
    gdelt_query = _build_location_query(location_name)
    articles = await fetch_articles(query=gdelt_query)

    resolved = _resolve_topic(topic)
    if resolved:
        articles = [a for a in articles if resolved in a.topic_tags]

    return articles[:_MAX_CLUSTER_ARTICLES]


@router.get("/news/summary", response_model=ClusterSummaryResponse)
async def get_cluster_summary(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(5.0, description="Search radius in degrees"),
    location_name: str | None = Query(None, description="Location name from GEO API"),
) -> ClusterSummaryResponse:
    """Return an AI-generated summary for the cluster at a location."""
    gdelt_query = _build_location_query(location_name)
    articles = await fetch_articles(query=gdelt_query)
    nearby = articles[:_MAX_CLUSTER_ARTICLES]

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
