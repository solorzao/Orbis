"""Tests for the one-off purge of stale re-crawls already stored (no database)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from scripts.purge_stale_recrawls import purge, select_stale

_PUBLISHED = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)

_STALE_URLS = [
    "https://www.newsbusters.org/blogs/nb/ken-shepherd/2005/07/11/moderate-muslims-condemn",
    "https://example.com/news/2020-08-04-tropical-storm-isaias",
    "https://example.com/2026/10/04/eight-days-before",
]
_KEPT_URLS = [
    "https://example.com/2026/10/05/seven-days-before",
    "https://example.com/2026/10/12/same-day",
    "https://example.com/news/no-date-here",
    "https://example.com/news?d=2005-07-11",  # query string, not path
    "https://example.com/story/200507111234",  # a numeric ID
]


def _rows(urls: list[str]) -> list[dict]:
    return [{"id": n, "source_url": u, "published_at": _PUBLISHED} for n, u in enumerate(urls)]


def test_selects_articles_whose_url_date_is_over_7_days_before_published_at():
    stale = select_stale(_rows(_STALE_URLS + _KEPT_URLS))
    assert [r["source_url"] for r in stale] == _STALE_URLS


def test_selects_nothing_when_no_url_is_old():
    assert select_stale(_rows(_KEPT_URLS)) == []


def _conn(urls: list[str]) -> AsyncMock:
    conn = AsyncMock()
    conn.fetch.return_value = _rows(urls)
    conn.execute.return_value = "DELETE 3"
    return conn


@pytest.mark.asyncio
async def test_without_yes_it_only_counts(capsys):
    conn = _conn(_STALE_URLS + _KEPT_URLS)

    assert await purge(conn, delete=False) == 3

    conn.execute.assert_not_awaited()
    out = capsys.readouterr().out
    assert "3 stale re-crawls" in out
    assert "--yes" in out


@pytest.mark.asyncio
async def test_with_yes_it_deletes_the_selected_ids_only():
    conn = _conn(_STALE_URLS + _KEPT_URLS)

    assert await purge(conn, delete=True) == 3

    conn.execute.assert_awaited_once()
    assert conn.execute.call_args.args[1] == [0, 1, 2]
