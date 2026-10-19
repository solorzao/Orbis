"""Migration 013 on a real PostgreSQL: threads, thread_centroids and thread_members.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied, 013 included. Every test runs in a transaction that is
rolled back. Skipped without it.
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
    "id", "centroid_sum", "first_seen", "last_seen", "n_articles", "n_stories",
    "n_sources", "velocity", "countries", "places", "top_entities", "topic",
    "lead_article_id", "lead_title", "title", "synopsis", "summarized_at",
    "summarized_n", "aggregated_at", "created_at",
}  # fmt: skip
CENTROID_COLUMNS = {"thread_id", "last_seen", "n_stories", "centroid"}
MEMBER_COLUMNS = {
    "article_id", "thread_id", "story_key", "source_name", "published_at", "latitude",
    "longitude", "region", "country_code", "topic", "entities", "tone",
    "has_https_image", "similarity",
}  # fmt: skip


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    if not await connection.fetchval("SELECT to_regclass('thread_centroids') IS NOT NULL"):
        await connection.close()
        pytest.skip("thread tables are missing: apply migration 013")
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


async def _thread(conn) -> int:
    thread = await conn.fetchval(
        "INSERT INTO threads (centroid_sum, first_seen, last_seen)"
        " VALUES (array_fill(0.01, ARRAY[512])::vector, $1, $1) RETURNING id",
        NOW,
    )
    await conn.execute(
        "INSERT INTO thread_centroids (thread_id, last_seen, centroid)"
        " VALUES ($1, $2, l2_normalize(array_fill(0.01, ARRAY[512])::vector)::halfvec)",
        thread,
        NOW,
    )
    return thread


async def _member(conn, thread_id) -> uuid.UUID:
    article = uuid.uuid4()
    await conn.execute(
        "INSERT INTO thread_members (article_id, thread_id, published_at, latitude, longitude,"
        " entities, similarity) VALUES ($1, $2, $3, 1, 2, '{Jane Doe}', 0.9)",
        article,
        thread_id,
        NOW,
    )
    return article


@pytest.mark.asyncio
async def test_the_tables_have_their_columns(conn):
    assert await _columns(conn, "threads") == THREAD_COLUMNS
    assert await _columns(conn, "thread_centroids") == CENTROID_COLUMNS
    assert await _columns(conn, "thread_members") == MEMBER_COLUMNS


@pytest.mark.asyncio
async def test_nothing_references_articles(conn):
    """No FK to articles: the migration never locks it, and purges fire no triggers."""
    referencing = await conn.fetch(
        "SELECT conrelid::regclass::text AS t FROM pg_constraint"
        " WHERE contype = 'f' AND confrelid = 'articles'::regclass"
        " AND conrelid::regclass::text IN ('threads', 'thread_centroids', 'thread_members')"
    )
    assert referencing == []


@pytest.mark.asyncio
async def test_deleting_a_thread_removes_its_members_and_centroid(conn):
    thread = await _thread(conn)
    await _member(conn, thread)
    await conn.execute("DELETE FROM threads WHERE id = $1", thread)
    for table in ("thread_members", "thread_centroids"):
        left = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE thread_id = $1", thread)
        assert left == 0, table


@pytest.mark.asyncio
async def test_centroids_are_searched_by_inner_product(conn):
    """The HNSW index serves `ORDER BY centroid <#> $1`, the assignment's query."""
    await _thread(conn)
    await conn.execute("SET LOCAL enable_seqscan = off")
    plan = "\n".join(
        r[0]
        for r in await conn.fetch(
            "EXPLAIN SELECT thread_id FROM thread_centroids ORDER BY centroid <#>"
            " l2_normalize(array_fill(0.02, ARRAY[512])::vector)::halfvec LIMIT 5"
        )
    )
    assert "idx_thread_centroids_hnsw" in plan


@pytest.mark.asyncio
async def test_members_are_found_by_entity(conn):
    thread = await _thread(conn)
    article = await _member(conn, thread)
    await conn.execute("SET LOCAL enable_seqscan = off")
    found = await conn.fetchval(
        "SELECT article_id FROM thread_members WHERE entities @> ARRAY['Jane Doe']"
    )
    plan = "\n".join(
        r[0]
        for r in await conn.fetch(
            "EXPLAIN SELECT article_id FROM thread_members WHERE entities @> ARRAY['Jane Doe']"
        )
    )
    assert found == article
    assert "idx_thread_members_entities" in plan


@pytest.mark.asyncio
async def test_threads_leave_room_for_hot_updates(conn):
    options = await conn.fetchval("SELECT reloptions FROM pg_class WHERE relname = 'threads'")
    assert "fillfactor=80" in (options or [])


@pytest.mark.asyncio
async def test_centroids_stay_inline_and_are_vacuumed_early(conn):
    """PLAIN storage keeps the 1 KB centroid in the row (no TOAST fetch per comparison);
    joins and deactivations churn the index, so vacuum runs after 5% changes."""
    storage = await conn.fetchval(
        "SELECT attstorage FROM pg_attribute"
        " WHERE attrelid = 'thread_centroids'::regclass AND attname = 'centroid'"
    )
    options = await conn.fetchval(
        "SELECT reloptions FROM pg_class WHERE relname = 'thread_centroids'"
    )
    assert storage == "p"
    assert "autovacuum_vacuum_scale_factor=0.05" in (options or [])
