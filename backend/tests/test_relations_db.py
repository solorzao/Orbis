"""The relations reads on a real PostgreSQL: their meaning on small hand-built
rows, and their plans and pages at production scale, each with a mutation twin.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (021 included). Every test runs in a transaction that is
rolled back; the production-scale ones then VACUUM (ANALYZE) the tables they
filled, outside it, since ANALYZE's counts outlive a rollback. Plans are the
planner's own choice, custom and generic: no enable_* setting is changed
anywhere. Rows are written day by day, as ingestion writes them
(events_fixture.fill_week).
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import relations
from tests import db_plans
from tests.events_fixture import ISO, fill_week

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

FIRST, LAST = relations.lens_days()
TODAY = LAST

_INSERT = """
INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events, mentions,
                               goldstein_sum, tone_sum, sample_urls, outlets)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""


async def _connect():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    if not await connection.fetchval("SELECT to_regclass('event_pairs_daily') IS NOT NULL"):
        await connection.close()
        pytest.skip("event_pairs_daily is missing: apply migration 021")
    return connection


@pytest_asyncio.fixture
async def conn():
    connection = await _connect()
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def big():
    """A connection in a transaction that is rolled back, then the filled tables
    vacuumed outside it (as test_board_db.big does)."""
    connection = await _connect()
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        try:
            await connection.execute("VACUUM (PARALLEL 0, ANALYZE) event_pairs_daily, articles")
        finally:
            await connection.close()


class _ConnPool:
    """The pool as relations reads it, on the test's connection."""

    def __init__(self, connection):
        self._conn = connection

    async def fetch(self, sql, *args):
        return await self._conn.fetch(sql, *args)

    async def fetchval(self, sql, *args):
        return await self._conn.fetchval(sql, *args)


@contextlib.contextmanager
def _reading(conn):
    with patch("app.services.relations.get_pool", AsyncMock(return_value=_ConnPool(conn))):
        yield


async def _add(conn, a, b, day, quad, n, outlets=("o1.test",), urls=()):
    await conn.execute(
        _INSERT, a, b, day, quad, n, 10 * n, -1.0 * n, -2.0 * n, list(urls), list(outlets)
    )


async def _listed(conn, kind: str = "all") -> list[dict]:
    with _reading(conn):
        rows = await relations.get_relation_pairs(FIRST, LAST, kind)
    return relations.rank_relations(rows, kind, 40)


# --- What the reads mean ----------------------------------------------------


@pytest.mark.asyncio
async def test_both_directions_merge_and_from_follows_the_majority(conn):
    await _add(conn, "US", "IR", TODAY, 3, 6, ["o1.test", "o2.test"])
    await _add(conn, "IR", "US", TODAY, 3, 4, ["o3.test"])
    await _add(conn, "DE", "FR", TODAY, 1, 5, ["o1.test"])  # a tie: 5 each way
    await _add(conn, "FR", "DE", TODAY, 1, 5, ["o2.test"])

    got = {(r["a"]["iso"], r["b"]["iso"]): (r["n"], r["from"]) for r in await _listed(conn)}
    assert got == {("IR", "US"): (10, "US"), ("DE", "FR"): (10, "DE")}


@pytest.mark.asyncio
async def test_the_conflict_filter_counts_quad_3_and_4_only(conn):
    await _add(conn, "US", "IR", TODAY, 1, 5, ["o1.test", "o2.test"])
    await _add(conn, "US", "IR", TODAY, 3, 6, ["o1.test", "o2.test"])
    await _add(conn, "US", "IR", TODAY, 4, 1, ["o3.test"])

    [rel] = await _listed(conn, "conflict")
    assert (rel["n"], rel["kind"], rel["outlets"]) == (7, "conflict", 3)
    assert rel["quad"] == {
        "verbal_cooperation": 0,
        "material_cooperation": 0,
        "verbal_conflict": 6,
        "material_conflict": 1,
    }


