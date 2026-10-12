"""What changed since a visit: the new stories, the places they're in, and the busiest five.

A story is a title without its outlet's name (see titles.py), so syndicated
copies count once, and a place is a 1° cell, as the globe's dots are.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.database import get_pool, globe_lead
from app.services.places import display_place
from app.services.titles import dedup_title_sql

TOP_PLACES = 5


def delta_query(since: datetime) -> tuple[Any, ...]:
    """SQL and arguments for the stories since *since*, as ``pool.fetch`` takes them.

    The stories since then are keyed once (``fresh``); from them come the
    distinct stories, the places with any (``cells``) and the 5 places with
    the most, each with its lead as the globe's: the newest new story,
    preferring an https image, by its exact time. Each row carries the
    totals and one top place; with no new stories, a single row of totals
    and NULLs.
    """
    query = f"""
        WITH fresh AS MATERIALIZED (
            SELECT FLOOR(latitude) AS lat_cell, FLOOR(longitude) AS lng_cell,
                   {dedup_title_sql("title")} AS story,
                   published_at, image_url
            FROM articles
            WHERE published_at >= $1
        ),
        cells AS (
            SELECT lat_cell, lng_cell,
                   count(DISTINCT story) AS new,
                   max(published_at) AS newest,
                   max(published_at) FILTER (WHERE image_url LIKE 'https://%') AS newest_with_image
            FROM fresh
            GROUP BY 1, 2
        ),
        top AS (
            SELECT lat_cell, lng_cell, new, newest, newest_with_image
            FROM cells
            ORDER BY new DESC, lat_cell, lng_cell
            LIMIT {TOP_PLACES}
        ),
        totals AS (
            SELECT (SELECT count(DISTINCT story) FROM fresh) AS new_stories,
                   (SELECT count(*) FROM cells) AS new_places
        )
        SELECT totals.new_stories, totals.new_places,
               top.lat_cell + 0.5 AS lat, top.lng_cell + 0.5 AS lng, top.new,
               lead.title, lead.source_name, lead.published_at, lead.image_url,
               lead.region, lead.topic_tags
        FROM totals
        LEFT JOIN (top CROSS JOIN LATERAL (
            SELECT title, source_name, published_at, image_url, region, topic_tags
            FROM articles
            WHERE published_at = COALESCE(top.newest_with_image, top.newest)
              AND (top.newest_with_image IS NULL OR image_url LIKE 'https://%')
              AND FLOOR(latitude) = top.lat_cell AND FLOOR(longitude) = top.lng_cell
            ORDER BY (image_url LIKE 'https://%') DESC NULLS LAST, id
            LIMIT 1
        ) lead) ON true
        ORDER BY top.new DESC, top.lat_cell, top.lng_cell
    """
    return query, since


async def get_delta(since: datetime) -> dict[str, Any]:
    """The distinct stories since *since*, the places they're in, and the top 5 places.

    ``{"new_stories", "new_places", "top": [{lat, lng, place, new, lead}]}``,
    the top places with the most new stories first.
    """
    pool = await get_pool()
    rows = await pool.fetch(*delta_query(since))
    return {
        "new_stories": rows[0]["new_stories"],
        "new_places": rows[0]["new_places"],
        "top": [
            {
                "lat": row["lat"],
                "lng": row["lng"],
                "place": display_place(row["region"]),
                "new": row["new"],
                "lead": globe_lead(row),
            }
            for row in rows
            if row["lat"] is not None
        ],
    }
