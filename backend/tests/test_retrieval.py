"""Tests for the agent retrieval functions."""

import re
import uuid
from pathlib import Path
from typing import Any
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


async def _run_semantic_search(
    db_rows: list[dict] | None = None, **kwargs: Any
) -> tuple[list[dict], str, list[Any]]:
    """Run semantic_search against mocked OpenAI and pool clients.

    Returns the results, the SQL with whitespace collapsed, and the query params.
    """
    from app.services.retrieval import semantic_search

    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=db_rows or [])

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
        results = await semantic_search("climate change", **kwargs)

    mock_client.embeddings.create.assert_called_once()
    mock_pool.fetch.assert_called_once()
    sql, *params = mock_pool.fetch.call_args[0]
    return results, " ".join(sql.split()), params


def _routed_fetch(*, co_mentions=(), traverse=(), edges=(), articles=()):
    """Fake ``pool.fetch`` that answers by SQL shape, so call order doesn't matter."""

    async def fetch(sql, *args):
        if "count(DISTINCT" in sql:
            return list(co_mentions)
        if "WITH RECURSIVE" in sql:
            return list(traverse)
        if "title" in sql:
            return list(articles)
        return list(edges)

    return AsyncMock(side_effect=fetch)


def _sql_calls(mock_fetch, marker: str) -> list:
    """Calls to *mock_fetch* whose SQL contains *marker*."""
    return [c for c in mock_fetch.call_args_list if marker in c.args[0]]


def _co_mention_row(name: str, weight: int, article_id, node_type: str = "PERSON") -> dict:
    return {
        "id": uuid.uuid4(),
        "type": node_type,
        "name": name,
        "rel_type": "CO_MENTIONED",
        "weight": weight,
        "article_id": article_id,
        "depth": 1,
    }


def _article_row(article_id, title: str = "Story") -> dict:
    return {
        "id": article_id,
        "title": title,
        "source_url": f"https://example.com/{article_id}",
        "source_name": "Example",
        "latitude": 40.0,
        "longitude": -74.0,
        "published_at": "2026-03-01T00:00:00Z",
        "sentiment_score": 0.5,
    }


