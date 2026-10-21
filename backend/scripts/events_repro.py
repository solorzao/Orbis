"""Measure GDELT Events ingestion on CI: what a cycle costs and what a week stores.

Run by hand (.github/workflows/events-repro.yml, workflow_dispatch) against
CI's throwaway Postgres (ORBIS_TEST_DATABASE_URL, migrations applied).
Downloads the last --files 15-minute exports from GDELT (about 80 KB each) on
the runner. Prints a Markdown report, also written to $GITHUB_STEP_SUMMARY on
CI.

Exits 1 only on a format problem in GDELT's data: under 99.9% of rows with 61
fields, or an event id repeated across files (rollups would double-count). A
network failure (GDELT unreachable, files missing) is reported, and exits 0.

Usage: cd backend && python -m scripts.events_repro --files 96
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import asyncpg

from app.services import events, relations
from app.services.gdelt import download_capped, fetch_lastupdate

# One vCore and little memory, as on the B1ms (production numbers otherwise look better).
B1MS = ("SET max_parallel_workers_per_gather = 0", "SET jit = off", "SET work_mem = '4MB'")
MIN_FIELDS_61 = 0.999
MAX_FILES = 96  # a day of 15-minute files: the workflow checks its input against this too
# The relations list over the week, on CI's disk (faster than the P4): checked by
# hand, reported, never a failure (only the format gates fail the run).
MAX_LIST_MS = 300


async def _b1ms(conn) -> None:
    for statement in B1MS:
        await conn.execute(statement)


async def _explain(conn, sql: str, *args) -> tuple[float, int]:
    """*sql*'s execution time (ms) and shared buffers (hit + read), as run."""
    raw = await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, *args)
    top = (json.loads(raw) if isinstance(raw, str) else raw)[0]
    plan = top["Plan"]
    return top["Execution Time"], plan.get("Shared Hit Blocks", 0) + plan.get(
        "Shared Read Blocks", 0
    )


def _median(values) -> float:
    values = list(values)
    return statistics.median(values) if values else 0.0


def _max(values) -> float:
    return max(values, default=0)


def _p95(values) -> float:
    values = list(values)
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=20)[-1]


def _emit(text: str) -> None:
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


