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
from app.services.places import display_place
from app.services.titles import story_key

__all__ = [
    "get_pool",
    "open_pool",
    "close_pool",
    "get_articles",
    "get_nearby_articles",
    "get_articles_by_country",
    "get_articles_in_bounds",
    "upsert_articles",
    "get_topic_counts",
    "get_globe_points",
    "get_globe_points_by_topic",
    "globe_lead",
    "dominant_topic",
    "get_hourly_density",
    "get_hourly_volume",
    "get_cell_spark",
    "get_cell_entities",
]

logger = logging.getLogger("orbis.database")

# ---------------------------------------------------------------------------
# Connection pool singleton
# ---------------------------------------------------------------------------

_pool: asyncpg.Pool | None = None

# Set by close_pool at shutdown, cleared by open_pool at startup: a query that
# lands after shutdown (a refill: breaking's, a warm's, a week read's) gets an
# error, rather than opening a second pool that nothing closes.
_pool_closed = False

# Counts close_pool's runs: a pool get_pool began opening before one is closed as
# it lands, even once open_pool has cleared _pool_closed (the app started again in
# one process, as tests do), so it never replaces the pool opened since.
_pool_generation = 0

_POOL_CLOSED = "The database pool is closed: the app is shutting down."


async def open_pool() -> asyncpg.Pool:
    """get_pool, at startup: also after a shutdown's close_pool (the app started
    again in one process, as tests do)."""
    global _pool_closed
    _pool_closed = False
    return await get_pool()


