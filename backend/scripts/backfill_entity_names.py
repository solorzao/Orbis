"""Fill kg_entity_names (migration 017) with the people and organisations stored before it.

Search and dossier name resolution read people and organisations from this
narrow table. Ingestion adds every PERSON and ORG node it writes or mentions
again (knowledge_graph.upsert_node), so only nodes stored before the deploy
and not mentioned since are missing; this adds them.

Nodes are read 5,000 at a time in id order (keyset paging, each batch its own
transaction), and only the missing ones are written, with ON CONFLICT DO
NOTHING, so a rerun, or ingestion writing at the same time, is safe.

Run from backend/ with DATABASE_URL set (it also reads backend/.env):

    python -m scripts.backfill_entity_names          # count only
    python -m scripts.backfill_entity_names --yes    # write them

Cached /api/search answers expire within 5 minutes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from urllib.parse import urlsplit

import asyncpg

from app.config import settings

BATCH_SIZE = 5000

_SELECT_BATCH = """
    SELECT n.id, n.type, n.name,
           EXISTS (SELECT 1 FROM kg_entity_names e WHERE e.node_id = n.id) AS present
    FROM kg_nodes n
    WHERE n.type IN ('PERSON', 'ORG') AND n.id > $1
    ORDER BY n.id
    LIMIT $2
"""

_INSERT = """
    INSERT INTO kg_entity_names (node_id, type, name)
    SELECT * FROM unnest($1::uuid[], $2::text[], $3::text[])
    ON CONFLICT (node_id) DO NOTHING
"""

# Before every node id.
_START = uuid.UUID(int=0)


async def backfill(conn, *, write: bool, batch_size: int = BATCH_SIZE) -> dict[str, int]:
    """Count the people and organisations missing from kg_entity_names; add them if *write*.

    Returns the counts: ``nodes`` read, ``missing`` among them, and ``added``.
    """
    totals = {"nodes": 0, "missing": 0, "added": 0}
    cursor = _START
    while True:
        # A dry run reads in a read-only transaction (unless already inside one).
        readonly = not write and not conn.is_in_transaction()
        async with conn.transaction(**({"readonly": True} if readonly else {})):
            rows = await conn.fetch(_SELECT_BATCH, cursor, batch_size)
            missing = [r for r in rows if not r["present"]]
            added = 0
            if write and missing:
                status = await conn.execute(
                    _INSERT,
                    [r["id"] for r in missing],
                    [r["type"] for r in missing],
                    [r["name"] for r in missing],
                )
                added = int(status.split()[-1])  # "INSERT 0 4210"
        if not rows:
            break
        totals["nodes"] += len(rows)
        totals["missing"] += len(missing)
        totals["added"] += added
        cursor = rows[-1]["id"]
        print(f"  {len(rows)} nodes: {len(missing)} missing, {added} added")
        if len(rows) < batch_size:
            break

    print(
        f"{totals['nodes']} people and organisations; {totals['missing']} missing from"
        f" kg_entity_names; {totals['added']} added."
    )
    if not write:
        print("Nothing written. Run again with --yes to write them.")
    return totals


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="write them (default: count only)")
    args = parser.parse_args(argv)

    if not settings.database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    print(f"Database: {urlsplit(settings.database_url).hostname}")
    conn = await asyncpg.connect(settings.database_url)
    try:
        await backfill(conn, write=args.yes)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
