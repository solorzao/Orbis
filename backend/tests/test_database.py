"""Tests for the SQL the database helpers send (the pool is mocked; no live database)."""

import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import database
from app.services.database import upsert_articles


def _mock_pool():
    conn = MagicMock()
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def _transaction():
        yield

    @asynccontextmanager
    async def _acquire():
        yield conn

    conn.transaction = _transaction
    pool = MagicMock()
    pool.acquire = _acquire
    return pool, conn


@pytest.mark.asyncio
async def test_upsert_writes_country_fips_and_never_null():
    pool, conn = _mock_pool()
    articles = [
        {"source_url": "https://example.com/a", "country_code": "GB", "country_fips": "UK"},
        {"source_url": "https://example.com/b", "country_code": ""},  # no country_fips key
        {"source_url": "https://example.com/c", "country_code": "", "country_fips": None},
    ]

    with patch("app.services.database.get_pool", new_callable=AsyncMock, return_value=pool):
        assert await upsert_articles(articles) == 3

    sql, *args = conn.execute.await_args_list[0].args
    assert "country_fips = EXCLUDED.country_fips" in sql
    # Every placeholder has an argument and vice versa.
    assert max(int(n) for n in re.findall(r"\$(\d+)", sql)) == len(args)

    fips_values = [call.args[-1] for call in conn.execute.await_args_list]
    assert fips_values == ["UK", "", ""]


START = datetime(2026, 3, 7, 10, tzinfo=timezone.utc)
END = datetime(2026, 3, 8, 10, tzinfo=timezone.utc)


@pytest.fixture
def pool():
    mock = MagicMock()
    mock.fetch = AsyncMock(return_value=[])
    with patch.object(database, "get_pool", AsyncMock(return_value=mock)):
        yield mock


def _globe_row(**overrides):
    row = {
        "lat": 40.5,
        "lng": -74.5,
        "article_count": 3,
        "top_headline": "Match report",
        "topic_tags": ["sport"],
        "location_name": "New York",
        "topics": ["conflict", "sport"],
    }
    return {**row, **overrides}


def _selected_columns(query: str) -> set[str]:
    """The columns the dedup subquery reads from ``articles``."""
    match = re.search(r"DISTINCT ON \(lower\(title\)\)\s+(.*?)\s+FROM articles", query, re.S)
    assert match, query
    return {col.strip() for col in match.group(1).split(",")}


class TestGetArticlesInBounds:
    @pytest.mark.asyncio
    async def test_window_and_limit_are_query_parameters(self, pool):
        await database.get_articles_in_bounds(
            40.0, -75.0, 41.0, -74.0, limit=300, start_time=START, end_time=END
        )

        query, *args = pool.fetch.call_args.args
        assert args == [40.0, -75.0, 41.0, -74.0, 300, START, END, None]
        assert "published_at >= $6" in query
        assert "published_at <= $7" in query

    @pytest.mark.asyncio
    async def test_topics_are_parameter_8(self, pool):
        await database.get_articles_in_bounds(40.0, -75.0, 41.0, -74.0, topics=["conflict"])

        query, *args = pool.fetch.call_args.args
        assert args[7] == ["conflict"]
        assert "($8::text[] IS NULL OR topic_tags && $8)" in query

    @pytest.mark.asyncio
    async def test_topic_filter_runs_inside_the_dedup_before_the_limit(self, pool):
        """Dedup picks among matching rows, and the limit counts matching rows only."""
        await database.get_articles_in_bounds(40.0, -75.0, 41.0, -74.0, topics=["conflict"])

        query = pool.fetch.call_args.args[0]
        topic = query.index("topic_tags && $8")
        assert query.index("DISTINCT ON (lower(title))") < topic
        assert topic < query.index(") deduped") < query.index("LIMIT $5")

    @pytest.mark.asyncio
    async def test_selects_the_article_columns_but_not_the_embedding(self, pool):
        """A 300-row cell must not pull 300 1536-dim vectors."""
        from app.models.news import NewsArticle

        await database.get_articles_in_bounds(40.0, -75.0, 41.0, -74.0)

        columns = _selected_columns(pool.fetch.call_args.args[0])
        assert "embedding" not in columns
        assert "*" not in columns
        assert columns == set(NewsArticle.model_fields)

    @pytest.mark.asyncio
    async def test_ties_on_published_at_have_a_stable_order(self, pool):
        """GDELT stamps a whole 15-minute batch alike; offset paging needs a total order."""
        await database.get_articles_in_bounds(40.0, -75.0, 41.0, -74.0)

        query = pool.fetch.call_args.args[0]
        outer = query[query.index(") deduped") :]
        assert "ORDER BY published_at DESC, id" in outer

    @pytest.mark.asyncio
    async def test_window_is_applied_before_the_limit(self, pool):
        await database.get_articles_in_bounds(
            40.0, -75.0, 41.0, -74.0, limit=300, start_time=START, end_time=END
        )

        query = pool.fetch.call_args.args[0]
        assert query.index("published_at >= $6") < query.index("LIMIT $5")

    @pytest.mark.asyncio
    async def test_envelope_takes_lng_lat_order(self, pool):
        await database.get_articles_in_bounds(40.0, -75.0, 41.0, -74.0)

        query = pool.fetch.call_args.args[0]
        assert "ST_MakeEnvelope($2, $1, $4, $3, 4326)" in query

    @pytest.mark.asyncio
    async def test_either_bound_may_be_given_alone(self, pool):
        await database.get_articles_in_bounds(40.0, -75.0, 41.0, -74.0, start_time=START)
        assert pool.fetch.call_args.args[6:8] == (START, None)

        await database.get_articles_in_bounds(40.0, -75.0, 41.0, -74.0, end_time=END)
        assert pool.fetch.call_args.args[6:8] == (None, END)


class TestGetGlobePoints:
    @pytest.mark.asyncio
    async def test_windowed_query_aggregates_cell_topics(self, pool):
        pool.fetch.return_value = [_globe_row()]

        await database.get_globe_points(cell_size=1.0, start_time=START, end_time=END)

        assert pool.fetch.call_count == 1
        query = pool.fetch.call_args.args[0]
        assert "unnest(topic_tags)" in query
        assert "array_agg(DISTINCT tag)" in query

    @pytest.mark.asyncio
    async def test_fallback_query_aggregates_cell_topics(self, pool):
        pool.fetch.side_effect = [[], [_globe_row()]]

        await database.get_globe_points(cell_size=1.0)

        assert pool.fetch.call_count == 2
        fallback = pool.fetch.call_args_list[1].args[0]
        assert "unnest(topic_tags)" in fallback
        assert "array_agg(DISTINCT tag)" in fallback

    @pytest.mark.asyncio
    async def test_rows_carry_all_cell_topics_and_newest_topic(self, pool):
        pool.fetch.return_value = [_globe_row()]

        [point] = await database.get_globe_points(cell_size=1.0)

        assert point["topic"] == "sport"  # newest story's first tag, for the dot colour
        assert point["topics"] == ["conflict", "sport"]

    @pytest.mark.asyncio
    async def test_cell_without_tags_has_no_topics(self, pool):
        pool.fetch.return_value = [_globe_row(topic_tags=None, topics=None)]

        [point] = await database.get_globe_points(cell_size=1.0)

        assert point["topic"] == "general"
        assert point["topics"] == []
