"""Entity dossiers: where and how a person or organisation is in the news.

A dossier reads ``thread_members`` (migration 013), the narrow row thread
assignment writes for every assigned article, through its GIN index on
``entities`` (idx_thread_members_entities). Members carry each article's
story, outlet, time, place and tone, so the only ``articles`` reads are the
10 headlines, by primary key. The knowledge graph resolves the name (its
spelling: the most mentioned when stored spellings differ only in case) and
types the co-mentioned names (at most 15 probes of its UNIQUE btree).

Bounds: the counts read every match in the last 7 days (narrow rows, about
2-3 s cold for the heaviest names, then cached); places, timeline,
co-mentions and headlines come from the newest MAX_MENTIONS members in the
window, with ``capped`` when there were more.

Limits: ``entities`` doesn't record whether a name is a person or an org, so
a person and an org with the same name share a dossier (rare; not solved).
Members exist only for articles assigned since thread assignment shipped;
``since`` (the earliest member) lets the UI say "since {date}" until a week
has passed.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta

from app.services.database import get_pool
from app.services.places import display_place
from app.services.titles import display_title

# The most members a dossier reads for its places, timeline, co-mentions and
# headlines; beyond it the response says capped.
MAX_MENTIONS = 2000

# The dossier's windows, on members' published_at.
WINDOWS: dict[str, timedelta] = {"24h": timedelta(hours=24), "168h": timedelta(days=7)}

# The graph's node type for each entity type the API takes.
NODE_TYPES = {"person": "PERSON", "org": "ORG"}

# Mentions counted per name to rank names (search, and spellings that differ
# only in case), up to this many. The count is an index-only scan of
# idx_kg_edges_source_recent, newest first, except that each entry on a page
# written since kg_edges' last vacuum costs a heap fetch, a random read.
MENTION_COUNT_CAP = 100

_TOP_PLACES = 12
_TOP_CO_MENTIONS = 15
_HEADLINES = 10

# Distinct stories naming the entity in the last 24 h ($3..), the 24 h
# before ($4..$3) and 7 days ($2..), and per country in the window ($5..):
# one pass over every match. A member without a story_key is a story of
# its own. ``since`` is the earliest member of all (idx_thread_members_published).
_SUMMARY_SQL = """
    WITH m AS (
        SELECT coalesce(story_key::text, article_id::text) AS story, published_at, country_code
        FROM thread_members
        WHERE entities @> ARRAY[$1]::text[] AND published_at >= $2
    ),
    c AS (
        SELECT country_code, count(DISTINCT story)::int AS n
        FROM m
        WHERE published_at >= $5 AND country_code <> ''
        GROUP BY country_code
    )
    SELECT count(DISTINCT story) FILTER (WHERE published_at >= $3)::int AS h24,
           count(DISTINCT story) FILTER (WHERE published_at >= $4 AND published_at < $3)::int
               AS prev24,
           count(DISTINCT story)::int AS d7,
           ARRAY(SELECT country_code FROM c ORDER BY n DESC, country_code) AS country_codes,
           ARRAY(SELECT n FROM c ORDER BY n DESC, country_code) AS country_counts,
           (SELECT min(published_at) FROM thread_members) AS since
    FROM m
"""

# The newest members in the window, one past the cap to tell it was reached.
# Every match is read first (MATERIALIZED), then sorted: asyncpg reuses
# prepared statements, and a generic plan (default selectivities, an unknown
# LIMIT) could otherwise trade the entity index for a backward scan of the
# week by published_at, reading every member for a rare name.
_MEMBERS_SQL = """
    WITH m AS MATERIALIZED (
        SELECT article_id, story_key, source_name, published_at, latitude, longitude,
               region, country_code, entities, tone
        FROM thread_members
        WHERE entities @> ARRAY[$1]::text[] AND published_at >= $2
    )
    SELECT * FROM m
    ORDER BY published_at DESC, article_id
    LIMIT $3
