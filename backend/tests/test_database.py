"""Tests for the article upsert in app.services.database."""

import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.database import upsert_articles


def _mock_pool():
    conn = MagicMock()
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def _transaction():
        yield

    @asynccontextmanager
    async def _acquire():
        yield conn

    conn.transaction = _transaction
    pool = MagicMock()
    pool.acquire = _acquire
    return pool, conn


@pytest.mark.asyncio
async def test_upsert_writes_country_fips_and_never_null():
    pool, conn = _mock_pool()
    articles = [
        {"source_url": "https://example.com/a", "country_code": "GB", "country_fips": "UK"},
        {"source_url": "https://example.com/b", "country_code": ""},  # no country_fips key
        {"source_url": "https://example.com/c", "country_code": "", "country_fips": None},
    ]

    with patch("app.services.database.get_pool", new_callable=AsyncMock, return_value=pool):
        assert await upsert_articles(articles) == 3

    sql, *args = conn.execute.await_args_list[0].args
    assert "country_fips = EXCLUDED.country_fips" in sql
    # Every placeholder has an argument and vice versa.
    assert max(int(n) for n in re.findall(r"\$(\d+)", sql)) == len(args)

    fips_values = [call.args[-1] for call in conn.execute.await_args_list]
    assert fips_values == ["UK", "", ""]
