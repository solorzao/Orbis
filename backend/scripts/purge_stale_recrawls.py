"""Delete stored articles that are old pages GDELT re-crawled as new.

Ingestion skips these now (app.services.gdelt._is_stale_recrawl); this one-off
removes the ones stored before it did: articles whose URL date is more than
RETENTION_DAYS (7) days before their published_at, the date GDELT listed them.

It judges by URL dates only. Ingestion prefers GDELT's PAGE_PRECISEPUBTIMESTAMP,
which is not stored, so this cannot see a page whose timestamp shows it was
updated after the date in its URL. Read the dry-run list before --yes.

Run from backend/ with DATABASE_URL set (it also reads backend/.env):

    python -m scripts.purge_stale_recrawls          # count and list them
    python -m scripts.purge_stale_recrawls --yes    # delete them

Deleting an article deletes its knowledge-graph edges (ON DELETE CASCADE); the
next ingestion cycle purges the nodes left without edges. Cached API responses
expire within DB_CACHE_TTL (5 minutes).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

import asyncpg

from app.config import settings
from app.services.gdelt import _is_stale_recrawl, _url_date

_SELECT = "SELECT id, source_url, published_at FROM articles"
_DELETE = "DELETE FROM articles WHERE id = ANY($1::uuid[])"


def select_stale(rows: Iterable[Mapping]) -> list[Mapping]:
    """The rows whose URL date is more than the retention window before published_at."""
    return [r for r in rows if _is_stale_recrawl(_url_date(r["source_url"]), r["published_at"])]


async def purge(conn, *, delete: bool) -> int:
    """Count and list the stale re-crawls; delete them if *delete*.

    Returns how many were found, or deleted.
    """
    stale = select_stale(await conn.fetch(_SELECT))
    print(f"{len(stale)} stale re-crawls (URL date over {settings.retention_days} days old).")
    for row in stale:
        url = row["source_url"]
        print(f"  published {row['published_at']:%Y-%m-%d}  URL date {_url_date(url)}  {url}")
    if not stale:
        return 0
    if not delete:
        print(
            "Nothing deleted. Judged by URL dates only (the precise publication "
            "timestamp is not stored). Read the list, then run again with --yes."
        )
        return len(stale)
    status = await conn.execute(_DELETE, [r["id"] for r in stale])
    deleted = int(status.split()[-1])  # "DELETE 64"
    print(f"Deleted {deleted} articles.")
    return deleted


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="delete them (default: count only)")
    args = parser.parse_args(argv)

    if not settings.database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    print(f"Database: {urlsplit(settings.database_url).hostname}")
    conn = await asyncpg.connect(settings.database_url)
    try:
        await purge(conn, delete=args.yes)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
