"""API routes for news data, clusters, summaries, and topics."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.config import settings
from app.models.news import (
    ClusterSummaryResponse,
    GlobeDataPoint,
    HourlyDensity,
    NewsArticle,
    SelectionSummaryRequest,
    SelectionSummaryResponse,
    TopicCount,
)
from app.services.ai_summary import summarise_cluster, summarise_selection
from app.services.cache import get_cached, set_cached
from app.services.database import (
    get_articles_in_bounds,
    get_globe_points,
    get_hourly_density,
    get_topic_counts,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["news"])

# Frontend sends "Climate" but classifier uses "environment"
_TOPIC_ALIASES = {"climate": "environment"}


_OUTLET_SEP = re.compile(r"\s+[|:–—-]\s+")


def _dedup_key(title: str) -> str:
    """Normalize a title for dedup by stripping the trailing outlet name."""
    parts = list(_OUTLET_SEP.finditer(title))
    if parts:
        last = parts[-1]
        suffix = title[last.end():]
        if len(suffix) < 40:
            title = title[:last.start()]
    return title.strip().lower()


def _deduplicate_articles(articles: list) -> list:
    """Remove syndicated duplicates, keeping the first (most recent) per title."""
    seen: set[str] = set()
    result = []
    for a in articles:
        key = _dedup_key(a.title)
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def _resolve_topic(topic: str | None) -> str | None:
    if not topic:
        return None
    lower = topic.lower()
    return _TOPIC_ALIASES.get(lower, lower)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string to a timezone-aware datetime."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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
        entities=(
            json.loads(row["entities"])
            if isinstance(row.get("entities"), str)
            else row.get("entities", {})
        ),
    )


@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    timespan: str = Query("24h", description="Timespan, e.g. 24h, 48h"),
    limit: int = Query(500, ge=1, le=500, description="Max data points"),
    start_time: str | None = Query(None, description="ISO start time"),
    end_time: str | None = Query(None, description="ISO end time"),
) -> list[GlobeDataPoint]:
    """Return globe data points clustered from articles in the database."""
    hours = _parse_timespan(timespan)
    start_dt = _parse_iso(start_time)
    end_dt = _parse_iso(end_time)

    cache_k = f"db:globe:{start_time or hours}:{end_time or ''}:{limit}"
    cached = await get_cached(cache_k)
    if cached:
        return [GlobeDataPoint(**p) for p in cached]

    rows = await get_globe_points(
        timespan_hours=hours, cell_size=1.0, limit=limit,
        start_time=start_dt, end_time=end_dt,
    )
    points = [GlobeDataPoint(**r) for r in rows]

    if points:
        await set_cached(cache_k, [p.model_dump() for p in points], settings.db_cache_ttl)

    return points


# Grid cell size must match get_globe_points() call in get_globe_data().
_CELL_SIZE = 1.0


async def _fetch_cell_articles(
    lat: float,
    lng: float,
    topic: str | None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    sentiment: str | None = None,
    search: str | None = None,
) -> list[NewsArticle]:
    """Fetch articles within the grid cell containing (lat, lng).

    Applies optional filters for topic, sentiment band, and title search.
    """
    half = _CELL_SIZE / 2.0
    rows = await get_articles_in_bounds(
        lat - half, lng - half, lat + half, lng + half, limit=50,
        start_time=start_time, end_time=end_time,
    )
    articles = _deduplicate_articles([_row_to_article(r) for r in rows])

    resolved = _resolve_topic(topic)
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

    if sentiment:
        s = sentiment.lower()
        if s == "positive":
            articles = [a for a in articles if a.sentiment_score >= 0.5]
        elif s == "neutral":
            articles = [a for a in articles if 0 <= a.sentiment_score < 0.5]
        elif s == "negative":
            articles = [a for a in articles if a.sentiment_score < 0]

    if search:
        q = search.lower()
        articles = [a for a in articles if q in a.title.lower()]

    return articles


@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(0.75, description="Deprecated — ignored, uses grid cell"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name"),
    offset: int = Query(0, ge=0, description="Number of articles to skip"),
    limit: int = Query(10, ge=1, le=50, description="Max articles to return"),
    start_time: str | None = Query(None, description="ISO start time"),
    end_time: str | None = Query(None, description="ISO end time"),
    sentiment: str | None = Query(None, description="Sentiment band: positive, neutral, negative"),
    search: str | None = Query(None, description="Title text search"),
) -> list[NewsArticle]:
    """Return full articles in the grid cell around (lat, lng)."""
    start_dt = _parse_iso(start_time)
    end_dt = _parse_iso(end_time)
    articles = await _fetch_cell_articles(
        lat, lng, topic,
        start_time=start_dt, end_time=end_dt,
        sentiment=sentiment, search=search,
    )
    return articles[offset:offset + limit]


@router.get("/news/summary", response_model=ClusterSummaryResponse)
async def get_cluster_summary(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(0.75, description="Deprecated — ignored, uses grid cell"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name"),
) -> ClusterSummaryResponse:
    """Return an AI-generated summary for the cluster at a location."""
    resolved = _resolve_topic(topic)
    articles = await _fetch_cell_articles(lat, lng, resolved)
    nearby = articles[:10]

    summary_text = await summarise_cluster(
        nearby,
        lat,
        lng,
        location_name=location_name,
        topic=resolved,
    )
    return ClusterSummaryResponse(
        lat=lat,
        lng=lng,
        article_count=len(nearby),
        summary=summary_text,
    )


@router.get("/news/density", response_model=list[HourlyDensity])
async def get_article_density(
    offset_days: int = Query(0, ge=0, le=6, description="Day offset (0=today, 1=yesterday, …6)"),
) -> list[HourlyDensity]:
    """Return article counts per hour for the time slider sparkline."""
    cache_k = f"db:density:{offset_days}"
    cached = await get_cached(cache_k)
    if cached:
        return [HourlyDensity(**d) for d in cached]

    data = await get_hourly_density(offset_days=offset_days)
    result = [HourlyDensity(hour=h, count=data.get(h, 0)) for h in range(24)]

    if result:
        await set_cached(cache_k, [d.model_dump() for d in result], settings.db_cache_ttl)
    return result


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


@router.post("/news/summarize-selection", response_model=SelectionSummaryResponse)
async def summarize_selection(body: SelectionSummaryRequest) -> SelectionSummaryResponse:
    """Generate an AI summary for a user-selected set of article headlines."""
    summary_text = await summarise_selection(
        body.headlines,
        location_name=body.location_name,
    )
    return SelectionSummaryResponse(
        summary=summary_text,
        article_count=len(body.headlines),
    )
