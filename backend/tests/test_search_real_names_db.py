"""Search on a production-like graph of real names, in a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (017 included). The test runs in a transaction that is
rolled back, then vacuums the tables its fixture filled (see ``conn``). Skipped
without it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.services import entities, search
from tests import search_fixture

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)


# The tables the fixture fills: 200K graph nodes and 100K thread members.
_FILLED = ("kg_nodes", "kg_entity_names", "thread_members")


@pytest_asyncio.fixture
async def conn():
    """A connection in a transaction that is rolled back; then the fixture's tables
    are vacuumed, outside any transaction.

    ANALYZE writes a table's row and page counts to pg_class in place, so a
    rollback keeps them, and the aborted rows stay in the heap until vacuum:
    later tests' plans would be made for 100K members. VACUUM (ANALYZE) removes
    the dead rows and counts the live ones again. PARALLEL 0: a parallel vacuum
    can fail on a container's 64 MB /dev/shm.
    """
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        try:
            await connection.execute(f"VACUUM (PARALLEL 0, ANALYZE) {', '.join(_FILLED)}")
        finally:
            await connection.close()


def _walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


async def _explain(conn, sql: str, *args) -> dict:
    """The executed plan's buffers touched (hit + read), relations and indexes."""
    raw = await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, *args)
    top = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
    nodes = list(_walk(top))
    return {
        "buffers": top.get("Shared Hit Blocks", 0) + top.get("Shared Read Blocks", 0),
        "relations": {n["Relation Name"] for n in nodes if "Relation Name" in n},
        "indexes": {n["Index Name"] for n in nodes if "Index Name" in n},
    }


@pytest.mark.asyncio
async def test_on_real_names_search_reads_a_few_pages_of_the_narrow_names_table(conn, capsys):
    """Production's shape: ~56K real-looking people and organisations among 150K
    headlines in kg_nodes, and 100K thread members. No enable_seqscan here: these are
    the planner's own choices.

    On kg_nodes with name % q (before), "sunak" rechecked ~3,200 candidates on
    ~2,500 kg_nodes pages, "hamas" ~4,700 on ~3,300: every name with a word
    starting "Su" or "Ha". Now a word of the name must resemble q (<%), in a table
    of people and organisations only, a few MB that stay cached.
    """
    await search_fixture.build(conn)
    pages = await conn.fetchval(
        "SELECT sum(pg_relation_size(c)) / 8192 FROM unnest("
        "ARRAY['kg_entity_names', 'idx_kg_entity_names_trgm']::regclass[]) AS c"
    )
    expected = {
        "sunak": "Rishi Sunak",
        "hamas": "Hamas",
        "biden": "Joe Biden",
        "modi": "Narendra Modi",
        "musk": "Elon Musk",
        "starmer": "Keir Starmer",
        "netanyahu": "Benjamin Netanyahu",
        "pfizer": "Pfizer",
        "netanyhu": "Benjamin Netanyahu",  # a typo still finds him
    }
    for q, name in expected.items():
        args = (q, entities.like_escape(q) + "%")
        plan = await _explain(conn, search._NAMES_SQL, *args)
        assert plan["relations"] == {"kg_entity_names"}, (q, plan)
        assert plan["buffers"] < min(pages, 400), (q, plan)
        found = [r["name"] for r in await conn.fetch(search._NAMES_SQL, *args)]
        assert name in found[:3], (q, found)

    # Selective names: the trigram index, by the planner's own choice.
    for q in ("biden", "netanyahu", "pfizer"):
        plan = await _explain(conn, search._NAMES_SQL, q, q + "%")
        assert "idx_kg_entity_names_trgm" in plan["indexes"], (q, plan)

    # Counts: the members of each candidate, through the entity index.
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    counts = await _explain(
        conn, search._COUNTS_SQL, ["Joe Biden", "Hunter Biden", "Jill Biden"], week_ago, 100
    )
    assert "idx_thread_members_entities" in counts["indexes"], counts
    # REPRO diagnostics (throwaway branch only).
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pageinspect")
    gin = await conn.fetchrow(
        "SELECT * FROM gin_metapage_info(get_raw_page('idx_kg_entity_names_trgm', 0))"
    )
    vacuums = await conn.fetch(
        "SELECT relname, n_live_tup, n_dead_tup, vacuum_count, autovacuum_count,"
        " analyze_count, autoanalyze_count FROM pg_stat_user_tables"
        " WHERE relname IN ('kg_nodes', 'kg_entity_names', 'thread_members')"
    )
    plan_text = await conn.fetch(
        "EXPLAIN " + entities._RESOLVE_SQL, "PERSON", "benjamin netanyahu", week_ago, 100
    )
    with capsys.disabled():
        print("\n=== REPRO resolve ===")
        print("gin metapage:", dict(gin))
        for row in vacuums:
            print("stats:", dict(row))
        print("\n".join(r[0] for r in plan_text))
        print("=== END REPRO resolve ===")
    # Resolution: the narrow table too, never kg_nodes.
    resolve = await _explain(
        conn, entities._RESOLVE_SQL, "PERSON", "benjamin netanyahu", week_ago, 100
    )
    assert "kg_nodes" not in resolve["relations"], resolve
    assert "idx_kg_entity_names_trgm" in resolve["indexes"], resolve
