"""The threads read API (/api/threads, /api/threads/{id}), with the queries stubbed.

The SQL runs in tests/test_thread_reads_db.py against a real PostgreSQL.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.cache import cycle_ttl

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
EDGE = "public, s-maxage=60, stale-while-revalidate=300"

PLACE = {
    "lat": 48.85,
    "lng": 2.35,
    "place": "Paris, France",
    "country_code": "FR",
    "first_seen": datetime(2026, 10, 18, 6, tzinfo=timezone.utc),
    "n": 3,
}
LEAD = {
    "title": "Strikes spread across France",
    "source_name": "example.com",
    "published_at": datetime(2026, 10, 18, 11, tzinfo=timezone.utc),
    "image_url": "https://cdn.example.com/a.jpg",
    "topic": "economy",
    "sensitive": False,
}


def _item(n: int = 7) -> dict:
    return {
        "id": n,
        "title": "Strikes spread across France",
        "synopsis": None,
        "status": "developing",
        "first_seen": datetime(2026, 10, 18, 6, tzinfo=timezone.utc),
        "last_seen": datetime(2026, 10, 18, 11, tzinfo=timezone.utc),
        "n_stories": 9,
        "n_sources": 6,
        "velocity": 4,
        "countries": ["BE", "FR"],
        "places": [PLACE],
        "topic": "economy",
        "lead": LEAD,
    }


def _detail(n: int = 7) -> dict:
    return {
        **_item(n),
        "entities": [{"name": "CGT", "n": 5}],
        "spread": [PLACE],
        "timeline": [
            {"hour": datetime(2026, 10, 18, 6, tzinfo=timezone.utc), "n": 2, "tone": -3.5}
        ],
        "articles": [
            {
                "title": "Strikes spread across France",
                "source_name": "example.com",
                "published_at": datetime(2026, 10, 18, 11, tzinfo=timezone.utc),
                "source_url": "https://example.com/strikes",
                "place": "Paris, France",
            }
        ],
    }


def _json(value):
    """*value* as the API (and the cache) serialise it: datetimes as ISO strings."""
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json(v) for v in value]
    return value


@pytest.fixture
def reads(monkeypatch):
    """The two queries stubbed, the cache empty, the clock frozen."""
    import app.routers.threads as threads_router

    monkeypatch.setattr(threads_router, "_now", lambda: NOW)
    with (
        patch("app.routers.threads.list_threads", AsyncMock(return_value=[_item()])) as listing,
        patch("app.routers.threads.thread_detail", AsyncMock(return_value=_detail())) as detail,
        patch("app.routers.threads.get_cached", AsyncMock(return_value=None)) as get_cached,
        patch("app.routers.threads.set_cached", new_callable=AsyncMock) as set_cached,
    ):
        yield SimpleNamespace(
            listing=listing, detail=detail, get_cached=get_cached, set_cached=set_cached
        )


async def _get(monkeypatch, path, **params):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, params=params)


# --- /api/threads ---------------------------------------------------------------


class TestListThreads:
    @pytest.mark.asyncio
    async def test_lists_the_last_24_hours_top_20_by_default(self, monkeypatch, reads):
        resp = await _get(monkeypatch, "/api/threads")

        assert resp.status_code == 200
        assert resp.json() == [_json(_item())]
        reads.listing.assert_awaited_once_with(NOW, 24, None, 20)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("params", "args"),
        [
            ({"timespan": "1h"}, (1, None, 20)),
            ({"timespan": "6H"}, (6, None, 20)),
            ({"timespan": "168h", "limit": 50}, (168, None, 50)),
            ({"topic": "Climate", "limit": 1}, (24, "environment", 1)),
            ({"topic": "All"}, (24, None, 20)),
        ],
    )
    async def test_window_topic_and_limit(self, monkeypatch, reads, params, args):
        resp = await _get(monkeypatch, "/api/threads", **params)

        assert resp.status_code == 200
        reads.listing.assert_awaited_once_with(NOW, *args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"timespan": "48h"},
            {"timespan": "day"},
            {"limit": 0},
            {"limit": 51},
            {"topic": "Sport"},
        ],
    )
    async def test_anything_else_is_a_422(self, monkeypatch, reads, params):
        resp = await _get(monkeypatch, "/api/threads", **params)

        assert resp.status_code == 422
        reads.listing.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_cached_list_that_no_longer_fits_the_model_is_recomputed(
        self, monkeypatch, reads
    ):
        """An entry cached before the model gained a required field is a miss, not a 500."""
        reads.get_cached.return_value = [{"id": 7, "title": "Strikes"}]

        resp = await _get(monkeypatch, "/api/threads")

        assert resp.status_code == 200
        assert resp.json() == [_json(_item())]
        reads.listing.assert_awaited_once()
        reads.set_cached.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_the_answer_is_cached_until_the_next_cycle(self, monkeypatch, reads):
        await _get(monkeypatch, "/api/threads", timespan="6h", topic="Climate", limit=5)

        reads.get_cached.assert_awaited_once_with("db:threads:list:v1:6h:environment:5")
        reads.set_cached.assert_awaited_once_with(
            "db:threads:list:v1:6h:environment:5", [_json(_item())], cycle_ttl(300)
        )

    @pytest.mark.asyncio
    async def test_no_threads_is_cached_too(self, monkeypatch, reads):
        reads.listing.return_value = []

        resp = await _get(monkeypatch, "/api/threads")

        assert resp.json() == []
        reads.set_cached.assert_awaited_once_with("db:threads:list:v1:24h::20", [], cycle_ttl(300))

    @pytest.mark.asyncio
    async def test_a_cached_answer_is_served_without_the_database(self, monkeypatch, reads):
        reads.get_cached.return_value = [_json(_item(9))]

        resp = await _get(monkeypatch, "/api/threads")

        assert resp.json() == [_json(_item(9))]
        reads.listing.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_is_edge_cached(self, monkeypatch, reads):
        resp = await _get(monkeypatch, "/api/threads")

        assert resp.headers["cache-control"] == EDGE

    @pytest.mark.asyncio
    async def test_a_database_error_is_a_500_and_nothing_is_cached(self, monkeypatch, reads):
        reads.listing.side_effect = RuntimeError("connection reset")

        resp = await _get(monkeypatch, "/api/threads")

        assert resp.status_code == 500
        assert "s-maxage" not in resp.headers.get("cache-control", "")
        reads.set_cached.assert_not_awaited()

    def test_is_in_the_data_rate_limit_group(self):
        from app.middleware.security import _get_rate_group

        assert _get_rate_group("/api/threads") == "data"
        assert _get_rate_group("/api/threads/7") == "data"

    @pytest.mark.asyncio
    async def test_the_warmer_caches_what_the_first_request_would(self, monkeypatch, reads):
        import app.routers.threads as threads_router

        await _get(monkeypatch, "/api/threads")
        requested = reads.set_cached.await_args
        reads.set_cached.reset_mock()
        await threads_router.warm_threads()

        assert reads.set_cached.await_args == requested


class TestListSingleFlight:
    @pytest.mark.asyncio
    async def test_two_concurrent_misses_run_the_query_once(self, reads):
        import app.routers.threads as threads_router

        release = asyncio.Event()

        async def slow(*_args):
            await release.wait()
            return [_item()]

        reads.listing.side_effect = slow
        first = asyncio.create_task(threads_router.cached_threads(24, None, 20))
        second = asyncio.create_task(threads_router.cached_threads(24, None, 20))
        await asyncio.sleep(0)
        release.set()
        a, b = await asyncio.gather(first, second)

        assert a == b
        assert reads.listing.await_count == 1
        assert reads.set_cached.await_count == 1
        assert threads_router._list_in_flight == {}

    @pytest.mark.asyncio
    async def test_an_error_reaches_every_waiter_and_nothing_is_cached(self, reads):
        import app.routers.threads as threads_router

        release = asyncio.Event()

        async def failing(*_args):
            await release.wait()
            raise RuntimeError("connection reset")

        reads.listing.side_effect = failing
        waiters = [
            asyncio.create_task(threads_router.cached_threads(24, None, 20)) for _ in range(2)
        ]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*waiters, return_exceptions=True)

        assert [type(r) for r in results] == [RuntimeError, RuntimeError]
        assert reads.listing.await_count == 1
        reads.set_cached.assert_not_awaited()
        assert threads_router._list_in_flight == {}

    @pytest.mark.asyncio
    async def test_different_keys_run_their_own_queries(self, reads):
        import app.routers.threads as threads_router

        await asyncio.gather(
            threads_router.cached_threads(24, None, 20),
            threads_router.cached_threads(6, None, 20),
        )

        assert reads.listing.await_count == 2


# --- /api/threads/{id} ------------------------------------------------------------


class TestThreadDetail:
    @pytest.mark.asyncio
    async def test_returns_the_thread_with_its_people_spread_and_stories(self, monkeypatch, reads):
        resp = await _get(monkeypatch, "/api/threads/7")

        assert resp.status_code == 200
        assert resp.json() == _json(_detail())
        reads.detail.assert_awaited_once_with(7, 0, NOW)

    @pytest.mark.asyncio
    async def test_pages_its_stories(self, monkeypatch, reads):
        await _get(monkeypatch, "/api/threads/7", offset=20)

        reads.detail.assert_awaited_once_with(7, 20, NOW)
        reads.set_cached.assert_awaited_once_with(
            "db:threads:detail:v1:7:20", _json(_detail()), cycle_ttl(300)
        )

    @pytest.mark.asyncio
    async def test_an_unknown_thread_is_a_404_and_nothing_is_cached(self, monkeypatch, reads):
        reads.detail.return_value = None

        resp = await _get(monkeypatch, "/api/threads/404")

        assert resp.status_code == 404
        assert "s-maxage" not in resp.headers.get("cache-control", "")
        reads.set_cached.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("path", "params"),
        [
            ("/api/threads/0", {}),
            ("/api/threads/abc", {}),
            ("/api/threads/99999999999999999999", {}),
            ("/api/threads/7", {"offset": -1}),
            ("/api/threads/7", {"offset": 1001}),
        ],
    )
    async def test_a_bad_id_or_offset_is_a_422(self, monkeypatch, reads, path, params):
        resp = await _get(monkeypatch, path, **params)

        assert resp.status_code == 422
        reads.detail.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_cached_thread_is_served_without_the_database(self, monkeypatch, reads):
        reads.get_cached.return_value = _json(_detail(8))

        resp = await _get(monkeypatch, "/api/threads/8")

        assert resp.json() == _json(_detail(8))
        reads.get_cached.assert_awaited_once_with("db:threads:detail:v1:8:0")
        reads.detail.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_is_edge_cached(self, monkeypatch, reads):
        resp = await _get(monkeypatch, "/api/threads/7")

        assert resp.headers["cache-control"] == EDGE

    @pytest.mark.asyncio
    async def test_a_database_error_is_a_500_and_nothing_is_cached(self, monkeypatch, reads):
        reads.detail.side_effect = RuntimeError("connection reset")

        resp = await _get(monkeypatch, "/api/threads/7")

        assert resp.status_code == 500
        reads.set_cached.assert_not_awaited()
