"""Migration 013 on a real PostgreSQL: threads and thread_members, and their cascades.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied, 013 included. Every test runs in a transaction that is
rolled back; its rows are titled ``zzthread-...``. Skipped without it.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

NOW = datetime(2001, 1, 10, tzinfo=timezone.utc)

THREAD_COLUMNS = {
    "id",
    "centroid_sum",
    "first_seen",
    "last_seen",
    "n_articles",
    "n_stories",
    "n_sources",
    "velocity",
    "countries",
    "places",
    "top_entities",
    "topic",
    "lead_article_id",
    "title",
    "synopsis",
    "summarized_at",
    "summarized_n",
    "created_at",
}
MEMBER_COLUMNS = {
    "article_id",
    "thread_id",
    "story_key",
    "source_name",
    "published_at",
    "latitude",
    "longitude",
    "region",
    "country_code",
    "topic",
    "entities",
    "tone",
    "similarity",
}


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    if not await connection.fetchval("SELECT to_regclass('threads') IS NOT NULL"):
        await connection.close()
        pytest.skip("threads is missing: apply migration 013")
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def _columns(conn, table: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table
    )
    return {r["column_name"] for r in rows}


async def _article(conn) -> uuid.UUID:
    return await conn.fetchval(
        "INSERT INTO articles (title, source_url, source_name, published_at, latitude, longitude,"
        " location) VALUES ($1, $2, 'zzthread.test', $3, 1, 2,"
        " ST_SetSRID(ST_MakePoint(2, 1), 4326)::geography) RETURNING id",
        f"zzthread-{uuid.uuid4()}",
        f"https://zzthread.test/{uuid.uuid4()}",
        NOW,
    )


async def _thread(conn) -> int:
    return await conn.fetchval(
        "INSERT INTO threads (centroid_sum, first_seen, last_seen)"
        " VALUES (array_fill(0.01, ARRAY[512])::vector, $1, $1) RETURNING id",
        NOW,
    )


async def _member(conn, article_id, thread_id) -> None:
    await conn.execute(
        "INSERT INTO thread_members (article_id, thread_id, published_at, latitude, longitude,"
        " similarity) VALUES ($1, $2, $3, 1, 2, 0.9)",
        article_id,
        thread_id,
        NOW,
    )


@pytest.mark.asyncio
async def test_both_tables_have_their_columns(conn):
    assert await _columns(conn, "threads") == THREAD_COLUMNS
    assert await _columns(conn, "thread_members") == MEMBER_COLUMNS


@pytest.mark.asyncio
async def test_deleting_an_article_removes_its_membership(conn):
    article, thread = await _article(conn), await _thread(conn)
    await _member(conn, article, thread)
    await conn.execute("DELETE FROM articles WHERE id = $1", article)
    members = "SELECT count(*) FROM thread_members WHERE thread_id = $1"
    assert await conn.fetchval(members, thread) == 0
    assert await conn.fetchval("SELECT count(*) FROM threads WHERE id = $1", thread) == 1


@pytest.mark.asyncio
async def test_deleting_a_thread_removes_its_members(conn):
    article, thread = await _article(conn), await _thread(conn)
    await _member(conn, article, thread)
    await conn.execute("DELETE FROM threads WHERE id = $1", thread)
    members = "SELECT count(*) FROM thread_members WHERE article_id = $1"
    assert await conn.fetchval(members, article) == 0
    assert await conn.fetchval("SELECT count(*) FROM articles WHERE id = $1", article) == 1


@pytest.mark.asyncio
async def test_a_thread_lead_is_cleared_when_its_article_goes(conn):
    article, thread = await _article(conn), await _thread(conn)
    await conn.execute("UPDATE threads SET lead_article_id = $1 WHERE id = $2", article, thread)
    await conn.execute("DELETE FROM articles WHERE id = $1", article)
    assert await conn.fetchval("SELECT lead_article_id FROM threads WHERE id = $1", thread) is None
