"""Reconcile kg_entity_names (migration 017) with the people and organisations in kg_nodes.

Migration 017 fills the table, and ingestion keeps it in sync
(knowledge_graph.upsert_node adds, the orphan purge deletes). This repairs
what that can miss: nodes the previous backend wrote while a deploy finished,
or the rare node whose row an upsert's re-read skipped. It adds the rows
missing for PERSON and ORG nodes, and with --prune deletes rows whose node is
gone.

Both tables are read in ranges of heap pages (a TID range scan: each stretch
of the heap in order, never random reads), each range in its own
transaction, with a short pause between ranges so ingestion keeps its share
of the disk. Writes are idempotent: a rerun, or ingestion writing at the same
time, is safe.

Run from backend/ with DATABASE_URL set (it also reads backend/.env):

    python -m scripts.reconcile_entity_names                  # count only
    python -m scripts.reconcile_entity_names --prune          # count both ways
    python -m scripts.reconcile_entity_names --yes            # add the missing
    python -m scripts.reconcile_entity_names --yes --prune    # and prune

Cached /api/search answers expire within 5 minutes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import asyncpg

from app.config import settings

BATCH_PAGES = 2000  # 16 MB of heap per range
PAUSE_S = 0.5

_PAGES = "SELECT pg_relation_size($1::regclass) / current_setting('block_size')::int"

_MISSING = """
    FROM kg_nodes n
    WHERE n.ctid >= $1 AND n.ctid < $2
      AND n.type IN ('PERSON', 'ORG')
      AND NOT EXISTS (SELECT 1 FROM kg_entity_names e WHERE e.node_id = n.id)
"""
_COUNT_MISSING = f"SELECT count(*) {_MISSING}"
_ADD_MISSING = f"""
    INSERT INTO kg_entity_names (node_id, type, name)
    SELECT n.id, n.type, n.name {_MISSING}
    ON CONFLICT (node_id) DO NOTHING
"""

_ORPHANS = """
    FROM kg_entity_names e
    WHERE e.ctid >= $1 AND e.ctid < $2
      AND NOT EXISTS (SELECT 1 FROM kg_nodes n WHERE n.id = e.node_id)
"""
_COUNT_ORPHANS = f"SELECT count(*) {_ORPHANS}"
_PRUNE_ORPHANS = f"DELETE {_ORPHANS}"


async def _ranges(conn, table: str, batch_pages: int, pause: float) -> AsyncIterator[tuple]:
    """(first, end) tids of successive ranges of *batch_pages* heap pages of *table*,
    up to its size as each range starts, pausing *pause* seconds between them."""
    start = 0
    while start < await conn.fetchval(_PAGES, table):
        if start:
            await asyncio.sleep(pause)
        yield (start, 0), (start + batch_pages, 0)
        start += batch_pages


async def reconcile(
    conn,
    *,
    write: bool,
    prune: bool,
    batch_pages: int = BATCH_PAGES,
    pause: float = PAUSE_S,
) -> dict[str, int]:
    """Count (or with *write*, add) the rows missing for PERSON and ORG nodes; with
    *prune*, count (or delete) the rows whose node is gone.

    Returns ``missing`` and ``added``, ``orphaned`` and ``pruned``.
    """
    totals = {"missing": 0, "added": 0, "orphaned": 0, "pruned": 0}
    passes = [("kg_nodes", _COUNT_MISSING, _ADD_MISSING, "missing", "added")]
    if prune:
        passes.append(("kg_entity_names", _COUNT_ORPHANS, _PRUNE_ORPHANS, "orphaned", "pruned"))
    for table, count_sql, write_sql, found, done in passes:
        async for first, end in _ranges(conn, table, batch_pages, pause):
            # A dry run reads in a read-only transaction (unless already inside one).
            readonly = not write and not conn.is_in_transaction()
            async with conn.transaction(**({"readonly": True} if readonly else {})):
                if write:
                    status = await conn.execute(write_sql, first, end)
                    changed = int(status.split()[-1])  # "INSERT 0 12", "DELETE 3"
                    totals[found] += changed
                    totals[done] += changed
                else:
                    totals[found] += await conn.fetchval(count_sql, first, end)

    print(
        f"{totals['missing']} people and organisations missing from kg_entity_names,"
        f" {totals['added']} added."
    )
    if prune:
        print(f"{totals['orphaned']} rows without a node, {totals['pruned']} pruned.")
    if not write:
        print("Nothing written. Run again with --yes to write.")
    return totals


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="write (default: count only)")
    parser.add_argument("--prune", action="store_true", help="also rows whose node is gone")
    args = parser.parse_args(argv)

    if not settings.database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    print(f"Database: {urlsplit(settings.database_url).hostname}")
    conn = await asyncpg.connect(settings.database_url)
    try:
        await reconcile(conn, write=args.yes, prune=args.prune)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
