"""GDELT raw GKG → PostgreSQL ingestion service.

Periodically downloads the latest GDELT GKG data file (published every
15 minutes), extracts articles with city-level locations, scrapes their
titles, and upserts them into the database.
"""

from __future__ import annotations

import logging

from app.services.cache import invalidate
from app.services.database import upsert_articles
from app.services.gdelt import fetch_raw_gkg, scrape_titles
from app.services.topic_classifier import classify_topic

logger = logging.getLogger("orbis.ingestion")


async def _ingest_from_raw_gkg() -> int:
    """Fetch the latest GKG file, scrape titles, and upsert to DB."""
    articles = await fetch_raw_gkg()
    if not articles:
        logger.warning("GKG raw file: 0 city-level articles.")
        return 0

    # Scrape <title> tags from article URLs
    await scrape_titles(articles)

    # Convert to DB upsert format, deduplicating by normalized title
    seen_titles: set[str] = set()
    rows = []
    for a in articles:
        title = a.get("title", "")
        if not title:
            continue

        # Deduplicate: keep first article per normalized title
        norm = title.strip().lower()
        if norm in seen_titles:
            continue
        seen_titles.add(norm)

        # Sentiment from GKG tone (scale is roughly -10 to +10)
        tone = a.get("tone", 0.0)
        sentiment = max(-1.0, min(1.0, tone / 10.0))

        # Topic classification from title
        topic_tags = classify_topic(title)

        rows.append(
            {
                "title": title,
                "summary": None,
                "source_url": a["url"],
                "source_name": a.get("domain", ""),
                "source_language": "en",
                "published_at": a["published_at"],
                "latitude": a["lat"],
                "longitude": a["lng"],
                "country_code": a.get("country_code", ""),
                "region": a.get("location_name", ""),
                "topic_tags": topic_tags,
                "sentiment_score": sentiment,
                "entities": {},
                "image_url": a.get("image_url") or None,
            }
        )

    if not rows:
        logger.warning("No articles with titles to upsert.")
        return 0

    count = await upsert_articles(rows)
    await invalidate("db:*")
    logger.info("GKG ingestion: upserted %d articles with city-level coords.", count)
    return count


async def run_ingestion_cycle() -> int:
    """Run the ingestion pipeline.  Never raises.

    Downloads the latest GDELT GKG raw data file, extracts articles with
    city-level locations, scrapes titles, and upserts to PostgreSQL.
    """
    try:
        logger.info("Ingestion cycle starting …")
        count = await _ingest_from_raw_gkg()
        logger.info("Ingestion cycle complete: %d articles.", count)
        return count
    except Exception:
        logger.error("Ingestion cycle failed.", exc_info=True)
        return 0