@pytest.mark.asyncio
async def test_the_thresholds_count_events_and_distinct_outlets(conn):
    two = ["o1.test", "o2.test"]
    await _add(conn, "CN", "JP", TODAY, 3, 4, two)  # 4 events: dropped
    await _add(conn, "DE", "FR", TODAY, 3, 5, two)  # 5 events: kept
    await _add(conn, "GB", "IN", TODAY, 3, 5, ["o1.test"])  # 1 outlet: dropped
    # 2 distinct outlets across days, though each day has only 1: kept.
    await _add(conn, "BR", "MX", TODAY, 3, 3, ["o1.test"])
    await _add(conn, "BR", "MX", TODAY - timedelta(days=1), 3, 2, ["o2.test"])
    # One article coded three ways (plan review I1): 5 events, 1 outlet: dropped.
    url, host = ["https://one.test/story"], ["one.test"]
    await _add(conn, "SA", "EG", TODAY, 3, 2, host, url)
    await _add(conn, "SA", "EG", TODAY, 4, 2, host, url)
    await _add(conn, "EG", "SA", TODAY, 3, 1, host, url)

    listed = {(r["a"]["iso"], r["b"]["iso"]): r["outlets"] for r in await _listed(conn)}
    assert listed == {("DE", "FR"): 2, ("BR", "MX"): 2}


@pytest.mark.asyncio
async def test_only_the_lens_days_are_read(conn):
    """today - 7 is still kept by retention, but outside the lens."""
    two = ["o1.test", "o2.test"]
    await _add(conn, "DE", "FR", FIRST - timedelta(days=1), 3, 50, two)
    await _add(conn, "US", "IR", FIRST, 3, 5, two)

    assert [(r["a"]["iso"], r["n"]) for r in await _listed(conn)] == [("IR", 5)]
    with _reading(conn):
        assert await relations.get_relation_detail("DE", "FR", FIRST, LAST) is None


@pytest.mark.asyncio
async def test_since_is_the_earliest_rollup_day_in_the_lens(conn):
    with _reading(conn):
        assert await relations.get_since(FIRST, LAST) is None
        await _add(conn, "DE", "FR", FIRST - timedelta(days=1), 3, 5)  # outside the lens
        await _add(conn, "US", "IR", TODAY - timedelta(days=3), 3, 5)
        await _add(conn, "US", "IR", TODAY, 3, 5)
        assert await relations.get_since(FIRST, LAST) == TODAY - timedelta(days=3)


@pytest.mark.asyncio
async def test_the_detail_takes_titles_from_our_articles(conn):
    url = "https://zzrel.test/2026/10/21/talks"
    await conn.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location)
        VALUES ('Zzrel talks resume - Reuters', $1, 'zzrel.test', now(), 10.5, 20.5,
                ST_SetSRID(ST_MakePoint(20.5, 10.5), 4326)::geography)
        """,
        url,
    )
    await _add(conn, "US", "IR", TODAY, 1, 2, ["zzrel.test"], [url, "https://other.test/a"])

    with _reading(conn):
        detail = await relations.get_relation_detail("IR", "US", FIRST, LAST)
    assert [(s["url"], s["title"]) for s in detail["samples"]] == [
        (url, "Zzrel talks resume"),
        ("https://other.test/a", None),
    ]


# --- Plans and pages at production scale -------------------------------------

# Pages each read may touch, custom or generic (the plan's table, 19c.3).
_SINCE_PAGES = 10  # the day index's first entry in the lens
_DETAIL_PAGES = 60  # 14 heap pages at most (7 days x 2 directions), plus the index's
_TITLES_PAGES = 60  # 10 lookups by source_url


def _report(capsys, line: str) -> None:
    """A measure into CI's log for the PR (pytest captures prints otherwise)."""
    with capsys.disabled():
        print(f"\n[relations] {line}")


async def _relation_pages(conn, *names: str) -> int:
    return sum(
        [
            await conn.fetchval(
                "SELECT pg_relation_size($1::regclass) / current_setting('block_size')::int", n
            )
            for n in names
        ]
    )


def _list_args(min_events: int = relations.MIN_EVENTS) -> tuple:
    return (FIRST, LAST, relations.QUADS["all"], min_events, relations.MIN_OUTLETS)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["custom", "generic"])
