"""Retrieval functions for the Orbis embedded agent.

Provides semantic search, knowledge-graph traversal, keyword filtering,
the top stories (Orbis's own cached rankings), entity lookup, and article
text extraction against the Orbis database.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from app.config import settings
from app.services.cache import cycle_ttl, get_cached, set_cached
from app.services.database import get_pool
from app.services.scraper import extract_article_text
from app.services.urls import web_url

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

# Stored-edge reads expand a node to at most N of its most recent edges, so
# their cost no longer grows with how many edges a hub (a hot entity, topic or
# region) has. Recency is per ingestion batch, not per edge: populate_graph
# writes a whole 15-minute batch in one transaction and created_at defaults to
# now(), so every edge in a batch has the same created_at. For a hub with more
# than N edges in its latest batch, the N read are an arbitrary N of that batch.
# N is the whole connection budget: graph_traverse returns depth-1 rows first
# and at most _GRAPH_CONNECTION_LIMIT rows in all, so a node's other edges
# could never add a row, and with every stored edge weighted 1 they would only
# change which tied row wins. A larger N buys nothing and multiplies per hop:
# depth 3 reads up to N^3 edges.
_RECENT_EDGES_PER_NODE = _GRAPH_CONNECTION_LIMIT
_STORED_EDGES_TIMEOUT_S = 2.0


def _recent_edges_sql(node: str, per_node: str, rel_filter: str = "") -> str:
    """Subquery for the *per_node* newest stored edges at *node*, either direction.

    Yields ``node_id`` (the edge's other end), ``rel_type``, ``weight``,
    ``article_id`` and ``created_at``, never stored CO_MENTIONED rows.
    *rel_filter* (`` AND e.rel_type = $n``) applies before the limit. Each
    direction is a range scan of idx_kg_edges_{source,target}_recent
    (migration 010) that stops after *per_node* rows; without those indexes
    it still works, reading all of the node's edges to sort them.
    """
    return f"""
        (SELECT e.target_node_id AS node_id, e.rel_type, e.weight, e.article_id, e.created_at
         FROM kg_edges e
         WHERE e.source_node_id = {node} AND e.rel_type <> 'CO_MENTIONED'{rel_filter}
         ORDER BY e.created_at DESC
         LIMIT {per_node})
        UNION ALL
        (SELECT e.source_node_id, e.rel_type, e.weight, e.article_id, e.created_at
         FROM kg_edges e
         WHERE e.target_node_id = {node} AND e.rel_type <> 'CO_MENTIONED'{rel_filter}
         ORDER BY e.created_at DESC
         LIMIT {per_node})
        ORDER BY created_at DESC
        LIMIT {per_node}
    """


async def _fetch_or_skip(
    pool: Any, what: str, node_id: Any, sql: str, *args: Any, timeout: float
) -> list[dict]:
    """``pool.fetch`` as dicts, or ``[]`` with a warning if it outlasts *timeout*.

    For the optional parts of a tool result: a slow one is left out instead
    of failing the whole tool call.
    """
    try:
        rows = await pool.fetch(sql, *args, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "%s query for node %s timed out after %.1fs; skipping it.", what, node_id, timeout
        )
        return []
    return [dict(r) for r in rows]


async def _co_mentions(pool: Any, node_id: Any) -> list[dict]:
    """Top-20 entities sharing a recent article with *node_id*, as CO_MENTIONED rows.

    Returns ``[]`` if the query times out, so callers still return their
    stored-edge results instead of failing the whole tool call.
    """
    return await _fetch_or_skip(
        pool,
        "Co-mention",
        node_id,
        _CO_MENTIONS_SQL,
        node_id,
        _CO_MENTION_ARTICLE_WINDOW,
        timeout=_CO_MENTIONS_TIMEOUT_S,
    )


async def _traverse_stored_edges(
    pool: Any,
    start_id: Any,
    rel_type: str | None,
    depth: int,
    limit: int,
) -> list[dict]:
    """Walk stored edges (never CO_MENTIONED) from *start_id* up to *depth* hops.

    Every hop, the first included, expands a node to its newest
    _RECENT_EDGES_PER_NODE edges. Returns ``[]`` if the walk times out, so
    graph_traverse still returns its co-mentions.
    """
    params: list[Any] = [start_id]
    rel_filter = ""
    if rel_type:
        params.append(rel_type)
        rel_filter = " AND e.rel_type = $2"

    depth_param = f"${len(params) + 1}"
    params.append(depth)

    per_node_param = f"${len(params) + 1}"
    params.append(_RECENT_EDGES_PER_NODE)

    limit_param = f"${len(params) + 1}"
    params.append(limit)

    query = f"""
        WITH RECURSIVE traverse AS (
            SELECT n.id, n.type, n.name, h.rel_type, h.weight, h.article_id, 1 AS depth
            FROM ({_recent_edges_sql("$1", per_node_param, rel_filter)}) h
            JOIN kg_nodes n ON n.id = h.node_id
          UNION
            SELECT n2.id, n2.type, n2.name, h2.rel_type, h2.weight, h2.article_id, t.depth + 1
            FROM traverse t
            CROSS JOIN LATERAL ({_recent_edges_sql("t.id", per_node_param, rel_filter)}) h2
            JOIN kg_nodes n2 ON n2.id = h2.node_id
            WHERE t.depth < {depth_param}
        )
        SELECT DISTINCT id, type, name, rel_type, weight, article_id, depth
        FROM traverse
        ORDER BY depth, weight DESC
        LIMIT {limit_param}
    """
    timed_out = False
    try:
        async with pool.acquire() as conn, conn.transaction():
            # A bitmap scan reads all of a node's edges before sorting them;
            # only an ordered index scan stops after the newest few. In the
            # recursive step the planner can't see which node it expands
            # (t.id), assumes the average handful of edges and picks bitmap
            # scans, which read every edge of each hub on the way: depth 3
            # from a hot entity took 2 s instead of 45 ms on a production-
            # sized graph. SET LOCAL ends with this transaction.
            await conn.execute("SET LOCAL enable_bitmapscan = off")
            try:
                rows = await conn.fetch(query, *params, timeout=_STORED_EDGES_TIMEOUT_S)
            except asyncio.TimeoutError:
                timed_out = True
                raise
    except asyncio.TimeoutError:
        logger.warning(
            "Stored-edge traversal from node %s timed out after %.1fs; skipping it.",
            start_id,
            _STORED_EDGES_TIMEOUT_S,
        )
        return []
    except (asyncpg.PostgresError, asyncpg.InterfaceError, ConnectionError, OSError):
        # After a timeout, the ROLLBACK or the connection's release can fail
        # too (e.g. the connection dropped); that replaces the TimeoutError
        # but is still just the timeout. Any other failure propagates.
        if not timed_out:
            raise
        logger.warning(
            "Stored-edge traversal from node %s timed out after %.1fs and its "
            "cleanup failed; skipping it.",
            start_id,
            _STORED_EDGES_TIMEOUT_S,
            exc_info=True,
        )
        return []
    return [dict(r) for r in rows]


async def graph_traverse(
    entity_name: str,
    rel_type: str | None = None,
    depth: int = 2,
) -> dict:
    """Traverse the knowledge graph starting from *entity_name*.

    Returns connected nodes up to *depth* hops (capped at 3), plus the
    source articles that establish those relationships. Co-mentions are
    computed from shared articles and listed first, as depth-1 rows. Each
    hop follows only a node's newest stored edges (_RECENT_EDGES_PER_NODE).
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
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict]:
    """Search articles using keyword / metadata filters.

    *start_time* and *end_time* bound ``published_at`` half-open, like the
    globe's windows; the co-pilot sets them from the visitor's screen.
    """
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

        if start_time is not None:
            conditions.append(f"published_at >= ${idx}")
            params.append(start_time)
            idx += 1

        if end_time is not None:
            conditions.append(f"published_at < ${idx}")
            params.append(end_time)
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


