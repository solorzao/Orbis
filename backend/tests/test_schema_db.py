"""The migrated schema on a real PostgreSQL: extensions, and the article upsert.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (CI's Backend Checks job does; locally, the Docker one).
Every test runs in a transaction that is rolled back, so nothing it inserts is
ever committed; its rows are titled ``zzschema-...``. Skipped without it.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.services.database import _UPSERT_ARTICLE_SQL, _upsert_article_args

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

ARTICLE = {
    "title": "zzschema-Quake hits Kathmandu - Reuters",
    "source_url": "https://zzschema.example/quake",
    "source_name": "reuters.com",
    "published_at": datetime(2001, 1, 10, tzinfo=timezone.utc),
    "latitude": 27.7,
    "longitude": 85.3,
    "country_code": "NP",
    "region": "Kathmandu, Bagmati, Nepal",
    "topic_tags": ["environment"],
    "sentiment_score": -0.4,
    "entities": {"persons": ["A Person"]},
    "image_url": "https://zzschema.example/a.jpg",
    "country_fips": "NP",
    "themes": ["NATURAL_DISASTER_EARTHQUAKE"],
    "persons": ["a person"],
    "orgs": ["red cross"],
    "names": ["Kathmandu"],
    "counts": [{"type": "KILL", "number": 3}],
    "mentioned_countries": ["NP", "IN"],
}


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


@pytest.mark.asyncio
async def test_the_extensions_the_migrations_need_are_installed(conn):
    installed = {r["extname"] for r in await conn.fetch("SELECT extname FROM pg_extension")}
    assert {"postgis", "vector", "pg_trgm", "uuid-ossp"} <= installed


@pytest.mark.asyncio
async def test_the_upsert_takes_exactly_the_arguments_ingestion_builds(conn):
    """A column the code writes but no migration added fails here, not on production."""
    statement = await conn.prepare(_UPSERT_ARTICLE_SQL)
    assert len(statement.get_parameters()) == len(_upsert_article_args(ARTICLE))


@pytest.mark.asyncio
async def test_an_article_round_trips_and_a_recrawl_replaces_it(conn):
    await conn.execute(_UPSERT_ARTICLE_SQL, *_upsert_article_args(ARTICLE))
    recrawl = {**ARTICLE, "title": "zzschema-Quake toll rises - Reuters", "orgs": []}
    await conn.execute(_UPSERT_ARTICLE_SQL, *_upsert_article_args(recrawl))

    rows = await conn.fetch(
        "SELECT title, orgs, mentioned_countries, ST_Y(location::geometry) AS lat "
        "FROM articles WHERE source_url = $1",
        ARTICLE["source_url"],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "zzschema-Quake toll rises - Reuters"
    assert row["orgs"] == []
    assert row["mentioned_countries"] == ["NP", "IN"]
    assert row["lat"] == pytest.approx(27.7)
