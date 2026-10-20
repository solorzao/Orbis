"""Read queries for story threads (/api/threads and /api/threads/{id}).

Threads are assigned at ingestion (app.services.threads). These reads touch
``threads`` and ``thread_members`` only, plus ``articles`` by primary key
for a bounded set of ids: each listed thread's lead (at most ``limit``) and
a detail page's 20 stories.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from app.services.database import get_pool, globe_lead
from app.services.places import display_place
from app.services.titles import display_title

# Outlets beat stories: a thread is listed with 3 stories from 3 outlets (the
# predicate of migration 015's idx_threads_listed, and of the cluster join in
# database.get_articles_in_bounds).
MIN_STORIES = 3
MIN_SOURCES = 3
# That predicate as SQL, with the thresholds as literals (not parameters) so
# every plan can match idx_threads_listed: the list's, and search's
# (app.services.search).
LISTED_SQL = f"n_stories >= {MIN_STORIES} AND n_sources >= {MIN_SOURCES}"
# The list's live windows, in hours (the timeline's presets); search looks
# over the longest.
LIST_HOURS = (1, 6, 24, 168)
EMERGING_HOURS = 6  # first seen this recently: emerging
DEVELOPING_VELOCITY = 2  # this many stories in the last 6 hours: developing
LIST_PLACES = 20
DETAIL_ENTITIES = 12
DETAIL_ARTICLES = 20

# A story is its story_key; a NULL key, its own article.
_STORY = "COALESCE(story_key::text, 'a:' || article_id::text)"

_THREAD_COLUMNS = """
    id, title, synopsis, lead_title, first_seen, last_seen, n_stories, n_sources, velocity,
    countries, places, topic, lead_article_id
"""

# The lead's card fields, from its article by primary key; NULL once it is purged.
_LEAD = """
    SELECT t.*, a.title AS lead_article_title, a.source_name AS lead_source_name,
           a.published_at AS lead_published_at, a.image_url AS lead_image_url,
           a.topic_tags AS lead_topic_tags
    FROM {threads} t LEFT JOIN articles a ON a.id = t.lead_article_id
"""

# A thread merged into another answers as the thread its merges end in (share
# links and the UI hold thread ids): merged_into is followed by primary key,
# through later merges, at most MERGE_HOPS. One that ends in a purged thread
# (merged_into has no foreign key) is unknown.
MERGE_HOPS = 10
DETAIL_SQL = f"""
    WITH RECURSIVE chain (id, next, hops) AS (
        SELECT id, merged_into, 0 FROM threads WHERE id = $1
        UNION ALL
        SELECT t.id, t.merged_into, c.hops + 1
        FROM chain c JOIN threads t ON t.id = c.next
        WHERE c.hops < {MERGE_HOPS}
    ),
    one AS (
        SELECT {_THREAD_COLUMNS} FROM threads
        WHERE id = (SELECT id FROM chain WHERE next IS NULL)
    )
    {_LEAD.format(threads="one")}
"""

ENTITIES_SQL = f"""
    SELECT e AS name, count(DISTINCT {_STORY}) AS n
    FROM thread_members, unnest(entities) AS e
    WHERE thread_id = $1
    GROUP BY e
    ORDER BY n DESC, e
    LIMIT {DETAIL_ENTITIES}
"""

TIMELINE_SQL = f"""
    SELECT date_trunc('hour', published_at, 'UTC') AS hour, count(DISTINCT {_STORY}) AS n,
           avg(tone) AS tone
    FROM thread_members
    WHERE thread_id = $1
    GROUP BY 1
    ORDER BY 1
"""

# The page of stories (each as its newest copy) before the primary-key join.
ARTICLES_SQL = f"""
    WITH stories AS (
        SELECT DISTINCT ON ({_STORY}) article_id, published_at, region, country_code
        FROM thread_members
        WHERE thread_id = $1
        ORDER BY {_STORY}, published_at DESC, article_id
    ),
    page AS (
        SELECT * FROM stories ORDER BY published_at DESC, article_id LIMIT $2 OFFSET $3
    )
    SELECT a.title, a.source_name, a.published_at, a.source_url, p.region, p.country_code
    FROM page p JOIN articles a ON a.id = p.article_id
    ORDER BY p.published_at DESC, p.article_id