# Broad questions (Phase 6, 21d): what Orbis already ranks, never a new heavy read.
TOP_THREADS = 5
TOP_BREAKING = 3
_TOP_TTL = 300
# Each top thread's lead link, by primary key on both tables (at most TOP_THREADS).
_LEAD_URLS_SQL = """
    SELECT t.id, a.source_url
    FROM threads t JOIN articles a ON a.id = t.lead_article_id
    WHERE t.id = ANY($1::bigint[])
"""


def by_breadth(threads: list[dict]) -> list[dict]:
    """Threads the most outlets, then countries, cover first (then the lower id)."""
    return sorted(threads, key=lambda t: (-t["n_sources"], -len(t["countries"]), t["id"]))


def coverage_words(outlets: int, countries: int, status: str) -> str:
    """A thread's breadth as the top_stories context says it: "12 outlets, 2 countries,
    developing"."""
    places = "country" if countries == 1 else "countries"
    return f"{outlets} outlets, {countries} {places}, {status}"


def top_story_rows(threads: list[dict], breaking: list[dict], urls: dict[int, str]) -> list[dict]:
    """The rows top_stories returns: the TOP_THREADS widest threads, then up to
    TOP_BREAKING breaking events, as retrieval rows _build_context numbers, each with a
    summary and a coverage line. Threads come as /api/threads answers them (JSON),
    breaking events as /api/news/breaking does; *urls* maps thread ids to lead links,
    which stay server-side (the context never shows a link). A breaking event has
    none: its citation flies to its place and opens nothing."""
    rows = []
    for t in by_breadth(threads)[:TOP_THREADS]:
        place = (t.get("places") or [{}])[0]
        rows.append(
            {
                "title": t["title"],
                "summary": t.get("synopsis"),
                "source_url": urls.get(t["id"], ""),
                "source_name": (t.get("lead") or {}).get("source_name", ""),
                "latitude": place.get("lat"),
                "longitude": place.get("lng"),
                "coverage": coverage_words(t["n_sources"], len(t["countries"]), t["status"]),
            }
        )
    for b in breaking[:TOP_BREAKING]:
        rows.append(
            {
                "title": b["headline"],
                "summary": None,
                "source_url": "",
                "source_name": b["lead"]["source_name"],
                "latitude": b["lat"],
                "longitude": b["lng"],
                "coverage": f"breaking: {b['outlets']} outlets in the last 2 hours, {b['place']}",
            }
        )
    return rows


