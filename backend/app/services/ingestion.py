"""GDELT → PostgreSQL ingestion service.

Periodically fetches articles from the GDELT DOC 2.0 API and city-level
globe points from the GEO 2.0 API, storing both locally so the app is
decoupled from GDELT's live availability.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.models.news import NewsArticle
from app.services.cache import invalidate, set_cached
from app.services.database import upsert_articles
from app.services.gdelt import (
    _fetch_with_retry,
    _parse_doc_response,
    _parse_geo_response,
)

logger = logging.getLogger("orbis.ingestion")

# Cache key for GEO-sourced globe points (city-level)
GEO_CACHE_KEY = "geo:globe_points"


async def _ingest_articles() -> int:
    """Fetch articles from GDELT DOC API and upsert into PostgreSQL."""
    params = {
        "query": "sourcelang:english",
        "mode": "ArtList",
        "maxrecords": 250,
        "format": "json",
        "timespan": "24h",
    }

    data = await _fetch_with_retry(settings.gdelt_doc_base_url, params)
    raw_articles: list[NewsArticle] = _parse_doc_response(data)

    articles = [a for a in raw_articles if a.latitude != 0.0 or a.longitude != 0.0]
    if not articles:
        logger.warning("DOC API: 0 geolocated articles.")
        return 0

    rows = []
    for a in articles:
        rows.append(
            {
                "title": a.title,
                "summary": a.summary,
                "source_url": a.source_url,
                "source_name": a.source_name,
                "source_language": a.source_language,
                "published_at": a.published_at,
                "latitude": a.latitude,
                "longitude": a.longitude,
                "country_code": a.country_code,
                "region": a.region,
                "topic_tags": a.topic_tags,
                "sentiment_score": a.sentiment_score,
                "entities": a.entities,
                "image_url": None,
            }
        )

    count = await upsert_articles(rows)
    await invalidate("db:*")
    logger.info("DOC API: upserted %d articles.", count)
    return count


async def _ingest_geo_points() -> int:
    """Fetch city-level globe points from GDELT and cache them.

    Tries GKG GeoJSON v1 first (reliable), then GEO 2.0 as fallback.
    """
    from app.services.gdelt import _parse_gkg_geojson

    # 1. Try GKG GeoJSON v1 — city-level, 2500 features
    gkg_url = "https://api.gdeltproject.org/api/v1/gkg_geojson"
    data = await _fetch_with_retry(gkg_url, {})
    points = _parse_gkg_geojson(data)

    # 2. Fallback to GEO 2.0 API
    if not points:
        logger.info("GKG GeoJSON empty — trying GEO 2.0 API.")
        params = {
            "query": "sourcelang:english",
            "mode": "PointData",
            "format": "GeoJSON",
            "timespan": "24h",
        }
        data = await _fetch_with_retry(settings.gdelt_geo_base_url, params)
        points = _parse_geo_response(data)

    if not points:
        logger.warning("GEO ingestion: 0 points from all sources.")
        return 0

    # Cache for 2x the ingestion interval so data survives between cycles
    ttl = settings.ingestion_interval_seconds * 2
    await set_cached(GEO_CACHE_KEY, [p.model_dump() for p in points], ttl)
    logger.info("GEO ingestion: cached %d city-level globe points.", len(points))
    return len(points)


async def run_ingestion_cycle() -> int:
    """Fetch from both GDELT APIs. Returns number of articles upserted.

    Never raises — all errors are logged and swallowed so the
    scheduler can keep running.
    """
    try:
        logger.info("Ingestion cycle starting …")

        # Fetch DOC articles and GEO points in parallel, with a small
        # delay between them to respect GDELT's rate limit.
        article_count = await _ingest_articles()
        await asyncio.sleep(5)  # GDELT rate limit: 1 req per 5 seconds
        geo_count = await _ingest_geo_points()

        logger.info(
            "Ingestion cycle complete: %d articles, %d geo points.",
            article_count,
            geo_count,
        )
        return article_count

    except Exception:
        logger.error("Ingestion cycle failed.", exc_info=True)
        return 0
