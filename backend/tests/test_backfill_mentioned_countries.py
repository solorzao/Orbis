"""Tests for the mentioned_countries backfill from the knowledge graph (no database)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import backfill_mentioned_countries as script
from scripts.backfill_mentioned_countries import backfill, countries

_NEWEST = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def _sql(query: str) -> str:
    return " ".join(query.split())


class TestCountries:
    def test_iso_nodes_are_kept_distinct_and_sorted(self):
        assert countries(["US", "IR", "US"], None) == ["IR", "US"]

    def test_nodes_written_before_the_iso_switch_hold_fips_codes(self):
        # No country_fips key: country_code is still GDELT's FIPS code.
        assert countries(["GB"], ["UK", "CH", "SP"]) == ["CN", "ES", "GB"]

    def test_empty_unknown_and_missing_codes_are_dropped(self):
        assert countries(["", None, "FR"], ["ZZ", "", None]) == ["FR"]
        assert countries(None, None) == []

    def test_capped_at_20_like_ingestion(self):
        codes = [f"{a}{b}" for a in "ABC" for b in "ABCDEFGHIJ"]
        assert countries(codes, None) == sorted(codes)[:20]


def test_selection_reads_location_mentions_of_empty_rows_newest_first():
    sql = _sql(script._SELECT_BATCH)
    assert "mentioned_countries = '{}'" in sql
    assert "ORDER BY published_at DESC, id DESC LIMIT $3" in sql
    # Keyset paging: rows the backfill leaves empty are not read again.
    assert "published_at <= $1 AND (published_at, id) < ($1, $2)" in sql
    assert "e.rel_type = 'MENTIONED_IN'" in sql and "n.type = 'LOCATION'" in sql
    assert "n.id = e.source_node_id" in sql  # LOCATION -> ARTICLE edges


def test_update_only_touches_rows_still_empty():
    sql = _sql(script._UPDATE)
    assert "WHERE a.id = v.id AND a.mentioned_countries = '{}'" in sql


def _row(n: int, iso=None, fips=None) -> dict:
    return {
        "id": uuid.UUID(int=1000 - n),
        "published_at": _NEWEST - timedelta(minutes=n),
        "iso": iso,
        "fips": fips,
    }


def _conn(batches: list[list[dict]], updated: list[str] | None = None) -> MagicMock:
    """A connection that serves *batches* to successive SELECTs and logs the calls."""
    events: list = []
    conn = MagicMock()
    conn.events = events
    served = iter(batches)

    async def fetch(sql, *args):
        events.append(("fetch", args))
        return next(served, [])

    async def execute(sql, *args):
        events.append(("execute", args))
        return (updated or ["UPDATE 0"]).pop(0)

    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(side_effect=execute)

    @asynccontextmanager
    async def transaction(**kwargs):
        events.append(("begin", kwargs))
        yield
        events.append(("commit",))

    conn.transaction = transaction
    return conn


@pytest.mark.asyncio
async def test_dry_run_counts_without_writing(capsys):
    rows = [_row(0, iso=["US", "IR"]), _row(1, iso=None, fips=["UK"]), _row(2)]
    conn = _conn([rows])

    result = await backfill(conn, write=False, batch_size=5)

    assert result == {"empty": 3, "filled": 2, "from_fips": 1}
    conn.execute.assert_not_awaited()
    assert conn.events[0] == ("begin", {"readonly": True})
    out = capsys.readouterr().out
    assert "3 articles without mentioned countries" in out
    assert "2 would get them from the knowledge graph" in out
    assert "--yes" in out


@pytest.mark.asyncio
async def test_writes_each_batch_in_its_own_transaction():
    first = [_row(0, iso=["US", "IR"]), _row(1)]
    second = [_row(2, fips=["UK", "FR"])]
    conn = _conn([first, second], updated=["UPDATE 1", "UPDATE 1"])

    result = await backfill(conn, write=True, batch_size=2)

    assert result == {"empty": 3, "filled": 2, "from_fips": 1}
    kinds = [e[0] for e in conn.events]
    assert kinds == ["begin", "fetch", "execute", "commit", "begin", "fetch", "execute", "commit"]
    assert conn.events[0] == ("begin", {})
    # Only the articles that get countries are updated, codes joined by commas.
    assert conn.events[2][1] == ([first[0]["id"]], ["IR,US"])
    assert conn.events[6][1] == ([second[0]["id"]], ["FR,GB"])


@pytest.mark.asyncio
async def test_pages_from_the_last_row_of_each_batch():
    first = [_row(0), _row(1)]
    second = [_row(2), _row(3)]
    conn = _conn([first, second, []])

    await backfill(conn, write=False, batch_size=2)

    fetches = [e[1] for e in conn.events if e[0] == "fetch"]
    assert len(fetches) == 3
    assert fetches[0][2] == 2  # batch size
    assert fetches[1][:2] == (first[-1]["published_at"], first[-1]["id"])
    assert fetches[2][:2] == (second[-1]["published_at"], second[-1]["id"])


@pytest.mark.asyncio
async def test_a_short_batch_is_the_last():
    conn = _conn([[_row(0)]])

    await backfill(conn, write=False, batch_size=5)

    assert conn.fetch.await_count == 1


@pytest.mark.asyncio
async def test_a_batch_with_nothing_to_fill_writes_nothing():
    conn = _conn([[_row(0), _row(1)]])

    result = await backfill(conn, write=True, batch_size=5)

    assert result == {"empty": 2, "filled": 0, "from_fips": 0}
    conn.execute.assert_not_awaited()


def test_batches_hold_5000_articles():
    assert script.BATCH_SIZE == 5000


@pytest.mark.asyncio
async def test_main_prints_the_database_host_first(monkeypatch, capsys):
    monkeypatch.setattr(script.settings, "database_url", "postgresql://u:p@db.example.com:5432/x")
    conn = AsyncMock()
    monkeypatch.setattr(script.asyncpg, "connect", AsyncMock(return_value=conn))
    calls = []

    async def fake_backfill(c, *, write):
        calls.append(write)
        print("counted")
        return {}

    monkeypatch.setattr(script, "backfill", fake_backfill)

    assert await script.main([]) == 0
    assert await script.main(["--yes"]) == 0

    assert calls == [False, True]
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Database: db.example.com"
    assert "p@" not in "\n".join(out)  # never the password
    conn.close.assert_awaited()


@pytest.mark.asyncio
async def test_main_needs_a_database_url(monkeypatch):
    monkeypatch.setattr(script.settings, "database_url", "")
    assert await script.main([]) == 2