async def get_pool() -> asyncpg.Pool:
    """Return a cached asyncpg connection pool. RuntimeError once close_pool has run
    (the app is shutting down), until open_pool."""
    global _pool
    if _pool is None:
        if _pool_closed:
            raise RuntimeError(_POOL_CLOSED)
        dsn = settings.database_url
        if not dsn:
            raise RuntimeError("DATABASE_URL must be set in environment variables.")
        generation = _pool_generation
        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        if _pool_generation != generation:  # close_pool ran while this one opened
            await pool.close()
            raise RuntimeError(_POOL_CLOSED)
        if _pool is not None:  # a concurrent first call's landed first: theirs is kept
            kept = _pool
            await pool.close()
            return kept
        _pool = pool
        logger.info("Database connection pool created.")
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool. get_pool raises from then on, until
    open_pool."""
    global _pool, _pool_closed, _pool_generation
    _pool_closed = True
    _pool_generation += 1
    pool, _pool = _pool, None  # no caller is handed it as it closes
    if pool is not None:
        await pool.close()
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


# Degrees added on every side of the geography prefilter box in
# get_articles_in_bounds: about 1 km, ten times the most (~0.001 degrees) a
# 1-degree cell's geodesic edge strays from its line of latitude.
_BOX_PAD_DEGREES = 0.01


def _cell_box(
    min_lat: float, min_lng: float, max_lat: float, max_lng: float
) -> tuple[list[str], list[Any]]:
    """WHERE conditions and their arguments ($1-$8) for a cell-sized lat/lng box.

    Index prefilter: the box as geography for idx_articles_location, padded
    (and kept on the globe) so its geodesic edges never cut off a point of
    the exact box; the half-open lat/lng range then decides, as the globe
    dots' FLOOR grid does.
    """
    params: list[Any] = [
        min_lat,
        min_lng,
        max_lat,
        max_lng,
        max(min_lng - _BOX_PAD_DEGREES, -180.0),
        max(min_lat - _BOX_PAD_DEGREES, -90.0),
        min(max_lng + _BOX_PAD_DEGREES, 180.0),
        min(max_lat + _BOX_PAD_DEGREES, 90.0),
    ]
    conditions = [
        "location && ST_MakeEnvelope($5, $6, $7, $8, 4326)::geography",
        "latitude >= $1 AND latitude < $3 AND longitude >= $2 AND longitude < $4",
    ]
    return conditions, params


async def get_articles_in_bounds(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    limit: int = 200,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    topics: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the newest articles in a cell-sized lat/lng box, one per title.

    The box must be cell-sized: the geography ``&&`` prefilter joins its
    corners by the shorter way round, so a box 180 degrees or more wide would
    not mean what it says.

    The box is half-open (min <= value < max), like the FLOOR grid the globe
    dots use, so a point on a cell edge belongs to exactly one cell. The time
    window and the topic filter (any of *topics*) apply before the dedup and
    the LIMIT: an older window or a topic still gets its newest *limit*
    articles. Either bound, and *topics*, may be None; absent filters are left
    out of the SQL rather than written as ``$n IS NULL OR ...``, so no plan
    asyncpg prepares has to cover both cases and miss the indexes.

    Selects only the columns a ``NewsArticle`` reads: never the embedding.
    Ties on ``published_at`` (a whole GDELT batch shares one) break on ``id``,
    in the dedup and the final order, so offset paging over repeated calls
    neither repeats nor skips articles.

    After the limit, each row names its story thread (``thread_*`` columns,
    read by thread_reads.article_thread) by primary-key lookups, when
    /api/threads would list it: 3 or more stories from 3 or more outlets.
    """
    conditions, params = _cell_box(min_lat, min_lng, max_lat, max_lng)
    params.append(limit)
    if start_time is not None:
        params.append(start_time)
        conditions.append(f"published_at >= ${len(params)}")
    if end_time is not None:
        params.append(end_time)
        conditions.append(f"published_at <= ${len(params)}")
    if topics is not None:
        params.append(topics)
        conditions.append(f"topic_tags && ${len(params)}")

    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT d.*, t.id AS thread_id, t.title AS thread_title,
               t.lead_title AS thread_lead_title, t.places AS thread_places
        FROM (
            SELECT * FROM (
                SELECT DISTINCT ON (lower(title))
                       id, title, summary, source_url, source_name, source_language,
                       published_at, ingested_at, latitude, longitude, country_code,
                       region, topic_tags, sentiment_score, entities, image_url
                FROM articles
                WHERE {" AND ".join(conditions)}
                ORDER BY lower(title), published_at DESC, id
            ) deduped
            ORDER BY published_at DESC, id
            LIMIT $9
        ) d
        LEFT JOIN thread_members m ON m.article_id = d.id
        -- thread_reads.MIN_STORIES and MIN_SOURCES (it imports this module)
        LEFT JOIN threads t ON t.id = m.thread_id AND t.n_stories >= 3 AND t.n_sources >= 3
        ORDER BY d.published_at DESC, d.id
        """,
        *params,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


_UPSERT_ARTICLE_SQL = """
    INSERT INTO articles (
        title, summary, source_url, source_name, source_language,
        published_at, latitude, longitude, location,
        country_code, region, topic_tags, sentiment_score,
        entities, image_url, country_fips,
        themes, persons, orgs, names, counts,
        mentioned_countries, story_key
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8,
        ST_SetSRID(ST_MakePoint($8, $7), 4326)::geography,
        $9, $10, $11, $12, $13, $14, $15,
        $16, $17, $18, $19, $20,
        $21, $22
    )
    ON CONFLICT (source_url) DO UPDATE SET
        title = EXCLUDED.title,
        summary = EXCLUDED.summary,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        location = EXCLUDED.location,
        country_code = EXCLUDED.country_code,
        country_fips = EXCLUDED.country_fips,
        region = EXCLUDED.region,
        sentiment_score = EXCLUDED.sentiment_score,
        topic_tags = EXCLUDED.topic_tags,
        entities = EXCLUDED.entities,
        image_url = EXCLUDED.image_url,
        themes = EXCLUDED.themes,
        persons = EXCLUDED.persons,
        orgs = EXCLUDED.orgs,
        names = EXCLUDED.names,
        counts = EXCLUDED.counts,
        mentioned_countries = EXCLUDED.mentioned_countries,
        story_key = EXCLUDED.story_key
    """


def _upsert_article_args(article: dict[str, Any]) -> tuple:
    """Arguments $1-$22 of _UPSERT_ARTICLE_SQL for one article."""
    title = article.get("title", "")
    return (
        title,
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
        # GDELT's own (FIPS) code, kept beside the ISO country_code; '' if none.
        article.get("country_fips") or "",
        article.get("themes", []),
        article.get("persons", []),
        article.get("orgs", []),
        article.get("names", []),
        json.dumps(article.get("counts", [])),
        article.get("mentioned_countries", []),
        # From the title written as $1, so a re-crawl's new title rekeys it.
        story_key(title, article["source_url"]),
    )


async def upsert_articles(articles: list[dict[str, Any]]) -> int:
    """Bulk upsert articles, deduplicating on source_url.

    One ``executemany`` in one transaction: asyncpg pipelines the rows rather
    than waiting a round trip for each.

    Returns the number of rows upserted.
    """
    if not articles:
        return 0

    pool = await get_pool()
    rows = [_upsert_article_args(a) for a in articles]
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_UPSERT_ARTICLE_SQL, rows)

    logger.info("Upserted %d articles.", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------


# The six topic pills' article tags, in the pills' order: the dots' colours
# and the hover card's topic mix. Climate's tag is "environment".
GLOBE_TOPIC_TAGS = ("politics", "conflict", "technology", "environment", "economy", "health")


async def get_globe_points(
    *,
    timespan_hours: int = 24,
    cell_size: float = 2.0,
    limit: int = 500,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    """Return clustered globe points from the database, with their hover card's data.

    Only stories inside the window count: a window without any gives no
    points, never older stories.

    Groups articles into grid cells of *cell_size* degrees. Each cell carries
    its story count, its six topics' counts (``topic_mix``), its mean
    sentiment (``tone``) and a lead story: the newest with an https image, or
    the newest when none has one, so the headline and the image are one
    story's. The place name is the lead's region, cleaned by display_place
    with the lead's country code.

    The dot colour (``topic``) is the cell's most common of the six topics; a
    tie goes to the lead's tags, then the topic pills' order, and a cell
    with none of them is ``general``. Unlike the newest story's tag, it holds
    still as stories arrive.

    *topic*, an article tag such as ``"politics"``, keeps only the stories
    tagged with it, before the cells are counted, ranked and limited: the
    cells are the busiest for that topic, their counts and lead are of its
    stories alone, and ``topic`` is the tag (the dot is the topic's colour).
    """
    pool = await get_pool()

    if start_time and end_time:
        window = ["published_at BETWEEN $1 AND $2"]
        window_args: list[Any] = [start_time, end_time]
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
        window = ["published_at >= $1"]
        window_args = [cutoff]

    rows = await pool.fetch(*_globe_points_query(window, window_args, topic, cell_size, limit))
    return [_globe_point(row, topic) for row in rows]


async def get_globe_points_by_topic(
    *,
    timespan_hours: int = 24,
    cell_size: float = 2.0,
    limit: int = 500,
) -> dict[str | None, list[dict[str, Any]]]:
    """get_globe_points' live window for All (``None``) and each of the six topics, at once.

    Each list is what ``get_globe_points(timespan_hours=..., cell_size=...,
    limit=..., topic=tag)`` returns, from one query that reads the window's
    stories once (tests/test_globe_week_db.py holds them equal). A topic
    without stories in the window has an empty list. The 7-day globe's cache
    warmer: seven 7-day queries took 20-73 s each, cold, on production.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
    pool = await get_pool()
    rows = await pool.fetch(*_globe_by_topic_query(cutoff, timespan_hours, cell_size, limit))
    globes: dict[str | None, list[dict[str, Any]]] = {None: []}
    globes.update((tag, []) for tag in GLOBE_TOPIC_TAGS)
    for row in rows:  # each variant's cells, busiest first
        tag = row["tag"] or None
        globes[tag].append(_globe_point(row, tag))
    return globes


def _globe_point(row: Any, topic: str | None) -> dict[str, Any]:
    """A globe query's cell row as a point (a GlobeDataPoint); *topic* is the
    filter's article tag, or None for every story."""
    mix = {tag: row[tag] for tag in GLOBE_TOPIC_TAGS if row[tag]}
    return {
        "lat": row["lat"],
        "lng": row["lng"],
        "weight": min(row["article_count"] * 10, 500),
        "article_count": row["article_count"],
        "top_headline": row["title"] or "",
        "topic": topic or dominant_topic(mix, row["topic_tags"] or []),
        "location_name": display_place(row["region"], row["country_code"]),
        "country_code": row["country_code"] or "",
        "lead": globe_lead(row),
        "topic_mix": mix,
        "tone": round(row["tone"] or 0.0, 3),
    }


def globe_lead(row: Any) -> dict[str, Any]:
    """A cell's lead story (a GlobeLead) from its row's title, source_name,
    published_at, image_url and topic_tags."""
    tags = row["topic_tags"] or []
    return {
        "title": row["title"] or "",
        "source_name": row["source_name"] or "",
        "published_at": row["published_at"],
        "image_url": row["image_url"],
        "topic": tags[0] if tags else "general",
        # The card veils its image: conflict anywhere in its tags.
        "sensitive": "conflict" in tags,
    }


def dominant_topic(mix: dict[str, int], lead_tags: list[str]) -> str:
    """The most common of the six topics in *mix*: ties go to the lead's tags in
    order, then the topic pills' order. ``general`` when *mix* is empty."""
    if not mix:
        return "general"
    most = max(mix.values())
    tied = [tag for tag in GLOBE_TOPIC_TAGS if mix.get(tag) == most]
    return next((tag for tag in lead_tags if tag in tied), tied[0])


def _globe_points_query(
    conditions: list[str],
    args: list[Any],
    topic: str | None,
    cell_size: float,
    limit: int,
) -> tuple[Any, ...]:
    """SQL and arguments for get_globe_points, as ``pool.fetch`` takes them.

    *conditions* refer to *args* as ``$1``..``$n``; the topic, the cell size
    and the limit are numbered after them. No topic leaves its predicate out
    rather than writing ``$n IS NULL OR ...``, so the plan for every story
    never carries a topic test.

    One pass over the window's stories counts each cell, its six topics, its
    tone and its newest story's time (with and without an https image); only
    the busiest *limit* cells (ties broken by the cell, so the set is the same
    every time) then look up their lead, by that exact time (an index lookup
    on published_at) in the same cell, window and topic. A whole GDELT batch
    shares a time, so a cell with an https image takes only an https story at
    it: a NULL image_url's LIKE is NULL, which DESC alone would sort first.
    A correlated subquery per topic, or DISTINCT ON over the window, took
    11-15 s on production; this shape took 0.16-0.24 s.
    """
    conditions = list(conditions)
    args = list(args)
    if topic is not None:
        args.append(topic)
        conditions.append(f"topic_tags && ARRAY[${len(args)}::text]")
    # The WHERE filters the stories before anything reads them: the counts,
    # the ranking, the LIMIT and the lead all see matching rows only.
    where = " AND ".join(conditions)
    cell = f"${len(args) + 1}"
    topic_counts = ",\n".join(
        f"                COUNT(*) FILTER (WHERE topic_tags && '{{{tag}}}') AS {tag}"
        for tag in GLOBE_TOPIC_TAGS
    )
    query = f"""
        WITH cells AS (
            SELECT
                FLOOR(latitude / {cell}) AS lat_cell,
                FLOOR(longitude / {cell}) AS lng_cell,
                COUNT(*) AS article_count,
                AVG(sentiment_score) AS tone,
{topic_counts},
                MAX(published_at) AS newest,
                MAX(published_at) FILTER (WHERE image_url LIKE 'https://%') AS newest_with_image
            FROM articles
            {f"WHERE {where}" if where else ""}
            GROUP BY 1, 2
            ORDER BY article_count DESC, 1, 2
            LIMIT ${len(args) + 2}
        )
        SELECT
            cells.lat_cell * {cell} + {cell} / 2 AS lat,
            cells.lng_cell * {cell} + {cell} / 2 AS lng,
            cells.article_count,
            cells.tone,
            {", ".join(f"cells.{tag}" for tag in GLOBE_TOPIC_TAGS)},
            lead.title,
            lead.source_name,
            lead.published_at,
            lead.image_url,
            lead.region,
            lead.country_code,
            lead.topic_tags
        FROM cells
        CROSS JOIN LATERAL (
            SELECT title, source_name, published_at, image_url, region, country_code, topic_tags
            FROM articles
            WHERE published_at = COALESCE(cells.newest_with_image, cells.newest)
              AND (cells.newest_with_image IS NULL OR image_url LIKE 'https://%')
              AND FLOOR(latitude / {cell}) = cells.lat_cell
              AND FLOOR(longitude / {cell}) = cells.lng_cell
              {f"AND {where}" if where else ""}
            ORDER BY (image_url LIKE 'https://%') DESC NULLS LAST, id
            LIMIT 1
        ) lead
        ORDER BY cells.article_count DESC, cells.lat_cell, cells.lng_cell
    """
    return query, *args, cell_size, limit


def _globe_by_topic_query(
    cutoff: datetime, hours: int, cell_size: float, limit: int
) -> tuple[Any, ...]:
    """SQL and arguments for get_globe_points_by_topic, as ``pool.fetch`` takes them.

    The stories since *cutoff* are read once, an hour at a time: each hour is a
    range of idx_articles_published_at (the last hour has no end, as the live
    window has none). With 7-day retention a 7-day window is the whole table,
    where a single range is planned as a Seq Scan of every page; OFFSET 0 keeps
    each hour's subquery from being flattened into a join, so it is planned on
    its own, as an index range.

    Then each story counts for All ('') and for each of the six topics it is
    tagged with: per variant and cell, the counts, topic mix, tone and newest
    times that _globe_points_query's ``cells`` gives with that topic's filter;
    the same ranking (count, then the cell) and LIMIT, per variant. The lead is
    _globe_points_query's too, picked from the stories already read: at the
    cell's newest time with an https image (else its newest), an https story
    first when the cell has one, then non-null images, then the lowest id. Only
    each lead's wide columns are read again, by primary key.

    A cell's tone may differ in its last bit from get_globe_points' (a float
    sum, added in another order) before both round it to 3 places.
    """
    starts = [cutoff + timedelta(hours=h) for h in range(max(hours, 1))]
    ends: list[datetime | None] = [*starts[1:], None]
    topic_counts = ",\n".join(
        f"                COUNT(*) FILTER (WHERE topic_tags && '{{{tag}}}') AS {tag}"
        for tag in GLOBE_TOPIC_TAGS
    )
    query = f"""
        WITH stories AS MATERIALIZED (
            SELECT
                id,
                FLOOR(latitude / $3) AS lat_cell,
                FLOOR(longitude / $3) AS lng_cell,
                sentiment_score,
                topic_tags,
                published_at,
                image_url LIKE 'https://%' AS https
            FROM unnest($1::timestamptz[], $2::timestamptz[]) AS s(lo, hi)
            CROSS JOIN LATERAL (
                SELECT id, latitude, longitude, sentiment_score, topic_tags, published_at,
                       image_url
                FROM articles
                WHERE published_at >= s.lo AND published_at < COALESCE(s.hi, 'infinity')
                OFFSET 0
            ) a
        ),
        variants AS (
            SELECT v.tag, w.*
            FROM stories w
            CROSS JOIN LATERAL (
                SELECT '' AS tag
                UNION ALL
                SELECT t FROM unnest($4::text[]) AS t WHERE w.topic_tags && ARRAY[t]
            ) v
        ),
        cells AS (
            SELECT
                tag,
                lat_cell,
                lng_cell,
                COUNT(*) AS article_count,
                AVG(sentiment_score) AS tone,
{topic_counts},
                MAX(published_at) AS newest,
                MAX(published_at) FILTER (WHERE https) AS newest_with_image,
                ROW_NUMBER() OVER (
                    PARTITION BY tag ORDER BY COUNT(*) DESC, lat_cell, lng_cell
                ) AS rank
            FROM variants
            GROUP BY tag, lat_cell, lng_cell
        ),
        leads AS (
            SELECT DISTINCT ON (c.tag, c.rank) c.*, w.id AS lead_id
            FROM cells c
            JOIN stories w
              ON w.lat_cell = c.lat_cell
             AND w.lng_cell = c.lng_cell
             AND w.published_at = COALESCE(c.newest_with_image, c.newest)
            WHERE c.rank <= $5
              AND (c.newest_with_image IS NULL OR w.https)
              AND (c.tag = '' OR w.topic_tags && ARRAY[c.tag])
            ORDER BY c.tag, c.rank, w.https DESC NULLS LAST, w.id
        )
        SELECT
            l.tag,
            l.lat_cell * $3 + $3 / 2 AS lat,
            l.lng_cell * $3 + $3 / 2 AS lng,
            l.article_count,
            l.tone,
            {", ".join(f"l.{tag}" for tag in GLOBE_TOPIC_TAGS)},
            lead.title,
            lead.source_name,
            lead.published_at,
            lead.image_url,
            lead.region,
            lead.country_code,
            lead.topic_tags
        FROM leads l
        CROSS JOIN LATERAL (
            SELECT title, source_name, published_at, image_url, region, country_code, topic_tags
            FROM articles
            WHERE id = l.lead_id
            LIMIT 1
        ) lead
        ORDER BY l.tag, l.rank
    """
    return query, starts, ends, cell_size, list(GLOBE_TOPIC_TAGS), limit


async def get_hourly_density(*, timespan_hours: int = 24, offset_days: int = 0) -> dict[int, int]:
    """Return article counts bucketed by hour for a 24h window.

    offset_days=0 means the last 24h, offset_days=1 means 24-48h ago, etc.
    """
    pool = await get_pool()
    window_end = datetime.now(timezone.utc) - timedelta(days=offset_days)
    window_start = window_end - timedelta(hours=timespan_hours)
    rows = await pool.fetch(
        """
        SELECT EXTRACT(HOUR FROM published_at) AS hour,
               COUNT(*) AS count
        FROM articles
        WHERE published_at >= $1 AND published_at < $2
        GROUP BY hour
        ORDER BY hour
        """,
        window_start,
        window_end,
    )
    return {int(r["hour"]): int(r["count"]) for r in rows}


async def get_hourly_volume(days: int) -> list[dict[str, Any]]:
    """Stories per UTC hour over the last *days* days, for the timeline chart.

    One row (``hour``, ``count``) for every hour from the hour *days* days ago
    to the current one, oldest first; hours without stories count 0. Hours
    are truncated in UTC whatever the session time zone.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT h.hour, COALESCE(c.count, 0)::int AS count
        FROM generate_series(
               date_trunc('hour', now() - make_interval(days => $1), 'UTC'),
               date_trunc('hour', now(), 'UTC'),
               interval '1 hour') AS h(hour)
        LEFT JOIN (
          SELECT date_trunc('hour', published_at, 'UTC') AS hour, count(*) AS count
          FROM articles
          WHERE published_at >= date_trunc('hour', now() - make_interval(days => $1), 'UTC')
          GROUP BY 1
        ) c USING (hour)
        ORDER BY h.hour
        """,
        days,
    )
    return [{"hour": r["hour"], "count": r["count"]} for r in rows]