"""

# The headlines' titles and links, by primary key: at most 10 rows.
_HEADLINE_SQL = "SELECT id, title, source_url FROM articles WHERE id = ANY($1::uuid[])"

# The graph's types of the co-mentioned names: the UNIQUE (type, name) btree.
_TYPES_SQL = """
    SELECT type, name FROM kg_nodes
    WHERE type IN ('PERSON', 'ORG') AND name = ANY($1::text[])
"""


def recent_mentions_sql(node: str, since: str, cap: str) -> str:
    """SQL for the *node*'s mentions (kg_edges) since *since*, counted up to *cap*.

    *node*, *since* and *cap* are SQL expressions (a column, a parameter).
    """
    return (
        "(SELECT count(*)::int FROM (SELECT 1 FROM kg_edges e"
        f" WHERE e.source_node_id = {node} AND e.created_at >= {since} LIMIT {cap}) x)"
    )


# A name of that type, in any case, as stored. Without wildcards (escaped),
# ILIKE is a case-insensitive equality the trigram index on kg_nodes.name
# serves. Stored spellings that differ only in case resolve to the most
# mentioned this week ($3, counted up to $4), then by name: the answer
# depends only on the lowercased name, as the dossier's cache key does.
_RESOLVE_SQL = f"""
    SELECT n.name FROM kg_nodes n
    WHERE n.type = $1 AND n.name ILIKE $2
    ORDER BY {recent_mentions_sql("n.id", "$3", "$4")} DESC, n.name
    LIMIT 1
"""


def like_escape(text: str) -> str:
    """*text* as a LIKE pattern that matches only itself (backslash, the default escape)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def trend(h24: int, prev24: int) -> float | None:
    """The last 24 h's stories over the 24 h before's, or None when there were none before."""
    if not prev24:
        return None
    return round(h24 / prev24, 2)


def _story(member: dict):
    """A member's story: its story_key, or the article alone when it has none."""
    key = member.get("story_key")
    return key if key is not None else ("article", member["article_id"])


def newest_per_story(members: list[dict]) -> list[dict]:
    """One member per story (its newest copy), newest first."""
    ordered = sorted(members, key=lambda m: m["article_id"])
    ordered.sort(key=lambda m: m["published_at"], reverse=True)
    seen: set = set()
    stories = []
    for member in ordered:
        story = _story(member)
        if story not in seen:
            seen.add(story)
            stories.append(member)
    return stories


def top_places(stories: list[dict]) -> list[dict]:
    """The 1° cells with the most stories (at most 12), named by each cell's newest story."""
    cells: dict[tuple[int, int], list[dict]] = {}
    for story in stories:  # newest first, so each cell's first is its newest
        cell = (math.floor(story["latitude"]), math.floor(story["longitude"]))
        cells.setdefault(cell, []).append(story)
    ranked = sorted(cells.values(), key=len, reverse=True)[:_TOP_PLACES]
    places = []
    for members in ranked:
        newest = members[0]
        tones = [m["tone"] for m in members if m.get("tone") is not None]
        places.append(
            {
                "lat": newest["latitude"],
                "lng": newest["longitude"],
                "place": display_place(newest.get("region"), newest.get("country_code")),
                "country_code": newest.get("country_code") or "",
                "n": len(members),
                "tone": round(sum(tones) / len(tones), 2) if tones else 0.0,
            }
        )
    return places


def timeline(stories: list[dict], now: datetime, timespan: str) -> list[dict]:
    """Stories per hour over the last 24 h, or per day over the last 7 days, oldest first.

    A story dated outside the window is counted in its nearest bucket.
    """
    step = timedelta(hours=1) if timespan == "24h" else timedelta(days=1)
    buckets = int(WINDOWS[timespan] / step)
    start = now - WINDOWS[timespan]
    counts = [0] * buckets
    for story in stories:
        index = math.floor((story["published_at"] - start) / step)
        counts[min(max(index, 0), buckets - 1)] += 1
    return [{"t": start + i * step, "n": n} for i, n in enumerate(counts)]


