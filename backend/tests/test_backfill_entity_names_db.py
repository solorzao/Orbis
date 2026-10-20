"""The kg_entity_names backfill on a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (017 included). The test runs in a transaction that is
rolled back; its nodes are named ``Zz ...``. Skipped without it.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from scripts import backfill_entity_names as script

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


async def _missing(conn) -> set[tuple[str, str]]:
    rows = await conn.fetch(
        "SELECT n.type, n.name FROM kg_nodes n WHERE n.type IN ('PERSON', 'ORG')"
        " AND NOT EXISTS (SELECT 1 FROM kg_entity_names e WHERE e.node_id = n.id)"
    )
    return {(r["type"], r["name"]) for r in rows}


@pytest.mark.asyncio
async def test_fills_the_people_and_orgs_stored_before_the_table_and_reruns_add_nothing(conn):
    # As stored before migration 017: kg_nodes only.
    await conn.execute(
        "INSERT INTO kg_nodes (type, name) SELECT t, 'Zz Backfill ' || t || ' ' || g"
        " FROM generate_series(1, 7) g, unnest(ARRAY['PERSON', 'ORG', 'ARTICLE', 'TOPIC']) t"
    )
    assert {n for n in await _missing(conn) if n[1].startswith("Zz Backfill")} == {
        (t, f"Zz Backfill {t} {g}") for t in ("PERSON", "ORG") for g in range(1, 8)
    }

    dry = await script.backfill(conn, write=False, batch_size=4)
    assert dry["missing"] >= 14 and dry["added"] == 0
    written = await script.backfill(conn, write=True, batch_size=4)
    assert written["added"] == dry["missing"]

    assert await _missing(conn) == set()
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM kg_entity_names WHERE name LIKE 'Zz Backfill ARTICLE%'"
            " OR name LIKE 'Zz Backfill TOPIC%'"
        )
        == 0
    )
    again = await script.backfill(conn, write=True, batch_size=4)
    assert (again["missing"], again["added"]) == (0, 0)