async def get_cell_spark(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    *,
    end_time: datetime,
    topic: str | None = None,
) -> list[int]:
    """Stories per UTC hour in a cell over the 24 hours up to *end_time*.

    24 counts, oldest first: the hour 23 before *end_time*'s, through
    *end_time*'s own (up to *end_time*). Hours without stories count 0.
    *topic*, an article tag, counts its stories only. The box is cell-sized
    and half-open, as in get_articles_in_bounds.
    """
    conditions, params = _cell_box(min_lat, min_lng, max_lat, max_lng)
    params.append(end_time)
    end = f"${len(params)}::timestamptz"
    first_hour = f"date_trunc('hour', {end}, 'UTC') - interval '23 hours'"
    conditions.append(f"published_at >= {first_hour} AND published_at <= ${len(params)}")
    if topic is not None:
        params.append(topic)
        conditions.append(f"topic_tags && ARRAY[${len(params)}::text]")

    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT h.hour, COALESCE(c.count, 0)::int AS count
        FROM generate_series(
               {first_hour},
               date_trunc('hour', {end}, 'UTC'),
               interval '1 hour') AS h(hour)
        LEFT JOIN (
          SELECT date_trunc('hour', published_at, 'UTC') AS hour, count(*) AS count
          FROM articles
          WHERE {" AND ".join(conditions)}
          GROUP BY 1
        ) c USING (hour)
        ORDER BY h.hour
        """,
        *params,
    )
    return [r["count"] for r in rows]


async def get_cell_entities(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    *,
    start_time: datetime,
    end_time: datetime,
    topic: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """The names a cell's stories mention most in a window: persons and orgs.

    Rows of ``name``, ``type`` ("person" or "org") and ``n``, the stories
    naming it, most first. A story is a title, so syndicated copies count
    once, and a name needs two stories. Names are GDELT's, uncleaned.
    *topic*, an article tag, keeps its stories only.
    """
    conditions, params = _cell_box(min_lat, min_lng, max_lat, max_lng)
    params.extend([start_time, end_time])
    conditions.append(f"published_at >= ${len(params) - 1} AND published_at <= ${len(params)}")
    if topic is not None:
        params.append(topic)
        conditions.append(f"topic_tags && ARRAY[${len(params)}::text]")
    params.append(limit)

    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        WITH cell AS (
          SELECT lower(title) AS story, persons, orgs
          FROM articles
          WHERE {" AND ".join(conditions)}
        )
        SELECT name, type, count(DISTINCT story) AS n
        FROM (
          SELECT story, unnest(persons) AS name, 'person' AS type FROM cell
          UNION ALL
          SELECT story, unnest(orgs) AS name, 'org' AS type FROM cell
        ) mentions
        GROUP BY name, type
        HAVING count(DISTINCT story) >= 2
        ORDER BY n DESC, name
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [{"name": r["name"], "type": r["type"], "n": r["n"]} for r in rows]


async def get_topic_counts() -> dict[str, int]:
    """Return a mapping of topic tag to article count."""
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM topic_counts()")
    return {row["topic"]: row["count"] for row in rows}
