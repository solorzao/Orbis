"""Retrieval functions for the Orbis embedded agent.

Provides semantic search, knowledge-graph traversal, keyword filtering,
trending-topic aggregation, entity lookup, and article text extraction
against the Orbis database.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from app.config import settings
from app.services.database import get_pool
from app.services.scraper import extract_article_text

logger = logging.getLogger("orbis.retrieval")

# An HNSW index scan returns at most hnsw.ef_search rows (pgvector default 40),
# so semantic_search never asks for more. The agent already caps limit at 20.
_HNSW_EF_SEARCH = 40


def _get_openai_client() -> Any | None:
    """Return an AsyncOpenAI client, or None if unavailable."""
    if not settings.openai_api_key:
        return None
    try:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=settings.openai_api_key)
    except ImportError:
        logger.warning("openai package not installed — skipping embeddings.")
        return None


async def semantic_search(query: str, limit: int = 10) -> list[dict]:
    """Search articles by semantic similarity to *query*."""
    client = _get_openai_client()
    if client is None:
        return []

    try:
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=[query],
        )
        vec = response.data[0].embedding
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"

        pool = await get_pool()
        # The cast must match the half-precision HNSW index expression in
        # database/migrations/008_halfvec_embedding_index.sql exactly, or the
        # planner falls back to a sequential scan.
        rows = await pool.fetch(
            """
            SELECT id, title, source_url, source_name, latitude, longitude,
                   published_at, sentiment_score,
                   embedding::halfvec(1536) <=> $1::halfvec(1536) AS distance
            FROM articles
            WHERE embedding IS NOT NULL
            ORDER BY embedding::halfvec(1536) <=> $1::halfvec(1536)
            LIMIT $2
            """,
            vec_str,
            min(limit, _HNSW_EF_SEARCH),
        )
        return [dict(r) for r in rows]
    except Exception:
        logger.error("Semantic search failed.", exc_info=True)
        return []


# Co-mentions are not stored as edges. Two entities are co-mentioned when
# both have a MENTIONED_IN edge (entity -> ARTICLE node) to the same ARTICLE
# node; weight is the number of distinct shared ARTICLE nodes. Legacy stored
# CO_MENTIONED rows are ignored by every query here and age out with their
# articles (kg_edges.article_id is ON DELETE CASCADE).
#
# Only the start entity's most recent article nodes ($2) are joined, which
# bounds the cost for hot entities with tens of thousands of mentions.
# The representative article prefers one that mentions the start entity too:
# ARTICLE nodes are keyed by title, so a same-titled copy may not.
_CO_MENTIONS_SQL = """
    WITH mine AS (
        SELECT target_node_id, article_id
        FROM kg_edges
        WHERE source_node_id = $1 AND rel_type = 'MENTIONED_IN'
        ORDER BY created_at DESC
        LIMIT $2
    )
    SELECT n.id, n.type, n.name, 'CO_MENTIONED' AS rel_type,
           count(DISTINCT e2.target_node_id)::int AS weight,
           (array_agg(e2.article_id
                      ORDER BY (e2.article_id = mine.article_id) DESC NULLS LAST,
                               e2.created_at DESC, e2.article_id))[1] AS article_id,
           1 AS depth
    FROM mine
    JOIN kg_edges e2 ON e2.target_node_id = mine.target_node_id
                    AND e2.rel_type = 'MENTIONED_IN'
                    AND e2.source_node_id <> $1
    JOIN kg_nodes n ON n.id = e2.source_node_id
    GROUP BY n.id, n.type, n.name
    ORDER BY weight DESC, max(e2.created_at) DESC, n.name
    LIMIT 20