"""


def list_query(now: datetime, hours: int, topic: str | None, limit: int) -> tuple[str, list]:
    """The list's SQL and arguments. No topic leaves its predicate out (no
    ``$n IS NULL OR``), so neither plan has to cover both. The thresholds are
    constants, not parameters, so every plan matches the partial index
    idx_threads_listed (migration 015) and skips the single-story threads."""
    args: list[Any] = [now - timedelta(hours=hours), limit]
    topic_sql = ""
    if topic is not None:
        args.append(topic)
        topic_sql = "AND topic = $3"
    query = f"""
        WITH listed AS (
            SELECT {_THREAD_COLUMNS}
            FROM threads
            WHERE last_seen >= $1 AND {LISTED_SQL}
                  {topic_sql}
            ORDER BY velocity DESC, n_stories DESC, id
            LIMIT $2
        )
        {_LEAD.format(threads="listed")}
        ORDER BY t.velocity DESC, t.n_stories DESC, t.id
    """
    return query, args


def thread_status(first_seen: datetime, velocity: int, now: datetime) -> str:
    if first_seen >= now - timedelta(hours=EMERGING_HOURS):
        return "emerging"
    if velocity >= DEVELOPING_VELOCITY:
        return "developing"
    return "fading"


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _place(place: dict) -> dict:
    return {
        "lat": place["lat"],
        "lng": place["lng"],
        "place": display_place(place.get("region"), place.get("country_code")),
        "country_code": place.get("country_code") or "",
        "first_seen": datetime.fromisoformat(place["first_seen"]),
        "n": place["n"],
    }


def thread_item(row: Any, now: datetime, places_cap: int | None = LIST_PLACES) -> dict:
    """A list item (a ThreadSummary) from a list or detail row."""
    places = _json(row["places"]) or []
    lead = None
    if row["lead_published_at"] is not None:  # the lead's article is still kept
        lead = globe_lead(
            {
                "title": row["lead_article_title"],
                "source_name": row["lead_source_name"],
                "published_at": row["lead_published_at"],
                "image_url": row["lead_image_url"],
                "topic_tags": row["lead_topic_tags"],
            }
        )
    return {
        "id": row["id"],
        "title": row["title"] or row["lead_title"],
        "synopsis": row["synopsis"],
        "status": thread_status(row["first_seen"], row["velocity"], now),
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "n_stories": row["n_stories"],
        "n_sources": row["n_sources"],
        "velocity": row["velocity"],
        "countries": list(row["countries"] or []),
        "places": [_place(p) for p in places[:places_cap]],
        "topic": row["topic"] or "general",
        "lead": lead,
    }


async def list_threads(now: datetime, hours: int, topic: str | None, limit: int) -> list[dict]:
    """Threads seen in the last *hours* with 3+ stories from 3+ outlets, fastest first."""
    query, args = list_query(now, hours, topic, limit)
    pool = await get_pool()
    return [thread_item(r, now) for r in await pool.fetch(query, *args)]


async def thread_detail(thread_id: int, offset: int, now: datetime) -> dict | None:
    """One thread (a ThreadDetail), or None for an unknown id. A merged thread's id
    answers as the thread it joined, with that thread's id.

    The thread's row first, so an unknown id costs one query; then its three
    parts at once, each on its own pool connection.
    """
    pool = await get_pool()
    row = await pool.fetchrow(DETAIL_SQL, thread_id)
    if row is None:
        return None
    resolved = row["id"]
    entities, timeline, articles = await asyncio.gather(
        pool.fetch(ENTITIES_SQL, resolved),
        pool.fetch(TIMELINE_SQL, resolved),
        pool.fetch(ARTICLES_SQL, resolved, DETAIL_ARTICLES, offset),
    )
    return {
        **thread_item(row, now),
        "entities": [{"name": r["name"], "n": r["n"]} for r in entities],
        "spread": thread_item(row, now, places_cap=None)["places"],
        "timeline": [
            {
                "hour": r["hour"],
                "n": r["n"],
                "tone": float(r["tone"]) if r["tone"] is not None else None,
            }
            for r in timeline
        ],
        "articles": [
            {
                "title": display_title(r["title"] or ""),
                "source_name": r["source_name"] or "",
                "published_at": r["published_at"],
                "source_url": r["source_url"],
                "place": display_place(r["region"], r["country_code"]),
            }
            for r in articles
        ],
    }


def article_thread(row: Any) -> dict | None:
    """A cluster article's thread (an ArticleThread) from its row's thread_* columns:
    its title and its first three place names, or None when it has no listed thread."""
    thread_id = row.get("thread_id")
    if thread_id is None:
        return None
    names: list[str] = []
    for place in _json(row.get("thread_places")) or []:
        name = display_place(place.get("region"), place.get("country_code"))
        if name and name not in names:
            names.append(name)
        if len(names) == 3:
            break
    return {
        "id": thread_id,
        "title": row.get("thread_title") or row.get("thread_lead_title") or "",
        "places": names,
    }
