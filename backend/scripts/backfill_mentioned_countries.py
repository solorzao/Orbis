"""Fill articles.mentioned_countries for stories stored before ingestion wrote it.

Ingestion fills the column from PR 13b on. Older articles still hold its
default, '{}'; this takes their countries from the knowledge graph instead:
the LOCATION nodes linked to the article by MENTIONED_IN edges, which
ingestion built from the same GKG country mentions. Nodes written before the
FIPS to ISO switch (2026-10-10) hold GDELT's FIPS code and no country_fips
key; their codes are mapped to ISO here. The graph keeps no mention order,
so the codes are sorted.

Only empty arrays are read and written, so a rerun is safe; an article the
graph has no country for stays empty. 5,000 articles per batch, newest
first, each batch in its own transaction.

Run from backend/ with DATABASE_URL set (it also reads backend/.env):

    python -m scripts.backfill_mentioned_countries          # count only
    python -m scripts.backfill_mentioned_countries --yes    # write them

Cached /api/links answers expire within 10 minutes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

import asyncpg

from app.config import settings
from app.services.country_codes import fips_to_iso2
from app.services.gdelt import _MAX_MENTIONED_COUNTRIES

BATCH_SIZE = 5000

# Keyset paging, newest first: after each batch the cursor moves to its last
# row, so articles left empty are never read again. The plain published_at
# bound lets the index scan start at the cursor.
_SELECT_BATCH = """
    SELECT a.id, a.published_at, m.iso, m.fips
    FROM (
        SELECT id, published_at FROM articles
        WHERE mentioned_countries = '{}'
          AND published_at <= $1 AND (published_at, id) < ($1, $2)
        ORDER BY published_at DESC, id DESC LIMIT $3
    ) a
    CROSS JOIN LATERAL (
        SELECT
            array_agg(n.metadata->>'country_code')
                FILTER (WHERE n.metadata ? 'country_fips') AS iso,
            array_agg(n.metadata->>'country_code')
                FILTER (WHERE NOT n.metadata ? 'country_fips') AS fips
        FROM kg_edges e
        JOIN kg_nodes n ON n.id = e.source_node_id
        WHERE e.article_id = a.id AND e.rel_type = 'MENTIONED_IN' AND n.type = 'LOCATION'
    ) m
    ORDER BY a.published_at DESC, a.id DESC
"""

# ISO codes never contain commas, so each article's list travels as one string.
_UPDATE = """
    UPDATE articles AS a
    SET mentioned_countries = string_to_array(v.codes, ',')
    FROM unnest($1::uuid[], $2::text[]) AS v(id, codes)
    WHERE a.id = v.id AND a.mentioned_countries = '{}'
"""

# Before every stored article.
_START = (datetime.max.replace(tzinfo=timezone.utc), uuid.UUID(int=(1 << 128) - 1))


def countries(iso: list[str | None] | None, fips: list[str | None] | None) -> list[str]:
    """An article's ISO codes from its LOCATION nodes' codes, sorted and capped.

    *iso* are the codes of nodes written after the switch, *fips* those of
    nodes written before it. Empty and unknown codes are dropped.
    """
    codes = {c for c in iso or [] if c} | {fips_to_iso2(f) for f in fips or [] if f}
    codes.discard("")
    return sorted(codes)[:_MAX_MENTIONED_COUNTRIES]


async def backfill(conn, *, write: bool, batch_size: int = BATCH_SIZE) -> dict[str, int]:
    """Count the empty articles and those the graph has countries for; fill them if *write*.

    Returns the counts: ``empty`` articles read, ``filled`` (or fillable on a
    dry run) and ``from_fips``, those with a node written before the switch.
    """
    totals = {"empty": 0, "filled": 0, "from_fips": 0}
    cursor = _START
    while True:
        # A dry run reads in a read-only transaction: it cannot write.
        async with conn.transaction(**({} if write else {"readonly": True})):
            rows = await conn.fetch(_SELECT_BATCH, *cursor, batch_size)
            if not rows:
                break
            found = {r["id"]: countries(r["iso"], r["fips"]) for r in rows}
            found = {article_id: codes for article_id, codes in found.items() if codes}
            filled = len(found)
            if write and found:
                status = await conn.execute(
                    _UPDATE, list(found), [",".join(codes) for codes in found.values()]
                )
                filled = int(status.split()[-1])  # "UPDATE 4210"
        totals["empty"] += len(rows)
        totals["filled"] += filled
        totals["from_fips"] += sum(1 for r in rows if r["fips"] and r["id"] in found)
        cursor = (rows[-1]["published_at"], rows[-1]["id"])
        print(
            f"  {len(rows)} articles down to {cursor[0]:%Y-%m-%d %H:%M}: "
            f"{filled} {'filled' if write else 'fillable'}"
        )
        if len(rows) < batch_size:
            break

    verb = "got them" if write else "would get them"
    print(
        f"{totals['empty']} articles without mentioned countries; "
        f"{totals['filled']} {verb} from the knowledge graph "
        f"({totals['from_fips']} through FIPS codes from before the ISO switch)."
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
