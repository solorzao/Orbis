"""The cache helpers (app.services.cache), Redis faked: several keys at once, entries
that no longer fit their model, single-flight computations, week-long entries' age."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.config import settings
from app.services import cache
from tests.fake_redis import FakeRedis as ClockRedis


class FakePipeline:
    """redis.asyncio's pipeline: commands are buffered, then sent by execute()."""

    def __init__(self, store: dict, fail: bool):
        self.store, self.fail, self.buffered = store, fail, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def set(self, key, value, ex=None):
        self.buffered.append((key, value, ex))
        return self

    async def execute(self):
        if self.fail:
            raise ConnectionError("down")
        for key, value, ex in self.buffered:
            self.store[key] = (value, ex)


class FakeRedis:
    def __init__(self, fail: bool = False):
        self.store: dict = {}
        self.fail = fail
        self.mget = AsyncMock(side_effect=self._mget)
        self.pipelines: list[FakePipeline] = []

    async def _mget(self, keys):
        if self.fail:
            raise ConnectionError("down")
        return [self.store[k][0] if k in self.store else None for k in keys]

    def pipeline(self, transaction=True):
        assert transaction is False  # plain batching, no MULTI
        pipe = FakePipeline(self.store, self.fail)
        self.pipelines.append(pipe)
        return pipe


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cache, "get_redis", AsyncMock(return_value=fake))
    return fake


class TestGetMany:
    @pytest.mark.asyncio
    async def test_values_in_the_keys_order_none_for_a_miss_in_one_round_trip(self, redis):
        redis.store = {"db:a": (json.dumps({"x": 1}), 60), "db:c": (json.dumps(None), 60)}

        values = await cache.get_many(["db:a", "db:b", "db:c"])

        # A cached JSON null reads as None too: wrap a value that may be null.
        assert values == [{"x": 1}, None, None]
        redis.mget.assert_awaited_once_with(["db:a", "db:b", "db:c"])

    @pytest.mark.asyncio
    async def test_no_keys_asks_nothing(self, redis):
        assert await cache.get_many([]) == []
        redis.mget.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_redis_every_key_misses(self, monkeypatch):
        monkeypatch.setattr(cache, "get_redis", AsyncMock(return_value=None))

        assert await cache.get_many(["db:a", "db:b"]) == [None, None]

    @pytest.mark.asyncio
    async def test_a_failed_read_misses_and_logs_no_key(self, redis, caplog):
        redis.fail = True

        with caplog.at_level(logging.WARNING, logger="app.services.cache"):
            assert await cache.get_many(["db:search:v1:zzsecret", "db:b"]) == [None, None]

        assert [r.getMessage() for r in caplog.records] == ["Redis MGET failed for 2 keys."]

    @pytest.mark.asyncio
    async def test_a_value_that_isnt_json_misses(self, redis):
        redis.store = {"db:a": ("{not json", 60)}

        assert await cache.get_many(["db:a"]) == [None]


class TestSetMany:
    @pytest.mark.asyncio
    async def test_every_value_is_written_with_the_ttl_in_one_round_trip(self, redis):
        await cache.set_many({"db:a": {"x": 1}, "db:b": [1, 2]}, 600)

        assert redis.store == {"db:a": ('{"x": 1}', 600), "db:b": ("[1, 2]", 600)}
        assert len(redis.pipelines) == 1

    @pytest.mark.asyncio
    async def test_nothing_to_write_asks_nothing(self, redis):
        await cache.set_many({}, 600)

        assert redis.pipelines == []

    @pytest.mark.asyncio
    async def test_without_redis_nothing_happens(self, monkeypatch):
        monkeypatch.setattr(cache, "get_redis", AsyncMock(return_value=None))

        await cache.set_many({"db:a": 1}, 600)  # no error

    @pytest.mark.asyncio
    async def test_a_failed_write_is_logged_without_keys_and_not_raised(self, redis, caplog):
        redis.fail = True

        with caplog.at_level(logging.WARNING, logger="app.services.cache"):
            await cache.set_many({"db:search:v1:zzsecret": 1}, 600)

        assert [r.getMessage() for r in caplog.records] == ["Redis SET of 1 keys failed."]


def test_the_fake_pipeline_matches_redis_py():
    """set() on redis.asyncio's pipeline buffers and returns the pipeline, unawaited
    (a client connects only when a command is sent)."""
    import redis.asyncio as aioredis

    pipe = aioredis.Redis().pipeline(transaction=False)
    assert pipe.set("k", "v", ex=1) is pipe
    assert len(pipe.command_stack) == 1


