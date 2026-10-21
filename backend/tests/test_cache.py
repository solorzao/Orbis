"""Reading and writing several cache keys at once (app.services.cache), Redis faked."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

import pytest

from app.services import cache


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
