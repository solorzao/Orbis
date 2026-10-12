"""Tests for the SQL the database helpers send (the pool is mocked; no live database)."""

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import database
from app.services.database import upsert_articles


def _mock_pool():
    """A pool whose connection records transaction boundaries and statements in ``events``."""
    events: list[str] = []
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=lambda *a: events.append("execute"))
    conn.executemany = AsyncMock(side_effect=lambda *a: events.append("executemany"))

    @asynccontextmanager
    async def _transaction():
        events.append("begin")
        yield
        events.append("commit")

    @asynccontextmanager
    async def _acquire():
        yield conn

    conn.transaction = _transaction
    conn.events = events
    pool = MagicMock()
    pool.acquire = _acquire
    return pool, conn


async def _upsert(articles):
    """Run upsert_articles on a mocked pool; return (count, sql, per-row argument tuples)."""
    pool, conn = _mock_pool()
    with patch("app.services.database.get_pool", new_callable=AsyncMock, return_value=pool):
        count = await upsert_articles(articles)
    sql, rows = conn.executemany.await_args.args
    return count, sql, [tuple(r) for r in rows], conn


@pytest.mark.asyncio
async def test_upsert_sends_all_rows_in_one_executemany_inside_a_transaction():
    articles = [{"source_url": f"https://example.com/{i}"} for i in range(400)]

    count, _, rows, conn = await _upsert(articles)

    assert count == 400
    assert len(rows) == 400
    assert conn.events == ["begin", "executemany", "commit"]
    assert [r[2] for r in rows] == [a["source_url"] for a in articles]  # $3 = source_url


@pytest.mark.asyncio
async def test_upsert_with_no_articles_touches_nothing():
    pool, conn = _mock_pool()
    with patch("app.services.database.get_pool", new_callable=AsyncMock, return_value=pool):
        assert await upsert_articles([]) == 0
    assert conn.events == []


@pytest.mark.asyncio
async def test_upsert_writes_country_fips_and_never_null():
    articles = [
        {"source_url": "https://example.com/a", "country_code": "GB", "country_fips": "UK"},
        {"source_url": "https://example.com/b", "country_code": ""},  # no country_fips key
        {"source_url": "https://example.com/c", "country_code": "", "country_fips": None},
    ]

    count, sql, rows, _ = await _upsert(articles)

    assert count == 3
    assert "country_fips = EXCLUDED.country_fips" in sql
    # Every placeholder has an argument and vice versa.
    assert all(max(int(n) for n in re.findall(r"\$(\d+)", sql)) == len(r) for r in rows)

    fips_values = [r[14] for r in rows]  # $15
    assert fips_values == ["UK", "", ""]


GKG_COLUMNS = ("themes", "persons", "orgs", "names", "counts")


