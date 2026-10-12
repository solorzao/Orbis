"""Tests for the /api/links endpoints (database, Redis and Claude mocked)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.http_cache import EDGE_CACHE_CONTROL
from app.services.links import TOPIC_TAGS

NOW = datetime(2026, 10, 12, 15, 37, tzinfo=timezone.utc)


def _pair(a="IR", b="US", n=10, **extra) -> dict:
    row = {"a": a, "b": b, "n": n, "n_a": 20, "n_b": 50, "total": 100, "tone": -0.3}
    row.update({"from_iso": "US", **{tag: 0 for tag in TOPIC_TAGS}, **extra})
    return row


def _client(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _no_cache_and_a_fixed_now(monkeypatch):
    from app.routers import links

    monkeypatch.setattr(links, "_now", lambda: NOW)
    with (
        patch("app.routers.links.get_cached", new_callable=AsyncMock, return_value=None),
        patch("app.routers.links.set_cached", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture
def db():
    with patch(
        "app.routers.links.get_link_pairs", new_callable=AsyncMock, return_value=[_pair()]
    ) as mock:
        yield mock


class TestGetLinks:
    @pytest.mark.asyncio
    async def test_returns_links_with_from_and_label_points(self, monkeypatch, db):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/links", params={"rank": "count"})

        assert resp.status_code == 200
        [link] = resp.json()
        assert link["a"] == {"iso": "IR", "name": "Iran", "lat": 32.52, "lng": 54.29}
        assert link["b"]["iso"] == "US"
        assert link["from"] == "US"
        assert (link["n"], link["lift"], link["tone"], link["topic"]) == (10, 1.0, -0.3, "general")

    @pytest.mark.asyncio
    async def test_live_window_is_the_last_hours_up_to_now(self, monkeypatch, db):
        async with _client(monkeypatch) as client:
            await client.get("/api/links", params={"timespan": "168h", "topic": "Climate"})

        db.assert_awaited_once_with(NOW - timedelta(hours=168), NOW, "environment")

    @pytest.mark.asyncio
    async def test_range_window(self, monkeypatch, db):
        params = {"start_time": "2026-10-10T08:15:00Z", "end_time": "2026-10-11T08:15:00Z"}
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/links", params=params)

        assert resp.status_code == 200
        db.assert_awaited_once_with(
            datetime(2026, 10, 10, 8, 15, tzinfo=timezone.utc),
            datetime(2026, 10, 11, 8, 15, tzinfo=timezone.utc),
            None,
        )

    @pytest.mark.asyncio
    async def test_ranks_by_lift_by_default(self, monkeypatch, db):
        db.return_value = [_pair(n=4), _pair("CN", "RU", n=5)]
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/links")
        assert [link["n"] for link in resp.json()] == [5]  # lift needs 5 stories

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"topic": "Sports"},
            {"rank": "surprise"},
            {"limit": 0},
            {"limit": 61},
            {"timespan": "48h"},
            {"timespan": "soon"},
            {"start_time": "2026-10-10T08:00:00Z"},
            {"start_time": "2026-10-10T08:00:00Z", "end_time": "yesterday"},
            {"start_time": "2026-10-11T08:00:00Z", "end_time": "2026-10-10T08:00:00Z"},
            {"start_time": "2026-10-01T08:00:00Z", "end_time": "2026-10-10T08:00:00Z"},
        ],
    )
    async def test_invalid_parameters_are_422(self, monkeypatch, db, params):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/links", params=params)

        assert resp.status_code == 422
        assert "cache-control" not in resp.headers
        db.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_edge_may_cache_an_answer(self, monkeypatch, db):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/links")
        assert resp.headers["cache-control"] == EDGE_CACHE_CONTROL

    @pytest.mark.asyncio
    async def test_cached_for_ten_minutes_by_window_topic_rank_and_limit(self, monkeypatch, db):
        with patch("app.routers.links.set_cached", new_callable=AsyncMock) as mock_set:
            async with _client(monkeypatch) as client:
                await client.get("/api/links", params={"topic": "Politics", "rank": "count"})
                await client.get(
                    "/api/links",
                    params={
                        "start_time": "2026-10-10T08:15:00Z",
                        "end_time": "2026-10-11T08:59:00Z",
                        "limit": 12,
                    },
                )

        (key1, value1, ttl1), (key2, _, _) = [c.args for c in mock_set.await_args_list]
        assert key1 == "db:links:v1:live:24:politics:count:40"
        assert ttl1 == 600
        assert value1[0]["from"] == "US"
        assert key2 == "db:links:v1:2026101008-2026101108::lift:12"

    @pytest.mark.asyncio
    async def test_an_empty_answer_is_cached_for_a_minute(self, monkeypatch, db):
        db.return_value = []
        with patch("app.routers.links.set_cached", new_callable=AsyncMock) as mock_set:
            async with _client(monkeypatch) as client:
                resp = await client.get("/api/links")
        assert resp.json() == []
        assert mock_set.await_args.args[1:] == ([], 60)

    @pytest.mark.asyncio
    async def test_serves_the_cached_answer(self, monkeypatch, db):
        cached = [
            {
                "a": {"iso": "IR", "name": "Iran", "lat": 32.52, "lng": 54.29},
                "b": {"iso": "US", "name": "United States", "lat": 39.5, "lng": -99.06},
                "n": 7,
                "lift": 2.5,
                "topic": "conflict",
                "tone": -0.4,
                "from": "IR",
            }
        ]
        with patch("app.routers.links.get_cached", new_callable=AsyncMock, return_value=cached):
            async with _client(monkeypatch) as client:
                resp = await client.get("/api/links")
        assert resp.json() == cached
        db.assert_not_awaited()