async def _cached_breaking() -> tuple[list[Any], str]:
    """The breaking ticker's list from the cache only, and where it came from: its fresh
    entry, else the last good one (up to an hour old), else none. Never the breaking
    query, nor one a miss started: it can outlast its 15 s limit, and a broad answer
    goes without breaking events rather than wait on it."""
    # Here, not at the top: the routers import the services.
    from app.routers.news import _BREAKING_KEY, _BREAKING_LAST_KEY, _breaking_entry

    for key, origin in ((_BREAKING_KEY, "fresh"), (_BREAKING_LAST_KEY, "last good")):
        stories = await _breaking_entry(key)
        if stories is not None:
            return stories, origin
    return [], "none cached"


async def top_stories(hours: int = 24, topic: str | None = None) -> list[dict]:
    """What Orbis ranks highest now, for broad questions: the threads the most outlets
    and countries cover in the window, then the breaking events. The threads come from
    the rail's list (its cache, or its own query on a miss), the breaking events from
    the ticker's cached lists only, plus the top threads' lead links by primary key;
    the answer is cached until the cycle ends. *hours* is a live window (1, 6, 24 or
    168); *topic* a topic pill, or None."""
    # Here, not at the top: the routers import the services.
    from app.routers.news import _globe_topic_tag
    from app.routers.threads import DEFAULT_LIMIT, cached_threads

    tag = _globe_topic_tag(topic)
    key = f"db:copilot:top:v1:{hours}h:{tag or ''}"
    cached = await get_cached(key)
    if isinstance(cached, list):
        return cached
    listed = await cached_threads(hours, tag, DEFAULT_LIMIT)
    threads = by_breadth([t.model_dump(mode="json") for t in listed])[:TOP_THREADS]
    stories, origin = await _cached_breaking()
    events = [b.model_dump(mode="json") for b in stories if tag in (None, b.topic)]
    urls: dict[int, str] = {}
    if threads:
        pool = await get_pool()
        rows = await pool.fetch(_LEAD_URLS_SQL, [t["id"] for t in threads])
        urls = {r["id"]: web_url(r["source_url"]) or "" for r in rows}
    result = top_story_rows(threads, events, urls)
    logger.info(
        "top_stories: %d threads, %d breaking events (breaking list: %s).",
        len(threads),
        min(len(events), TOP_BREAKING),
        origin,
    )
    await set_cached(key, result, cycle_ttl(_TOP_TTL))
    return result


# entity_lookup reads both from $2 of the entity's most recent stored edges,
# recent by ingestion batch (see _RECENT_EDGES_PER_NODE): the heaviest 20 of
# them (all weigh 1 today, so 20 from the latest batches, ties arbitrary) and
# the 10 most recently published articles among those edges' articles. For a
# hub whose latest batch alone exceeds $2 edges, that is an arbitrary sample
# of that batch, not the entity's 10 most recent articles overall.
_ENTITY_EDGES_SQL = f"""
    SELECT n.id, n.type, n.name, h.rel_type, h.weight, n.metadata::text
    FROM ({_recent_edges_sql("$1", "$2")}) h
    JOIN kg_nodes n ON n.id = h.node_id
    ORDER BY h.weight DESC, h.created_at DESC
    LIMIT 20
"""
_ENTITY_ARTICLES_SQL = f"""
    SELECT DISTINCT a.id, a.title, a.source_url, a.source_name,
           a.latitude, a.longitude, a.published_at, a.sentiment_score
    FROM ({_recent_edges_sql("$1", "$2")}) h
    JOIN articles a ON a.id = h.article_id
    ORDER BY a.published_at DESC
    LIMIT 10
"""


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
        connections += await _fetch_or_skip(
            pool,
            "Entity edge",
            node_id,
            _ENTITY_EDGES_SQL,
            node_id,
            _RECENT_EDGES_PER_NODE,
            timeout=_STORED_EDGES_TIMEOUT_S,
        )
        articles = await _fetch_or_skip(
            pool,
            "Entity article",
            node_id,
            _ENTITY_ARTICLES_SQL,
            node_id,
            _RECENT_EDGES_PER_NODE,
            timeout=_STORED_EDGES_TIMEOUT_S,
        )

        return {"node": node, "connections": connections, "articles": articles}
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