async def test_at_production_scale_the_list_reads_the_table_once(big, mode, capsys):
    """The lens reads 7 of 8 days by design (a seq scan is the right choice):
    once, never once per pair."""
    await fill_week(big, TODAY)
    bound = (
        await _relation_pages(big, "event_pairs_daily", "event_pairs_daily_pkey")
        + await _relation_pages(big, "idx_event_pairs_day")
        + 100
    )
    pages = await db_plans.pages(big, relations.LIST_SQL, _list_args(), mode)
    assert pages <= bound, (pages, bound)

    # Timed under B1ms-like settings: printed for the PR, not asserted.
    for setting in ("max_parallel_workers_per_gather = 0", "jit = off", "work_mem = '4MB'"):
        await big.execute(f"SET LOCAL {setting}")
    raw = await big.fetchval("EXPLAIN (ANALYZE, FORMAT JSON) " + relations.LIST_SQL, *_list_args())
    ms = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Execution Time"]
    _report(capsys, f"list over the lens ({mode}): {pages} pages, bound {bound}; {ms:.0f} ms")


_PER_PAIR_LIST_SQL = """
WITH p AS (
    SELECT least(a_iso, b_iso) AS a, greatest(a_iso, b_iso) AS b,
           sum(n_events)::int AS n, sum(mentions)::bigint AS mentions
    FROM event_pairs_daily
    WHERE day BETWEEN $1 AND $2 AND quad_class = ANY($3::smallint[])
    GROUP BY 1, 2
    HAVING sum(n_events) >= $4
)
SELECT p.*, o.outlets
FROM p CROSS JOIN LATERAL (
    SELECT count(DISTINCT x)::int AS outlets
    FROM event_pairs_daily e CROSS JOIN LATERAL unnest(e.outlets) AS x
    WHERE least(e.a_iso, e.b_iso) = p.a AND greatest(e.a_iso, e.b_iso) = p.b
      AND e.day BETWEEN $1 AND $2 AND e.quad_class = ANY($3::smallint[])
) o
WHERE o.outlets >= $5
ORDER BY p.mentions DESC, p.n DESC, p.a, p.b
"""


@pytest.mark.asyncio
async def test_the_list_page_bound_fails_for_a_per_pair_read(big, capsys):
    """The mutation twin: outlets counted per pair against the table, the shape this
    plan rejected, read it once per pair and break the bound. (Only the busiest
    pairs, so the twin stays quick: a few dozen reads of the table.)"""
    await fill_week(big, TODAY)
    bound = (
        await _relation_pages(big, "event_pairs_daily", "event_pairs_daily_pkey")
        + await _relation_pages(big, "idx_event_pairs_day")
        + 100
    )
    busiest = await big.fetchval(
        "SELECT max(n) FROM (SELECT sum(n_events) AS n FROM event_pairs_daily"
        " WHERE day BETWEEN $1 AND $2 GROUP BY least(a_iso, b_iso), greatest(a_iso, b_iso)) s",
        FIRST,
        LAST,
    )
    pages = await db_plans.pages(big, _PER_PAIR_LIST_SQL, _list_args(busiest), "custom")
    _report(capsys, f"per-pair list (twin): {pages} pages, bound {bound}")
    assert pages > bound, (pages, bound)


@pytest.mark.asyncio
async def test_at_production_scale_since_reads_the_day_index(big, capsys):
    await fill_week(big, TODAY)
    custom = await db_plans.custom_plan(big, relations.SINCE_SQL, FIRST, LAST)
    generic = await db_plans.generic_plan(
        big, relations.SINCE_SQL, ["date", "date"], [db_plans.literal(d) for d in (FIRST, LAST)]
    )
    for plan in (custom, generic):
        assert "event_pairs_daily" not in plan["seq_scans"], plan
        assert "idx_event_pairs_day" in plan["indexes"], plan
    for mode in ("custom", "generic"):
        pages = await db_plans.pages(big, relations.SINCE_SQL, (FIRST, LAST), mode)
        _report(capsys, f"since ({mode}): {pages} pages, bound {_SINCE_PAGES}")
        assert pages <= _SINCE_PAGES, (mode, pages)


@pytest.mark.asyncio
async def test_the_since_checks_fail_without_the_day_index(big, capsys):
    """The mutation twin of the checks above (19b's twin covers the purge): without
    the day index, since reads the whole table or the whole primary key (it holds
    day too; 19b's CI showed the planner prefers it), past the page bound."""
    await fill_week(big, TODAY)
    with pytest.raises(_Undo):
        async with big.transaction():  # a savepoint
            await big.execute("DROP INDEX idx_event_pairs_day")
            plan = await db_plans.custom_plan(big, relations.SINCE_SQL, FIRST, LAST)
            assert "idx_event_pairs_day" not in plan["indexes"], plan
            pages = await db_plans.pages(big, relations.SINCE_SQL, (FIRST, LAST), "custom")
            _report(capsys, f"since, no day index (twin): {pages} pages, bound {_SINCE_PAGES}")
            assert pages > _SINCE_PAGES, (pages, plan)
            raise _Undo


