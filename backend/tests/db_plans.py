"""Plan checks for the opt-in database tests: what PostgreSQL chooses, and reads.

Shared by tests/test_board_db.py, tests/test_events_db.py and
tests/test_relations_db.py. Plans are checked both ways a statement can run:
custom (the first executions of a prepared statement) and generic (asyncpg
reuses its prepared statements, and PostgreSQL may switch one to a generic
plan). Each helper sets plan_cache_mode with SET LOCAL, so it must run inside a
transaction, and sets it back to auto afterwards.
"""

from __future__ import annotations

import json
from datetime import datetime


def walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from walk(child)


def summary(raw) -> dict:
    top = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
    nodes = list(walk(top))
    return {
        "seq_scans": {n["Relation Name"] for n in nodes if n["Node Type"] == "Seq Scan"},
        "indexes": {n["Index Name"] for n in nodes if "Index Name" in n},
    }


async def custom_plan(conn, sql: str, *args) -> dict:
    """The plan PostgreSQL runs with these values, as executed (its first runs)."""
    return summary(await conn.fetchval("EXPLAIN (ANALYZE, FORMAT JSON) " + sql, *args))


async def generic_plan(conn, sql: str, types: list[str], values: list[str]) -> dict:
    """The plan made without the values, which a reused prepared statement may switch to."""
    await conn.execute("SET LOCAL plan_cache_mode = force_generic_plan")
    await conn.execute(f"PREPARE zzplan_plan ({', '.join(types)}) AS {sql}")
    try:
        raw = await conn.fetchval(
            f"EXPLAIN (FORMAT JSON) EXECUTE zzplan_plan ({', '.join(values)})"
        )
    finally:
        await conn.execute("DEALLOCATE zzplan_plan")
        await conn.execute("SET LOCAL plan_cache_mode = auto")
    return summary(raw)


def literal(value) -> str:
    """*value* as an SQL literal of unknown type, which EXECUTE coerces to the parameter's."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        items = ",".join(
            '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"' for v in value
        )
        return literal("{" + items + "}")
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    return "'" + text.replace("'", "''") + "'"


async def pages(conn, sql: str, args: tuple, mode: str) -> int:
    """Shared buffers (hit + read) the statement touches when run with a *mode* plan."""
    await conn.execute(f"SET LOCAL plan_cache_mode = force_{mode}_plan")
    await conn.execute(f"PREPARE zzplan_q AS {sql}")
    try:
        raw = await conn.fetchval(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) EXECUTE zzplan_q"
            f" ({', '.join(literal(a) for a in args)})"
        )
    finally:
        await conn.execute("DEALLOCATE zzplan_q")
        await conn.execute("SET LOCAL plan_cache_mode = auto")
    plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
    return plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0)
