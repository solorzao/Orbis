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


def _sql(query: str) -> str:
    """*query* with its whitespace collapsed, for substring and order checks."""
    return " ".join(query.split())


def _fetched(pool) -> tuple[str, list]:
    """The last query sent (whitespace collapsed) and its arguments."""
    query, *args = pool.fetch.call_args.args
    return _sql(query), args


def _selected_columns(query: str) -> set[str]:
    """The columns the dedup subquery reads from ``articles``."""
    match = re.search(r"DISTINCT ON \(lower\(title\)\) (.*?) FROM articles", _sql(query))
    assert match, query
    return {col.strip() for col in match.group(1).split(",")}


# The New York cell: lat [40, 41), lng [-75, -74).
CELL = (40.0, -75.0, 41.0, -74.0)


class TestGetArticlesInBounds:
    @pytest.mark.asyncio
    async def test_cell_box_and_limit_are_the_first_parameters(self, pool):
        await database.get_articles_in_bounds(*CELL, limit=300)

        _, args = _fetched(pool)
        # Bounds, then the padded (lng, lat) box for the index, then the limit.
        assert args == pytest.approx([*CELL, -75.01, 39.99, -73.99, 41.01, 300])

    @pytest.mark.asyncio
    async def test_cell_is_half_open_like_the_dots(self, pool):
        """Dots use FLOOR, so a point on the lower edge belongs to this cell."""
        await database.get_articles_in_bounds(*CELL)

        query, _ = _fetched(pool)
        assert "latitude >= $1 AND latitude < $3 AND longitude >= $2 AND longitude < $4" in query

    @pytest.mark.asyncio
    async def test_index_prefilter_is_a_geography_box(self, pool):
        """&& on the geography column can use idx_articles_location; ST_Within on a cast cannot."""
        await database.get_articles_in_bounds(*CELL)

        query, _ = _fetched(pool)
        assert "location && ST_MakeEnvelope($5, $6, $7, $8, 4326)::geography" in query
        assert "ST_Within" not in query

    @pytest.mark.asyncio
    async def test_padded_box_stays_on_the_globe(self, pool):
        await database.get_articles_in_bounds(89.0, 179.0, 90.0, 180.0)
        assert _fetched(pool)[1][4:8] == pytest.approx([178.99, 88.99, 180.0, 90.0])

        await database.get_articles_in_bounds(-90.0, -180.0, -89.0, -179.0)
        assert _fetched(pool)[1][4:8] == pytest.approx([-180.0, -90.0, -178.99, -88.99])

    @pytest.mark.asyncio
    async def test_no_window_or_topic_means_no_such_predicates(self, pool):
        """No `$n IS NULL OR ...`: a generic plan for those could not use the indexes."""
        await database.get_articles_in_bounds(*CELL)

        query, args = _fetched(pool)
        assert len(args) == 9
        assert "IS NULL" not in query
        assert "published_at >=" not in query
        assert "published_at <=" not in query
        assert "topic_tags &&" not in query

    @pytest.mark.asyncio
    async def test_window_and_topics_follow_the_limit(self, pool):
        await database.get_articles_in_bounds(
            *CELL, limit=300, start_time=START, end_time=END, topics=["conflict"]
        )

        query, args = _fetched(pool)
        assert args[8:] == [300, START, END, ["conflict"]]
        assert "published_at >= $10" in query
        assert "published_at <= $11" in query
        assert "topic_tags && $12" in query
        # Every placeholder has an argument and vice versa.
        assert max(int(n) for n in re.findall(r"\$(\d+)", query)) == len(args)

    @pytest.mark.asyncio
    async def test_either_bound_or_topics_may_be_given_alone(self, pool):
        await database.get_articles_in_bounds(*CELL, start_time=START)
        query, args = _fetched(pool)
        assert args[9:] == [START]
        assert "published_at >= $10" in query and "published_at <=" not in query

        await database.get_articles_in_bounds(*CELL, end_time=END)
        query, args = _fetched(pool)
        assert args[9:] == [END]
        assert "published_at <= $10" in query and "published_at >=" not in query

        await database.get_articles_in_bounds(*CELL, topics=["conflict"])
        query, args = _fetched(pool)
        assert args[9:] == [["conflict"]]
        assert "topic_tags && $10" in query

    @pytest.mark.asyncio
    async def test_filters_run_inside_the_dedup_before_the_limit(self, pool):
        """Dedup picks among matching rows; the limit counts matching rows only."""
        await database.get_articles_in_bounds(
            *CELL, start_time=START, end_time=END, topics=["conflict"]
        )

        query, _ = _fetched(pool)
        dedup = query.index("DISTINCT ON (lower(title))")
        subquery_end = query.index(") deduped")
        for predicate in (
            "location &&",
            "latitude >= $1",
            "published_at >= $10",
            "published_at <= $11",
            "topic_tags && $12",
        ):
            assert dedup < query.index(predicate) < subquery_end, predicate
        assert subquery_end < query.index("LIMIT $9")

    @pytest.mark.asyncio
    async def test_selects_the_article_columns_but_not_the_embedding(self, pool):
        """A 300-row cell must not pull 300 1536-dim vectors."""
        from app.models.news import NewsArticle

        await database.get_articles_in_bounds(*CELL)

        columns = _selected_columns(pool.fetch.call_args.args[0])
        assert "embedding" not in columns
        assert "*" not in columns
        assert columns == set(NewsArticle.model_fields)

    @pytest.mark.asyncio
    async def test_duplicates_and_ties_resolve_the_same_way_every_call(self, pool):
        """GDELT stamps a whole 15-minute batch alike: offset paging needs a total order,
        and the copy dedup keeps must not change between pages."""
        await database.get_articles_in_bounds(*CELL)

        query, _ = _fetched(pool)
        assert "ORDER BY lower(title), published_at DESC, id ) deduped" in query
        assert ") deduped ORDER BY published_at DESC, id LIMIT $9" in query


class TestGetGlobePoints:
    @pytest.mark.asyncio
    async def test_windowed_query_aggregates_cell_topics(self, pool):
        pool.fetch.return_value = [_globe_row()]

        await database.get_globe_points(cell_size=1.0, start_time=START, end_time=END)

        assert pool.fetch.call_count == 1
        query = _sql(pool.fetch.call_args.args[0])
        assert "unnest(topic_tags)" in query
        assert "array_agg(DISTINCT tag)" in query

    @pytest.mark.asyncio
    async def test_fallback_query_aggregates_cell_topics(self, pool):
        pool.fetch.side_effect = [[], [_globe_row()]]

        await database.get_globe_points(cell_size=1.0)

        assert pool.fetch.call_count == 2
        fallback = _sql(pool.fetch.call_args_list[1].args[0])
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
