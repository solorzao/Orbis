"""Global search: people, organisations and story threads by name.

Places are searched client-side, over the globe's loaded points. Every read
is bounded: at most 20 candidate names (by prefix or trigram similarity, on
the trigram index of kg_nodes.name), each counted over at most
MAX_MENTIONS of its edges in the week, through idx_kg_edges_source_recent.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.database import get_pool
from app.services.entities import MAX_MENTIONS, like_escape

__all__ = ["MAX_MENTIONS", "search"]

_WINDOW = timedelta(days=7)
_PER_GROUP = 5

# Up to 20 people and organisations whose name starts with q or resembles it
# (pg_trgm's %), the closest first; then each one's mentions this week,
# counted up to the cap by a range scan of the recency index.
_CANDIDATES_SQL = """
    WITH c AS (
        SELECT id, type, name, similarity(name, $1) AS sim
        FROM kg_nodes
        WHERE type IN ('PERSON', 'ORG') AND (name ILIKE $2 OR name % $1)
        ORDER BY sim DESC, name
        LIMIT 20
    )
    SELECT c.type, c.name, c.sim,
           (SELECT count(*)::int FROM (
                SELECT 1 FROM kg_edges e
                WHERE e.source_node_id = c.id AND e.created_at >= $3
                LIMIT $4
            ) x) AS n
    FROM c
"""

# Story threads (migration 013), selected as the thread list selects them,
# whose AI title or lead headline contains q: threads alone, no articles.
_THREADS_SQL = """
    SELECT t.id, t.title, t.lead_title
    FROM threads t
    WHERE t.last_seen >= $1
      AND t.n_stories >= 3 AND t.n_sources >= 3
      AND (t.title ILIKE $2 OR t.lead_title ILIKE $2)
    ORDER BY t.velocity DESC, t.n_stories DESC, t.id LIMIT 5
"""


async def search(q: str, now: datetime) -> dict:
    """People, organisations and threads matching *q* (2-80 characters, trimmed).

    People and organisations are ranked by mentions in the last 7 days, then
    by how close the name is, up to five of each; a name not mentioned this
    week is left out. Threads are up to five listed threads (as the thread
    list selects them), the fastest first.
    """
    pool = await get_pool()
    week_ago = now - _WINDOW
    rows = await pool.fetch(_CANDIDATES_SQL, q, like_escape(q) + "%", week_ago, MAX_MENTIONS)
    ranked = sorted((r for r in rows if r["n"] > 0), key=lambda r: (-r["n"], -r["sim"], r["name"]))
    groups: dict[str, list[dict]] = {"PERSON": [], "ORG": []}
    for row in ranked:
        group = groups[row["type"]]
        if len(group) < _PER_GROUP:
            group.append({"type": row["type"].lower(), "name": row["name"], "n": row["n"]})
    return {
        "people": groups["PERSON"],
        "orgs": groups["ORG"],
        "threads": await _threads(pool, q, week_ago),
    }


async def _threads(pool, q: str, since: datetime) -> list[dict]:
    """Listed threads whose AI title or lead headline contains *q*, as ``{id, title}``."""
    rows = await pool.fetch(_THREADS_SQL, since, "%" + like_escape(q) + "%")
    return [{"id": r["id"], "title": r["title"] or r["lead_title"]} for r in rows]
