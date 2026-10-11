"""Tests for the agent retrieval functions."""

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import retrieval

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"
HALFVEC_MIGRATION = MIGRATIONS / "008_halfvec_embedding_index.sql"
EDGE_RECENCY_MIGRATION = MIGRATIONS / "010_kg_edge_recency_indexes.sql"

_EMPTY_GRAPH = {"entity": None, "connections": [], "articles": []}

# One bounded read of a node's newest stored edges in one direction.
_RECENT_EDGE_SCAN = re.compile(
    r"FROM kg_edges e WHERE e\.(source|target)_node_id = (\$1|t\.id)"
    r" AND e\.rel_type <> 'CO_MENTIONED'( AND e\.rel_type = \$2)?"
    r" ORDER BY e\.created_at DESC LIMIT (\$\d+)\)"
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


def _is_co_mentions(sql: str) -> bool:
    return sql is retrieval._CO_MENTIONS_SQL


def _routed_fetch(*, co_mentions=(), traverse=(), edges=(), articles=()):
    """Fake ``pool.fetch`` that answers by query, so call order doesn't matter.

    Any answer may be an exception instance, which that query raises.
    """

    def answer(rows):
        if isinstance(rows, BaseException):
            raise rows
        return list(rows)

    async def fetch(sql, *args, **kwargs):
        if _is_co_mentions(sql):
            return answer(co_mentions)
        if "WITH RECURSIVE" in sql:
            return answer(traverse)
        if re.search(r"\barticles\b", sql):
            return answer(articles)
        return answer(edges)

    return AsyncMock(side_effect=fetch)


def _graph_pool(start_row: dict, fetch: AsyncMock) -> AsyncMock:
    """Fake pool for graph queries: ``fetchrow`` finds *start_row*.

    ``acquire()`` hands out ``pool.conn``, whose ``fetch`` is the pool's own
    *fetch*, so every query lands in one call list; its ``transaction()`` is
    ``pool.tx``.
    """
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=start_row)
    pool.fetch = fetch
    pool.conn = MagicMock()
    pool.conn.fetch = fetch
    pool.conn.execute = AsyncMock()
    pool.tx = MagicMock()
    pool.conn.transaction = MagicMock(return_value=pool.tx)
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = pool.conn
    return pool


def _start_row(name: str = "John Doe", node_type: str = "PERSON") -> dict:
    return {"id": uuid.uuid4(), "type": node_type, "name": name, "metadata": "{}"}


def _sql_calls(mock_fetch, marker: str) -> list:
    """Calls to *mock_fetch* whose SQL contains *marker*."""
    return [c for c in mock_fetch.call_args_list if marker in c.args[0]]


def _flat(sql: str) -> str:
    return " ".join(sql.split())


def _recent_edge_scans(call) -> list[tuple]:
    """(column, node, rel filter, per-node limit value) for each bounded edge read.

    Asserts that every kg_edges read in the query is such a bounded read.
    """
    sql = _flat(call.args[0])
    scans = _RECENT_EDGE_SCAN.findall(sql.replace("( SELECT", "(SELECT"))
    assert len(scans) == sql.count("FROM kg_edges"), "every kg_edges read must be bounded"
    assert sql.count("<> 'CO_MENTIONED'") == len(scans)
    return [
        (column, node, bool(rel), call.args[int(param[1:])]) for column, node, rel, param in scans
    ]


def _co_mention_calls(mock_fetch) -> list:
    return [c for c in mock_fetch.call_args_list if _is_co_mentions(c.args[0])]


def _article_calls(mock_fetch) -> list:
    return [c for c in mock_fetch.call_args_list if re.search(r"\barticles\b", c.args[0])]


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


def _sql_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]


