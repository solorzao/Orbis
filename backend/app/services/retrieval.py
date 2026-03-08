"""Retrieval functions for the Orbis embedded agent.

Provides semantic search, knowledge-graph traversal, keyword filtering,
trending-topic aggregation, and entity lookup against the Orbis database.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.config import settings
from app.services.database import get_pool

logger = logging.getLogger("orbis.retrieval")


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
        rows = await pool.fetch(
            """
            SELECT id, title, source_url, source_name, latitude, longitude,
                   published_at, sentiment_score,
                   embedding <=> $1::vector AS distance
            FROM articles
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_str,
            limit,
        )
        return [dict(r) for r in rows]
    except Exception:
        logger.error("Semantic search failed.", exc_info=True)
        return []


async def graph_traverse(
    entity_name: str,
    rel_type: str | None = None,
    depth: int = 2,
) -> dict:
    """Traverse the knowledge graph starting from *entity_name*.

    Returns connected nodes up to *depth* hops (capped at 3), plus the
    source articles that establish those relationships.
    """
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

        rel_filter = "AND e.rel_type = $2" if rel_type else ""
        params: list[Any] = [start_id]
        if rel_type:
            params.append(rel_type)

        depth_param = f"${len(params) + 1}"
        params.append(depth)

        limit_param = f"${len(params) + 1}"
        params.append(50)

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
                {"AND e2.rel_type = $2" if rel_type else ""}
            )
            SELECT DISTINCT id, type, name, rel_type, weight, article_id, depth
            FROM traverse
            ORDER BY depth, weight DESC
            LIMIT {limit_param}
        """

        rows = await pool.fetch(query, *params)
        connections = [dict(r) for r in rows]

        # Collect unique article IDs from traversal edges
        article_ids = list({r["article_id"] for r in rows if r["article_id"]})

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
            conditions.append(f"country_code = ${idx}")
            params.append(country)
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

        conn_rows = await pool.fetch(
            """
            SELECT n.id, n.type, n.name, e.rel_type, e.weight, n.metadata::text
            FROM kg_edges e
            JOIN kg_nodes n
                ON n.id = CASE
                    WHEN e.source_node_id = $1 THEN e.target_node_id
                    ELSE e.source_node_id
                END
            WHERE e.source_node_id = $1 OR e.target_node_id = $1
            ORDER BY e.weight DESC
            LIMIT 20
            """,
            node_id,
        )

        # Fetch articles linked to this entity via MENTIONED_IN edges
        art_rows = await pool.fetch(
            """
            SELECT DISTINCT a.id, a.title, a.source_url, a.source_name,
                   a.latitude, a.longitude, a.published_at, a.sentiment_score
            FROM kg_edges e
            JOIN articles a ON a.id = e.article_id
            WHERE (e.source_node_id = $1 OR e.target_node_id = $1)
              AND e.article_id IS NOT NULL
            ORDER BY a.published_at DESC
            LIMIT 10
            """,
            node_id,
        )

        return {
            "node": node,
            "connections": [dict(r) for r in conn_rows],
            "articles": [dict(r) for r in art_rows],
        }
    except Exception:
        logger.error("Entity lookup failed.", exc_info=True)
        return {"node": None, "connections": [], "articles": []}