def co_mentioned(members: list[dict], name: str) -> list[dict]:
    """The 15 names in the most of these members' stories, other than *name* (any case).

    A story counts once per name, whichever of its copies names it.
    """
    per_story: dict = {}
    for member in members:
        per_story.setdefault(_story(member), set()).update(member["entities"] or ())
    own = name.casefold()
    counts = Counter(e for names in per_story.values() for e in names if e.casefold() != own)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:_TOP_CO_MENTIONS]
    return [{"name": e, "n": n} for e, n in ranked]


async def _headlines(pool, stories: list[dict]) -> list[dict]:
    """The stories as the globe shows a headline, with their articles' titles and links.

    A story whose article is gone is left out.
    """
    if not stories:
        return []
    rows = await pool.fetch(_HEADLINE_SQL, [s["article_id"] for s in stories])
    articles = {r["id"]: r for r in rows}
    return [
        {
            "title": display_title(articles[s["article_id"]]["title"] or ""),
            "source_name": s["source_name"] or "",
            "published_at": s["published_at"],
            "source_url": articles[s["article_id"]]["source_url"] or "",
            "place": display_place(s["region"], s["country_code"]),
        }
        for s in stories
        if s["article_id"] in articles
    ]


async def _with_types(pool, co: list[dict]) -> list[dict]:
    """The co-mentions with the types the graph has for each name: ``["person"]``,
    ``["org"]``, both when a person and an org share it, or none (not trackable)."""
    if not co:
        return co
    rows = await pool.fetch(_TYPES_SQL, [c["name"] for c in co])
    found: dict[str, set[str]] = {}
    for row in rows:
        found.setdefault(row["name"], set()).add(row["type"])
    return [
        {**c, "types": [t for t, node in NODE_TYPES.items() if node in found.get(c["name"], ())]}
        for c in co
    ]


async def resolve_entity(entity_type: str, name: str, now: datetime) -> str | None:
    """The stored name of the graph node of that type named *name* (any case), or None.

    Spellings that differ only in case: the most mentioned in the 7 days to
    *now* (counted up to MENTION_COUNT_CAP), then by name.
    """
    pool = await get_pool()
    return await pool.fetchval(
        _RESOLVE_SQL,
        NODE_TYPES[entity_type],
        like_escape(name),
        now - timedelta(days=7),
        MENTION_COUNT_CAP,
    )


async def get_entity_dossier(name: str, entity_type: str, timespan: str, now: datetime) -> dict:
    """The dossier of a resolved *name* (as stored) over the window (24h or 168h) to *now*.

    ``counts``, ``trend`` and ``countries`` count distinct stories among every
    match; the rest come from the newest MAX_MENTIONS members (``capped``).
    """
    pool = await get_pool()
    start = now - WINDOWS[timespan]
    summary = await pool.fetchrow(
        _SUMMARY_SQL,
        name,
        now - timedelta(days=7),
        now - timedelta(hours=24),
        now - timedelta(hours=48),
        start,
    )
    rows = await pool.fetch(_MEMBERS_SQL, name, start, MAX_MENTIONS + 1)
    members = [dict(r) for r in rows[:MAX_MENTIONS]]
    stories = newest_per_story(members)

    return {
        "name": name,
        "type": entity_type,
        "counts": {"h24": summary["h24"], "d7": summary["d7"]},
        "trend": trend(summary["h24"], summary["prev24"]),
        "capped": len(rows) > MAX_MENTIONS,
        "cap": MAX_MENTIONS,
        "countries": [
            {"country_code": code, "n": n}
            for code, n in zip(summary["country_codes"], summary["country_counts"])
        ],
        "places": top_places(stories),
        "timeline": timeline(stories, now, timespan),
        "co_mentions": await _with_types(pool, co_mentioned(members, name)),
        "headlines": await _headlines(pool, stories[:_HEADLINES]),
        "since": summary["since"],
    }
