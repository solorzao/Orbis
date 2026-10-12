"""articles.story_key on a real PostgreSQL: ingestion's upsert writes it.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied, 012 (story_key) included. Every test runs in a
transaction that is rolled back, so nothing it inserts is ever committed;
its rows are titled ``zzstory-...``. Skipped without it.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from app.services.database import _UPSERT_ARTICLE_SQL, _upsert_article_args
from app.services.titles import story_key, story_key_sql

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    has_column = await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'articles' AND column_name = 'story_key')"
    )
    if not has_column:
        await connection.close()
        pytest.skip("articles.story_key is missing: apply migration 012")
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


def _url() -> str:
    return f"https://zzstory.test/{uuid.uuid4()}"


async def _upsert(conn, article: dict) -> None:
    await conn.execute(_UPSERT_ARTICLE_SQL, *_upsert_article_args(article))


async def _keys(conn, urls: list[str]) -> list[int | None]:
    rows = await conn.fetch(
        "SELECT source_url, story_key FROM articles WHERE source_url = ANY($1::text[])", urls
    )
    by_url = {r["source_url"]: r["story_key"] for r in rows}
    return [by_url[u] for u in urls]


@pytest.mark.asyncio
async def test_upsert_writes_the_key_and_a_recrawl_replaces_it(conn):
    url = _url()
    article = {"source_url": url, "title": "zzstory-Quake hits Kathmandu - Reuters"}
    await _upsert(conn, article)
    assert await _keys(conn, [url]) == [story_key("zzstory-Quake hits Kathmandu", url)]

    article["title"] = "zzstory-Quake toll rises in Kathmandu - Reuters"
    await _upsert(conn, article)
    assert await _keys(conn, [url]) == [story_key("zzstory-Quake toll rises in Kathmandu", url)]


@pytest.mark.asyncio
async def test_copies_share_a_key_and_untitled_rows_do_not(conn):
    titles = [
        "zzstory-Quake hits Kathmandu - Reuters",
        "zzstory-Quake hits Kathmandu | BBC News",
        "zzstory-Floods hit Dhaka",
        "",  # untitled: keyed by its URL
        "",
    ]
    urls = [_url() for _ in titles]
    for title, url in zip(titles, urls):
        await _upsert(conn, {"source_url": url, "title": title})

    keys = await _keys(conn, urls)
    assert keys == [story_key(t, u) for t, u in zip(titles, urls)]
    assert keys[0] == keys[1]  # syndicated copies: one story
    assert len({keys[0], keys[2], keys[3], keys[4]}) == 4


async def _insert_keyless(conn, title: str, url: str) -> None:
    """A row as written before ingestion stored story_key."""
    await conn.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude, longitude,
                              location)
        VALUES ($1, $2, 'zzstory.test', now(), 0, 0,
                ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography)
        """,
        title,
        url,
    )


@pytest.mark.asyncio
async def test_story_key_sql_is_the_stored_key_else_the_lowercased_title(conn):
    keyed, unkeyed, unkeyed_upper, unkeyed_other = _url(), _url(), _url(), _url()
    await _upsert(conn, {"source_url": keyed, "title": "zzstory-Quake hits Kathmandu - Reuters"})
    await _insert_keyless(conn, "zzstory-Quake hits Kathmandu", unkeyed)
    await _insert_keyless(conn, "zzstory-QUAKE HITS KATHMANDU", unkeyed_upper)
    await _insert_keyless(conn, "zzstory-Floods hit Dhaka", unkeyed_other)
    urls = [keyed, unkeyed, unkeyed_upper, unkeyed_other]

    rows = await conn.fetch(
        f"SELECT a.source_url, a.story_key, {story_key_sql('a')} AS story"
        " FROM articles a WHERE a.source_url = ANY($1::text[])",
        urls,
    )
    stories = {r["source_url"]: r["story"] for r in rows}
    assert all(stories[u] is not None for u in urls)
    assert stories[keyed] == story_key("zzstory-Quake hits Kathmandu", keyed)
    # Unkeyed: exact-title copies, any case, share one; other titles do not.
    assert stories[unkeyed] == stories[unkeyed_upper]
    assert len({stories[keyed], stories[unkeyed], stories[unkeyed_other]}) == 3
