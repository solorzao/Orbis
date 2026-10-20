"""Tests for the kg_entity_names backfill (no database)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import backfill_entity_names as script


def _sql(query: str) -> str:
    return " ".join(query.split())


def test_batches_walk_people_and_orgs_by_id():
    sql = _sql(script._SELECT_BATCH)
    assert "FROM kg_nodes n WHERE n.type IN ('PERSON', 'ORG') AND n.id > $1" in sql
    assert sql.endswith("ORDER BY n.id LIMIT $2")
    # Whether each is in the table already: a primary-key probe.
    assert "EXISTS (SELECT 1 FROM kg_entity_names e WHERE e.node_id = n.id) AS present" in sql


def test_writes_are_idempotent():
    sql = _sql(script._INSERT)
    assert "INSERT INTO kg_entity_names (node_id, type, name)" in sql
    assert "unnest($1::uuid[], $2::text[], $3::text[])" in sql
    assert sql.endswith("ON CONFLICT (node_id) DO NOTHING")


def _conn(batches):
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=batches)
    conn.execute = AsyncMock(side_effect=lambda sql, ids, *_: f"INSERT 0 {len(ids)}")

    @asynccontextmanager
    async def transaction(**_kwargs):
        yield

    conn.transaction = transaction
    return conn


def _row(i: int, present: bool) -> dict:
    return {"id": uuid.UUID(int=i), "type": "PERSON", "name": f"Name {i}", "present": present}


@pytest.mark.asyncio
async def test_a_dry_run_counts_and_writes_nothing():
    conn = _conn([[_row(1, True), _row(2, False)], []])
    totals = await script.backfill(conn, write=False, batch_size=2)
    assert totals == {"nodes": 2, "missing": 1, "added": 0}
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_writes_the_missing_ones_batch_after_batch():
    conn = _conn([[_row(1, True), _row(2, False)], [_row(3, False)]])
    totals = await script.backfill(conn, write=True, batch_size=2)

    assert totals == {"nodes": 3, "missing": 2, "added": 2}
    first, second = conn.fetch.await_args_list
    assert first.args[1:] == (uuid.UUID(int=0), 2)
    assert second.args[1:] == (uuid.UUID(int=2), 2)  # keyset: after the last id read
    written = [call.args[1] for call in conn.execute.await_args_list]
    assert written == [[uuid.UUID(int=2)], [uuid.UUID(int=3)]]
