"""GDELT raw GKG → PostgreSQL ingestion service.

Periodically downloads the latest GDELT GKG data file (published every
15 minutes), extracts articles with city-level locations, scrapes their
titles, and upserts them into the database.
"""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.services.cache import invalidate
from app.services.database import get_pool, upsert_articles
from app.services.embeddings import generate_embeddings
from app.services.gdelt import fetch_raw_gkg, scrape_titles
from app.services.knowledge_graph import populate_graph, purge_orphaned_nodes
from app.services.ml_models import classify_topics_ml, analyze_sentiment_ml
from app.services.topic_classifier import classify_topic

logger = logging.getLogger("orbis.ingestion")

# Pattern: "Headline : NPR", "Headline | WXXJ News", "Headline - The Post"
_OUTLET_SEP = re.compile(r"\s+[|:–—-]\s+")


def _dedup_key(title: str) -> str:
    """Normalize a title for dedup by stripping the trailing outlet name."""
    # Split on the last separator; if suffix is short it's likely an outlet name
    parts = list(_OUTLET_SEP.finditer(title))
    if parts:
        last = parts[-1]
        suffix = title[last.end():]
        if len(suffix) < 40:
            title = title[:last.start()]
    return title.strip().lower()


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
    tones: list[float] = []
    for a in articles:
        title = a.get("title", "")
        if not title:
            continue

        # Deduplicate: strip outlet suffix so syndicated copies collapse
        norm = _dedup_key(title)
        if norm in seen_titles:
            continue
        seen_titles.add(norm)

        # Placeholders — overwritten by batch ML classification below
        topic_tags = ["general"]
        sentiment = 0.0

        tones.append(a.get("tone", 0.0))
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
                "persons": a.get("persons", []),
                "organizations": a.get("organizations", []),
                "mentioned_locations": a.get("mentioned_locations", []),
            }
        )

    # Batch ML classification (replaces per-article keyword matching)
    if settings.ml_classification_enabled:
        titles = [r["title"] for r in rows]
        all_topics = classify_topics_ml(titles)
        all_sentiments = analyze_sentiment_ml(titles)
        for row, topics, sent in zip(rows, all_topics, all_sentiments):
            row["topic_tags"] = topics
            row["sentiment_score"] = sent
    else:
        # Fallback: keyword topic + GDELT tone
        for row, tone in zip(rows, tones):
            row["topic_tags"] = classify_topic(row["title"])
            row["sentiment_score"] = max(-1.0, min(1.0, tone / 10.0))

    if not rows:
        logger.warning("No articles with titles to upsert.")
        return 0

    count = await upsert_articles(rows)

    # Query back upserted articles to get DB-generated UUIDs for KG population
    pool = await get_pool()
    source_urls = [r["source_url"] for r in rows]
    db_rows = await pool.fetch(
        "SELECT id, title, source_url, latitude, longitude, region, "
        "country_code, topic_tags, published_at FROM articles "
        "WHERE source_url = ANY($1::text[])",
        source_urls,
    )
    # Build a lookup from source_url to DB record
    db_lookup = {r["source_url"]: dict(r) for r in db_rows}
    # Merge entity data from ingestion rows into DB records
    graph_articles = []
    for row in rows:
        db_rec = db_lookup.get(row["source_url"])
        if db_rec:
            db_rec["persons"] = row.get("persons", [])
            db_rec["organizations"] = row.get("organizations", [])
            db_rec["mentioned_locations"] = row.get("mentioned_locations", [])
            graph_articles.append(db_rec)
    await populate_graph(graph_articles)

    await invalidate("db:*")
    logger.info("GKG ingestion: upserted %d articles with city-level coords.", count)
    return count


async def _purge_old_articles() -> None:
    """Delete articles older than the retention window."""
    pool = await get_pool()
    status = await pool.execute(
        "DELETE FROM articles WHERE published_at < NOW() - make_interval(days => $1)",
        settings.retention_days,
    )
    # status is e.g. "DELETE 42"
    count = int(status.split()[-1])
    if count:
        logger.info("Purged %d articles older than %d days.", count, settings.retention_days)
    await purge_orphaned_nodes()


async def run_ingestion_cycle() -> int:
    """Run the ingestion pipeline.  Never raises.

    Downloads the latest GDELT GKG raw data file, extracts articles with
    city-level locations, scrapes titles, and upserts to PostgreSQL.
    Then purges articles outside the retention window.
    """
    try:
        logger.info("Ingestion cycle starting …")
        count = await _ingest_from_raw_gkg()
        await _purge_old_articles()
        await generate_embeddings()
        logger.info("Ingestion cycle complete: %d articles.", count)
        return count
    except Exception:
        logger.error("Ingestion cycle failed.", exc_info=True)
        return 0
