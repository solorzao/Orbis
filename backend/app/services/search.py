"""Global search: people, organisations and story threads by name.

Places are searched client-side, over the globe's loaded points. Every read
is bounded, in three phases:
- names: at most 20 candidates from kg_entity_names (migration 017), the
  people and organisations alone, a few MB that stay cached, by prefix or by
  word similarity on its trigram index;
- counts: each candidate's stories this week from at most SEARCH_COUNT_CAP of
  its thread members, through idx_thread_members_entities, as the dossier
  counts them;
- threads: listed threads whose title contains q.
A search slower than a second logs each phase's time and the query's length,
never its text (INFO), so production can be checked without database access.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from app.services.database import get_pool
from app.services.entities import MENTION_COUNT_CAP, like_escape, member_mentions_sql
from app.services.thread_reads import LIST_HOURS, LISTED_SQL

logger = logging.getLogger(__name__)

# A name's coverage this week is read from at most this many members, so a
# heavy name costs no more on this type-ahead read. ``n`` is the distinct
# stories among them; ``capped`` says the cap was reached (the UI shows
# "{n}+"). Capped names rank first, among themselves by how close the name
# is: their n is a sample (whichever members the scan met first).
SEARCH_COUNT_CAP = MENTION_COUNT_CAP

_WINDOW = timedelta(days=7)
_PER_GROUP = 5
_SLOW_SEARCH_S = 1.0

# Up to 20 people and organisations whose name starts with q, or has a word
# that resembles q (pg_trgm's <%, word similarity at least 0.6), the closest
# first. Plain similarity (%) at its 0.3 threshold lets a 5-letter q match on
# 2 of its 6 trigrams: for "sunak", every name with a word starting "Su",
# thousands of candidates each rechecked and scored. Word similarity needs 4
# ("Suna..."), and still forgives a typo ("netanyhu").
_NAMES_SQL = """
    SELECT type, name, word_similarity($1, name) AS sim, similarity(name, $1) AS full_sim
    FROM kg_entity_names
    WHERE name ILIKE $2 OR $1 <% name
    ORDER BY sim DESC, full_sim DESC, name
    LIMIT 20
"""

# The candidates' stories this week, each name once (members record no type).
_COUNTS_SQL = f"""
    SELECT c.name, m.stories, m.capped
    FROM unnest($1::text[]) AS c(name)
    CROSS JOIN LATERAL {member_mentions_sql("c.name", "$2", "$3")} m
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
    with SEARCH_COUNT_CAP members or more first (``capped``), by how close the
    name is; then the rest by distinct stories (``n``), then closeness; up to
    five of each. A name in no story this week is left out. Threads are up to
    five listed threads (as the thread list selects them), the fastest first.
    """
    pool = await get_pool()
    started = time.perf_counter()
    names = await pool.fetch(_NAMES_SQL, q, like_escape(q) + "%")
    named = time.perf_counter()
    counts = {}
    if names:
        rows = await pool.fetch(
            _COUNTS_SQL, sorted({r["name"] for r in names}), now - _WINDOW, SEARCH_COUNT_CAP
        )
        counts = {r["name"]: r for r in rows}
    counted = time.perf_counter()
    threads = await _threads(pool, q, now - _THREAD_WINDOW)
    done = time.perf_counter()
    if done - started > _SLOW_SEARCH_S:
        # The query's length, never its text: it is what a visitor typed.
        logger.info(
            "Search of %d characters took %.2fs: names %.2fs (%d candidates), counts %.2fs,"
            " threads %.2fs",
            len(q),
            done - started,
            named - started,
            len(names),
            counted - named,
            done - counted,
        )

    candidates = [
        {**dict(r), "stories": counts[r["name"]]["stories"], "capped": counts[r["name"]]["capped"]}
        for r in names
        if r["name"] in counts
    ]
    ranked = sorted((c for c in candidates if c["stories"] > 0), key=_rank)
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
    return {"people": groups["PERSON"], "orgs": groups["ORG"], "threads": threads}


def _rank(row) -> tuple:
    """Capped names first, the closest first (their stories are a sample); then
    the rest by stories, then closeness; then by name. Closeness is how well q
    matches a word of the name, then the whole name (the shorter, the closer)."""
    close = (-row["sim"], -row["full_sim"])
    if row["capped"]:
        return (0, *close, -row["stories"], row["name"])
    return (1, -row["stories"], *close, row["name"])


async def _threads(pool, q: str, since: datetime) -> list[dict]:
    """Listed threads whose AI title or lead headline contains *q*, as ``{id, title}``."""
    rows = await pool.fetch(_THREADS_SQL, since, "%" + like_escape(q) + "%")
    return [{"id": r["id"], "title": r["title"] or r["lead_title"]} for r in rows]
