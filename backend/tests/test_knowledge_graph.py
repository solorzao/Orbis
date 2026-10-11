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
            edges = await populate_graph([article])

        # Should have edges: 2 MENTIONED_IN (persons) + 1 LOCATED_AT + 1 CO_MENTIONED
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
    async def test_creates_co_mentioned_edges(self):
        from app.services.knowledge_graph import populate_graph

        pool, conn = _mock_pool()
        # 2 persons + 1 org = 3 entities => C(3,2) = 3 CO_MENTIONED edges
        article = _make_article(topic_tags=[])

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            edges = await populate_graph([article])

        # CO_MENTIONED: since execute returns "UPDATE 0", all will INSERT
        execute_calls = conn.execute.call_args_list
        co_mentioned_calls = [
            c for c in execute_calls if len(c[0]) >= 4 and c[0][3] == "CO_MENTIONED"
        ]
        assert len(co_mentioned_calls) == 3

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
        # 2 persons + 1 org = 3 MENTIONED_IN + 1 LOCATED_AT + 1 ABOUT_TOPIC + 3 CO_MENTIONED = 8
        article = _make_article()

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            edges = await populate_graph([article])

        assert edges == 8

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
    async def test_returns_zero_when_no_orphans(self):
        from app.services.knowledge_graph import purge_orphaned_nodes

        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 0")

        with patch(
            "app.services.knowledge_graph.get_pool", new_callable=AsyncMock, return_value=pool
        ):
            count = await purge_orphaned_nodes()

        assert count == 0
