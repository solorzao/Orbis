"""Knowledge graph population service.

Extracts entities (persons, organizations, locations, topics) from ingested
articles and populates the kg_nodes / kg_edges tables to form a queryable
knowledge graph.
"""

from __future__ import annotations

import json
import logging
from itertools import combinations

from app.services.database import get_pool

logger = logging.getLogger("orbis.knowledge_graph")


async def populate_graph(articles: list[dict]) -> int:
    """Upsert KG nodes and edges for a batch of articles.

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
                article_node_id = await conn.fetchval(
                    "INSERT INTO kg_nodes (type, name, metadata) "
                    "VALUES ($1, $2, $3::jsonb) "
                    "ON CONFLICT (type, name) DO UPDATE "
                    "SET metadata = kg_nodes.metadata || $3::jsonb "
                    "RETURNING id",
                    "ARTICLE",
                    title,
                    json.dumps(
                        {
                            "url": article.get("source_url", ""),
                            "lat": article.get("latitude"),
                            "lng": article.get("longitude"),
                            "published_at": str(article.get("published_at", "")),
                        }
                    ),
                )

                persons = article.get("persons", [])
                organizations = article.get("organizations", [])
                region = article.get("region", "")
                topic_tags = article.get("topic_tags", [])

                # Collect entity node IDs for CO_MENTIONED edges
                entity_node_ids: list = []

                # 2. Upsert PERSON nodes + MENTIONED_IN edges
                for person in persons:
                    if not person:
                        continue
                    person_node_id = await conn.fetchval(
                        "INSERT INTO kg_nodes (type, name, metadata) "
                        "VALUES ($1, $2, $3::jsonb) "
                        "ON CONFLICT (type, name) DO UPDATE "
                        "SET metadata = kg_nodes.metadata || $3::jsonb "
                        "RETURNING id",
                        "PERSON",
                        person,
                        json.dumps({}),
                    )
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
                    entity_node_ids.append(person_node_id)

                # 3. Upsert ORG nodes + MENTIONED_IN edges
                for org in organizations:
                    if not org:
                        continue
                    org_node_id = await conn.fetchval(
                        "INSERT INTO kg_nodes (type, name, metadata) "
                        "VALUES ($1, $2, $3::jsonb) "
                        "ON CONFLICT (type, name) DO UPDATE "
                        "SET metadata = kg_nodes.metadata || $3::jsonb "
                        "RETURNING id",
                        "ORG",
                        org,
                        json.dumps({}),
                    )
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
                    entity_node_ids.append(org_node_id)

                # 4. Upsert LOCATION node + LOCATED_AT edge
                if region:
                    location_node_id = await conn.fetchval(
                        "INSERT INTO kg_nodes (type, name, metadata) "
                        "VALUES ($1, $2, $3::jsonb) "
                        "ON CONFLICT (type, name) DO UPDATE "
                        "SET metadata = kg_nodes.metadata || $3::jsonb "
                        "RETURNING id",
                        "LOCATION",
                        region,
                        json.dumps(
                            {
                                "lat": article.get("latitude"),
                                "lng": article.get("longitude"),
                                "country_code": article.get("country_code", ""),
                            }
                        ),
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
                    topic_node_id = await conn.fetchval(
                        "INSERT INTO kg_nodes (type, name, metadata) "
                        "VALUES ($1, $2, $3::jsonb) "
                        "ON CONFLICT (type, name) DO UPDATE "
                        "SET metadata = kg_nodes.metadata || $3::jsonb "
                        "RETURNING id",
                        "TOPIC",
                        tag,
                        json.dumps({}),
                    )
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
                    loc_node_id = await conn.fetchval(
                        "INSERT INTO kg_nodes (type, name, metadata) "
                        "VALUES ($1, $2, $3::jsonb) "
                        "ON CONFLICT (type, name) DO UPDATE "
                        "SET metadata = kg_nodes.metadata || $3::jsonb "
                        "RETURNING id",
                        "LOCATION",
                        loc_name,
                        json.dumps(
                            {
                                "lat": loc.get("lat"),
                                "lng": loc.get("lng"),
                                "country_code": loc.get("country_code", ""),
                            }
                        ),
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
                    entity_node_ids.append(loc_node_id)

                # 7. CO_MENTIONED edges between all entity pairs
                for node_a, node_b in combinations(entity_node_ids, 2):
                    # Try to increment weight on an existing edge first
                    updated = await conn.execute(
                        "UPDATE kg_edges SET weight = weight + 1 "
                        "WHERE source_node_id = $1 AND target_node_id = $2 "
                        "AND rel_type = 'CO_MENTIONED'",
                        node_a,
                        node_b,
                    )
                    if updated == "UPDATE 0":
                        await conn.execute(
                            "INSERT INTO kg_edges (source_node_id, "
                            "target_node_id, rel_type, weight, article_id) "
                            "VALUES ($1, $2, $3, 1, $4)",
                            node_a,
                            node_b,
                            "CO_MENTIONED",
                            article_id,
                        )
                    edge_count += 1

    logger.info("Knowledge graph: created %d edges from %d articles.", edge_count, len(articles))
    return edge_count


async def purge_orphaned_nodes() -> int:
    """Delete kg_nodes that have no edges pointing to or from them.

    Returns the number of nodes deleted.
    """
    pool = await get_pool()
    status = await pool.execute(
        "DELETE FROM kg_nodes WHERE id NOT IN ("
        "  SELECT source_node_id FROM kg_edges "
        "  UNION "
        "  SELECT target_node_id FROM kg_edges"
        ")"
    )
    count = int(status.split()[-1])
    if count:
        logger.info("Purged %d orphaned KG nodes.", count)
    return count
