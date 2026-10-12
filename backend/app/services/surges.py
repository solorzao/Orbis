"""Surges: places whose coverage in the last two hours far outruns their week.

Per 1° cell (the globe's dots), ``recent`` is the distinct stories of the
last 2 hours and ``baseline`` the distinct stories of the 166 hours before
(the rest of the 7-day retention) per 2 hours: over 83 blocks. A story is a
title without its outlet's name (see titles.py), so one wire story run by 40
outlets is one story, not 40.

A cell surges when ``recent / max(baseline, 0.5)`` is at least 3, it has at
least 8 recent stories, and they come from at least 3 sources (one outlet's
burst isn't news breaking). The floor of half a story keeps a quiet place's
ratio finite and modest: a place with no baseline (a cold start) needs 8
stories for 16×, not a division by zero.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from app.services.database import GLOBE_TOPIC_TAGS, _dominant_topic, get_pool, globe_lead
from app.services.places import display_place
from app.services.titles import dedup_title_sql

logger = logging.getLogger(__name__)

RECENT = timedelta(hours=2)
# Articles are kept 7 days, so the baseline is the 166 hours before RECENT.
RETENTION = timedelta(days=7)
BASELINE_BLOCKS = 83  # 2-hour blocks in those 166 hours
BASELINE_FLOOR = 0.5  # stories per block a quiet place is assumed to have

MIN_RECENT = 8
MIN_SOURCES = 3
MIN_RATIO = 3
MAX_SURGES = 8


def surges_query(now: datetime, topic: str | None) -> tuple[Any, ...]:
    """SQL and arguments for the surging cells, as ``pool.fetch`` takes them.

    One pass over the last 2 hours keys each story and counts every cell's
    stories, sources and six topics (distinct stories each). Only the cells
    with enough stories and sources then read their week, joined by cell, so
    only their older stories are keyed. The ratio, threshold, order and limit
    follow; the top cells then look up their lead as the globe does: the
    newest recent story, preferring an https image, by its exact time.

    *topic*, an article tag, keeps its stories only, in both windows and the
    lead. Thresholds are literals; the windows and topic are arguments.
    """
    args: list[Any] = [now - RECENT, now - RETENTION]
    tag, a_tag = "", ""
    if topic is not None:
        args.append(topic)
        tag = f"AND topic_tags && ARRAY[${len(args)}::text]"
        a_tag = f"AND a.topic_tags && ARRAY[${len(args)}::text]"
    topic_counts = ",\n".join(
        f"                count(DISTINCT story) FILTER (WHERE topic_tags && '{{{t}}}') AS {t}"
        for t in GLOBE_TOPIC_TAGS
    )
    tags = ", ".join(GLOBE_TOPIC_TAGS)
    c_tags = ", ".join(f"c.{t}" for t in GLOBE_TOPIC_TAGS)
    baseline = f"COALESCE(b.stories, 0)::float8 / {BASELINE_BLOCKS}"
    query = f"""
        WITH recent AS (
            SELECT FLOOR(latitude) AS lat_cell, FLOOR(longitude) AS lng_cell,
                   {dedup_title_sql("title")} AS story,
                   source_name, topic_tags, published_at, image_url
            FROM articles
            WHERE published_at >= $1 {tag}
        ),
        candidates AS (
            SELECT lat_cell, lng_cell,
                count(DISTINCT story) AS recent,
{topic_counts},
                max(published_at) AS newest,
                max(published_at) FILTER (WHERE image_url LIKE 'https://%') AS newest_with_image
            FROM recent
            GROUP BY 1, 2
            HAVING count(DISTINCT story) >= {MIN_RECENT}
               AND count(DISTINCT source_name) >= {MIN_SOURCES}
        ),
        before AS (
            SELECT c.lat_cell, c.lng_cell,
                   count(DISTINCT {dedup_title_sql("a.title")}) AS stories
            FROM candidates c JOIN articles a
              ON FLOOR(a.latitude) = c.lat_cell AND FLOOR(a.longitude) = c.lng_cell
            WHERE a.published_at >= $2 AND a.published_at < $1 {a_tag}
            GROUP BY 1, 2
        ),
        ranked AS (
            SELECT c.lat_cell, c.lng_cell, c.recent, {c_tags}, c.newest, c.newest_with_image,
                   {baseline} AS baseline,
                   c.recent / GREATEST({baseline}, {BASELINE_FLOOR}) AS ratio
            FROM candidates c LEFT JOIN before b USING (lat_cell, lng_cell)
        ),
        top AS (
            SELECT lat_cell, lng_cell, recent, {tags}, newest, newest_with_image, baseline, ratio
            FROM ranked
            WHERE ratio >= {MIN_RATIO}
            ORDER BY ratio DESC, recent DESC, lat_cell, lng_cell
            LIMIT {MAX_SURGES}
        )
        SELECT top.lat_cell + 0.5 AS lat, top.lng_cell + 0.5 AS lng,
               top.recent, top.baseline, top.ratio,
               {", ".join(f"top.{t}" for t in GLOBE_TOPIC_TAGS)},
               lead.title, lead.source_name, lead.published_at, lead.image_url,
               lead.region, lead.country_code, lead.topic_tags
        FROM top
        CROSS JOIN LATERAL (
            SELECT title, source_name, published_at, image_url, region, country_code, topic_tags
            FROM articles
            WHERE published_at = COALESCE(top.newest_with_image, top.newest)
              AND (top.newest_with_image IS NULL OR image_url LIKE 'https://%')
              AND FLOOR(latitude) = top.lat_cell AND FLOOR(longitude) = top.lng_cell
              {tag}
            ORDER BY (image_url LIKE 'https://%') DESC NULLS LAST, id
            LIMIT 1
        ) lead
        ORDER BY top.ratio DESC, top.recent DESC, top.lat_cell, top.lng_cell
    """
    return query, *args


async def get_surges(now: datetime, topic: str | None = None) -> list[dict[str, Any]]:
    """The surging cells as of *now*, most surging first: at most 8 Surge dicts.

    If no story at all (of any topic) arrived in the last 2 hours, the feed
    is down rather than the world quiet: no surges, and the week isn't read.
    """
    pool = await get_pool()
    arrived = await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM articles WHERE published_at >= $1)", now - RECENT
    )
    if not arrived:
        logger.info("No stories in the last %s: no surges.", RECENT)
        return []
    rows = await pool.fetch(*surges_query(now, topic))
    return [_surge(row, topic) for row in rows]


def _surge(row: Any, topic: str | None) -> dict[str, Any]:
    mix = {t: row[t] for t in GLOBE_TOPIC_TAGS if row[t]}
    return {
        "lat": row["lat"],
        "lng": row["lng"],
        "place": display_place(row["region"], row["country_code"]),
        "recent": row["recent"],
        "baseline": round(row["baseline"], 2),
        "ratio": round(row["ratio"], 2),
        "topic": topic or _dominant_topic(mix, row["topic_tags"] or []),
        "lead": globe_lead(row),
    }
