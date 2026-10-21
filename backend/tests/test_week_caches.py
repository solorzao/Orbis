"""The week-long caches: the 7-day globe (All and each topic) and the 7-day links list.

Each refresh reads a week of stories, so they live under wk:*, outside the db:*
a cycle invalidates, and app.warm refreshes them hourly rather than each cycle.
Redis is faked (with a clock); the queries are stubbed.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.http_cache import EDGE_CACHE_CONTROL
from app.services.cache import WEEK_TTL, invalidate
from app.services.links import TOPIC_TAGS
from tests.fake_redis import FakeRedis

# The topic pills as the frontend sends them (All: no topic), and their article tags.
PILLS = [
    (None, None),
    ("Politics", "politics"),
    ("Conflict", "conflict"),
    ("Technology", "technology"),
    ("Climate", "environment"),
    ("Economy", "economy"),
    ("Health", "health"),
]
WEEK_GLOBE_KEYS = [f"wk:globe:v2:168::500:{tag or ''}" for _, tag in PILLS]
# Health's week is empty in these tests: cached a minute only.
FULL_WEEK_KEYS = [key for key in WEEK_GLOBE_KEYS if not key.endswith(":health")]
WEEK_LINKS_KEY = "wk:links:v5:live:168::lift:40"
CYCLE = 15 * 60


def _point(lat: float, topic: str) -> dict:
    """A get_globe_points row: a cell's dot with its hover card's data."""
    return {
        "lat": lat,
        "lng": 2.5,
        "weight": 30,
        "article_count": 3,
        "top_headline": "Talks resume",
        "topic": topic,
        "location_name": "Paris, France",
        "country_code": "FR",
        "lead": {
            "title": "Talks resume",
            "source_name": "Reuters",
            "published_at": "2026-10-21T09:45:00Z",
            "image_url": "https://cdn.example.com/a.jpg",
            "topic": topic,
            "sensitive": False,
        },
        "topic_mix": {"politics": 3},
        "tone": -0.25,
    }


def _variants() -> dict:
    """get_globe_points_by_topic's answer: each pill's cells (Health has none)."""
    globes = {tag: [_point(10.5 + i, tag or "politics")] for i, (_, tag) in enumerate(PILLS)}
    globes["health"] = []
    return globes


def _pair() -> dict:
    """A get_link_pairs row: Iran and the US."""
    row = {"a": "IR", "b": "US", "n": 10, "n_a": 20, "n_b": 50, "total": 100, "outlets": 4}
    row.update({"tone": -0.3, "top_exclusive_stories": 2, "from_iso": "US"})
    return {**row, **{tag: 0 for tag in TOPIC_TAGS}}


@pytest.fixture
def redis():
    fake = FakeRedis()
    with (
        patch("app.services.cache.get_redis", AsyncMock(return_value=fake)),
        patch("app.warm.get_redis", AsyncMock(return_value=fake)),
    ):
        yield fake


@pytest.fixture
def week():
    """The week's queries stubbed; get_globe_points (one topic at a time) for other windows."""
    with (
        patch(
            "app.routers.news.get_globe_points_by_topic",
            new_callable=AsyncMock,
            return_value=_variants(),
        ) as globes,
        patch(
            "app.routers.news.get_globe_points",
            new_callable=AsyncMock,
            return_value=[_point(40.5, "economy")],
        ) as one_topic,
        patch(
            "app.routers.links.get_link_pairs", new_callable=AsyncMock, return_value=[_pair()]
        ) as links,
    ):
        yield type("Week", (), {"globes": globes, "one_topic": one_topic, "links": links})


async def _warm_week():
    from app.routers.links import warm_links_7d
    from app.routers.news import warm_globe_week

    await warm_globe_week()
    await warm_links_7d()