async def main(n_files: int) -> int:
    index = await fetch_lastupdate()
    newest = events.slot_of(index["export"].url) if index and "export" in index else None
    if newest is None:
        _emit(
            "## GDELT Events repro\n\n"
            "lastupdate.txt was unreachable or had no export: nothing measured."
        )
        return 0
    pool = await asyncpg.create_pool(
        os.environ["ORBIS_TEST_DATABASE_URL"], min_size=1, max_size=1, init=_b1ms
    )
    slots = [newest - k * events.SLOT for k in range(n_files)][::-1]  # oldest first
    now = datetime.now(timezone.utc)
    per_file: list[dict] = []
    ids: Counter = Counter()
    totals = events.ParseStats()
    cycles: list[tuple[int, float]] = []
    rollups: dict = {}
    files: list[events.FileResult] = []
    unavailable = unreadable = 0
    for i, slot in enumerate(slots):
        got = await download_capped(events.slot_url(slot), events.MAX_ZIP_BYTES)
        raw = events.read_export(got.body) if got.status == "ok" else None
        if got.status != "ok":
            unavailable += 1  # network or GDELT: reported, never a failure
            files.append(events.FileResult(slot, "missing", 0, 0))
        elif raw is None:
            unreadable += 1
            files.append(events.FileResult(slot, "unreadable", 0, 0))
        else:
            lines = [line.rstrip("\r") for line in raw.split("\n") if line.rstrip("\r")]
            ids.update(line.split("\t", 1)[0] for line in lines)
            started = time.perf_counter()
            stats = events.parse_events(raw, now.date(), rollups)
            per_file.append(
                {
                    "zip_kb": len(got.body) / 1024,
                    "csv_kb": len(raw) / 1024,
                    "rows": stats.rows,
                    "fields_61": sum(
                        len(line.split("\t", events.COLUMNS)) == events.COLUMNS for line in lines
                    ),
                    "parse_ms": (time.perf_counter() - started) * 1000,
                }
            )
            totals.add(stats)
            files.append(events.FileResult(slot, "ok", stats.rows, stats.kept))
        if len(files) == 2 or i == len(slots) - 1:
            started = time.perf_counter()
            upserted = await events.store_rollups(pool, rollups, files)
            cycles.append((upserted, (time.perf_counter() - started) * 1000))
            rollups, files = {}, []
    async with pool.acquire() as conn:
        day_rows = await conn.fetchval("SELECT count(*) FROM event_pairs_daily")
        await conn.execute("SELECT pg_stat_force_next_flush()")
        await conn.execute("SELECT pg_stat_clear_snapshot()")
        upd, hot = await conn.fetchrow(
            "SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables"
            " WHERE relname = 'event_pairs_daily'"
        )
        await conn.execute(
            "INSERT INTO event_pairs_daily SELECT a_iso, b_iso, day - k, quad_class, n_events,"
            " mentions, goldstein_sum, tone_sum, sample_urls, outlets"
            " FROM event_pairs_daily, generate_series(1, 7) k ON CONFLICT DO NOTHING"
        )
        await conn.execute("VACUUM (ANALYZE) event_pairs_daily")
        week = await conn.fetchrow(
            "SELECT count(*) AS rows,"
            " pg_size_pretty(pg_total_relation_size('event_pairs_daily')) AS total,"
            " pg_size_pretty(pg_relation_size('event_pairs_daily')) AS heap,"
            " pg_size_pretty(pg_relation_size('event_pairs_daily_pkey')) AS pkey,"
            " pg_size_pretty(pg_relation_size('idx_event_pairs_day')) AS day_index"
            " FROM event_pairs_daily"
        )
        # The relations reads (19c) over the week just built: the lens's 7 days.
        first, last = relations.lens_days(now)
        list_ms, list_buffers = await _explain(
            conn,
            relations.LIST_SQL,
            first,
            last,
            relations.QUADS["all"],
            relations.MIN_EVENTS,
            relations.MIN_OUTLETS,
        )
        busiest = await conn.fetchrow(
            "SELECT least(a_iso, b_iso) AS a, greatest(a_iso, b_iso) AS b"
            " FROM event_pairs_daily WHERE day BETWEEN $1 AND $2"
            " GROUP BY 1, 2 ORDER BY sum(mentions) DESC, 1, 2 LIMIT 1",
            first,
            last,
        )
        detail_ms, detail_buffers = (
            await _explain(conn, relations.DETAIL_SQL, busiest["a"], busiest["b"], first, last)
            if busiest
            else (0.0, 0)
        )
    await pool.close()

    rows = max(totals.rows, 1)
    fields_61 = sum(f["fields_61"] for f in per_file) / rows
    repeated = sum(n - 1 for n in ids.values() if n > 1)
    store_ms = [ms for _, ms in cycles[1:]] or [ms for _, ms in cycles]
    zip_kb = [f["zip_kb"] for f in per_file]
    csv_kb = [f["csv_kb"] for f in per_file]
    file_rows = [f["rows"] for f in per_file]
    parse_ms = [f["parse_ms"] for f in per_file]
    upserts = [n for n, _ in cycles]
    shares = " / ".join(
        f"{100 * n / rows:.{2 if name in ('malformed', 'stale') else 1}f}%"
        for name, n in (
            ("kept", totals.kept),
            ("not root", totals.not_root),
            ("no pair", totals.no_pair),
            ("same country", totals.same_country),
            ("malformed", totals.malformed),
            ("stale", totals.stale),
        )
    )
    root = 100 * (1 - totals.not_root / max(rows - totals.malformed, 1))
    unmapped = ", ".join(f"{c} {n}" for c, n in totals.unmapped.most_common(10))
    first_store = cycles[0][1] if cycles else 0
    report = [
        f"## GDELT Events repro: {len(per_file)} of {n_files} files read"
        f" ({unavailable} unavailable, {unreadable} unreadable)",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Zip KB per file (median / max) | {_median(zip_kb):.0f} / {_max(zip_kb):.0f} |",
        f"| CSV KB per file (median / max) | {_median(csv_kb):.0f} / {_max(csv_kb):.0f} |",
        f"| Rows per file (median / max) | {_median(file_rows):.0f} / {_max(file_rows)} |",
        f"| Rows with 61 fields | {100 * fields_61:.2f}% |",
        f"| Kept / not root / no pair / same country / malformed / stale | {shares} |",
        f"| Root events among valid rows (only these are kept) | {root:.1f}% |",
        f"| Repeated event ids across files | {repeated} |",
        f"| Unmapped actor codes (top 10) | {unmapped} |",
        f"| Parse ms per file (median / p95) | {_median(parse_ms):.0f} / {_p95(parse_ms):.0f} |",
        f"| Rows upserted per cycle (median / max) | {_median(upserts):.0f} / {_max(upserts)} |",
        f"| Store ms per cycle (first / median / p95) | {first_store:.0f}"
        f" / {_median(store_ms):.0f} / {_p95(store_ms):.0f} |",
        f"| Rows after the day (upper bound for rows a day) | {day_rows} |",
        f"| HOT updates during the day | {hot} of {upd} ({100 * hot / max(upd, 1):.0f}%) |",
        f"| Week (8 days): rows, total, heap, pkey, day index | {week['rows']}, {week['total']},"
        f" {week['heap']}, {week['pkey']}, {week['day_index']} |",
        f"| Relations list over the lens ({first} to {last}): ms, buffers"
        f" | {list_ms:.0f}, {list_buffers} |",
        f"| Relations detail, busiest pair"
        f" ({busiest['a'] + '-' + busiest['b'] if busiest else 'none'}): ms, buffers"
        f" | {detail_ms:.1f}, {detail_buffers} |",
    ]
    if list_ms > MAX_LIST_MS:
        report.append(
            f"\n**Read gate:** the relations list took {list_ms:.0f} ms, over {MAX_LIST_MS} ms:"
            " stop and report before 19c merges."
        )
    _emit("\n".join(report))
    if not per_file:
        _emit("\nNo file could be read (network or GDELT): no format gate checked.")
        return 0
    failures = []
    if fields_61 < MIN_FIELDS_61:
        failures.append(f"only {100 * fields_61:.2f}% of rows have 61 fields: the format changed")
    if repeated:
        failures.append(f"{repeated} event ids repeat across files: rollups would double-count")
    if failures:
        _emit("\n**Format gates failed:** " + "; ".join(failures) + ".")
        return 1
    return 0


def _files(value: str) -> int:
    """--files: an integer from 1 to MAX_FILES, whatever the workflow passed."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if not 1 <= n <= MAX_FILES:
        raise argparse.ArgumentTypeError(f"must be from 1 to {MAX_FILES}, not {n}")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=_files, default=MAX_FILES)
    sys.exit(asyncio.run(main(parser.parse_args().files)))