class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_semantic_search_queries_by_embedding(self):
        db_rows = [
            {
                "id": uuid.uuid4(),
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

        results, _sql, _params = await _run_semantic_search(db_rows)

        assert len(results) == 1
        assert results[0]["title"] == "Climate summit begins"

    @pytest.mark.asyncio
    async def test_semantic_search_compares_at_half_precision(self):
        _results, sql, _params = await _run_semantic_search()

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

        _results, sql, _params = await _run_semantic_search()
        assert f"ORDER BY {index_cast} <=> " in sql

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("requested", "sent"), [(10, 10), (40, 40), (100, 40)])
    async def test_semantic_search_caps_limit_at_hnsw_ef_search(self, requested, sent):
        # An HNSW scan returns at most hnsw.ef_search (default 40) rows.
        _results, _sql, params = await _run_semantic_search(limit=requested)

        assert params[1] == sent


class TestHalfvecMigration:
    def test_rerun_drops_the_half_index_only_when_invalid(self):
        # A rerun after a failure past the CREATE must keep the valid index the
        # new backend depends on; only a failed (INVALID) build is dropped.
        lines = [
            line.strip()
            for line in HALFVEC_MIGRATION.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        sql = "\n".join(lines)

        assert "NOT i.indisvalid" in sql
        assert r"AS half_index_invalid \gset" in sql
        assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_embedding_half" in sql
        assert "DROP INDEX CONCURRENTLY IF EXISTS idx_articles_embedding;" in sql

        half_drops = []
        guarded = False
        for line in lines:
            if line == r"\if :half_index_invalid":
                guarded = True
            elif line == r"\endif":
                guarded = False
            elif line.startswith("DROP INDEX") and "idx_articles_embedding_half" in line:
                half_drops.append((line, guarded))

        assert half_drops == [("DROP INDEX CONCURRENTLY idx_articles_embedding_half;", True)]


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
        mock_pool.fetch = _routed_fetch(traverse=conn_rows, articles=art_rows)

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

    @pytest.mark.asyncio
    async def test_co_mentioned_filter_computes_co_mentions_without_cte(self):
        from app.services.retrieval import graph_traverse

        start_id = uuid.uuid4()
        article_id = uuid.uuid4()
        co_rows = [_co_mention_row("Jane Doe", 3, article_id)]

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={"id": start_id, "type": "PERSON", "name": "John Doe"}
        )
        mock_pool.fetch = _routed_fetch(co_mentions=co_rows, articles=[_article_row(article_id)])

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await graph_traverse("John Doe", rel_type="CO_MENTIONED")

        assert not _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        (co_call,) = _sql_calls(mock_pool.fetch, "count(DISTINCT")
        assert "'MENTIONED_IN'" in co_call.args[0]
        assert co_call.args[1] == start_id
        assert result["connections"] == co_rows
        # The representative article backs the co-mention as a citable source
        (art_call,) = _sql_calls(mock_pool.fetch, "title")
        assert art_call.args[1] == [article_id]
        assert [a["id"] for a in result["articles"]] == [article_id]

    @pytest.mark.asyncio
    async def test_default_traversal_skips_stored_co_mentions_and_merges_computed(self):
        from app.services.retrieval import graph_traverse

        start_id = uuid.uuid4()
        co_article = uuid.uuid4()
        cte_article = uuid.uuid4()
        co_rows = [
            _co_mention_row("Jane Doe", 4, co_article),
            _co_mention_row("Acme Corp", 2, co_article, node_type="ORG"),
        ]
        cte_rows = [
            {
                "id": uuid.uuid4(),
                "type": "ARTICLE",
                "name": "Article about John",
                "rel_type": "MENTIONED_IN",
                "weight": 1,
                "article_id": cte_article,
                "depth": 1,
            }
        ]

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={"id": start_id, "type": "PERSON", "name": "John Doe"}
        )
        mock_pool.fetch = _routed_fetch(
            co_mentions=co_rows,
            traverse=cte_rows,
            articles=[_article_row(co_article), _article_row(cte_article)],
        )

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await graph_traverse("John Doe")

        (cte_call,) = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        # Both halves of the recursive CTE ignore stored CO_MENTIONED rows
        assert cte_call.args[0].count("<> 'CO_MENTIONED'") == 2
        # The CTE only fills what is left of the 50-row budget
        assert cte_call.args[-1] == 50 - len(co_rows)
        assert len(_sql_calls(mock_pool.fetch, "count(DISTINCT")) == 1
        # Computed co-mentions (depth 1, weighted) come first, then the CTE rows
        assert result["connections"] == co_rows + cte_rows
        (art_call,) = _sql_calls(mock_pool.fetch, "title")
        assert set(art_call.args[1]) == {co_article, cte_article}

    @pytest.mark.asyncio
    async def test_other_rel_type_filter_skips_co_mentions(self):
        from app.services.retrieval import graph_traverse

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={"id": uuid.uuid4(), "type": "PERSON", "name": "John Doe"}
        )
        mock_pool.fetch = _routed_fetch()

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await graph_traverse("John Doe", rel_type="LOCATED_AT")

        assert not _sql_calls(mock_pool.fetch, "count(DISTINCT")
        (cte_call,) = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        assert "LOCATED_AT" in cte_call.args


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
        mock_pool.fetch = _routed_fetch(edges=conn_rows, articles=art_rows)

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
        # Computed co-mentions, stored edges, articles
        assert mock_pool.fetch.call_count == 3

    @pytest.mark.asyncio
    async def test_entity_lookup_computes_co_mentions_and_skips_stored_ones(self):
        from app.services.retrieval import entity_lookup

        node_id = uuid.uuid4()
        co_rows = [_co_mention_row("Secretary General", 5, uuid.uuid4())]
        edge_rows = [
            {
                "id": uuid.uuid4(),
                "type": "ARTICLE",
                "name": "UN Summit",
                "rel_type": "MENTIONED_IN",
                "weight": 1,
                "metadata": "{}",
            }
        ]

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={"id": node_id, "type": "ORG", "name": "United Nations", "metadata": "{}"}
        )
        mock_pool.fetch = _routed_fetch(co_mentions=co_rows, edges=edge_rows)

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await entity_lookup("United Nations")

        (co_call,) = _sql_calls(mock_pool.fetch, "count(DISTINCT")
        assert co_call.args[1] == node_id
        # Every query that reads stored edges ignores CO_MENTIONED rows
        stored = [c for c in mock_pool.fetch.call_args_list if "count(DISTINCT" not in c.args[0]]
        assert len(stored) == 2
        for c in stored:
            assert "<> 'CO_MENTIONED'" in c.args[0]
        assert result["connections"] == co_rows + edge_rows
