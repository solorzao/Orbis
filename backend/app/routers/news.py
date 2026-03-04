"""API routes for news data, clusters, summaries, and topics."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.config import settings
from app.models.news import (
    ClusterSummaryResponse,
    GlobeDataPoint,
    NewsArticle,
    TopicCount,
)
from app.services.ai_summary import summarise_cluster
from app.services.cache import get_cached, set_cached
from app.services.database import get_globe_points, get_nearby_articles, get_topic_counts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["news"])

# Frontend sends "Climate" but classifier uses "environment"
_TOPIC_ALIASES = {"climate": "environment"}


def _resolve_topic(topic: str | None) -> str | None:
    if not topic:
        return None
    lower = topic.lower()
    return _TOPIC_ALIASES.get(lower, lower)


def _parse_timespan(timespan: str) -> int:
    """Convert a timespan string like '24h' or '48h' to integer hours."""
    s = timespan.strip().lower()
    if s.endswith("h"):
        try:
            return int(s[:-1])
        except ValueError:
            pass
    return 24


def _row_to_article(row: dict) -> NewsArticle:
    """Convert a database row dict to a NewsArticle model."""
    return NewsArticle(
        id=str(row.get("id", "")),
        title=row.get("title", ""),
        summary=row.get("summary"),
        source_url=row.get("source_url", ""),
        source_name=row.get("source_name", ""),
        source_language=row.get("source_language", "en"),
        published_at=row.get("published_at", datetime.now(timezone.utc)),
        ingested_at=row.get("ingested_at", datetime.now(timezone.utc)),
        latitude=row.get("latitude", 0.0),
        longitude=row.get("longitude", 0.0),
        country_code=row.get("country_code", ""),
        region=row.get("region", ""),
        topic_tags=row.get("topic_tags", []),
        sentiment_score=row.get("sentiment_score", 0.0),
        entities=json.loads(row["entities"]) if isinstance(row.get("entities"), str) else row.get("entities", {}),
    )


@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    timespan: str = Query("24h", description="Timespan, e.g. 24h, 48h"),
    limit: int = Query(500, ge=1, le=500, description="Max data points"),
) -> list[GlobeDataPoint]:
    """Return clustered globe data points from the database."""
    hours = _parse_timespan(timespan)

    cache_k = f"db:globe:{hours}:{limit}"
    cached = await get_cached(cache_k)
    if cached:
        return [GlobeDataPoint(**p) for p in cached]

    rows = await get_globe_points(timespan_hours=hours, limit=limit)
    points = [GlobeDataPoint(**r) for r in rows]

    if points:
        await set_cached(cache_k, [p.model_dump() for p in points], settings.db_cache_ttl)

    return points


_MAX_CLUSTER_ARTICLES = 10


@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(5.0, description="Search radius in degrees"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name"),
) -> list[NewsArticle]:
    """Return full articles near a given lat/lng point from the database."""
    resolved = _resolve_topic(topic)

    # Convert radius in degrees to rough km (1 deg ≈ 111 km)
    radius_km = radius * 111.0
    rows = await get_nearby_articles(lat, lng, radius_km=radius_km, limit=50)
    articles = [_row_to_article(r) for r in rows]

    if resolved:
        filtered = [a for a in articles if resolved in a.topic_tags]
        if filtered:
            articles = filtered
        else:
            logger.info(
                "Topic filter '%s' matched 0 of %d articles — returning unfiltered",
                resolved,
                len(articles),
            )

    return articles[:_MAX_CLUSTER_ARTICLES]


@router.get("/news/summary", response_model=ClusterSummaryResponse)
async def get_cluster_summary(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(5.0, description="Search radius in degrees"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name"),
) -> ClusterSummaryResponse:
    """Return an AI-generated summary for the cluster at a location."""
    resolved = _resolve_topic(topic)

    radius_km = radius * 111.0
    rows = await get_nearby_articles(lat, lng, radius_km=radius_km, limit=50)
    articles = [_row_to_article(r) for r in rows]

    if resolved:
        filtered = [a for a in articles if resolved in a.topic_tags]
        if filtered:
            articles = filtered

    nearby = articles[:_MAX_CLUSTER_ARTICLES]

    summary_text = await summarise_cluster(nearby, lat, lng, location_name=location_name, topic=resolved)
    return ClusterSummaryResponse(
        lat=lat,
        lng=lng,
        article_count=len(nearby),
        summary=summary_text,
    )


@router.get("/topics", response_model=list[TopicCount])
async def get_topics() -> list[TopicCount]:
    """Return available topic categories with article counts from the database."""
    cache_k = "db:topics"
    cached = await get_cached(cache_k)
    if cached:
        return [TopicCount(**t) for t in cached]

    counts = await get_topic_counts()
    result = [TopicCount(topic=t, count=c) for t, c in counts.items()]
    result.sort(key=lambda t: t.count, reverse=True)

    if result:
        await set_cached(cache_k, [t.model_dump() for t in result], settings.db_cache_ttl)

    return result
