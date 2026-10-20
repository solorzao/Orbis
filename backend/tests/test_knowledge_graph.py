"""Tests for the knowledge graph population service."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_article(**overrides):
    """Build a sample article dict for knowledge graph population."""
    base = {
        "id": uuid.uuid4(),
        "title": "Test Article",
        "source_url": "https://example.com/story",
        "latitude": 35.7,
        "longitude": 51.4,
        "region": "Tehran, Tehran, Iran",
        "country_code": "IR",
        "topic_tags": ["politics"],
        "persons": ["Alice Smith", "Bob Jones"],
        "organizations": ["Acme Corp"],
        "published_at": datetime(2026, 3, 5, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def _mock_pool():
    """Create a mock asyncpg pool with connection context manager."""
    conn = AsyncMock()
    # Each fetchval call returns a new UUID (for node IDs)
    conn.fetchval = AsyncMock(side_effect=lambda *a, **kw: uuid.uuid4())
    conn.execute = AsyncMock(return_value="UPDATE 0")

    # Make conn usable as async context manager for transaction
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    # Make conn usable as async context manager for acquire
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)

    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=acq)
    pool.execute = AsyncMock(return_value="DELETE 0")

    return pool, conn


class TestPopulateGraph:
    @pytest.mark.asyncio
    async def test_creates_article_nodes(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        article = _make_article(persons=[], organizations=[], topic_tags=[])

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await populate_graph([article])

        # First fetchval call should be for the ARTICLE node
        first_call = conn.fetchval.call_args_list[0]
        assert first_call[0][1] == "ARTICLE"
        assert first_call[0][2] == "Test Article"

    @pytest.mark.asyncio
    async def test_creates_mentioned_in_edges_for_persons(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        article = _make_article(organizations=[], topic_tags=[])

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await populate_graph([article])

        # Should have edges: 2 MENTIONED_IN (persons) + 1 LOCATED_AT
        # Check that MENTIONED_IN was used in execute calls
        execute_calls = conn.execute.call_args_list
        mentioned_in_calls = [
            c for c in execute_calls if len(c[0]) >= 4 and c[0][3] == "MENTIONED_IN"
        ]
        assert len(mentioned_in_calls) == 2

    @pytest.mark.asyncio
    async def test_creates_mentioned_in_edges_for_orgs(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        article = _make_article(persons=[], topic_tags=[])

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await populate_graph([article])

        execute_calls = conn.execute.call_args_list
        mentioned_in_calls = [
            c for c in execute_calls if len(c[0]) >= 4 and c[0][3] == "MENTIONED_IN"
        ]
        assert len(mentioned_in_calls) == 1

    @pytest.mark.asyncio
    async def test_does_not_store_co_mentioned_edges(self):
        """Co-mentions are computed at query time, so no pair rows are written."""
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        # 2 persons + 1 org + 1 mentioned location: 4 entities, 6 possible pairs
        article = _make_article(
            topic_tags=[],
            mentioned_locations=[{"name": "China", "lat": 35, "lng": 105}],
        )

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await populate_graph([article])

        sent = [
            str(arg)
            for c in conn.execute.call_args_list + conn.fetchval.call_args_list
            for arg in c.args
        ]
        assert not [arg for arg in sent if "CO_MENTIONED" in arg]
        # One INSERT per edge and nothing else: 4 MENTIONED_IN + 1 LOCATED_AT
        assert conn.execute.await_count == 5

    @pytest.mark.asyncio
    async def test_creates_located_at_edges(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        article = _make_article(persons=[], organizations=[], topic_tags=[])

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await populate_graph([article])

        execute_calls = conn.execute.call_args_list
        located_at_calls = [c for c in execute_calls if len(c[0]) >= 4 and c[0][3] == "LOCATED_AT"]
        assert len(located_at_calls) == 1

    @pytest.mark.asyncio
    async def test_location_metadata_keeps_iso_and_fips_codes(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        article = _make_article(
            persons=[],
            organizations=[],
            topic_tags=[],
            region="London, London, United Kingdom",
            country_code="GB",
            country_fips="UK",
            mentioned_locations=[
                {"name": "China", "country_code": "CN", "country_fips": "CH", "lat": 35, "lng": 105}
            ],
        )

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await populate_graph([article])

        metadata = {
            c.args[2]: json.loads(c.args[3])
            for c in conn.fetchval.call_args_list
            if len(c.args) >= 4 and c.args[1] == "LOCATION"
        }
        city = metadata["London, London, United Kingdom"]
        assert (city["country_code"], city["country_fips"]) == ("GB", "UK")
        assert (metadata["China"]["country_code"], metadata["China"]["country_fips"]) == (
            "CN",
            "CH",
        )

    @pytest.mark.asyncio
    async def test_creates_about_topic_edges(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        article = _make_article(persons=[], organizations=[], topic_tags=["politics", "economy"])

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await populate_graph([article])

        execute_calls = conn.execute.call_args_list
        topic_calls = [c for c in execute_calls if len(c[0]) >= 4 and c[0][3] == "ABOUT_TOPIC"]
        assert len(topic_calls) == 2

    @pytest.mark.asyncio
    async def test_returns_edge_count(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        # 2 persons + 1 org = 3 MENTIONED_IN + 1 LOCATED_AT + 1 ABOUT_TOPIC = 5
        article = _make_article()

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            edges = await populate_graph([article])

        assert edges == 5

    @pytest.mark.asyncio
    async def test_empty_articles_returns_zero(self):
        from app.services.knowledge_graph import populate_graph

        result = await populate_graph([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_skips_articles_without_id(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        article = _make_article()
        article["id"] = None

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            edges = await populate_graph([article])

        assert edges == 0
        conn.fetchval.assert_not_called()


class TestPurgeOrphanedNodes:
    @pytest.mark.asyncio
    async def test_calls_delete_on_kg_nodes(self):
        from app.services.knowledge_graph import purge_orphaned_nodes

        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 5")

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            count = await purge_orphaned_nodes()

        assert count == 5
        pool.execute.assert_called_once()
        call_sql = pool.execute.call_args[0][0]
        assert "DELETE FROM kg_nodes" in call_sql

    @pytest.mark.asyncio
    async def test_finds_orphans_with_not_exists(self):
        """NOT IN over every edge can't hash in 4 MB of work_mem and ran for minutes."""
        from app.services.knowledge_graph import purge_orphaned_nodes

        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 0")

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await purge_orphaned_nodes()

        sql = " ".join(pool.execute.call_args[0][0].split())
        assert "NOT IN" not in sql
        assert "NOT EXISTS (SELECT 1 FROM kg_edges e WHERE e.source_node_id = n.id)" in sql
        assert "NOT EXISTS (SELECT 1 FROM kg_edges e WHERE e.target_node_id = n.id)" in sql

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_orphans(self):
        from app.services.knowledge_graph import purge_orphaned_nodes

        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 0")

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            count = await purge_orphaned_nodes()

        assert count == 0