@pytest.fixture
def clock_redis():
    """Redis with a clock (tests/fake_redis.py), for the week-long entries."""
    fake = ClockRedis()
    with patch("app.services.cache.get_redis", AsyncMock(return_value=fake)):
        yield fake


class Story(BaseModel):
    title: str
    capped: bool  # a field the model gained after entries were cached without it


class TestCachedModel:
    def test_an_entry_that_fits_is_parsed(self):
        story = cache.cached_model("db:x", {"title": "t", "capped": True}, Story.model_validate)
        assert story == Story(title="t", capped=True)

    def test_an_entry_that_no_longer_fits_its_model_is_a_miss_logged_once(self, caplog):
        """A model gaining a required field must not 500 the entries cached before it."""
        with caplog.at_level(logging.WARNING, logger="app.services.cache"):
            parsed = cache.cached_model(
                "db:search:v1:abbas",
                [{"title": "a"}, {"title": "b"}],
                lambda rows: [Story.model_validate(r) for r in rows],
            )

        assert parsed is None
        [record] = caplog.records
        assert record.getMessage().startswith("Cached db:search:v1:abbas no longer fits its model")
        assert record.exc_info is None  # one line, no traceback

    def test_other_errors_are_not_a_miss(self):
        with pytest.raises(KeyError):
            cache.cached_model("db:x", {}, lambda entry: entry["missing"])


class TestSingleFlight:
    @pytest.mark.asyncio
    async def test_concurrent_callers_share_one_computation(self):
        calls = 0
        release = asyncio.Event()

        async def compute():
            nonlocal calls
            calls += 1
            await release.wait()
            return calls

        waiting = [asyncio.create_task(cache.single_flight("k", compute)) for _ in range(3)]
        await asyncio.sleep(0)
        release.set()

        assert await asyncio.gather(*waiting) == [1, 1, 1]
        assert calls == 1
        assert await cache.single_flight("k", compute) == 2  # landed: the next runs anew

    @pytest.mark.asyncio
    async def test_a_cancelled_caller_leaves_it_running_for_the_others(self):
        release = asyncio.Event()

        async def compute():
            await release.wait()
            return "done"

        first = asyncio.create_task(cache.single_flight("k", compute))
        second = asyncio.create_task(cache.single_flight("k", compute))
        await asyncio.sleep(0)
        first.cancel()  # a browser aborts its request
        release.set()

        assert await second == "done"
        with pytest.raises(asyncio.CancelledError):
            await first


class TestWeekFresh:
    @pytest.mark.asyncio
    async def test_a_week_entry_is_fresh_until_it_is_55_minutes_old(self, clock_redis):
        """Its age is its TTL's: written with WEEK_TTL, it is WEEK_TTL - TTL seconds old."""
        await cache.set_cached("wk:x", [1], cache.WEEK_TTL)
        assert await cache.week_fresh("wk:x")

        clock_redis.elapse(54 * 60)
        assert await cache.week_fresh("wk:x")
        clock_redis.elapse(2 * 60)
        assert not await cache.week_fresh("wk:x")  # 56 minutes old: the warm refreshes it
        assert await cache.get_cached("wk:x") == [1]  # still served meanwhile

    @pytest.mark.asyncio
    async def test_missing_or_short_lived_entries_are_never_fresh(self, clock_redis):
        assert not await cache.week_fresh("wk:none")
        await cache.set_cached("wk:empty", [], 60)  # an empty answer, cached briefly
        assert not await cache.week_fresh("wk:empty")

    @pytest.mark.asyncio
    async def test_without_redis_nothing_is_fresh(self):
        with patch("app.services.cache.get_redis", AsyncMock(return_value=None)):
            assert not await cache.week_fresh("wk:x")

    def test_an_hourly_refresh_lands_before_the_entry_expires(self):
        """Refreshed at the first warm once 55 minutes old, an entry has 25 minutes left:
        a cycle's interval (15) and the allowance for a cycle and its warm to run."""
        assert cache.WEEK_REFRESH_AGE == 55 * 60
        assert cache.WEEK_TTL == 80 * 60
        slack = cache.WEEK_TTL - cache.WEEK_REFRESH_AGE
        assert slack >= cache.cycle_ttl(0) > settings.ingestion_interval_seconds
