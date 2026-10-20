"""Tests for the kg_entity_names reconcile (no database)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts import reconcile_entity_names as script


def _sql(query: str) -> str:
    return " ".join(query.split())


def test_missing_rows_are_found_in_ctid_ranges_of_kg_nodes():
    for query in (script._COUNT_MISSING, script._ADD_MISSING):
        sql = _sql(query)
        # A TID range scan: one stretch of the heap read in order, not random reads.
        assert "FROM kg_nodes n WHERE n.ctid >= $1 AND n.ctid < $2" in sql
        assert "n.type IN ('PERSON', 'ORG')" in sql
        assert "NOT EXISTS (SELECT 1 FROM kg_entity_names e WHERE e.node_id = n.id)" in sql
    assert _sql(script._ADD_MISSING).endswith("ON CONFLICT (node_id) DO NOTHING")


def test_orphaned_rows_are_found_in_ctid_ranges_of_the_names_table():
    for query in (script._COUNT_ORPHANS, script._PRUNE_ORPHANS):
        sql = _sql(query)
        assert "FROM kg_entity_names e WHERE e.ctid >= $1 AND e.ctid < $2" in sql
        assert "NOT EXISTS (SELECT 1 FROM kg_nodes n WHERE n.id = e.node_id)" in sql
    assert _sql(script._PRUNE_ORPHANS).startswith("DELETE FROM kg_entity_names e")


def _conn(pages: dict[str, int]):
    conn = MagicMock()
    conn.is_in_transaction = MagicMock(return_value=False)

    async def fetchval(sql, *args):
        if "pg_relation_size" in sql:
            return pages[args[0]]
        return 1  # one row missing (or orphaned) per range

    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.execute = AsyncMock(
        side_effect=lambda sql, *_: "INSERT 0 2" if "INSERT" in sql else "DELETE 3"
    )

    @asynccontextmanager
    async def transaction(**_kwargs):
        yield

    conn.transaction = MagicMock(side_effect=transaction)
    return conn


@pytest.mark.asyncio
async def test_a_dry_run_counts_both_ways_and_writes_nothing():
    conn = _conn({"kg_nodes": 5, "kg_entity_names": 2})
    with patch("scripts.reconcile_entity_names.asyncio.sleep", new_callable=AsyncMock) as sleep:
        totals = await script.reconcile(conn, write=False, prune=True, batch_pages=2, pause=0.5)

    assert totals == {"missing": 3, "added": 0, "orphaned": 1, "pruned": 0}
    conn.execute.assert_not_awaited()
    ranges = [c.args[1:] for c in conn.fetchval.await_args_list if "count" in c.args[0]]
    assert ranges == [((0, 0), (2, 0)), ((2, 0), (4, 0)), ((4, 0), (6, 0)), ((0, 0), (2, 0))]
    # A pause between batches, so ingestion's reads keep their share of the disk.
    assert [c.args for c in sleep.await_args_list] == [(0.5,), (0.5,)]
    # Read-only transactions for a dry run.
    assert all(c.kwargs == {"readonly": True} for c in conn.transaction.call_args_list)


@pytest.mark.asyncio
async def test_writes_add_the_missing_and_prune_only_when_asked():
    conn = _conn({"kg_nodes": 3, "kg_entity_names": 1})
    with patch("scripts.reconcile_entity_names.asyncio.sleep", new_callable=AsyncMock):
        added = await script.reconcile(conn, write=True, prune=False, batch_pages=2, pause=0)
    assert added == {"missing": 4, "added": 4, "orphaned": 0, "pruned": 0}
    assert [c.args[1:] for c in conn.execute.await_args_list] == [
        ((0, 0), (2, 0)),
        ((2, 0), (4, 0)),
    ]

    conn = _conn({"kg_nodes": 1, "kg_entity_names": 1})
    with patch("scripts.reconcile_entity_names.asyncio.sleep", new_callable=AsyncMock):
        both = await script.reconcile(conn, write=True, prune=True, batch_pages=2, pause=0)
    assert both == {"missing": 2, "added": 2, "orphaned": 3, "pruned": 3}