NODE = uuid.UUID("00000000-0000-0000-0000-00000000000b")


def _flat(sql: str) -> str:
    return " ".join(sql.split())


class TestUpsertNode:
    @pytest.mark.asyncio
    async def test_a_node_without_metadata_is_never_rewritten(self):
        from app.services.knowledge_graph import upsert_node

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=NODE)
        assert await upsert_node(conn, "PERSON", "Alice Smith", {}) == NODE

        sql, *args = conn.fetchval.await_args.args
        # A known name is left as it is: no new row version, so no index entries.
        assert "ON CONFLICT (type, name) DO NOTHING" in _flat(sql)
        assert args == ["PERSON", "Alice Smith", "{}"]

    @pytest.mark.asyncio
    async def test_metadata_is_merged_only_when_the_merge_changes_it(self):
        from app.services.knowledge_graph import upsert_node

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=NODE)
        await upsert_node(conn, "LOCATION", "Tehran", {"lat": 35.7, "lng": 51.4})

        sql, *args = conn.fetchval.await_args.args
        # The merge is compared whole (jsonb equality), so what is written is exactly
        # what || makes, whatever the values' shapes.
        assert (
            "ON CONFLICT (type, name) DO UPDATE"
            " SET metadata = kg_nodes.metadata || EXCLUDED.metadata"
            " WHERE kg_nodes.metadata || EXCLUDED.metadata IS DISTINCT FROM kg_nodes.metadata"
        ) in _flat(sql)
        assert args == ["LOCATION", "Tehran", json.dumps({"lat": 35.7, "lng": 51.4})]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("metadata", [{}, {"lat": 1.0}])
    async def test_an_untouched_rows_id_comes_from_the_same_statement(self, metadata):
        from app.services.knowledge_graph import upsert_node

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=NODE)
        await upsert_node(conn, "ORG", "Acme Corp", metadata)

        sql = _flat(conn.fetchval.await_args.args[0])
        assert sql.startswith("WITH up AS ( INSERT INTO kg_nodes (type, name, metadata)")
        assert sql.endswith(
            ") SELECT id FROM up UNION ALL SELECT id FROM kg_nodes"
            " WHERE type = $1 AND name = $2 AND NOT EXISTS (SELECT 1 FROM up)"
        )
        conn.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_row_a_concurrent_writer_inserted_is_read_by_a_new_statement(self):
        from app.services.knowledge_graph import upsert_node

        conn = AsyncMock()
        # The statement's snapshot predates the other writer's commit: no id.
        conn.fetchval = AsyncMock(side_effect=[None, NODE])
        assert await upsert_node(conn, "PERSON", "Alice Smith", {}) == NODE

        sql, *args = conn.fetchval.await_args.args
        assert _flat(sql) == "SELECT id FROM kg_nodes WHERE type = $1 AND name = $2"
        assert args == ["PERSON", "Alice Smith"]

    @pytest.mark.asyncio
    async def test_a_node_gone_before_its_edge_is_a_clear_error(self):
        from app.services.knowledge_graph import upsert_node

        conn = AsyncMock()
        # Deleted in between, by an orphan purge from an overlapping backend.
        conn.fetchval = AsyncMock(side_effect=[None, None])
        with pytest.raises(RuntimeError, match=r"PERSON node 'Alice Smith'"):
            await upsert_node(conn, "PERSON", "Alice Smith", {})

    @pytest.mark.asyncio
    async def test_every_node_of_an_article_goes_through_it(self):
        from app.services import knowledge_graph

        pool, conn = _mock_pool()
        article = _make_article(mentioned_locations=[{"name": "China", "lat": 35, "lng": 105}])
        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            await knowledge_graph.populate_graph([article])

        sql_by_type = {}
        for call in conn.fetchval.call_args_list:
            sql_by_type.setdefault(call.args[1], set()).add(call.args[0])
        keep, merge = knowledge_graph._KEEP_NODE_SQL, knowledge_graph._MERGE_NODE_SQL
        assert sql_by_type == {
            "ARTICLE": {merge},
            "PERSON": {keep},
            "ORG": {keep},
            "LOCATION": {merge},
            "TOPIC": {keep},
        }
