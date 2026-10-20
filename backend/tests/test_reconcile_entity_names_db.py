"""The kg_entity_names reconcile on a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (017 included). The test runs in a transaction that is
rolled back; its nodes are named ``Zz ...``. Skipped without it.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from scripts import reconcile_entity_names as script

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def _names(conn) -> set[tuple[str, str]]:
    rows = await conn.fetch("SELECT type, name FROM kg_entity_names WHERE name LIKE 'Zz Rec%'")
    return {(r["type"], r["name"]) for r in rows}


async def _run(conn, **kwargs) -> dict[str, int]:
    return await script.reconcile(conn, batch_pages=1, pause=0, **kwargs)


@pytest.mark.asyncio
async def test_adds_the_missing_people_and_orgs_and_prunes_rows_without_a_node(conn):
    # Written by the previous backend during a deploy: kg_nodes only.
    await conn.execute(
        "INSERT INTO kg_nodes (type, name) SELECT t, 'Zz Rec ' || t || ' ' || g"
        " FROM generate_series(1, 5) g, unnest(ARRAY['PERSON', 'ORG', 'ARTICLE', 'TOPIC']) t"
    )
    # A names row whose node is gone.
    await conn.execute(
        "INSERT INTO kg_entity_names (node_id, type, name)"
        " VALUES (gen_random_uuid(), 'PERSON', 'Zz Rec Ghost')"
    )
    people_and_orgs = {(t, f"Zz Rec {t} {g}") for t in ("PERSON", "ORG") for g in range(1, 6)}

    dry = await _run(conn, write=False, prune=True)
    assert dry["missing"] >= 10 and dry["orphaned"] >= 1
    assert (dry["added"], dry["pruned"]) == (0, 0)
    assert await _names(conn) == {("PERSON", "Zz Rec Ghost")}  # nothing written

    added = await _run(conn, write=True, prune=False)
    assert added["added"] == dry["missing"]
    assert await _names(conn) == people_and_orgs | {("PERSON", "Zz Rec Ghost")}

    pruned = await _run(conn, write=True, prune=True)
    assert (pruned["added"], pruned["pruned"]) == (0, dry["orphaned"])
    assert await _names(conn) == people_and_orgs

    again = await _run(conn, write=False, prune=True)
    assert (again["missing"], again["orphaned"]) == (0, 0)