def _client(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


class TestHourlyWarm:
    @pytest.mark.asyncio
    async def test_a_day_of_cycles_reads_the_week_hourly_not_every_cycle(self, redis, week):
        """96 cycles a day each read the week twice (192 reads); now one cycle an hour
        refreshes each, and no entry with stories is ever missing between refreshes."""
        for _ in range(96):  # a day of 15-minute cycles, each ending in an invalidation
            await invalidate("db:*")
            await _warm_week()
            assert all(key in redis.values for key in [*FULL_WEEK_KEYS, WEEK_LINKS_KEY])
            redis.elapse(CYCLE)

        # Refreshed once 55 minutes old: every fourth cycle (at 0, 60, 120 ... minutes).
        assert week.globes.await_count == week.links.await_count == 24
        week.one_topic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_fresh_entry_is_skipped_and_a_stale_one_refreshed(self, redis, week):
        await _warm_week()
        assert redis.ttls[WEEK_LINKS_KEY] == redis.ttls[WEEK_GLOBE_KEYS[0]] == WEEK_TTL

        redis.elapse(54 * 60)
        await _warm_week()
        assert week.globes.await_count == week.links.await_count == 1  # fresh: skipped

        redis.elapse(2 * 60)  # 56 minutes old
        await _warm_week()
        assert week.globes.await_count == week.links.await_count == 2
        assert redis.ttls[WEEK_LINKS_KEY] == redis.ttls[WEEK_GLOBE_KEYS[0]] == WEEK_TTL

    @pytest.mark.asyncio
    async def test_cycle_invalidation_leaves_the_week_entries(self, redis, week):
        from app.routers.news import warm_globe

        await warm_globe()  # the 24-hour globe: db:*, refilled each cycle
        await _warm_week()
        await invalidate("db:*")  # as each ingestion cycle ends

        assert not any(key.startswith("db:") for key in redis.values)
        assert all(key in redis.values for key in [*WEEK_GLOBE_KEYS, WEEK_LINKS_KEY])

    @pytest.mark.asyncio
    async def test_an_empty_week_is_cached_a_minute_and_refreshed_by_the_next_warm(
        self, redis, week
    ):
        """As any empty answer: new stories show soon. So it is never fresh."""
        from app.routers.links import warm_links_7d

        week.links.return_value = []
        await warm_links_7d()
        assert json.loads(redis.values[WEEK_LINKS_KEY]) == []
        assert redis.ttls[WEEK_LINKS_KEY] == 60

        await warm_links_7d()
        assert week.links.await_count == 2

    @pytest.mark.asyncio
    async def test_each_globe_variant_is_stored_as_its_request_reads_it(self, redis, week):
        """Under the request's key, as the request's bytes, for the week's TTL; an empty
        topic only a minute, as any empty globe."""
        from app.models.news import GlobeDataPoint
        from app.routers.news import warm_globe_week

        await warm_globe_week()

        week.globes.assert_awaited_once_with(timespan_hours=168, cell_size=1.0, limit=500)
        variants = _variants()
        for key, (_, tag) in zip(WEEK_GLOBE_KEYS, PILLS):
            dumped = [GlobeDataPoint(**r).model_dump(mode="json") for r in variants[tag]]
            assert json.loads(redis.values[key]) == dumped, key
        assert redis.ttls[WEEK_GLOBE_KEYS[0]] == WEEK_TTL
        assert json.loads(redis.values["wk:globe:v2:168::500:health"]) == []
        assert redis.ttls["wk:globe:v2:168::500:health"] == 60


def _blocking(mock: AsyncMock) -> tuple[asyncio.Event, asyncio.Event]:
    """Make *mock* wait until cancelled: events for its start and its cancellation."""
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def wait(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    mock.side_effect = wait
    return started, cancelled


class TestStopping:
    """A week read must end with the warm that started it: never run on, untracked, into
    the next cycle's writes (shield keeps a request's from its cancellation)."""

    @pytest.mark.asyncio
    async def test_a_timed_out_week_refresh_is_cancelled(self, redis, week):
        from app import warm
        from app.routers.news import warm_globe_week
        from app.services import cache

        started, cancelled = _blocking(week.globes)

        await warm.warm_caches((warm_globe_week,), timeout=0.05, timeouts={})

        assert started.is_set()
        await asyncio.wait_for(cancelled.wait(), 1)
        await asyncio.sleep(0)
        assert not cache._in_flight

    @pytest.mark.asyncio
    async def test_a_stopped_week_refresh_is_cancelled_and_one_a_request_started(self, redis, week):
        """At a cycle's start or at shutdown (stop_background_tasks): the warm's week read,
        and a request's cold miss of the other (that request gets an error)."""
        from app.routers.links import warm_links_7d
        from app.routers.news import cached_globe
        from app.services import cache, ingestion

        links_started, links_cancelled = _blocking(week.links)
        globe_started, globe_cancelled = _blocking(week.globes)
        request = asyncio.create_task(cached_globe(168, None, None, 500, "politics"))
        with patch("app.warm.warm_caches", lambda: warm_links_7d()):
            ingestion._start_cache_warm()
            await asyncio.wait_for(links_started.wait(), 1)
            await asyncio.wait_for(globe_started.wait(), 1)

            await ingestion.stop_background_tasks()

        assert links_cancelled.is_set() and globe_cancelled.is_set()
        with pytest.raises(RuntimeError, match="cancelled"):
            await request
        await asyncio.sleep(0)
        assert not cache._in_flight
        assert not ingestion._background_tasks


class TestReads:
    @pytest.mark.asyncio
    async def test_requests_read_the_week_entries(self, monkeypatch, redis, week):
        await _warm_week()

        async with _client(monkeypatch) as client:
            for pill, tag in PILLS:
                params = {"timespan": "168h", "limit": 500, **({"topic": pill} if pill else {})}
                resp = await client.get("/api/news", params=params)
                assert resp.status_code == 200
                assert [p["lat"] for p in resp.json()] == [r["lat"] for r in _variants()[tag]]
                # The edge keeps it a minute (five more while it refetches): with an
                # hourly refresh, at most six minutes on top of the entry's age.
                assert resp.headers["cache-control"] == EDGE_CACHE_CONTROL
            links = await client.get("/api/links", params={"timespan": "168h"})
            assert [(link["a"]["iso"], link["b"]["iso"]) for link in links.json()] == [("IR", "US")]
            assert links.headers["cache-control"] == EDGE_CACHE_CONTROL

        assert week.globes.await_count == week.links.await_count == 1  # the warm's only
        week.one_topic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_other_windows_stay_under_db(self, monkeypatch, redis, week):
        async with _client(monkeypatch) as client:
            await client.get("/api/news", params={"timespan": "24h", "limit": 500})
            await client.get("/api/links", params={"timespan": "24h"})

        assert set(redis.values) == {"db:globe:v2:24::500:", "db:links:v5:live:24::lift:40"}

    @pytest.mark.asyncio
    async def test_the_boards_co_coverage_finds_the_hourly_entry(self, redis, week):
        from app.routers.links import cached_links_7d, warm_links_7d

        assert await cached_links_7d() is None  # never computed there
        await warm_links_7d()
        await invalidate("db:*")
        redis.elapse(50 * 60)  # three cycles on, none of which refreshed it

        [link] = await cached_links_7d()
        assert (link.a.iso, link.b.iso) == ("IR", "US")
        assert week.links.await_count == 1

    @pytest.mark.asyncio
    async def test_a_cold_7_day_globe_miss_runs_one_pass_for_every_topic(
        self, monkeypatch, redis, week
    ):
        """Concurrent misses (topics clicked through) share one pass, which stores all
        seven: the warm then finds them fresh."""
        release = asyncio.Event()

        async def slow(**_kwargs):
            await release.wait()
            return _variants()

        week.globes.side_effect = slow
        async with _client(monkeypatch) as client:
            requests = [
                asyncio.create_task(
                    client.get("/api/news", params={"timespan": "168h", "topic": pill})
                )
                for pill in ("Politics", "Conflict", "Economy")
            ]
            await asyncio.sleep(0.05)
            release.set()
            answers = await asyncio.gather(*requests)

        assert [len(a.json()) for a in answers] == [1, 1, 1]
        assert week.globes.await_count == 1
        assert all(key in redis.values for key in WEEK_GLOBE_KEYS)
        from app.routers.news import warm_globe_week

        await warm_globe_week()
        assert week.globes.await_count == 1  # fresh

    @pytest.mark.asyncio
    async def test_a_cold_7_day_links_miss_is_computed_once(self, monkeypatch, redis, week):
        release = asyncio.Event()

        async def slow(*_args):
            await release.wait()
            return [_pair()]

        week.links.side_effect = slow
        async with _client(monkeypatch) as client:
            requests = [
                asyncio.create_task(client.get("/api/links", params={"timespan": "168h"}))
                for _ in range(3)
            ]
            await asyncio.sleep(0.05)
            release.set()
            answers = await asyncio.gather(*requests)

        assert [a.status_code for a in answers] == [200, 200, 200]
        assert week.links.await_count == 1
        assert redis.ttls[WEEK_LINKS_KEY] == WEEK_TTL

    @pytest.mark.asyncio
    async def test_another_7_day_globe_limit_is_its_own_week_entry(self, monkeypatch, redis, week):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/news", params={"timespan": "168h", "limit": 100})

        assert resp.status_code == 200
        week.one_topic.assert_awaited_once()
        assert week.one_topic.await_args.kwargs["timespan_hours"] == 168
        assert redis.ttls["wk:globe:v2:168::100:"] == WEEK_TTL
