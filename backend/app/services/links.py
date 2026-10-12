"""Co-coverage links: countries the window's stories cover together.

A story links its own country (``articles.country_code``, where it is
placed on the globe) with each other country it mentions
(``articles.mentioned_countries``). A pair's ``n`` is how many stories link
it, whichever side they come from.

Hubs (the US, Russia) are in most pairs, so links are ranked by lift by
default: ``n_ab * N / (n_a * n_b)``, how many times more often the two are
covered together than if each story's countries were independent. ``N`` is
the window's linking stories, ``n_a`` those touching country a.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Literal

from app.services.country_centroids import centroid
from app.services.database import get_pool

logger = logging.getLogger(__name__)

# The six topic pills' article tags (Climate is "environment"), in tie order.
TOPIC_TAGS = ("politics", "conflict", "technology", "environment", "economy", "health")

# Lift is noisy on few stories: a pair needs this many to rank by it.
MIN_LIFT_STORIES = 5

# So that the US does not take every slot.
MAX_ARCS_PER_COUNTRY = 6

Rank = Literal["lift", "count"]


def _window(start: datetime, end: datetime, topic: str | None) -> tuple[list[str], list[Any]]:
    """The window and topic predicates on articles, as SQL conditions and their arguments."""
    conditions = ["published_at >= $1", "published_at <= $2"]
    args: list[Any] = [start, end]
    if topic is not None:
        args.append(topic)
        conditions.append(f"topic_tags && ARRAY[${len(args)}::text]")
    return conditions, args


def links_query(start: datetime, end: datetime, topic: str | None) -> tuple[Any, ...]:
    """SQL and arguments for every country pair in the window, as ``pool.fetch`` takes them.

    Each row is a pair (``a`` < ``b``) with its stories ``n``, mean ``tone``,
    most common origin ``from_iso``, stories per topic tag, and what lift
    needs: ``n_a``, ``n_b`` and the window's linking stories, ``total``.

    Every count is ``count(*)``, which is exact because each story's
    ``mentioned_countries`` holds distinct codes (ingestion and the backfill
    see to it): a story gives a pair at most one row. ``count(DISTINCT id)``
    and ``mode()`` would sort every pair row instead of hashing: 0.40 s rather
    than 0.15 s at 7 days on 150K synthetic stories with 89K mentions (same
    rows). A pair's origin is always one of its two ends, so the most common
    one is a count against half.
    """
    conditions, args = _window(start, end, topic)
    topic_counts = ",\n".join(
        f"count(*) FILTER (WHERE l.topic_tags && '{{{tag}}}') AS {tag}" for tag in TOPIC_TAGS
    )
    query = f"""
        WITH linking AS (
            SELECT country_code, topic_tags, sentiment_score, others
            FROM (
                SELECT country_code, topic_tags, sentiment_score,
                       array_remove(mentioned_countries, country_code) AS others
                FROM articles
                WHERE {" AND ".join(conditions)}
                  AND country_code <> '' AND cardinality(mentioned_countries) > 0
            ) w
            WHERE cardinality(others) > 0
        ),
        touched AS (
            SELECT c, count(*) AS n
            FROM linking l, unnest(l.others || l.country_code) AS c
            GROUP BY c
        ),
        grouped AS (
            SELECT LEAST(l.country_code, m) AS a, GREATEST(l.country_code, m) AS b,
                   count(*) AS n, avg(l.sentiment_score) AS tone,
                   count(*) FILTER (WHERE l.country_code < m) AS from_a,
                   {topic_counts}
            FROM linking l, unnest(l.others) AS m
            GROUP BY 1, 2
        )
        SELECT g.a, g.b, g.n, g.tone,
               CASE WHEN 2 * g.from_a >= g.n THEN g.a ELSE g.b END AS from_iso,
               {", ".join(f"g.{tag}" for tag in TOPIC_TAGS)},
               ta.n AS n_a, tb.n AS n_b,
               (SELECT count(*) FROM linking) AS total
        FROM grouped g
        JOIN touched ta ON ta.c = g.a
        JOIN touched tb ON tb.c = g.b
    """
    return query, *args


async def get_link_pairs(start: datetime, end: datetime, topic: str | None) -> list[dict]:
    """Every country pair the window's stories (of *topic*, if given) link."""
    pool = await get_pool()
    rows = await pool.fetch(*links_query(start, end, topic))
    return [dict(r) for r in rows]


def dominant_topic(row: dict) -> str:
    """The topic tag most of the row's stories carry (ties: TOPIC_TAGS order), or general."""
    best = max(TOPIC_TAGS, key=lambda tag: (row.get(tag) or 0, -TOPIC_TAGS.index(tag)))
    return best if row.get(best) else "general"


def lift(n: int, n_a: int, n_b: int, total: int) -> float:
    """How many times more often a and b are covered together than by chance."""
    return n * total / (n_a * n_b) if n_a and n_b else 0.0


def _country(iso: str) -> dict:
    point = centroid(iso)
    return {"iso": iso, "name": point.name, "lat": point.lat, "lng": point.lng}


def rank_links(rows: list[dict], rank: Rank, limit: int, topic: str | None = None) -> list[dict]:
    """The top *limit* pairs as links, at most MAX_ARCS_PER_COUNTRY per country.

    ``lift`` ranks pairs with MIN_LIFT_STORIES stories or more by lift, then
    stories; ``count`` ranks every pair by stories, then lift. Pairs with a
    country that has no label point are dropped first. *topic* is the
    window's topic filter: every link is then of that topic.
    """
    usable = [r for r in rows if centroid(r["a"]) and centroid(r["b"])]
    if dropped := len(rows) - len(usable):
        logger.debug("Links: dropped %d country pairs without a label point.", dropped)
    scored = [(lift(r["n"], r["n_a"], r["n_b"], r["total"]), r) for r in usable]
    if rank == "lift":
        scored = [(x, r) for x, r in scored if r["n"] >= MIN_LIFT_STORIES]
        scored.sort(key=lambda s: (-s[0], -s[1]["n"], s[1]["a"], s[1]["b"]))
    else:
        scored.sort(key=lambda s: (-s[1]["n"], -s[0], s[1]["a"], s[1]["b"]))

    arcs: Counter[str] = Counter()
    links = []
    for score, row in scored:
        if len(links) == limit:
            break
        if arcs[row["a"]] >= MAX_ARCS_PER_COUNTRY or arcs[row["b"]] >= MAX_ARCS_PER_COUNTRY:
            continue
        arcs.update((row["a"], row["b"]))
        links.append(
            {
                "a": _country(row["a"]),
                "b": _country(row["b"]),
                "n": row["n"],
                "lift": round(score, 2),
                "topic": topic or dominant_topic(row),
                "tone": round(row["tone"] or 0.0, 2),
                "from": row["from_iso"],
            }
        )
    return links
