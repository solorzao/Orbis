"""Global search: people, organisations and story threads by name.

Places are searched client-side, over the globe's loaded points. Every read
is bounded: at most 20 candidate names (by prefix or trigram similarity, on
the trigram index of kg_nodes.name), each counted over at most
SEARCH_COUNT_CAP of its edges in the week, through idx_kg_edges_source_recent.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.database import get_pool
from app.services.entities import MENTION_COUNT_CAP, like_escape, recent_mentions_sql
from app.services.thread_reads import LIST_HOURS, LISTED_SQL

# A name's mentions this week are counted up to this, so ``n`` is capped
# (the UI shows "100+"): on this type-ahead read a heavy name must not cost
# a heap fetch per mention. Ranking still holds, ties broken by similarity.
SEARCH_COUNT_CAP = MENTION_COUNT_CAP

_WINDOW = timedelta(days=7)
_PER_GROUP = 5

# Up to 20 people and organisations whose name starts with q or resembles it
# (pg_trgm's %), the closest first; then each one's mentions this week,
# counted up to the cap by a range scan of the recency index.
_CANDIDATES_SQL = f"""
    WITH c AS (
        SELECT id, type, name, similarity(name, $1) AS sim
        FROM kg_nodes
        WHERE type IN ('PERSON', 'ORG') AND (name ILIKE $2 OR name % $1)
        ORDER BY sim DESC, name
        LIMIT 20
    )
    SELECT c.type, c.name, c.sim, {recent_mentions_sql("c.id", "$3", "$4")} AS n
    FROM c
"""

# Story threads (migration 013), selected as the thread list selects them,
# whose AI title or lead headline contains q: threads alone, no articles.
# The list's own predicate (literal thresholds, so the plan can use the
# partial idx_threads_listed) over its longest window.
_THREADS_SQL = f"""
    SELECT id, title, lead_title
    FROM threads
    WHERE last_seen >= $1 AND {LISTED_SQL}
      AND (title ILIKE $2 OR lead_title ILIKE $2)
    ORDER BY velocity DESC, n_stories DESC, id LIMIT 5
"""
_THREAD_WINDOW = timedelta(hours=max(LIST_HOURS))


async def search(q: str, now: datetime) -> dict:
    """People, organisations and threads matching *q* (2-80 characters, trimmed).

    People and organisations are ranked by mentions in the last 7 days, then
    by how close the name is, up to five of each; a name not mentioned this
    week is left out. Threads are up to five listed threads (as the thread
    list selects them), the fastest first.
    """
    pool = await get_pool()
    week_ago = now - _WINDOW
    rows = await pool.fetch(_CANDIDATES_SQL, q, like_escape(q) + "%", week_ago, SEARCH_COUNT_CAP)
    ranked = sorted((r for r in rows if r["n"] > 0), key=lambda r: (-r["n"], -r["sim"], r["name"]))
    groups: dict[str, list[dict]] = {"PERSON": [], "ORG": []}
    for row in ranked:
        group = groups[row["type"]]
        if len(group) < _PER_GROUP:
            group.append({"type": row["type"].lower(), "name": row["name"], "n": row["n"]})
    return {
        "people": groups["PERSON"],
        "orgs": groups["ORG"],
        "threads": await _threads(pool, q, now - _THREAD_WINDOW),
    }


async def _threads(pool, q: str, since: datetime) -> list[dict]:
    """Listed threads whose AI title or lead headline contains *q*, as ``{id, title}``."""
    rows = await pool.fetch(_THREADS_SQL, since, "%" + like_escape(q) + "%")
    return [{"id": r["id"], "title": r["title"] or r["lead_title"]} for r in rows]