class TestEdgeRecencyMigration:
    NEW_INDEXES = {
        "idx_kg_edges_source_recent": "source_node_id",
        "idx_kg_edges_target_recent": "target_node_id",
    }

    @pytest.mark.parametrize(("index", "column"), NEW_INDEXES.items())
    def test_rerun_drops_each_new_index_only_when_invalid(self, index, column):
        # A rerun after a failure past a CREATE must keep the valid index the
        # new backend depends on; only a failed (INVALID) build is dropped.
        lines = _sql_lines(EDGE_RECENCY_MIGRATION)
        sql = "\n".join(lines)
        flag = index.removeprefix("idx_kg_edges_") + "_invalid"

        assert f"WHERE c.relname = '{index}' AND NOT i.indisvalid" in sql
        assert rf"AS {flag} \gset" in sql
        assert (
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index}\n"
            f"ON kg_edges ({column}, created_at DESC);"
        ) in sql

        drops, guard = [], None
        for line in lines:
            if line.startswith(r"\if "):
                guard = line.removeprefix(r"\if ")
            elif line == r"\endif":
                guard = None
            elif line.startswith("DROP INDEX") and index in line:
                drops.append((line, guard))

        assert drops == [(f"DROP INDEX CONCURRENTLY {index};", f":{flag}")]

    def test_old_indexes_go_only_after_both_replacements_exist(self):
        lines = _sql_lines(EDGE_RECENCY_MIGRATION)
        last_create = max(
            i for i, line in enumerate(lines) if line.startswith("CREATE INDEX CONCURRENTLY")
        )
        for old in ("idx_kg_edges_source", "idx_kg_edges_target", "idx_kg_edges_rel"):
            drop = f"DROP INDEX CONCURRENTLY IF EXISTS {old};"
            assert drop in lines
            assert lines.index(drop) > last_create

    @pytest.mark.parametrize(("index", "column"), NEW_INDEXES.items())
    def test_bounded_edge_reads_match_the_index_order(self, index, column):
        # The index only stops a read early when the query filters on its
        # first column and orders by its second, in the same direction.
        sql = _flat(retrieval._recent_edges_sql("$1", "$2"))

        assert f"WHERE e.{column} = $1 AND" in sql
        scan = sql.split(f"WHERE e.{column} = $1", 1)[1]
        assert scan.split(")", 1)[0].endswith("ORDER BY e.created_at DESC LIMIT $2")


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

        mock_pool = _graph_pool(start_row, _routed_fetch(traverse=conn_rows, articles=art_rows))

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
    async def test_every_hop_reads_only_each_nodes_recent_edges(self):
        from app.services.retrieval import graph_traverse

        start = _start_row()
        mock_pool = _graph_pool(start, _routed_fetch())

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await graph_traverse("John Doe")

        (cte_call,) = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        assert cte_call.args[1] == start["id"]
        # The first hop ($1) and every later hop (t.id) read the node's newest
        # edges in each direction, never stored CO_MENTIONED rows.
        assert sorted(_recent_edge_scans(cte_call)) == [
            ("source", "$1", False, retrieval._RECENT_EDGES_PER_NODE),
            ("source", "t.id", False, retrieval._RECENT_EDGES_PER_NODE),
            ("target", "$1", False, retrieval._RECENT_EDGES_PER_NODE),
            ("target", "t.id", False, retrieval._RECENT_EDGES_PER_NODE),
        ]
        # Still one 50-row budget for the whole traversal
        assert _flat(cte_call.args[0]).endswith(f"LIMIT ${len(cte_call.args) - 1}")
        assert cte_call.args[-1] == retrieval._GRAPH_CONNECTION_LIMIT

    @pytest.mark.asyncio
    async def test_rel_type_filter_applies_inside_each_recent_edge_window(self):
        from app.services.retrieval import graph_traverse

        mock_pool = _graph_pool(_start_row(), _routed_fetch())

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await graph_traverse("John Doe", rel_type="located_at")

        (cte_call,) = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        assert cte_call.args[2] == "LOCATED_AT"
        scans = _recent_edge_scans(cte_call)
        # Filtered before the limit: the newest N edges of that type
        assert len(scans) == 4
        assert all(rel_filtered for _col, _node, rel_filtered, _n in scans)

    @pytest.mark.asyncio
    async def test_traversal_runs_without_bitmap_scans_and_with_a_timeout(self):
        from app.services.retrieval import graph_traverse

        mock_pool = _graph_pool(_start_row(), _routed_fetch())
        order = MagicMock()
        order.attach_mock(mock_pool.tx.__aenter__, "begin")
        order.attach_mock(mock_pool.conn.execute, "execute")
        order.attach_mock(mock_pool.fetch, "fetch")
        order.attach_mock(mock_pool.tx.__aexit__, "end")

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await graph_traverse("John Doe")

        steps = [
            (name, args[0] if name in ("execute", "fetch") else None)
            for name, args, _kwargs in order.mock_calls
        ]
        cte_step = next(
            i for i, (name, sql) in enumerate(steps) if name == "fetch" and "RECURSIVE" in sql
        )
        # SET LOCAL inside the traversal's own transaction, just before the CTE
        assert steps[cte_step - 2 : cte_step + 2] == [
            ("begin", None),
            ("execute", "SET LOCAL enable_bitmapscan = off"),
            steps[cte_step],
            ("end", None),
        ]
        (cte_call,) = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        assert cte_call.kwargs["timeout"] == retrieval._STORED_EDGES_TIMEOUT_S

    @pytest.mark.asyncio
    async def test_traversal_timeout_returns_co_mentions_only(self, caplog):
        from app.services.retrieval import graph_traverse

        co_article = uuid.uuid4()
        co_rows = [_co_mention_row("Jane Doe", 4, co_article)]
        mock_pool = _graph_pool(
            _start_row(),
            _routed_fetch(
                co_mentions=co_rows,
                traverse=asyncio.TimeoutError(),
                articles=[_article_row(co_article)],
            ),
        )

        with (
            patch(
                "app.services.retrieval.get_pool",
                new_callable=AsyncMock,
                return_value=mock_pool,
            ),
            caplog.at_level(logging.WARNING, logger="orbis.retrieval"),
        ):
            result = await graph_traverse("John Doe")

        assert result["entity"]["name"] == "John Doe"
        assert result["connections"] == co_rows
        assert [a["id"] for a in result["articles"]] == [co_article]
        assert "timed out" in caplog.text

    @pytest.mark.asyncio
    async def test_co_mentioned_filter_computes_co_mentions_without_cte(self):
        from app.services.retrieval import graph_traverse

        start_id = uuid.uuid4()
        article_id = uuid.uuid4()
        co_rows = [_co_mention_row("Jane Doe", 3, article_id)]

        mock_pool = _graph_pool(
            {"id": start_id, "type": "PERSON", "name": "John Doe"},
            _routed_fetch(co_mentions=co_rows, articles=[_article_row(article_id)]),
        )

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await graph_traverse("John Doe", rel_type="CO_MENTIONED")

        assert not _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        (co_call,) = _co_mention_calls(mock_pool.fetch)
        # Bounded: start entity's recent article window, with a statement timeout
        assert co_call.args[1:] == (start_id, retrieval._CO_MENTION_ARTICLE_WINDOW)
        assert co_call.kwargs["timeout"] == retrieval._CO_MENTIONS_TIMEOUT_S
        assert result["connections"] == co_rows
        # The representative article backs the co-mention as a citable source
        (art_call,) = _article_calls(mock_pool.fetch)
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

        mock_pool = _graph_pool(
            {"id": start_id, "type": "PERSON", "name": "John Doe"},
            _routed_fetch(
                co_mentions=co_rows,
                traverse=cte_rows,
                articles=[_article_row(co_article), _article_row(cte_article)],
            ),
        )

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await graph_traverse("John Doe")

        (cte_call,) = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        # Every edge read in the recursive CTE ignores stored CO_MENTIONED rows
        assert len(_recent_edge_scans(cte_call)) == 4
        # The CTE only fills what is left of the 50-row budget
        assert cte_call.args[-1] == 50 - len(co_rows)
        assert len(_co_mention_calls(mock_pool.fetch)) == 1
        # Computed co-mentions (depth 1, weighted) come first, then the CTE rows
        assert result["connections"] == co_rows + cte_rows
        (art_call,) = _article_calls(mock_pool.fetch)
        assert set(art_call.args[1]) == {co_article, cte_article}

    @pytest.mark.asyncio
    async def test_co_mention_timeout_falls_back_to_stored_edges(self, caplog):
        from app.services.retrieval import graph_traverse

        cte_article = uuid.uuid4()
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

        mock_pool = _graph_pool(
            _start_row(),
            _routed_fetch(
                co_mentions=asyncio.TimeoutError(),
                traverse=cte_rows,
                articles=[_article_row(cte_article)],
            ),
        )

        with (
            patch(
                "app.services.retrieval.get_pool",
                new_callable=AsyncMock,
                return_value=mock_pool,
            ),
            caplog.at_level(logging.WARNING, logger="orbis.retrieval"),
        ):
            result = await graph_traverse("John Doe")

        assert len(_co_mention_calls(mock_pool.fetch)) == 1
        assert result["entity"]["name"] == "John Doe"
        assert result["connections"] == cte_rows
        assert [a["id"] for a in result["articles"]] == [cte_article]
        # The whole 50-row budget goes to the stored-edge traversal
        (cte_call,) = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        assert cte_call.args[-1] == 50
        assert "timed out" in caplog.text

    @pytest.mark.asyncio
    async def test_co_mention_error_returns_empty_result(self):
        from app.services.retrieval import graph_traverse

        mock_pool = _graph_pool(
            _start_row(), _routed_fetch(co_mentions=RuntimeError("connection lost"))
        )

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await graph_traverse("John Doe")

        assert result == _EMPTY_GRAPH

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("rel_type", "runs_co_mentions", "runs_cte", "cte_rel_param"),
        [
            ("co_mentioned", True, False, None),
            ("", True, True, None),
            ("located_at", False, True, "LOCATED_AT"),
        ],
    )
    async def test_rel_type_is_normalised(
        self, rel_type, runs_co_mentions, runs_cte, cte_rel_param
    ):
        from app.services.retrieval import graph_traverse

        mock_pool = _graph_pool(_start_row(), _routed_fetch())

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await graph_traverse("John Doe", rel_type=rel_type)

        assert bool(_co_mention_calls(mock_pool.fetch)) is runs_co_mentions
        cte_calls = _sql_calls(mock_pool.fetch, "WITH RECURSIVE")
        assert bool(cte_calls) is runs_cte
        if runs_cte:
            (cte_call,) = cte_calls
            if cte_rel_param is None:
                # No rel filter: start id, depth, edges per node and limit
                assert len(cte_call.args) == 5
            else:
                assert cte_call.args[2] == cte_rel_param

    @pytest.mark.asyncio
    async def test_other_rel_type_filter_skips_co_mentions(self):
        from app.services.retrieval import graph_traverse

        mock_pool = _graph_pool(_start_row(), _routed_fetch())

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await graph_traverse("John Doe", rel_type="LOCATED_AT")

        assert not _co_mention_calls(mock_pool.fetch)
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

        (co_call,) = _co_mention_calls(mock_pool.fetch)
        assert co_call.args[1] == node_id
        # Every query that reads stored edges ignores CO_MENTIONED rows
        stored = [c for c in mock_pool.fetch.call_args_list if not _is_co_mentions(c.args[0])]
        assert len(stored) == 2
        for c in stored:
            assert "<> 'CO_MENTIONED'" in c.args[0]
        assert result["connections"] == co_rows + edge_rows

    @pytest.mark.asyncio
    async def test_entity_lookup_keeps_stored_edges_when_co_mentions_time_out(self):
        from app.services.retrieval import entity_lookup

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
            return_value={
                "id": uuid.uuid4(),
                "type": "ORG",
                "name": "United Nations",
                "metadata": "{}",
            }
        )
        mock_pool.fetch = _routed_fetch(co_mentions=asyncio.TimeoutError(), edges=edge_rows)

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await entity_lookup("United Nations")

        assert result["node"]["name"] == "United Nations"
        assert result["connections"] == edge_rows

    @pytest.mark.asyncio
    async def test_entity_lookup_reads_only_recent_edges_with_a_timeout(self):
        from app.services.retrieval import entity_lookup

        node = _start_row("United Nations", "ORG")
        mock_pool = _graph_pool(node, _routed_fetch())

        with patch(
            "app.services.retrieval.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await entity_lookup("United Nations")

        stored = [c for c in mock_pool.fetch.call_args_list if not _is_co_mentions(c.args[0])]
        assert len(stored) == 2  # connections, then articles
        for call in stored:
            assert call.args[1] == node["id"]
            # Both directions, newest edges first, never stored CO_MENTIONED rows
            assert sorted(_recent_edge_scans(call)) == [
                ("source", "$1", False, retrieval._RECENT_EDGES_PER_NODE),
                ("target", "$1", False, retrieval._RECENT_EDGES_PER_NODE),
            ]
            assert call.kwargs["timeout"] == retrieval._STORED_EDGES_TIMEOUT_S

    @pytest.mark.asyncio
    @pytest.mark.parametrize("timed_out", ["edges", "articles", "both"])
    async def test_entity_lookup_keeps_what_finished_when_edge_queries_time_out(
        self, timed_out, caplog
    ):
        from app.services.retrieval import entity_lookup

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
        art_rows = [_article_row(uuid.uuid4(), "UN Summit")]
        timeout = asyncio.TimeoutError()
        mock_pool = _graph_pool(
            _start_row("United Nations", "ORG"),
            _routed_fetch(
                co_mentions=co_rows,
                edges=timeout if timed_out in ("edges", "both") else edge_rows,
                articles=timeout if timed_out in ("articles", "both") else art_rows,
            ),
        )

        with (
            patch(
                "app.services.retrieval.get_pool",
                new_callable=AsyncMock,
                return_value=mock_pool,
            ),
            caplog.at_level(logging.WARNING, logger="orbis.retrieval"),
        ):
            result = await entity_lookup("United Nations")

        assert result["node"]["name"] == "United Nations"
        edges_ok = timed_out == "articles"
        assert result["connections"] == co_rows + (edge_rows if edges_ok else [])
        assert result["articles"] == ([] if timed_out in ("articles", "both") else art_rows)
        assert "timed out" in caplog.text
