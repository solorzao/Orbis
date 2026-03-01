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
from app.services.clustering import (
    articles_near,
    cluster_articles,
    clusters_to_globe_points,
)
from app.services.gdelt import fetch_articles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["news"])


@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    topic: str | None = Query(None, description="Optional topic filter"),
    timespan: str = Query("24h", description="GDELT timespan, e.g. 24h, 48h"),
    limit: int = Query(100, ge=1, le=500, description="Max data points"),
) -> list[GlobeDataPoint]:
    """Return globe data points for rendering on the 3-D globe.

    Fetches articles from GDELT, optionally filters by classified topic,
    clusters nearby articles, and returns lightweight ``GlobeDataPoint``
    objects.
    """
    articles = await fetch_articles(timespan=timespan)

    # Post-filter by classified topic tags (not GDELT query)
    if topic:
        articles = [a for a in articles if topic in a.topic_tags]

    clusters = cluster_articles(articles)
    points = clusters_to_globe_points(clusters)
    # Sort by article count descending so the front-end gets the heaviest dots first.
    points.sort(key=lambda p: p.article_count, reverse=True)
    return points[:limit]


@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(2.0, description="Search radius in degrees"),
    topic: str | None = Query(None, description="Optional topic filter"),
) -> list[NewsArticle]:
    """Return full articles near a given lat/lng point.

    Used when a user clicks a dot on the globe.
    """
    articles = await fetch_articles()
    if topic:
        articles = [a for a in articles if topic in a.topic_tags]
    nearby = articles_near(articles, lat, lng, radius)
    return nearby


@router.get("/news/summary", response_model=ClusterSummaryResponse)
async def get_cluster_summary(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(2.0, description="Search radius in degrees"),
) -> ClusterSummaryResponse:
    """Return an AI-generated summary for the cluster at a location."""
    articles = await fetch_articles()
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