@pytest.mark.asyncio
async def test_upsert_writes_gkg_fields_as_16_to_20():
    counts = [{"type": "KILL", "n": 4, "object": "", "country": "ZA", "place": "Beitbridge"}]
    articles = [
        {
            "source_url": "https://example.com/a",
            "themes": ["KILL", "TERROR"],
            "persons": ["Benjamin Netanyahu"],
            "orgs": ["United Nations"],
            "names": ["Gaza Strip"],
            "counts": counts,
        },
        {"source_url": "https://example.com/b"},  # none of the GKG keys
    ]

    count, sql, rows, _ = await _upsert(articles)

    assert count == 2
    flat = _sql(sql)
    insert_columns = re.search(r"INSERT INTO articles \((.*?)\) VALUES", flat).group(1)
    values = re.search(r"VALUES \((.*?)\) ON CONFLICT", flat).group(1)
    assert [c.strip() for c in insert_columns.split(",")][-5:] == list(GKG_COLUMNS)
    assert [v.strip() for v in values.split(",")][-5:] == ["$16", "$17", "$18", "$19", "$20"]
    for column in GKG_COLUMNS:
        assert f"{column} = EXCLUDED.{column}" in flat
    assert max(int(n) for n in re.findall(r"\$(\d+)", sql)) == len(rows[0]) == 20

    assert list(rows[0][15:]) == [
        ["KILL", "TERROR"],
        ["Benjamin Netanyahu"],
        ["United Nations"],
        ["Gaza Strip"],
        json.dumps(counts),
    ]
    assert list(rows[1][15:]) == [[], [], [], [], "[]"]


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
    async def test_query_spends_nothing_on_a_cells_topic_list(self, pool):
        """Nothing reads a cell's every tag any more: no unnest over the window's stories."""
        pool.fetch.return_value = [_globe_row()]

        await database.get_globe_points(cell_size=1.0, start_time=START, end_time=END)

        assert pool.fetch.call_count == 1
        query = _sql(pool.fetch.call_args.args[0])
        assert "unnest" not in query
        assert "array_agg" not in query
        assert "cell_topics" not in query

    @pytest.mark.asyncio
    async def test_rows_carry_the_newest_storys_topic(self, pool):
        pool.fetch.return_value = [_globe_row()]

        [point] = await database.get_globe_points(cell_size=1.0)

        assert point["topic"] == "sport"  # newest story's first tag, for the dot colour
        assert "topics" not in point

    @pytest.mark.asyncio
    async def test_cell_without_tags_is_general(self, pool):
        pool.fetch.return_value = [_globe_row(topic_tags=None)]

        [point] = await database.get_globe_points(cell_size=1.0)

        assert point["topic"] == "general"

    @pytest.mark.asyncio
    async def test_topic_filters_the_stories_before_cells_are_ranked_and_limited(self, pool):
        """The cells are the busiest for the topic, counted and headlined by its stories alone."""
        pool.fetch.return_value = [_globe_row()]

        await database.get_globe_points(
            cell_size=1.0, limit=500, start_time=START, end_time=END, topic="politics"
        )

        query, args = _fetched(pool)
        assert args == [START, END, "politics", 1.0, 500]
        # In the WHERE of the CTE every count, headline and rank reads: before
        # ROW_NUMBER picks a cell's newest story, COUNT(*) and the LIMIT.
        assert (
            "FROM articles WHERE published_at BETWEEN $1 AND $2 "
            "AND topic_tags && ARRAY[$3::text] ), cells AS (" in query
        )
        assert query.index("topic_tags &&") < query.index("COUNT(*)")
        assert query.index("topic_tags &&") < query.index("ORDER BY article_count DESC LIMIT $5")
        assert "FLOOR(latitude / $4)" in query
        assert max(int(n) for n in re.findall(r"\$(\d+)", query)) == len(args)

    @pytest.mark.asyncio
    async def test_topic_with_a_live_window(self, pool):
        pool.fetch.return_value = [_globe_row()]

        await database.get_globe_points(cell_size=1.0, timespan_hours=6, topic="health")

        query, args = _fetched(pool)
        assert args[1:] == ["health", 1.0, 500]
        assert "WHERE published_at >= $1 AND topic_tags && ARRAY[$2::text] )" in query
        assert "LIMIT $4" in query

    @pytest.mark.asyncio
    async def test_no_topic_leaves_the_predicate_out(self, pool):
        """No `$n IS NULL OR ...`: the plan for every story never carries a topic test."""
        pool.fetch.return_value = [_globe_row()]

        await database.get_globe_points(cell_size=1.0, start_time=START, end_time=END)

        query, args = _fetched(pool)
        assert args == [START, END, 1.0, 500]
        assert "topic_tags &&" not in query
        assert "IS NULL" not in query

    @pytest.mark.asyncio
    @pytest.mark.parametrize("topic", [None, "conflict"])
    @pytest.mark.parametrize(
        "window",
        [{"timespan_hours": 1}, {"start_time": START, "end_time": END}],
        ids=["live", "range"],
    )
    async def test_an_empty_window_returns_no_cells(self, pool, window, topic):
        """No fallback to older stories: "Last 1 h" with nothing in it is an empty globe."""
        pool.fetch.return_value = []

        assert await database.get_globe_points(cell_size=1.0, topic=topic, **window) == []

        assert pool.fetch.call_count == 1
        query, _ = _fetched(pool)
        assert "published_at" in query  # the window's query, never one without it

    @pytest.mark.asyncio
    async def test_a_filtered_cell_takes_the_topic_as_its_colour(self, pool):
        """The newest matching story may list another tag first; the dot is still the topic's."""
        pool.fetch.return_value = [_globe_row(topic_tags=["sport", "politics"])]

        [point] = await database.get_globe_points(cell_size=1.0, topic="politics")

        assert point["topic"] == "politics"


class TestGetHourlyVolume:
    @pytest.mark.asyncio
    async def test_counts_every_hour_of_the_window_zeros_included(self, pool):
        hour = datetime(2026, 10, 11, 14, tzinfo=timezone.utc)
        pool.fetch.return_value = [{"hour": hour, "count": 0}]

        rows = await database.get_hourly_volume(7)

        query, args = _fetched(pool)
        assert args == [7]
        # One row per hour from the window's first hour to the current one, oldest first.
        assert (
            "generate_series( date_trunc('hour', now() - make_interval(days => $1), 'UTC'), "
            "date_trunc('hour', now(), 'UTC'), interval '1 hour') AS h(hour)" in query
        )
        assert "LEFT JOIN" in query and "COALESCE(c.count, 0)::int AS count" in query
        assert query.endswith("ORDER BY h.hour")
        assert rows == [{"hour": hour, "count": 0}]

    @pytest.mark.asyncio
    async def test_buckets_published_at_by_utc_hour_inside_the_window(self, pool):
        await database.get_hourly_volume(3)

        query, args = _fetched(pool)
        assert args == [3]
        assert "date_trunc('hour', published_at, 'UTC') AS hour" in query
        assert (
            "WHERE published_at >= date_trunc('hour', now() - make_interval(days => $1), 'UTC')"
            in query
        )