"""
_CO_MENTION_ARTICLE_WINDOW = 500
_CO_MENTIONS_TIMEOUT_S = 2.0

_GRAPH_CONNECTION_LIMIT = 50


async def _co_mentions(pool: Any, node_id: Any) -> list[dict]:
    """Top-20 entities sharing a recent article with *node_id*, as CO_MENTIONED rows.

    Returns ``[]`` if the query times out, so callers still return their
    stored-edge results instead of failing the whole tool call.
    """
    try:
        rows = await pool.fetch(
            _CO_MENTIONS_SQL,
            node_id,
            _CO_MENTION_ARTICLE_WINDOW,
            timeout=_CO_MENTIONS_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Co-mention query for node %s timed out after %.1fs; skipping co-mentions.",
            node_id,
            _CO_MENTIONS_TIMEOUT_S,
        )
        return []
    return [dict(r) for r in rows]


async def _traverse_stored_edges(
    pool: Any,
    start_id: Any,
    rel_type: str | None,
    depth: int,
    limit: int,
) -> list[dict]:
    """Walk stored edges (never CO_MENTIONED) from *start_id* up to *depth* hops."""
    rel_filter = "AND e.rel_type = $2" if rel_type else ""
    params: list[Any] = [start_id]
    if rel_type:
        params.append(rel_type)

    depth_param = f"${len(params) + 1}"
    params.append(depth)

    limit_param = f"${len(params) + 1}"
    params.append(limit)

    query = f"""
        WITH RECURSIVE traverse AS (
            SELECT
                n.id,
                n.type,
                n.name,
                e.rel_type,
                e.weight,
                e.article_id,
                1 AS depth
            FROM kg_edges e
            JOIN kg_nodes n
                ON n.id = CASE
                    WHEN e.source_node_id = $1 THEN e.target_node_id
                    ELSE e.source_node_id
                END
            WHERE (e.source_node_id = $1 OR e.target_node_id = $1)
            AND e.rel_type <> 'CO_MENTIONED'
            {rel_filter}
          UNION
            SELECT
                n2.id,
                n2.type,
                n2.name,
                e2.rel_type,
                e2.weight,
                e2.article_id,
                t.depth + 1
            FROM traverse t
            JOIN kg_edges e2
                ON e2.source_node_id = t.id OR e2.target_node_id = t.id
            JOIN kg_nodes n2
                ON n2.id = CASE
                    WHEN e2.source_node_id = t.id THEN e2.target_node_id
                    ELSE e2.source_node_id
                END
            WHERE t.depth < {depth_param}
            AND e2.rel_type <> 'CO_MENTIONED'
            {"AND e2.rel_type = $2" if rel_type else ""}
        )
        SELECT DISTINCT id, type, name, rel_type, weight, article_id, depth
        FROM traverse
        ORDER BY depth, weight DESC
        LIMIT {limit_param}
    """
    rows = await pool.fetch(query, *params)
    return [dict(r) for r in rows]


async def graph_traverse(
    entity_name: str,
    rel_type: str | None = None,
    depth: int = 2,
) -> dict:
    """Traverse the knowledge graph starting from *entity_name*.

    Returns connected nodes up to *depth* hops (capped at 3), plus the
    source articles that establish those relationships. Co-mentions are
    computed from shared articles and listed first, as depth-1 rows.
    *rel_type* is case-insensitive; an empty string means no filter.
    """
    rel_type = (rel_type or "").upper() or None
    depth = min(depth, 3)

    try:
        pool = await get_pool()

        start = await pool.fetchrow(
            "SELECT id, type, name FROM kg_nodes WHERE name ILIKE '%' || $1 || '%' "
            "ORDER BY similarity(name, $1) DESC LIMIT 1",
            entity_name,
        )
        if start is None:
            return {"entity": None, "connections": [], "articles": []}

        start_id = start["id"]

        connections: list[dict] = []
        if rel_type in (None, "CO_MENTIONED"):
            connections = await _co_mentions(pool, start_id)

        if rel_type != "CO_MENTIONED":
            connections += await _traverse_stored_edges(
                pool, start_id, rel_type, depth, _GRAPH_CONNECTION_LIMIT - len(connections)
            )

        # Collect unique article IDs from traversal edges
        article_ids = list({c["article_id"] for c in connections if c["article_id"]})

        articles: list[dict] = []
        if article_ids:
            art_rows = await pool.fetch(
                """
                SELECT id, title, source_url, source_name, latitude, longitude,
                       published_at, sentiment_score
                FROM articles
                WHERE id = ANY($1::uuid[])
                ORDER BY published_at DESC
                LIMIT 15
                """,
                article_ids,
            )
            articles = [dict(r) for r in art_rows]

        return {
            "entity": {"id": str(start["id"]), "type": start["type"], "name": start["name"]},
            "connections": connections,
            "articles": articles,
        }
    except Exception:
        logger.error("Graph traversal failed.", exc_info=True)
        return {"entity": None, "connections": [], "articles": []}


async def keyword_search(
    terms: str | None = None,
    topic: str | None = None,
    country: str | None = None,
    time_range: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search articles using keyword / metadata filters."""
    try:
        pool = await get_pool()

        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if terms:
            conditions.append(f"title ILIKE '%' || ${idx} || '%'")
            params.append(terms)
            idx += 1

        if topic:
            conditions.append(f"${idx} = ANY(topic_tags)")
            params.append(topic)
            idx += 1

        if country:
            # Stored codes are upper-case ISO 3166-1 alpha-2.
            conditions.append(f"country_code = ${idx}")
            params.append(country.strip().upper())
            idx += 1

        if time_range:
            # Convert string interval to timedelta for asyncpg
            _INTERVAL_MAP = {
                "1 hour": timedelta(hours=1),
                "6 hours": timedelta(hours=6),
                "12 hours": timedelta(hours=12),
                "24 hours": timedelta(hours=24),
                "48 hours": timedelta(hours=48),
                "7 days": timedelta(days=7),
            }
            td = _INTERVAL_MAP.get(time_range, timedelta(hours=24))
            conditions.append(f"published_at > NOW() - ${idx}::interval")
            params.append(td)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        query = f"""
            SELECT id, title, source_url, source_name, latitude, longitude,
                   published_at, sentiment_score, topic_tags, country_code
            FROM articles
            {where}
            ORDER BY published_at DESC
            LIMIT ${idx}
        """

        rows = await pool.fetch(query, *params)
        return [dict(r) for r in rows]
    except Exception:
        logger.error("Keyword search failed.", exc_info=True)
        return []


