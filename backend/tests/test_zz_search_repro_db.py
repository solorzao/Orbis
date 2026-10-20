"""THROWAWAY (claude/search-names-repro, never merged): measure search's name match on
a production-like graph of real names, in CI's database, and print the numbers.

Buffers touched (shared hit + read), candidate rows and rechecks, per query and
variant: the current kg_nodes match (% on the 016 partial index), word
similarity (<%), a narrow names table, and both; plus the member counts.
"""

from __future__ import annotations

import json
import os
import time

import pytest
import pytest_asyncio

from app.services.entities import member_mentions_sql
from tests import search_fixture

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

QUERIES = [
    "sunak", "hamas", "biden", "modi", "musk", "starmer", "netanyahu", "meloni", "erdogan",
    "pfizer", "openai", "trump", "putin", "macron", "netanyhu", "zelenski", "bidn", "sunk",
]  # fmt: skip

_NAMES = {
    "now: kg_nodes %": (
        "kg_nodes",
        "type IN ('PERSON', 'ORG') AND (name ILIKE $2 OR name % $1)",
        "similarity(name, $1)",
    ),
    "kg_nodes <%": (
        "kg_nodes",
        "type IN ('PERSON', 'ORG') AND (name ILIKE $2 OR $1 <% name)",
        "word_similarity($1, name)",
    ),
    "narrow %": ("zz_names", "(name ILIKE $2 OR name % $1)", "similarity(name, $1)"),
    "narrow <%": ("zz_names", "(name ILIKE $2 OR $1 <% name)", "word_similarity($1, name)"),
}

_COUNTS = f"""
    SELECT c.name, m.stories, m.capped
    FROM unnest($1::text[]) AS c(name)
    CROSS JOIN LATERAL {member_mentions_sql("c.name", "now() - interval '7 days'", "100")} m
"""


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


def _walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


async def _explain(conn, sql: str, *args) -> dict:
    raw = await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, *args)
    plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]
    top = plan["Plan"]
    stats = {
        "buffers": top.get("Shared Hit Blocks", 0) + top.get("Shared Read Blocks", 0),
        "read": top.get("Shared Read Blocks", 0),
        "ms": round(plan.get("Execution Time", 0.0), 1),
        "index_rows": 0,
        "heap_rows": 0,
        "recheck_removed": 0,
        "heap_blocks": 0,
        "nodes": [],
    }
    for node in _walk(top):
        kind = node["Node Type"]
        name = node.get("Index Name") or node.get("Relation Name") or ""
        stats["nodes"].append(f"{kind}{'(' + name + ')' if name else ''}")
        loops = node.get("Actual Loops", 1)
        if kind == "Bitmap Index Scan":
            stats["index_rows"] += node.get("Actual Rows", 0) * loops
        if kind == "Bitmap Heap Scan":
            stats["heap_rows"] += node.get("Actual Rows", 0) * loops
            stats["recheck_removed"] += node.get("Rows Removed by Index Recheck", 0) * loops
            stats["heap_blocks"] += node.get("Exact Heap Blocks", 0) + node.get(
                "Lossy Heap Blocks", 0
            )
    return stats


@pytest.mark.asyncio
async def test_measure_search_name_match(conn, capsys):
    started = time.perf_counter()
    names = await search_fixture.build(conn)
    built = time.perf_counter() - started
    await conn.execute(
        "CREATE TABLE zz_names (node_id uuid PRIMARY KEY, type text NOT NULL, name text NOT NULL)"
    )
    await conn.execute(
        "INSERT INTO zz_names SELECT id, type, name FROM kg_nodes"
        " WHERE type IN ('PERSON', 'ORG') ORDER BY ctid"
    )
    await conn.execute("CREATE INDEX zz_names_trgm ON zz_names USING gin (name gin_trgm_ops)")
    await conn.execute("ANALYZE zz_names")
    sizes = await conn.fetch(
        "SELECT relname, pg_relation_size(oid) / 8192 AS pages FROM pg_class WHERE relname IN"
        " ('kg_nodes', 'zz_names', 'thread_members', 'idx_kg_nodes_entity_name_trgm',"
        " 'idx_kg_nodes_name_trgm', 'zz_names_trgm', 'idx_thread_members_entities')"
        " ORDER BY relname"
    )
    counts = await conn.fetch("SELECT type, count(*) FROM kg_nodes GROUP BY type ORDER BY type")

    lines = [
        "",
        "=== SEARCH REPRO ===",
        f"fixture built in {built:.0f}s; {len(names)} people/orgs",
        "rows: " + ", ".join(f"{r['type']}={r['count']}" for r in counts),
        "pages: " + ", ".join(f"{r['relname']}={r['pages']}" for r in sizes),
    ]
    for q in QUERIES:
        pattern = q + "%"
        for label, (table, where, sim) in _NAMES.items():
            sql = f"SELECT {sim} AS sim, type, name FROM {table} WHERE {where}"
            stats = await _explain(conn, f"{sql} ORDER BY sim DESC, name LIMIT 20", q, pattern)
            candidates = await conn.fetchval(
                f"SELECT count(*) FROM {table} WHERE {where}", q, pattern
            )
            top = await conn.fetch(f"{sql} ORDER BY sim DESC, name LIMIT 20", q, pattern)
            lines.append(
                f"{q:10} | {label:16} | buffers={stats['buffers']:6} read={stats['read']:5}"
                f" | index_rows={stats['index_rows']:6} heap_rows={stats['heap_rows']:5}"
                f" recheck_removed={stats['recheck_removed']:6}"
                f" heap_blocks={stats['heap_blocks']:6} | candidates={candidates:5}"
                f" | {stats['ms']:7.1f} ms | {' > '.join(dict.fromkeys(stats['nodes']))}"
            )
            lines.append(f"{'':10} | {'':16} | top: {[r['name'] for r in top[:6]]}")
            if label == "now: kg_nodes %":
                current = [r["name"] for r in top]
        counted = await _explain(conn, _COUNTS, sorted(set(current)))
        lines.append(
            f"{q:10} | {'counts (now 20)':16} | buffers={counted['buffers']:6}"
            f" | heap_rows={counted['heap_rows']:6} heap_blocks={counted['heap_blocks']:6}"
            f" | {counted['ms']:7.1f} ms"
        )
    lines.append("=== END SEARCH REPRO ===")
    with capsys.disabled():
        print("\n".join(lines))
