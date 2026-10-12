"""Shared fixtures."""

import os

import asyncpg
import pytest
import pytest_asyncio

# A scratch PostgreSQL 16 with PostGIS, pgvector and the migrations applied,
# e.g. postgresql://postgres:test@localhost:55432/postgres. CI has none, so
# the tests that need it are skipped there.
_TEST_DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _no_surge_query_in_flight():
    """Every test starts and ends with no shared surge query pending, so one that
    fails mid-query can't leave the next a task tied to its closed event loop."""
    from app.routers import news

    news._surges_in_flight.clear()
    yield
    news._surges_in_flight.clear()


@pytest_asyncio.fixture
async def pg():
    """A connection to the scratch database, inside a transaction rolled back afterwards.

    Nothing a test writes is ever committed, and other sessions never see it.
    Skips the test when ORBIS_TEST_DATABASE_URL is not set, or the database
    lacks migration 012's articles.story_key.
    """
    if not _TEST_DATABASE_URL:
        pytest.skip("ORBIS_TEST_DATABASE_URL is not set")
    conn = await asyncpg.connect(_TEST_DATABASE_URL)
    has_story_key = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'articles' AND column_name = 'story_key')"
    )
    if not has_story_key:
        await conn.close()
        pytest.skip("articles.story_key is missing: apply migration 012")
    transaction = conn.transaction()
    await transaction.start()
    try:
        yield conn
    finally:
        await transaction.rollback()
        await conn.close()
