"""GDELT raw GKG → PostgreSQL ingestion service.

Periodically downloads the latest GDELT GKG data file (published every
15 minutes), extracts articles with city-level locations, takes their
titles from GDELT (scraping the page only when GDELT has none), and
upserts them with their GKG fields into the database.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.config import settings
from app.services.cache import invalidate
from app.services.database import get_pool, upsert_articles
from app.services.embeddings import generate_embeddings
from app.services.gdelt import fetch_raw_gkg, scrape_titles
from app.services.knowledge_graph import populate_graph, purge_orphaned_nodes
from app.services.ml_models import analyze_sentiment_ml, classify_topics_ml
from app.services.titles import dedup_key
from app.services.topic_classifier import classify_topic

logger = logging.getLogger("orbis.ingestion")


async def _assign_titles(articles: list[dict]) -> None:
    """Set each article's ``title``: GDELT's page title, else a scraped <title>.

    Only records without a usable GDELT title are scraped. Articles left
    without a title are dropped by the caller.
    """
    untitled = []
    for a in articles:
        if a.get("page_title"):
            a["title"] = a["page_title"]
        else:
            untitled.append(a)
    if untitled:
        await scrape_titles(untitled)
    scraped = sum(1 for a in untitled if a.get("title"))
    logger.info(
        "Titles: %d from GDELT, %d scraped, %d dropped.",
        len(articles) - len(untitled),
        scraped,
        len(untitled) - scraped,
    )


async def _ingest_from_raw_gkg() -> int:
    """Fetch the latest GKG file, take or scrape titles, and upsert to DB."""
    articles = await fetch_raw_gkg()
    if not articles:
        logger.warning("GKG raw file: 0 city-level articles.")
        return 0

    await _assign_titles(articles)

    # Convert to DB upsert format, deduplicating by normalized title
    seen_titles: set[str] = set()
    rows = []
    tones: list[float] = []
    for a in articles:
        title = a.get("title", "")
        if not title:
            continue

        # Deduplicate: strip outlet suffix so syndicated copies collapse
        norm = dedup_key(title)
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
                # '' when GKG has no country.
                "country_fips": a.get("country_fips") or "",
                "region": a.get("location_name", ""),
                "topic_tags": topic_tags,
                "sentiment_score": sentiment,
                "entities": {"tone": a["tone_detail"]} if a.get("tone_detail") else {},
                "image_url": a.get("image_url") or None,
                # GKG fields written to articles columns by upsert_articles
                "themes": a.get("themes", []),
                # persons: the articles.persons column AND populate_graph's PERSON nodes
                "persons": a.get("persons", []),
                # orgs: the articles.orgs column (upsert_articles reads this key)
                "orgs": a.get("organizations", []),
                "names": a.get("names", []),
                "counts": a.get("counts", []),
                # ISO codes of the countries the story mentions, for links
                "mentioned_countries": a.get("mentioned_countries", []),
                # Read only by populate_graph (below), not written by upsert_articles:
                # organizations -> ORG nodes (same list as orgs),
                # mentioned_locations -> country LOCATION nodes.
                "organizations": a.get("organizations", []),
                "mentioned_locations": a.get("mentioned_locations", []),
            }
        )

    # Batch ML classification (replaces per-article keyword matching)
    if settings.ml_classification_enabled:
        titles = [r["title"] for r in rows]
        all_topics, all_sentiments = await asyncio.gather(
            classify_topics_ml(titles),
            analyze_sentiment_ml(titles),
        )
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
        "country_code, country_fips, topic_tags, published_at FROM articles "
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


# Held for a whole ingestion cycle, so the startup run and the scheduler never overlap.
_ingestion_lock = asyncio.Lock()
# time.monotonic() when the cycle holding _ingestion_lock started.
_cycle_started_at: float | None = None


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


# The cycle's background tasks, held so they are not garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


async def _warm_caches() -> None:
    try:
        # Here, not at the top: app.warm imports the routers, which import services.
        from app.warm import warm_caches

        await warm_caches()
    except Exception:
        logger.warning("Cache warm failed; continuing.", exc_info=True)


def _start_cache_warm() -> None:
    """Refill the busiest API caches (app.warm) in the background."""
    task = asyncio.create_task(_warm_caches())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def stop_background_tasks() -> None:
    """Cancel the cycle's background tasks (a cache warm) and wait until they stop.

    At shutdown, before Redis and the pool close, so a warm cannot reopen
    them; and as a cycle starts, so a warm cannot write answers back after
    the cycle has invalidated them.
    """
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def run_ingestion_cycle() -> int:
    """Run the ingestion pipeline.  Never raises.

    Downloads the latest GDELT GKG raw data file, extracts articles with
    city-level locations, scrapes titles, and upserts to PostgreSQL.
    Then purges articles outside the retention window and embeds the new
    rows. Breaking stories (and so deltas) count embedded rows only, so their
    caches are invalidated again once the rows are embedded: one cached
    between the upsert's invalidation and then would miss the newest batch.
    Once the cycle has released its lock, the caches it invalidated are
    refilled in the background, so neither the next cycle nor a visitor
    waits on that.

    Cycles never overlap: if one is already running (the startup run and the
    scheduler can coincide), this returns 0 without doing anything.
    """
    global _cycle_started_at
    if _ingestion_lock.locked():
        running_for = time.monotonic() - (_cycle_started_at or time.monotonic())
        logger.warning("Ingestion cycle already running for %.0fs; skipping this one.", running_for)
        return 0
    async with _ingestion_lock:
        _cycle_started_at = time.monotonic()
        await stop_background_tasks()  # the last cycle's warm, if still running
        try:
            logger.info("Ingestion cycle starting …")
            count = await _ingest_from_raw_gkg()
            await _purge_old_articles()
            await generate_embeddings()
            await invalidate("db:breaking*")
            await invalidate("db:delta*")
            logger.info("Ingestion cycle complete: %d articles.", count)
        except Exception:
            logger.error("Ingestion cycle failed.", exc_info=True)
            count = 0
    _start_cache_warm()
    return count
