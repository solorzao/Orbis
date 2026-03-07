"""Async PostgreSQL client for the Orbis backend (via asyncpg).

Provides helpers for querying articles with spatial, temporal, and
topic-based filters against Azure Database for PostgreSQL.

All public functions are importable via:

    from app.services.database import *
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.config import settings

__all__ = [
    "get_pool",
    "close_pool",
    "get_articles",
    "get_nearby_articles",
    "get_articles_by_country",
    "get_articles_in_bounds",
    "upsert_articles",
    "get_topic_counts",
    "get_globe_points",
    "get_hourly_density",
]

logger = logging.getLogger("orbis.database")

# ---------------------------------------------------------------------------
# Connection pool singleton
# ---------------------------------------------------------------------------

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return a cached asyncpg connection pool."""
    global _pool
    if _pool is None:
        dsn = settings.database_url
        if not dsn:
            raise RuntimeError("DATABASE_URL must be set in environment variables.")
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info("Database connection pool created.")
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed.")


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


async def get_articles(
    *,
    topic: str | None = None,
    timespan_hours: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch articles with optional topic and timespan filters."""
    pool = await get_pool()

    conditions = []
    params: list[Any] = []
    idx = 1

    if topic:
        conditions.append(f"${idx} = ANY(topic_tags)")
        params.append(topic)
        idx += 1

    if timespan_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
        conditions.append(f"published_at >= ${idx}")
        params.append(cutoff)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    query = f"""
        SELECT id, title, summary, source_url, source_name, source_language,
               published_at, ingested_at, latitude, longitude, country_code,
               region, topic_tags, sentiment_score, entities, image_url
        FROM articles
        {where}
        ORDER BY published_at DESC
        LIMIT ${idx}
    """

    rows = await pool.fetch(query, *params)
    return [dict(r) for r in rows]


async def get_nearby_articles(
    lat: float,
    lng: float,
    radius_km: float = 100,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find articles within *radius_km* of a geographic point via PostGIS."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM nearby_articles($1, $2, $3, $4)",
        lat,
        lng,
        radius_km,
        limit,
    )
    return [dict(r) for r in rows]


async def get_articles_by_country(
    country_code: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find articles matching a country code."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, title, summary, source_url, source_name, source_language,
               published_at, ingested_at, latitude, longitude, country_code,
               region, topic_tags, sentiment_score, entities, image_url
        FROM articles
        WHERE country_code = $1
        ORDER BY published_at DESC
        LIMIT $2
        """,
        country_code,
        limit,
    )
    return [dict(r) for r in rows]


async def get_articles_in_bounds(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    limit: int = 200,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return articles inside a lat/lng bounding box (for globe viewport)."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM articles_in_bounds($1, $2, $3, $4, $5)",
        min_lat,
        min_lng,
        max_lat,
        max_lng,
        limit,
    )
    result = [dict(r) for r in rows]
    if start_time and end_time:
        result = [
            r for r in result
            if start_time
            <= r.get("published_at", datetime.min.replace(tzinfo=timezone.utc))
            <= end_time
        ]
    return result


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


async def upsert_articles(articles: list[dict[str, Any]]) -> int:
    """Bulk upsert articles, deduplicating on source_url.

    Returns the number of rows upserted.
    """
    if not articles:
        return 0

    pool = await get_pool()
    count = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for article in articles:
                await conn.execute(
                    """
                    INSERT INTO articles (
                        title, summary, source_url, source_name, source_language,
                        published_at, latitude, longitude, location,
                        country_code, region, topic_tags, sentiment_score,
                        entities, image_url
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        ST_SetSRID(ST_MakePoint($8, $7), 4326)::geography,
                        $9, $10, $11, $12, $13, $14
                    )
                    ON CONFLICT (source_url) DO UPDATE SET
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        location = EXCLUDED.location,
                        country_code = EXCLUDED.country_code,
                        region = EXCLUDED.region,
                        sentiment_score = EXCLUDED.sentiment_score,
                        topic_tags = EXCLUDED.topic_tags,
                        entities = EXCLUDED.entities,
                        image_url = EXCLUDED.image_url
                    """,
                    article.get("title", ""),
                    article.get("summary"),
                    article["source_url"],
                    article.get("source_name", ""),
                    article.get("source_language", "en"),
                    article.get("published_at", datetime.now(timezone.utc)),
                    article.get("latitude", 0.0),
                    article.get("longitude", 0.0),
                    article.get("country_code", ""),
                    article.get("region", ""),
                    article.get("topic_tags", []),
                    article.get("sentiment_score", 0.0),
                    json.dumps(article.get("entities", {})),
                    article.get("image_url"),
                )
                count += 1

    logger.info("Upserted %d articles.", count)
    return count


# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------


async def get_globe_points(
    *,
    timespan_hours: int = 24,
    cell_size: float = 2.0,
    limit: int = 500,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return clustered globe points from the database.

    Groups articles into grid cells of *cell_size* degrees, picking the
    most recent headline and dominant topic per cell.
    """
    pool = await get_pool()

    if start_time and end_time:
        time_filter = "WHERE published_at BETWEEN $1 AND $2"
        cell_param = "$3"
        limit_param = "$4"
        base_params: list[Any] = [start_time, end_time]
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
        time_filter = "WHERE published_at >= $1"
        cell_param = "$2"
        limit_param = "$3"
        base_params = [cutoff]

    base_query = f"""
        WITH clustered AS (
            SELECT
                FLOOR(latitude / {cell_param}) * {cell_param} + {cell_param} / 2  AS lat,
                FLOOR(longitude / {cell_param}) * {cell_param} + {cell_param} / 2 AS lng,
                title,
                topic_tags,
                region,
                published_at,
                ROW_NUMBER() OVER (
                    PARTITION BY FLOOR(latitude / {cell_param}), FLOOR(longitude / {cell_param})
                    ORDER BY published_at DESC
                ) AS rn
            FROM articles
            {{time_filter}}
        )
        SELECT
            lat,
            lng,
            COUNT(*) AS article_count,
            MAX(CASE WHEN rn = 1 THEN title END) AS top_headline,
            MAX(CASE WHEN rn = 1 THEN topic_tags END) AS topic_tags,
            MAX(CASE WHEN rn = 1 THEN region END) AS location_name
        FROM clustered
        GROUP BY lat, lng
        ORDER BY article_count DESC
        LIMIT {limit_param}
    """

    # Try with time filter first, fall back to all data if empty
    query = base_query.format(time_filter=time_filter)
    rows = await pool.fetch(query, *base_params, cell_size, limit)

    if not rows:
        logger.warning("No articles in last %dh — falling back to all data.", timespan_hours)
        query_all = base_query.format(time_filter="")
        rows = await pool.fetch(query_all, *base_params, cell_size, limit)
    results = []
    for row in rows:
        tags = row["topic_tags"] or []
        results.append(
            {
                "lat": row["lat"],
                "lng": row["lng"],
                "weight": min(row["article_count"] * 10, 500),
                "article_count": row["article_count"],
                "top_headline": row["top_headline"] or "",
                "topic": tags[0] if tags else "general",
                "location_name": row["location_name"] or "",
            }
        )
    return results


async def get_hourly_density(*, timespan_hours: int = 24) -> dict[int, int]:
    """Return article counts bucketed by hour for the last N hours."""
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
    rows = await pool.fetch(
        """
        SELECT EXTRACT(HOUR FROM published_at) AS hour,
               COUNT(*) AS count
        FROM articles
        WHERE published_at >= $1
        GROUP BY hour
        ORDER BY hour
        """,
        cutoff,
    )
    return {int(r["hour"]): int(r["count"]) for r in rows}


async def get_topic_counts() -> dict[str, int]:
    """Return a mapping of topic tag to article count."""
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM topic_counts()")
    return {row["topic"]: row["count"] for row in rows}
