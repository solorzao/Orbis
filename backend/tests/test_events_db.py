"""GDELT Events rollups on a real PostgreSQL: the upsert, the claim, the purge,
HOT updates and the purge's plan at production scale.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (021 included). Every test runs in a transaction that is
rolled back. The production-scale tests then VACUUM (ANALYZE) the table
outside it: ANALYZE's counts outlive a rollback, and later tests' plans would
be made for them. Plans are the planner's own choice: no enable_* setting is
changed anywhere.
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import events
from app.services.events import AlreadyIngested, FileResult, Rollup, plan_slots, store_rollups
from app.services.gdelt import Download
from tests import db_plans
from tests.events_fixture import fill_week

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
TODAY = NOW.date()
Q = timedelta(minutes=15)


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
async def week():
    """A connection in a transaction that is rolled back, then the table vacuumed
    outside it (as test_board_db.big does)."""
    connection = await _connect()
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        try:
            await connection.execute("VACUUM (PARALLEL 0, ANALYZE) event_pairs_daily")
        finally:
            await connection.close()


class _OnePool:
    """The pool as events uses it, on the test's connection: its transactions
    become savepoints in the test's, so everything still rolls back."""

    def __init__(self, connection):
        self._conn = connection

    async def fetch(self, sql, *args):
        return await self._conn.fetch(sql, *args)

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self._conn


class _Undo(Exception):
    """Raised inside a savepoint to roll it back (a mutation check's DROP)."""


async def _row(conn, a: str, b: str, day: date, quad: int):
    return await conn.fetchrow(
        "SELECT * FROM event_pairs_daily"
        " WHERE a_iso = $1 AND b_iso = $2 AND day = $3 AND quad_class = $4",
        a,
        b,
        day,
        quad,
    )


@pytest.mark.asyncio
async def test_two_cycles_add_up_and_keep_the_first_seen_samples_and_outlets(conn):
    pool = _OnePool(conn)
    key = ("US", "IR", TODAY, 3)
    first = Rollup(
        n_events=1,
        mentions=10,
        goldstein_sum=-2.0,
        tone_sum=-3.0,
        samples=["https://u1.test/a"],
        outlets=["o1.test"],
    )
    second = Rollup(
        n_events=2,
        mentions=5,
        goldstein_sum=-4.0,
        tone_sum=-1.0,
        samples=[
            "https://u1.test/a",
            "https://u2.test/a",
            "https://u3.test/a",
            "https://u4.test/a",
        ],
        outlets=[f"o{i}.test" for i in range(2, 10)],
    )
    assert await store_rollups(pool, {key: first}, [FileResult(NOW, "ok", 1, 1)]) == 1
    assert await store_rollups(pool, {key: second}, [FileResult(NOW + Q, "ok", 2, 2)]) == 1

    row = await _row(conn, *key)
    assert (row["n_events"], row["mentions"], row["goldstein_sum"], row["tone_sum"]) == (
        3,
        15,
        -6.0,
        -4.0,
    )
    assert row["sample_urls"] == ["https://u1.test/a", "https://u2.test/a", "https://u3.test/a"]
    assert len(row["outlets"]) == events.MAX_OUTLETS and row["outlets"][0] == "o1.test"
    assert row["outlets"] == [f"o{i}.test" for i in range(1, 9)]


@pytest.mark.asyncio
async def test_a_file_is_never_added_twice(conn):
    pool = _OnePool(conn)
    key = ("US", "IR", TODAY, 3)
    rollup = Rollup(n_events=4, mentions=8, goldstein_sum=-1.0, tone_sum=-1.0)
    await store_rollups(pool, {key: rollup}, [FileResult(NOW, "ok", 4, 4)])

    again = Rollup(n_events=100, mentions=100, goldstein_sum=0.0, tone_sum=0.0)
    with pytest.raises(AlreadyIngested, match=f"{NOW:%Y%m%d%H%M%S}"):
        await store_rollups(
            pool, {key: again}, [FileResult(NOW + Q, "ok", 1, 1), FileResult(NOW, "ok", 1, 1)]
        )

    assert (await _row(conn, *key))["n_events"] == 4
    claimed = await conn.fetch("SELECT slot FROM event_files WHERE slot >= $1", NOW)
    assert [r["slot"] for r in claimed] == [NOW]  # the newer slot's claim rolled back too


@pytest.mark.asyncio
async def test_missing_and_unreadable_files_are_recorded_and_add_no_rows(conn):
    pool = _OnePool(conn)
    files = [FileResult(NOW - Q, "missing", 0, 0), FileResult(NOW - 2 * Q, "unreadable", 0, 0)]
    assert await store_rollups(pool, {}, files) == 0

    rows = await conn.fetch(
        "SELECT slot, status, n_rows, n_kept FROM event_files WHERE slot >= $1 ORDER BY slot DESC",
        NOW - 2 * Q,
    )
    assert [tuple(r) for r in rows] == [
        (NOW - Q, "missing", 0, 0),
        (NOW - 2 * Q, "unreadable", 0, 0),
    ]
    assert await conn.fetchval("SELECT count(*) FROM event_pairs_daily") == 0
    # DONE_SQL reads every status, so neither is planned again.
    done = {r["slot"] for r in await conn.fetch(events.DONE_SQL, NOW - timedelta(hours=3))}
    assert plan_slots(NOW, done) == [NOW, NOW - 3 * Q, NOW - 4 * Q, NOW - 5 * Q]