async def trending_topics(hours: int = 24) -> list[dict]:
    """Return the top-20 trending topics over the last *hours* hours."""
    try:
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT UNNEST(topic_tags) AS topic, COUNT(*) AS count
            FROM articles
            WHERE published_at > NOW() - make_interval(hours => $1)
            GROUP BY topic
            ORDER BY count DESC
            LIMIT 20
            """,
            hours,
        )
        return [dict(r) for r in rows]
    except Exception:
        logger.error("Trending topics query failed.", exc_info=True)
        return []


async def entity_lookup(name: str) -> dict:
    """Look up a knowledge-graph entity by fuzzy name match.

    Returns ``{"node": ..., "connections": [...], "articles": [...]}``
    or ``{"node": None, "connections": [], "articles": []}`` if not found.
    """
    try:
        pool = await get_pool()

        node_row = await pool.fetchrow(
            """
            SELECT id, type, name, metadata::text
            FROM kg_nodes
            WHERE name ILIKE '%' || $1 || '%'
            ORDER BY similarity(name, $1) DESC
            LIMIT 1
            """,
            name,
        )

        if node_row is None:
            return {"node": None, "connections": [], "articles": []}

        node = dict(node_row)
        node_id = node["id"]

        # Co-mentioned entities first (computed, weighted), then stored edges
        connections = await _co_mentions(pool, node_id)

        conn_rows = await pool.fetch(
            """
            SELECT n.id, n.type, n.name, e.rel_type, e.weight, n.metadata::text
            FROM kg_edges e
            JOIN kg_nodes n
                ON n.id = CASE
                    WHEN e.source_node_id = $1 THEN e.target_node_id
                    ELSE e.source_node_id
                END
            WHERE (e.source_node_id = $1 OR e.target_node_id = $1)
              AND e.rel_type <> 'CO_MENTIONED'
            ORDER BY e.weight DESC
            LIMIT 20
            """,
            node_id,
        )
        connections += [dict(r) for r in conn_rows]

        # Fetch articles linked to this entity via MENTIONED_IN edges
        art_rows = await pool.fetch(
            """
            SELECT DISTINCT a.id, a.title, a.source_url, a.source_name,
                   a.latitude, a.longitude, a.published_at, a.sentiment_score
            FROM kg_edges e
            JOIN articles a ON a.id = e.article_id
            WHERE (e.source_node_id = $1 OR e.target_node_id = $1)
              AND e.rel_type <> 'CO_MENTIONED'
              AND e.article_id IS NOT NULL
            ORDER BY a.published_at DESC
            LIMIT 10
            """,
            node_id,
        )

        return {
            "node": node,
            "connections": connections,
            "articles": [dict(r) for r in art_rows],
        }
    except Exception:
        logger.error("Entity lookup failed.", exc_info=True)
        return {"node": None, "connections": [], "articles": []}


async def read_article(
    urls: list[str],
    question: str | None = None,
) -> list[dict]:
    """Fetch and extract article text from up to 5 URLs concurrently.

    Returns a list of ``{"url", "title", "text", "quality"}`` dicts.
    Quality is one of: ``"full"``, ``"partial"``, ``"meta_only"``, ``"failed"``.
    """
    urls = urls[:5]
    keywords = question.split() if question else []

    results = await asyncio.gather(
        *[extract_article_text(url, keywords) for url in urls],
        return_exceptions=True,
    )

    out: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("read_article task failed: %s", r)
            continue
        out.append(r)
    return out
