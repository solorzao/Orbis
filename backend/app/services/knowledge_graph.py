"""Knowledge graph population service.

Extracts entities (persons, organizations, locations, topics) from ingested
articles and populates the kg_nodes / kg_edges tables to form a queryable
knowledge graph.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.database import get_pool

logger = logging.getLogger("orbis.knowledge_graph")


def _node_upsert_sql(on_conflict: str) -> str:
    """Insert a node, or apply *on_conflict* to the existing one, and return its id.

    ``RETURNING`` yields nothing for a row the conflict clause left alone, so
    the id then comes from a plain read in the same statement. That read sees
    the statement's snapshot: a row another transaction committed after it
    began isn't there, and upsert_node reads it again in a new statement.
    Ingestion is the only writer (one cycle at a time, under its lock), so that
    happens only if two backends overlap, as during a deploy.

    A person or organisation is also kept in kg_entity_names (migration 017),
    the narrow table search reads: added when new, or when a node stored
    before the table (or by the previous backend during a deploy) is mentioned
    again. A row already there costs a primary-key probe; DO NOTHING writes
    nothing. (In the rare re-read case above, the next mention adds it.)
    """
    return f"""
        WITH up AS (
            INSERT INTO kg_nodes (type, name, metadata) VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (type, name) {on_conflict}
            RETURNING id
        ),
        node AS (
            SELECT id FROM up
            UNION ALL
            SELECT id FROM kg_nodes WHERE type = $1 AND name = $2 AND NOT EXISTS (SELECT 1 FROM up)
        ),
        named AS (
            INSERT INTO kg_entity_names (node_id, type, name)
            SELECT id, $1, $2 FROM node WHERE $1 IN ('PERSON', 'ORG')
            ON CONFLICT (node_id) DO NOTHING
        )
        SELECT id FROM node
    """


# A node with no metadata to add (people, organisations, topics): a known name
# is left as it is. Every cycle names thousands of known people and orgs; the
# old unconditional "SET metadata = metadata || '{}'" rewrote each one, and on
# a full page that is a non-HOT update into every kg_nodes index, including
# both trigram GIN indexes (006, 016).
_KEEP_NODE_SQL = _node_upsert_sql("DO NOTHING")

# A node with metadata (articles, locations): merged as before, but written
# only when the merge changes it. The merge is compared whole (jsonb equality),
# not with @> (deep containment, where an array or object value could be
# "contained" yet replaced by ||), so a row is rewritten exactly when || would
# change it. Today's values are all flat scalars (strings, numbers, nulls).
# An unchanged row is still locked by DO UPDATE: that dirties its page and
# writes a lock WAL record. Far less than a new version and its index
# entries, but not nothing.
_MERGE_NODE_SQL = _node_upsert_sql(
    "DO UPDATE SET metadata = kg_nodes.metadata || EXCLUDED.metadata "
    "WHERE kg_nodes.metadata || EXCLUDED.metadata IS DISTINCT FROM kg_nodes.metadata"
)

_NODE_ID_SQL = "SELECT id FROM kg_nodes WHERE type = $1 AND name = $2"


async def upsert_node(conn: Any, node_type: str, name: str, metadata: dict) -> Any:
    """The id of the node *node_type*/*name*, inserted if new, its *metadata* merged in.

    A row is rewritten only when the merge adds or changes a key, so a known
    name costs an index probe, not a new row version and its index entries.
    """
    sql = _MERGE_NODE_SQL if metadata else _KEEP_NODE_SQL
    node_id = await conn.fetchval(sql, node_type, name, json.dumps(metadata))
    if node_id is None:  # committed by another writer after this statement began
        node_id = await conn.fetchval(_NODE_ID_SQL, node_type, name)
    if node_id is None:
        # DO NOTHING doesn't row-lock the existing node (DO UPDATE did), so an
        # orphan purge from an overlapping backend, as during a deploy, could
        # delete it between the two reads. Rare and accepted; say which node
        # rather than fail on the edge's NULL id.
        raise RuntimeError(f"{node_type} node {name!r} vanished before its edge was written")
    return node_id


async def populate_graph(articles: list[dict]) -> int:
    """Upsert KG nodes and edges for a batch of articles.

    Co-mentions are not stored: retrieval derives them from entities whose
    MENTIONED_IN edges share an ARTICLE node.

    Returns the total number of edges created.
    """
    if not articles:
        return 0

    pool = await get_pool()
    edge_count = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for article in articles:
                article_id = article.get("id")
                title = article.get("title", "")
                if not title or not article_id:
                    continue

                # 1. Upsert ARTICLE node
                article_node_id = await upsert_node(
                    conn,
                    "ARTICLE",
                    title,
                    {
                        "url": article.get("source_url", ""),
                        "lat": article.get("latitude"),
                        "lng": article.get("longitude"),
                        "published_at": str(article.get("published_at", "")),
                    },
                )

                persons = article.get("persons", [])
                organizations = article.get("organizations", [])
                region = article.get("region", "")
                topic_tags = article.get("topic_tags", [])

                # 2. Upsert PERSON nodes + MENTIONED_IN edges
                for person in persons:
                    if not person:
                        continue
                    person_node_id = await upsert_node(conn, "PERSON", person, {})
                    await conn.execute(
                        "INSERT INTO kg_edges (source_node_id, "
                        "target_node_id, rel_type, weight, article_id) "
                        "VALUES ($1, $2, $3, 1, $4)",
                        person_node_id,
                        article_node_id,
                        "MENTIONED_IN",
                        article_id,
                    )
                    edge_count += 1

                # 3. Upsert ORG nodes + MENTIONED_IN edges
                for org in organizations:
                    if not org:
                        continue
                    org_node_id = await upsert_node(conn, "ORG", org, {})
                    await conn.execute(
                        "INSERT INTO kg_edges (source_node_id, "
                        "target_node_id, rel_type, weight, article_id) "
                        "VALUES ($1, $2, $3, 1, $4)",
                        org_node_id,
                        article_node_id,
                        "MENTIONED_IN",
                        article_id,
                    )
                    edge_count += 1

                # 4. Upsert LOCATION node + LOCATED_AT edge
                if region:
                    location_node_id = await upsert_node(
                        conn,
                        "LOCATION",
                        region,
                        {
                            "lat": article.get("latitude"),
                            "lng": article.get("longitude"),
                            "country_code": article.get("country_code", ""),
                            "country_fips": article.get("country_fips", ""),
                        },
                    )
                    await conn.execute(
                        "INSERT INTO kg_edges (source_node_id, "
                        "target_node_id, rel_type, weight, article_id) "
                        "VALUES ($1, $2, $3, 1, $4)",
                        article_node_id,
                        location_node_id,
                        "LOCATED_AT",
                        article_id,
                    )
                    edge_count += 1

                # 5. Upsert TOPIC nodes + ABOUT_TOPIC edges
                for tag in topic_tags:
                    if not tag:
                        continue
                    topic_node_id = await upsert_node(conn, "TOPIC", tag, {})
                    await conn.execute(
                        "INSERT INTO kg_edges (source_node_id, "
                        "target_node_id, rel_type, weight, article_id) "
                        "VALUES ($1, $2, $3, 1, $4)",
                        article_node_id,
                        topic_node_id,
                        "ABOUT_TOPIC",
                        article_id,
                    )
                    edge_count += 1

                # 6. Upsert mentioned LOCATION nodes + MENTIONED_IN edges
                mentioned_locations = article.get("mentioned_locations", [])
                for loc in mentioned_locations:
                    loc_name = loc.get("name", "")
                    if not loc_name:
                        continue
                    loc_node_id = await upsert_node(
                        conn,
                        "LOCATION",
                        loc_name,
                        {
                            "lat": loc.get("lat"),
                            "lng": loc.get("lng"),
                            "country_code": loc.get("country_code", ""),
                            "country_fips": loc.get("country_fips", ""),
                        },
                    )
                    await conn.execute(
                        "INSERT INTO kg_edges (source_node_id, "
                        "target_node_id, rel_type, weight, article_id) "
                        "VALUES ($1, $2, $3, 1, $4)",
                        loc_node_id,
                        article_node_id,
                        "MENTIONED_IN",
                        article_id,
                    )
                    edge_count += 1

    logger.info("Knowledge graph: created %d edges from %d articles.", edge_count, len(articles))
    return edge_count


# Orphaned nodes, and the kg_entity_names rows of the people and
# organisations among them, by key, in one statement.
_PURGE_ORPHANS_SQL = """
    WITH gone AS (
        DELETE FROM kg_nodes n
        WHERE NOT EXISTS (SELECT 1 FROM kg_edges e WHERE e.source_node_id = n.id)
          AND NOT EXISTS (SELECT 1 FROM kg_edges e WHERE e.target_node_id = n.id)
        RETURNING n.id
    ),
    names AS (
        DELETE FROM kg_entity_names e USING gone WHERE e.node_id = gone.id
    )
    SELECT count(*) FROM gone
"""


async def purge_orphaned_nodes() -> int:
    """Delete kg_nodes that have no edges pointing to or from them, and their
    kg_entity_names rows.

    NOT EXISTS lets each node probe the source and target indexes. The old
    NOT IN (… UNION …) form could not hash every edge id in 4 MB of work_mem,
    so it compared each node with each edge: minutes per cycle at 800K edges.

    Returns the number of nodes deleted.
    """
    pool = await get_pool()
    count = await pool.fetchval(_PURGE_ORPHANS_SQL)
    if count:
        logger.info("Purged %d orphaned KG nodes.", count)
    return count
