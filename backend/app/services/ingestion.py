"""GDELT → PostgreSQL ingestion service.

Periodically fetches articles from the GDELT DOC 2.0 API and upserts
them into the local PostgreSQL database.  This decouples the app from
GDELT's availability — the globe is always served from the database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import settings
from app.models.news import NewsArticle
from app.services.cache import invalidate
from app.services.database import upsert_articles
from app.services.gdelt import _fetch_with_retry, _parse_doc_response

logger = logging.getLogger("orbis.ingestion")


async def run_ingestion_cycle() -> int:
    """Fetch articles from GDELT and upsert into PostgreSQL.

    Returns the number of articles upserted, or 0 on failure.
    Never raises — all errors are logged and swallowed so the
    scheduler can keep running.
    """
    try:
        logger.info("Ingestion cycle starting …")

        params = {
            "query": "sourcelang:english",
            "mode": "ArtList",
            "maxrecords": 250,
            "format": "json",
            "timespan": "24h",
        }

        data = await _fetch_with_retry(settings.gdelt_doc_base_url, params)
        raw_articles: list[NewsArticle] = _parse_doc_response(data)

        # Drop articles without valid coordinates — they cannot be plotted
        articles = [a for a in raw_articles if a.latitude != 0.0 or a.longitude != 0.0]

        if not articles:
            logger.warning("Ingestion cycle: 0 geolocated articles from GDELT.")
            return 0

        # Convert Pydantic models → dicts for upsert_articles()
        rows = []
        for a in articles:
            rows.append({
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
            })

        count = await upsert_articles(rows)

        # Invalidate DB-sourced caches so next request picks up fresh data
        await invalidate("db:*")

        logger.info("Ingestion cycle complete: %d articles upserted.", count)
        return count

    except Exception:
        logger.error("Ingestion cycle failed.", exc_info=True)
        return 0
