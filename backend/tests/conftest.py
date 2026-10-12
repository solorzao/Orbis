"""Shared fixtures."""

import os

import asyncpg
import pytest
import pytest_asyncio

# A scratch PostgreSQL 16 with PostGIS, pgvector and the migrations applied,
# e.g. postgresql://postgres:test@localhost:55432/postgres. CI has none, so
# the tests that need it are skipped there.
_TEST_DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def pg():
    """A connection to the scratch database, inside a transaction rolled back afterwards.

    Nothing a test writes is ever committed, and other sessions never see it.
    Skips the test when ORBIS_TEST_DATABASE_URL is not set.
    """
    if not _TEST_DATABASE_URL:
        pytest.skip("ORBIS_TEST_DATABASE_URL is not set")
    conn = await asyncpg.connect(_TEST_DATABASE_URL)
    transaction = conn.transaction()
    await transaction.start()
    try:
        yield conn
    finally:
        await transaction.rollback()
        await conn.close()
