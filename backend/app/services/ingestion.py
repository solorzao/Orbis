"""GDELT raw GKG → PostgreSQL ingestion service.

Periodically downloads the latest GDELT GKG data file (published every
15 minutes), extracts articles with city-level locations, takes their
titles from GDELT (scraping the page only when GDELT has none), and
upserts them with their GKG fields into the database.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from app.config import settings
from app.services.cache import invalidate
from app.services.country_codes import fips_to_iso2
from app.services.database import get_pool, upsert_articles
from app.services.embeddings import generate_embeddings
from app.services.gdelt import fetch_raw_gkg, scrape_titles
from app.services.knowledge_graph import populate_graph, purge_orphaned_nodes
from app.services.ml_models import analyze_sentiment_ml, classify_topics_ml
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
        suffix = title[last.end() :]
        if len(suffix) < 40:
            title = title[: last.start()]
    return title.strip().lower()


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
                # '' not NULL when GKG has no country: NULL means "written before
                # the FIPS to ISO switch" and is what the backfill looks for.
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


# Consecutive backfill runs that found nothing to convert. At
# _BACKFILL_IDLE_RUNS_TO_STOP the backfill is skipped for the rest of the process.
_backfill_idle_runs = 0
_BACKFILL_IDLE_RUNS_TO_STOP = 2

# Held for a whole ingestion cycle, so the startup run and the scheduler never overlap.
_ingestion_lock = asyncio.Lock()
# time.monotonic() when the cycle holding _ingestion_lock started.
_cycle_started_at: float | None = None


async def _backfill_iso_country_codes(pool, budget: int = 5000) -> int:
    """Convert up to *budget* rows written before the FIPS to ISO switch, newest first.

    Pre-switch rows (country_fips IS NULL) hold GDELT's FIPS code in
    country_code. Their ids are grouped by that code (NULL counts as ''), and
    each group is updated by id: the code moves to country_fips and
    country_code becomes the ISO code ('' if unknown). A failed group is
    logged and skipped. If anything changed, the API cache is invalidated.

    Cost: country_fips is not indexed, so every run's SELECT scans the whole
    articles table, even when nothing is left to convert. After two
    consecutive runs find no rows, the backfill is skipped for the rest of the
    process. Two rather than one, so rows an old revision inserts during a
    deploy overlap are still converted.

    TODO(2026-10-18): remove the backfill and country_fips IS NULL handling
    once pre-switch rows have aged out (7-day retention).
    """
    global _backfill_idle_runs
    if _backfill_idle_runs >= _BACKFILL_IDLE_RUNS_TO_STOP:
        return 0

    rows = await pool.fetch(
        "SELECT id, country_code FROM articles "
        "WHERE country_fips IS NULL ORDER BY published_at DESC LIMIT $1",
        budget,
    )
    if not rows:
        _backfill_idle_runs += 1
        return 0
    _backfill_idle_runs = 0

    ids_by_fips: dict[str, list] = {}
    for row in rows:
        ids_by_fips.setdefault(row["country_code"] or "", []).append(row["id"])

    updated = 0
    for fips, ids in ids_by_fips.items():
        try:
            result = await pool.execute(
                # Re-check the code so a row changed since the SELECT is not
                # converted from a stale value (it is picked up next run).
                "UPDATE articles SET country_fips = $1, country_code = $2 "
                "WHERE id = ANY($3::uuid[]) AND country_fips IS NULL "
                "AND coalesce(country_code, '') = $1",
                fips,
                fips_to_iso2(fips),
                ids,
            )
            updated += int(result.split()[-1])
        except Exception:
            logger.warning(
                "ISO country code backfill failed for %d rows with code %r; continuing.",
                len(ids),
                fips,
                exc_info=True,
            )
    if updated:
        logger.info("Backfilled ISO country codes for %d articles.", updated)
        await invalidate("db:*")
    return updated


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

    First converts any rows still holding FIPS country codes to ISO. Then
    downloads the latest GDELT GKG raw data file, extracts articles with
    city-level locations, scrapes titles, and upserts to PostgreSQL.
    Then purges articles outside the retention window.

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
        try:
            logger.info("Ingestion cycle starting …")
            try:
                await _backfill_iso_country_codes(await get_pool())
            except Exception:
                logger.warning("ISO country code backfill failed; continuing.", exc_info=True)
            count = await _ingest_from_raw_gkg()
            await _purge_old_articles()
            await generate_embeddings()
            logger.info("Ingestion cycle complete: %d articles.", count)
            return count
        except Exception:
            logger.error("Ingestion cycle failed.", exc_info=True)
            return 0
