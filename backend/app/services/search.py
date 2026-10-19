"""Global search: people, organisations and story threads by name.

Places are searched client-side, over the globe's loaded points. Every read
is bounded: at most 20 candidate names (by prefix or trigram similarity, on
idx_kg_nodes_entity_name_trgm, the trigram index of people and organisations
only), each counted from at most SEARCH_COUNT_CAP of its thread members this
week, through idx_thread_members_entities: the narrow rows the dossier reads.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.database import get_pool
from app.services.entities import MENTION_COUNT_CAP, like_escape, member_mentions_sql
from app.services.thread_reads import LIST_HOURS, LISTED_SQL

# A name's coverage this week is read from at most this many members, so a
# heavy name costs no more on this type-ahead read. ``n`` is the distinct
# stories among them; ``capped`` says the cap was reached (the UI shows
# "{n}+"), and capped names rank first.
SEARCH_COUNT_CAP = MENTION_COUNT_CAP

_WINDOW = timedelta(days=7)
_PER_GROUP = 5

# Up to 20 people and organisations whose name starts with q or resembles it
# (pg_trgm's %), the closest first; then each one's stories this week, as the
# dossier counts them (member_mentions_sql). The literal type predicate lets
# every plan use idx_kg_nodes_entity_name_trgm (migration 016), never the
# full trigram index, where headlines (ARTICLE nodes) sharing q's words would
# each cost a heap read to be dropped.
_CANDIDATES_SQL = f"""
    WITH c AS (
        SELECT id, type, name, similarity(name, $1) AS sim
        FROM kg_nodes
        WHERE type IN ('PERSON', 'ORG') AND (name ILIKE $2 OR name % $1)
        ORDER BY sim DESC, name
        LIMIT 20
    )
    SELECT c.type, c.name, c.sim, m.stories, m.capped
    FROM c CROSS JOIN LATERAL {member_mentions_sql("c.name", "$3", "$4")} m
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

    People and organisations are ranked by coverage in the last 7 days: names
    with SEARCH_COUNT_CAP members or more first (``capped``), then by distinct
    stories (``n``, among the members read), then by how close the name is, up
    to five of each; a name in no story this week is left out. Threads are up to five listed
    threads (as the thread list selects them), the fastest first.
    """
    pool = await get_pool()
    week_ago = now - _WINDOW
    rows = await pool.fetch(_CANDIDATES_SQL, q, like_escape(q) + "%", week_ago, SEARCH_COUNT_CAP)
    ranked = sorted(
        (r for r in rows if r["stories"] > 0),
        key=lambda r: (not r["capped"], -r["stories"], -r["sim"], r["name"]),
    )
    groups: dict[str, list[dict]] = {"PERSON": [], "ORG": []}
    for row in ranked:
        group = groups[row["type"]]
        if len(group) < _PER_GROUP:
            group.append(
                {
                    "type": row["type"].lower(),
                    "name": row["name"],
                    "n": row["stories"],
                    "capped": row["capped"],
                }
            )
    return {
        "people": groups["PERSON"],
        "orgs": groups["ORG"],
        "threads": await _threads(pool, q, now - _THREAD_WINDOW),
    }


async def _threads(pool, q: str, since: datetime) -> list[dict]:
    """Listed threads whose AI title or lead headline contains *q*, as ``{id, title}``."""
    rows = await pool.fetch(_THREADS_SQL, since, "%" + like_escape(q) + "%")
    return [{"id": r["id"], "title": r["title"] or r["lead_title"]} for r in rows]
