"""Tests for the agent retrieval functions."""

import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

HALFVEC_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "008_halfvec_embedding_index.sql"
)


def _fake_embedding(dim: int = 1536) -> list[float]:
    return [0.01 * (i % 100) for i in range(dim)]


async def _semantic_search_sql() -> str:
    """Run semantic_search against mocks; return its SQL, whitespace-collapsed."""
    from app.services.retrieval import semantic_search

    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[])

    emb_obj = MagicMock()
    emb_obj.embedding = _fake_embedding()
    mock_response = MagicMock()
    mock_response.data = [emb_obj]

    mock_client = AsyncMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with (
        patch(
            "app.services.retrieval._get_openai_client",
            return_value=mock_client,
        ),
        patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        await semantic_search("climate change")

    mock_pool.fetch.assert_called_once()
    return " ".join(mock_pool.fetch.call_args[0][0].split())


class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_semantic_search_queries_by_embedding(self):
        from app.services.retrieval import semantic_search

        article_id = uuid.uuid4()
        db_rows = [
            {
                "id": article_id,
                "title": "Climate summit begins",
                "source_url": "https://example.com/1",
                "source_name": "Example News",
                "latitude": 48.8,
                "longitude": 2.3,
                "published_at": "2026-03-01T00:00:00Z",
                "sentiment_score": 0.5,
                "distance": 0.12,
            }
        ]

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=db_rows)

        emb_obj = MagicMock()
        emb_obj.embedding = _fake_embedding()
        mock_response = MagicMock()
        mock_response.data = [emb_obj]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with (
            patch(
                "app.services.retrieval._get_openai_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.retrieval.get_pool",
                new_callable=AsyncMock,
                return_value=mock_pool,
            ),
        ):
            results = await semantic_search("climate change")

        assert len(results) == 1
        assert results[0]["title"] == "Climate summit begins"
        mock_client.embeddings.create.assert_called_once()
        mock_pool.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_semantic_search_compares_at_half_precision(self):
        sql = await _semantic_search_sql()

        assert "embedding::halfvec(1536) <=> $1::halfvec(1536) AS distance" in sql
        assert "ORDER BY embedding::halfvec(1536) <=> $1::halfvec(1536)" in sql
        assert "::vector" not in sql

    @pytest.mark.asyncio
    async def test_semantic_search_matches_halfvec_index_expression(self):
        # The planner uses the HNSW index only when the ORDER BY expression
        # matches the index expression exactly; otherwise it scans the table.
        migration = HALFVEC_MIGRATION.read_text(encoding="utf-8")
        match = re.search(
            r"USING hnsw \(\((embedding::halfvec\(\d+\))\) halfvec_cosine_ops\)",
            migration,
        )
        assert match, "008 must index (embedding::halfvec(N)) halfvec_cosine_ops"
        index_cast = match.group(1)
        assert index_cast == "embedding::halfvec(1536)"

        sql = await _semantic_search_sql()
        assert f"ORDER BY {index_cast} <=> " in sql


class TestGraphTraverse:
    @pytest.mark.asyncio
    async def test_graph_traverse_returns_connected_nodes(self):
        from app.services.retrieval import graph_traverse

        node_id = uuid.uuid4()
        connected_id = uuid.uuid4()
        article_id = uuid.uuid4()

        start_row = {"id": node_id, "type": "PERSON", "name": "John Doe"}
        conn_rows = [
            {
                "id": connected_id,
                "type": "PERSON",
                "name": "Jane Doe",
                "rel_type": "MENTIONED_IN",
                "weight": 1.0,
                "article_id": article_id,
                "depth": 1,
            }
        ]
        art_rows = [
            {
                "id": article_id,
                "title": "Article about John",
                "source_url": "https://example.com/1",
                "source_name": "Example",
                "latitude": 40.0,
                "longitude": -74.0,
                "published_at": "2026-03-01T00:00:00Z",
                "sentiment_score": 0.5,
            }
        ]

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=start_row)
        mock_pool.fetch = AsyncMock(side_effect=[conn_rows, art_rows])

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await graph_traverse("John Doe")

        assert result["entity"]["name"] == "John Doe"
        assert len(result["connections"]) == 1
        assert result["connections"][0]["name"] == "Jane Doe"
        assert result["connections"][0]["rel_type"] == "MENTIONED_IN"
        assert len(result["articles"]) == 1


class TestKeywordSearch:
    @pytest.mark.asyncio
    async def test_keyword_search_filters_articles(self):
        from app.services.retrieval import keyword_search

        article_id = uuid.uuid4()
        db_rows = [
            {
                "id": article_id,
                "title": "Election results announced",
                "source_url": "https://example.com/2",
                "source_name": "News Outlet",
                "latitude": 38.9,
                "longitude": -77.0,
                "published_at": "2026-03-01T00:00:00Z",
                "sentiment_score": 0.2,
                "topic_tags": ["politics"],
                "country_code": "US",
            }
        ]

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=db_rows)

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            results = await keyword_search(terms="election", topic="politics")

        assert len(results) == 1
        assert results[0]["title"] == "Election results announced"
        mock_pool.fetch.assert_called_once()
        # Verify the query received both filter params plus the limit
        call_args = mock_pool.fetch.call_args
        assert call_args[0][1] == "election"  # terms param
        assert call_args[0][2] == "politics"  # topic param

    @pytest.mark.asyncio
    async def test_keyword_search_uppercases_country_code(self):
        from app.services.retrieval import keyword_search

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await keyword_search(country="es")

        query, country, _limit = mock_pool.fetch.call_args[0]
        assert "country_code = $1" in query
        assert country == "ES"


class TestTrendingTopics:
    @pytest.mark.asyncio
    async def test_trending_topics_returns_counts(self):
        from app.services.retrieval import trending_topics

        db_rows = [
            {"topic": "politics", "count": 42},
            {"topic": "climate", "count": 31},
        ]

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=db_rows)

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            results = await trending_topics(hours=12)

        assert len(results) == 2
        assert results[0]["topic"] == "politics"
        assert results[0]["count"] == 42
        mock_pool.fetch.assert_called_once()
        # Verify hours param was passed
        assert mock_pool.fetch.call_args[0][1] == 12


class TestEntityLookup:
    @pytest.mark.asyncio
    async def test_entity_lookup_finds_node_and_connections(self):
        from app.services.retrieval import entity_lookup

        node_id = uuid.uuid4()
        conn_id = uuid.uuid4()
        article_id = uuid.uuid4()

        node_row = {
            "id": node_id,
            "type": "ORGANIZATION",
            "name": "United Nations",
            "metadata": '{"abbrev": "UN"}',
        }
        conn_rows = [
            {
                "id": conn_id,
                "type": "PERSON",
                "name": "Secretary General",
                "rel_type": "LEADS",
                "weight": 1.0,
                "metadata": "{}",
            }
        ]
        art_rows = [
            {
                "id": article_id,
                "title": "UN Summit",
                "source_url": "https://example.com/un",
                "source_name": "News",
                "latitude": 40.7,
                "longitude": -74.0,
                "published_at": "2026-03-01T00:00:00Z",
                "sentiment_score": 0.3,
            }
        ]

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=node_row)
        mock_pool.fetch = AsyncMock(side_effect=[conn_rows, art_rows])

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await entity_lookup("United Nations")

        assert result["node"]["name"] == "United Nations"
        assert len(result["connections"]) == 1
        assert result["connections"][0]["rel_type"] == "LEADS"
        assert len(result["articles"]) == 1
        mock_pool.fetchrow.assert_called_once()
        assert mock_pool.fetch.call_count == 2