@pytest.mark.asyncio
async def test_a_timeout_during_the_store_claims_and_adds_nothing(conn, monkeypatch, caplog):
    """Another writer holds the events lock (a deploy's overlap, a slow commit): the
    step times out while it waits, and the claim and the upsert roll back together,
    so the file is tried again next cycle and nothing is counted twice."""
    import asyncpg

    from tests.test_events import T, _event, _export_zip, _index

    key = ("US", "IR", T.date(), 3)
    await conn.execute(
        "INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events, mentions,"
        " goldstein_sum, tone_sum) VALUES ($1, $2, $3, $4, 4, 40, -8, -12)",
        *key,
    )
    body = _export_zip(_event())
    holder = await asyncpg.connect(DATABASE_URL)
    held = holder.transaction()
    await held.start()
    try:
        await holder.execute("SELECT pg_advisory_xact_lock($1)", events._EVENTS_LOCK)
        monkeypatch.setattr(events, "EVENTS_STEP_TIMEOUT_S", 1.0)
        monkeypatch.setattr(events, "_last_newest", None)
        with (
            patch("app.services.events.fetch_lastupdate", AsyncMock(return_value=_index(body))),
            patch(
                "app.services.events.download_capped",
                AsyncMock(return_value=Download("ok", body)),
            ),
            patch("app.services.events.get_pool", AsyncMock(return_value=_OnePool(conn))),
            caplog.at_level(logging.WARNING, logger="orbis.events"),
        ):
            await events.ingest_events(now=T)
    finally:
        await held.rollback()
        await holder.close()

    assert "timed out" in caplog.text
    assert await conn.fetchval("SELECT count(*) FROM event_files WHERE slot = $1", T) == 0
    assert (await _row(conn, *key))["n_events"] == 4


@pytest.mark.asyncio
async def test_the_purge_keeps_retention_days_and_two_days_of_files(conn):
    insert = (
        "INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events, mentions,"
        " goldstein_sum, tone_sum) VALUES ('US', 'IR', $1, 3, 1, 1, 0, 0)"
    )
    for days_ago in (8, 7):
        await conn.execute(insert, TODAY - timedelta(days=days_ago))
    await conn.execute(
        "INSERT INTO event_files (slot, status) VALUES ($1, 'ok'), ($2, 'ok')",
        NOW - timedelta(days=2, minutes=15),
        NOW - timedelta(days=1),
    )

    await events.purge_events(_OnePool(conn), 7, NOW)

    days = await conn.fetch("SELECT day FROM event_pairs_daily ORDER BY day")
    assert [r["day"] for r in days] == [TODAY - timedelta(days=7)]
    slots = await conn.fetch("SELECT slot FROM event_files ORDER BY slot")
    assert [r["slot"] for r in slots] == [NOW - timedelta(days=1)]


@pytest.mark.asyncio
async def test_at_production_scale_a_cycle_updates_rows_in_place(week):
    """fillfactor 70 leaves room on each page: a cycle's additions change no indexed
    column, so they are HOT updates (no new index entries, less I/O on the P4 disk)."""
    await fill_week(week, TODAY)
    # Spread across the day's pages, as a cycle's busy pairs are (their rows were
    # written over the day), rather than 500 adjacent rows filling whole pages.
    keys = await week.fetch(
        "SELECT a_iso, b_iso, day, quad_class FROM event_pairs_daily WHERE day = $1"
        " ORDER BY md5(a_iso || b_iso || quad_class::text) LIMIT 500",
        TODAY,
    )
    assert len(keys) == 500
    rollups = {
        tuple(k): Rollup(
            n_events=1,
            mentions=3,
            goldstein_sum=-1.0,
            tone_sum=-2.0,
            samples=["https://zzevents-new.test/2026/10/21/a-new-story"],
            outlets=["zzevents-new.test"],
        )
        for k in keys
    }
    assert await store_rollups(_OnePool(week), rollups, [FileResult(NOW, "ok", 500, 500)]) == 500

    upd, hot = await week.fetchrow(
        "SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables"
        " WHERE relname = 'event_pairs_daily'"
    )
    assert upd == 500
    assert hot / upd >= 0.9, (hot, upd)


# Pages the steady-state purge may read: a descent of the day index that finds nothing.
_PURGE_PAGES = 10


@pytest.mark.asyncio
async def test_at_production_scale_the_steady_state_purge_is_an_index_range(week):
    """Nothing is older than retention, as on every cycle but the first after
    midnight: the custom plan (purge_events forces it) reads the day index only."""
    await fill_week(week, TODAY)
    plan = await db_plans.custom_plan(week, events.PURGE_PAIRS_SQL, TODAY, 7)
    assert "event_pairs_daily" not in plan["seq_scans"], plan
    assert "idx_event_pairs_day" in plan["indexes"], plan
    pages = await db_plans.pages(week, events.PURGE_PAIRS_SQL, (TODAY, 7), "custom")
    assert pages <= _PURGE_PAGES, pages


@pytest.mark.asyncio
async def test_the_purge_checks_fail_without_the_day_index(week):
    """The mutation twin: without idx_event_pairs_day the purge reads the whole table
    or, as the planner prefers, the whole primary key (it holds day too, and is
    narrower than the heap) every cycle, so the checks above can't pass vacuously."""
    await fill_week(week, TODAY)
    with pytest.raises(_Undo):
        async with week.transaction():  # a savepoint
            await week.execute("DROP INDEX idx_event_pairs_day")
            plan = await db_plans.custom_plan(week, events.PURGE_PAIRS_SQL, TODAY, 7)
            assert "idx_event_pairs_day" not in plan["indexes"], plan
            pages = await db_plans.pages(week, events.PURGE_PAIRS_SQL, (TODAY, 7), "custom")
            assert pages > _PURGE_PAGES, (pages, plan)
            raise _Undo
    assert await week.fetchval("SELECT to_regclass('idx_event_pairs_day') IS NOT NULL")
