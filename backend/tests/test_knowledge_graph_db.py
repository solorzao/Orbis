"""Knowledge-graph node upserts on a real PostgreSQL: a node is written only when it changes.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied. Every test runs in a transaction that is rolled back, so
nothing it inserts is ever committed; its nodes are named ``Zz ...`` and its
articles titled ``zzgraph-...``. Each upsert runs in its own savepoint, as a
subtransaction with its own xid, so a rewritten row would show a new xmin.
Skipped without it.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import knowledge_graph

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def _upsert(conn, node_type: str, name: str, metadata: dict):
    async with conn.transaction():  # a savepoint: its own subtransaction
        return await knowledge_graph.upsert_node(conn, node_type, name, metadata)


async def _version(conn, node_type: str, name: str):
    """The node's id, the transaction that wrote its live version, and where it is."""
    return await conn.fetchrow(
        "SELECT id, xmin::text AS xmin, ctid::text AS ctid, metadata FROM kg_nodes"
        " WHERE type = $1 AND name = $2",
        node_type,
        name,
    )


@pytest.mark.asyncio
async def test_a_fresh_name_is_inserted_and_its_id_returned(conn):
    node_id = await _upsert(conn, "PERSON", "Zz Fresh", {})
    row = await _version(conn, "PERSON", "Zz Fresh")
    assert node_id == row["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_type", "metadata"),
    [
        ("PERSON", {}),
        ("ORG", {}),
        ("TOPIC", {}),
        ("LOCATION", {"lat": 35.7, "lng": 51.4, "country_code": "IR", "country_fips": "IR"}),
        ("ARTICLE", {"url": "https://zz.test/1", "lat": None, "lng": None, "published_at": "x"}),
    ],
)
async def test_a_repeat_upsert_with_nothing_new_writes_no_row_version(conn, node_type, metadata):
    first = await _upsert(conn, node_type, "Zz Repeat", metadata)
    before = await _version(conn, node_type, "Zz Repeat")
    again = await _upsert(conn, node_type, "Zz Repeat", metadata)
    after = await _version(conn, node_type, "Zz Repeat")

    assert again == first == before["id"]
    # No new row version, so no new entry in any kg_nodes index.
    assert (after["xmin"], after["ctid"]) == (before["xmin"], before["ctid"])


@pytest.mark.asyncio
async def test_an_upsert_that_adds_metadata_updates_and_returns_the_id(conn):
    first = await _upsert(conn, "LOCATION", "Zz Place", {"lat": 1.5, "lng": 2.5})
    before = await _version(conn, "LOCATION", "Zz Place")
    changed = await _upsert(conn, "LOCATION", "Zz Place", {"country_code": "IR"})
    after = await _version(conn, "LOCATION", "Zz Place")

    assert changed == first == after["id"]
    assert after["xmin"] != before["xmin"]
    assert after["metadata"] == '{"lat": 1.5, "lng": 2.5, "country_code": "IR"}'
    # A changed value is a change too; the same value again is not.
    await _upsert(conn, "LOCATION", "Zz Place", {"lat": 9.5})
    moved = await _version(conn, "LOCATION", "Zz Place")
    assert moved["xmin"] != after["xmin"]
    await _upsert(conn, "LOCATION", "Zz Place", {"lat": 9.5})
    assert (await _version(conn, "LOCATION", "Zz Place"))["xmin"] == moved["xmin"]


class _Pool:
    """The pool as populate_graph uses it: the test's connection, in a savepoint."""

    def __init__(self, connection):
        self._conn = connection

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self._conn


async def _article(conn, title: str) -> uuid.UUID:
    return await conn.fetchval(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location)
        VALUES ($1, $2, 'zzgraph.test', now(), 0, 0,
                ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography)
        RETURNING id
        """,
        title,
        f"https://zzgraph.test/{uuid.uuid4()}",
    )


def _graph_article(article_id, title: str) -> dict:
    return {
        "id": article_id,
        "title": title,
        "source_url": "https://zzgraph.test/" + title,
        "latitude": 35.7,
        "longitude": 51.4,
        "published_at": datetime(2026, 10, 19, tzinfo=timezone.utc),
        "persons": ["Zz Graph Person"],
        "organizations": ["Zz Graph Org"],
        "region": "Zz Region, Iran",
        "country_code": "IR",
        "topic_tags": ["zz-topic"],
        "mentioned_locations": [{"name": "Zz Mentioned", "lat": 1.0, "lng": 2.0}],
    }


@pytest.mark.asyncio
async def test_a_cycle_writes_its_edges_and_leaves_known_nodes_alone(conn):
    pool = _Pool(conn)
    known = [
        ("PERSON", "Zz Graph Person"),
        ("ORG", "Zz Graph Org"),
        ("LOCATION", "Zz Region, Iran"),
        ("TOPIC", "zz-topic"),
        ("LOCATION", "Zz Mentioned"),
    ]
    with patch.object(knowledge_graph, "get_pool", new_callable=AsyncMock, return_value=pool):
        first_id = await _article(conn, "zzgraph-One")
        assert await knowledge_graph.populate_graph([_graph_article(first_id, "zzgraph-One")]) == 5
        before = {key: await _version(conn, *key) for key in known}

        second_id = await _article(conn, "zzgraph-Two")  # the next cycle: the same names
        assert await knowledge_graph.populate_graph([_graph_article(second_id, "zzgraph-Two")]) == 5
        after = {key: await _version(conn, *key) for key in known}

    assert {k: (v["xmin"], v["ctid"]) for k, v in after.items()} == {
        k: (v["xmin"], v["ctid"]) for k, v in before.items()
    }
    edges = await conn.fetch(
        """
        SELECT s.type AS source_type, s.name AS source, e.rel_type, t.name AS target
        FROM kg_edges e
        JOIN kg_nodes s ON s.id = e.source_node_id
        JOIN kg_nodes t ON t.id = e.target_node_id
        WHERE e.article_id = $1
        """,
        second_id,
    )
    assert sorted(tuple(r) for r in edges) == [
        ("ARTICLE", "zzgraph-Two", "ABOUT_TOPIC", "zz-topic"),
        ("ARTICLE", "zzgraph-Two", "LOCATED_AT", "Zz Region, Iran"),
        ("LOCATION", "Zz Mentioned", "MENTIONED_IN", "zzgraph-Two"),
        ("ORG", "Zz Graph Org", "MENTIONED_IN", "zzgraph-Two"),
        ("PERSON", "Zz Graph Person", "MENTIONED_IN", "zzgraph-Two"),
    ]
