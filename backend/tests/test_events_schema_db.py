"""event_pairs_daily and event_files on a real PostgreSQL (migration 021).

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied. Every test runs in a transaction that is rolled back.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
import pytest_asyncio

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    if not await connection.fetchval("SELECT to_regclass('event_pairs_daily') IS NOT NULL"):
        await connection.close()
        pytest.skip("event_pairs_daily is missing: apply migration 021")
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def _columns(conn, table: str) -> list[tuple[str, str]]:
    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_name = $1 ORDER BY ordinal_position",
        table,
    )
    return [(r["column_name"], r["data_type"]) for r in rows]


@pytest.mark.asyncio
async def test_each_table_has_exactly_its_planned_columns(conn):
    assert await _columns(conn, "event_pairs_daily") == [
        ("a_iso", "text"),
        ("b_iso", "text"),
        ("day", "date"),
        ("quad_class", "smallint"),
        ("n_events", "integer"),
        ("mentions", "integer"),
        ("goldstein_sum", "double precision"),
        ("tone_sum", "double precision"),
        ("sample_urls", "ARRAY"),
        ("outlets", "ARRAY"),
    ]
    assert await _columns(conn, "event_files") == [
        ("slot", "timestamp with time zone"),
        ("status", "text"),
        ("n_rows", "integer"),
        ("n_kept", "integer"),
        ("processed_at", "timestamp with time zone"),
    ]


@pytest.mark.asyncio
async def test_keys_indexes_and_storage(conn):
    pk = await conn.fetch(
        "SELECT a.attname FROM pg_index i"
        " JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)"
        " WHERE i.indrelid = 'event_pairs_daily'::regclass AND i.indisprimary"
        " ORDER BY array_position(i.indkey::int2[], a.attnum)"
    )
    assert [r["attname"] for r in pk] == ["a_iso", "b_iso", "day", "quad_class"]
    assert (
        await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_event_pairs_day'"
        )
        == "CREATE INDEX idx_event_pairs_day ON public.event_pairs_daily USING btree (day)"
    )
    assert await conn.fetchval(
        "SELECT reloptions FROM pg_class WHERE oid = 'event_pairs_daily'::regclass"
    ) == ["fillfactor=70"]
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f'"
            " AND conrelid IN ('event_pairs_daily'::regclass, 'event_files'::regclass)"
        )
        == 0
    )


_ROW = (
    "INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events,"
    " mentions, goldstein_sum, tone_sum) VALUES ($1, $2, $3, $4, 1, 1, 0, 0)"
)
_FILE = "INSERT INTO event_files (slot, status) VALUES (now() - $2::interval, $1)"


@pytest.mark.asyncio
async def test_checks_reject_bad_rows(conn):
    """A bad quad class, a domestic pair, a code that isn't 2 letters, a bad status."""
    import asyncpg

    day = date(2026, 10, 21)
    await conn.execute(_ROW, "US", "IR", day, 3)
    bad_rows = [
        ("US", "IR", day, 5),
        ("US", "US", day, 1),
        ("USA", "IR", day, 1),
        ("U", "IR", day, 1),
    ]
    for args in bad_rows:
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():  # a savepoint
                await conn.execute(_ROW, *args)
    for i, status in enumerate(("ok", "missing", "unreadable")):
        # asyncpg encodes an interval from a timedelta, not a string.
        await conn.execute(_FILE, status, timedelta(minutes=15 * (i + 1)))
    with pytest.raises(asyncpg.CheckViolationError):
        async with conn.transaction():
            await conn.execute(_FILE, "other", timedelta(hours=2))