def _busy_pair() -> tuple[str, str]:
    """A pair events_fixture writes every day (g = 1): its rows sit on a page a day."""
    return ISO[1], ISO[2]


@pytest.mark.asyncio
async def test_at_production_scale_the_detail_reads_the_primary_key(big, capsys):
    await fill_week(big, TODAY)
    a, b = _busy_pair()
    args = (a, b, FIRST, LAST)
    assert len(await big.fetch(relations.DETAIL_SQL, *args)) == 28  # 7 days x 4 classes
    custom = await db_plans.custom_plan(big, relations.DETAIL_SQL, *args)
    generic = await db_plans.generic_plan(
        big,
        relations.DETAIL_SQL,
        ["text", "text", "date", "date"],
        [db_plans.literal(v) for v in args],
    )
    for plan in (custom, generic):
        assert "event_pairs_daily" not in plan["seq_scans"], plan
        assert "event_pairs_daily_pkey" in plan["indexes"], plan
    for mode in ("custom", "generic"):
        pages = await db_plans.pages(big, relations.DETAIL_SQL, args, mode)
        _report(capsys, f"detail ({mode}): {pages} pages, bound {_DETAIL_PAGES}")
        assert pages <= _DETAIL_PAGES, (mode, pages)


@pytest.mark.asyncio
async def test_the_detail_check_fails_without_the_primary_key(big, capsys):
    """The mutation twin: without the primary key the detail can't read by pair, so
    it reads the lens's days whole (a seq scan, or the day index's 7 of 8 days),
    past the page bound."""
    await fill_week(big, TODAY)
    a, b = _busy_pair()
    with pytest.raises(_Undo):
        async with big.transaction():  # a savepoint
            await big.execute(
                "ALTER TABLE event_pairs_daily DROP CONSTRAINT event_pairs_daily_pkey"
            )
            plan = await db_plans.custom_plan(big, relations.DETAIL_SQL, a, b, FIRST, LAST)
            assert "event_pairs_daily_pkey" not in plan["indexes"], plan
            pages = await db_plans.pages(big, relations.DETAIL_SQL, (a, b, FIRST, LAST), "custom")
            _report(capsys, f"detail, no primary key (twin): {pages} pages, bound {_DETAIL_PAGES}")
            assert pages > _DETAIL_PAGES, (pages, plan)
            raise _Undo


@pytest.mark.asyncio
async def test_at_production_scale_titles_are_read_by_source_url(big, capsys):
    await big.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location)
        SELECT 'Zzrel story number ' || i || ' in the news today',
               'https://zzrel.test/2026/10/21/' || i, 'zzrel.test',
               now() - i * interval '30 seconds', 10.5, 20.5,
               ST_SetSRID(ST_MakePoint(20.5, 10.5), 4326)::geography
        FROM generate_series(1, 20000) AS i
        """
    )
    await big.execute("ANALYZE articles")
    urls = [f"https://zzrel.test/2026/10/21/{i}" for i in range(100, 20000, 2000)]
    assert len(await big.fetch(relations.TITLES_SQL, urls)) == 10
    custom = await db_plans.custom_plan(big, relations.TITLES_SQL, urls)
    generic = await db_plans.generic_plan(
        big, relations.TITLES_SQL, ["text[]"], [db_plans.literal(urls)]
    )
    for plan in (custom, generic):
        assert "articles" not in plan["seq_scans"], plan
        assert "articles_source_url_key" in plan["indexes"], plan
    for mode in ("custom", "generic"):
        pages = await db_plans.pages(big, relations.TITLES_SQL, (urls,), mode)
        _report(capsys, f"titles, 10 URLs ({mode}): {pages} pages, bound {_TITLES_PAGES}")
        assert pages <= _TITLES_PAGES, (mode, pages)


class _Undo(Exception):
    """Raised inside a savepoint to roll it back (a mutation twin's DROP)."""
