"""Tests for the /api/relations endpoints (the pool and Redis faked).

Every answer is the 7-day lens (the last 7 UTC days), whatever window a request
sends, cached under db:* (relations.CACHE_PREFIX), which ingestion clears as soon
as a cycle's events land and again as the cycle ends, so the list and every detail
refresh together.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.http_cache import EDGE_CACHE_CONTROL
from app.services import relations
from app.services.cache import WEEK_TTL, cycle_ttl, invalidate
from tests.fake_redis import FakeRedis

NOW = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)
FIRST, LAST = date(2026, 10, 15), date(2026, 10, 21)
LIST_KEY = "db:relations:v1:20261015-20261021:all:40"
DETAIL_KEY = "db:relations:detail:v1:IR:US:20261015-20261021"
NOT_FOUND = {"detail": "No reported events between them in the last 7 days."}
QUAD_KEYS = {"verbal_cooperation", "material_cooperation", "verbal_conflict", "material_conflict"}


def _pair(
    a="IR", b="US", n=20, q=(2, 1, 12, 5), from_a=5, mentions=300, outlets=4, goldstein=-2.0
) -> dict:
    """A LIST_SQL row: a pair over the lens."""
    return {
        "a": a,
        "b": b,
        "n": n,
        "mentions": mentions,
        "goldstein": goldstein,
        "tone": -3.0,
        "q1": q[0],
        "q2": q[1],
        "q3": q[2],
        "q4": q[3],
        "from_a": from_a,
        "outlets": outlets,
    }


def _rollup(a: str, b: str, day: date, quad: int, n: int, urls=(), outlets=()) -> dict:
    """A DETAIL_SQL row: one direction's day and class."""
    return {
        "a_iso": a,
        "b_iso": b,
        "day": day,
        "quad_class": quad,
        "n_events": n,
        "mentions": 10 * n,
        "goldstein_sum": -2.0 * n,
        "tone_sum": -1.0 * n,
        "sample_urls": list(urls),
        "outlets": list(outlets),
    }


class FakePool:
    """The pool as app.services.relations reads it: each statement's rows, and every call."""

    def __init__(self) -> None:
        self.pairs = [_pair()]
        self.since: date | None = FIRST
        self.detail = [
            _rollup("US", "IR", LAST, 3, 4, ["https://a.test/1"], ["a.test"]),
            _rollup("IR", "US", date(2026, 10, 20), 1, 1, ["https://b.test/2"], ["b.test"]),
        ]
        self.titles: list[dict] = []
        self.calls: list[tuple[str, tuple]] = []
        self.gate: asyncio.Event | None = None  # when set, the list waits for it
        self.detail_gate: asyncio.Event | None = None  # when set, the detail waits for it

    async def fetch(self, sql: str, *args):
        self.calls.append((sql, args))
        if sql == relations.LIST_SQL:
            if self.gate is not None:
                await self.gate.wait()
            return self.pairs
        if sql == relations.DETAIL_SQL:
            if self.detail_gate is not None:
                await self.detail_gate.wait()
            return self.detail
        if sql == relations.TITLES_SQL:
            return self.titles
        raise AssertionError(f"unexpected statement: {sql}")

    async def fetchval(self, sql: str, *args):
        self.calls.append((sql, args))
        assert sql == relations.SINCE_SQL
        return self.since

    def statements(self, sql: str) -> list[tuple]:
        return [args for s, args in self.calls if s == sql]


@pytest.fixture
def redis():
    fake = FakeRedis()
    with patch("app.services.cache.get_redis", AsyncMock(return_value=fake)):
        yield fake


@pytest.fixture
def pool(monkeypatch):
    from app.routers import relations as router

    monkeypatch.setattr(router, "_now", lambda: NOW)
    fake = FakePool()
    with patch("app.services.relations.get_pool", AsyncMock(return_value=fake)):
        yield fake


def _client(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


class TestList:
    @pytest.mark.asyncio
    async def test_answers_the_lens_with_from_and_no_report_count(self, monkeypatch, redis, pool):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations")

        assert resp.status_code == 200
        body = resp.json()
        assert (body["first_day"], body["last_day"], body["since"]) == (
            "2026-10-15",
            "2026-10-21",
            "2026-10-15",
        )
        [rel] = body["relations"]
        assert rel["a"] == {"iso": "IR", "name": "Iran", "lat": 32.52, "lng": 54.29}
        assert rel["b"]["iso"] == "US"
        assert rel["from"] == "US" and "from_" not in rel
        assert "reports" not in rel
        assert set(rel["quad"]) == QUAD_KEYS
        assert (rel["n"], rel["outlets"], rel["mentions"], rel["kind"]) == (20, 4, 300, "conflict")
        assert pool.statements(relations.LIST_SQL) == [
            (FIRST, LAST, [1, 2, 3, 4], relations.MIN_EVENTS, relations.MIN_OUTLETS)
        ]
        assert pool.statements(relations.SINCE_SQL) == [(FIRST, LAST)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"timespan": "24h"},
            {"start_time": "2026-10-10T08:15:00Z", "end_time": "2026-10-11T08:15:00Z"},
        ],
    )
    async def test_window_parameters_change_nothing(self, monkeypatch, redis, pool, params):
        async with _client(monkeypatch) as client:
            plain = await client.get("/api/relations")
            windowed = await client.get("/api/relations", params=params)

        assert windowed.status_code == 200 and windowed.json() == plain.json()
        assert pool.statements(relations.LIST_SQL)[0][:2] == (FIRST, LAST)
        assert len(pool.statements(relations.LIST_SQL)) == 1  # the same key: a cache hit
        assert list(redis.values) == [LIST_KEY]

    @pytest.mark.asyncio
    async def test_a_class_filter_names_itself_and_keeps_every_quad_key(
        self, monkeypatch, redis, pool
    ):
        pool.pairs = [_pair(n=17, q=(0, 0, 12, 5))]
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations", params={"kind": "conflict"})

        assert resp.status_code == 200
        for rel in resp.json()["relations"]:
            assert rel["kind"] == "conflict"
            assert set(rel["quad"]) == QUAD_KEYS
            assert rel["quad"]["verbal_cooperation"] == rel["quad"]["material_cooperation"] == 0
        assert pool.statements(relations.LIST_SQL)[0][2] == [3, 4]
        assert list(redis.values) == ["db:relations:v1:20261015-20261021:conflict:40"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("params", "name", "error"),
        [
            ({"kind": "war"}, "kind", "literal_error"),
            ({"limit": "0"}, "limit", "greater_than_equal"),
            ({"limit": "61"}, "limit", "less_than_equal"),
        ],
    )
    async def test_a_bad_kind_or_limit_is_a_422(
        self, monkeypatch, redis, pool, params, name, error
    ):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations", params=params)

        assert resp.status_code == 422
        [problem] = resp.json()["detail"]
        assert problem["loc"] == ["query", name] and problem["type"] == error
        assert pool.calls == []

    @pytest.mark.asyncio
    async def test_cached_for_a_backstop_ttl_the_cycles_invalidation_beats(
        self, monkeypatch, redis, pool
    ):
        async with _client(monkeypatch) as client:
            await client.get("/api/relations")

        assert redis.ttls[LIST_KEY] == WEEK_TTL >= cycle_ttl(0)

    @pytest.mark.asyncio
    async def test_an_empty_list_is_cached_a_minute_so_new_rollups_show_soon(
        self, monkeypatch, redis, pool
    ):
        pool.pairs = []
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations")

        assert resp.status_code == 200 and resp.json()["relations"] == []
        assert redis.ttls[LIST_KEY] == 60

    @pytest.mark.asyncio
    async def test_the_lens_moves_at_utc_midnight(self, monkeypatch, redis, pool):
        from app.routers import relations as router

        monkeypatch.setattr(
            router, "_now", lambda: datetime(2026, 10, 22, 0, 5, tzinfo=timezone.utc)
        )
        async with _client(monkeypatch) as client:
            await client.get("/api/relations")

        assert list(redis.values) == ["db:relations:v1:20261016-20261022:all:40"]
        assert pool.statements(relations.LIST_SQL)[0][:2] == (
            date(2026, 10, 16),
            date(2026, 10, 22),
        )

    @pytest.mark.asyncio
    async def test_a_cached_answer_computes_nothing(self, monkeypatch, redis, pool):
        async with _client(monkeypatch) as client:
            first = await client.get("/api/relations")
            pool.calls.clear()
            again = await client.get("/api/relations")

        assert again.json() == first.json()
        assert pool.calls == []

    @pytest.mark.asyncio
    async def test_an_entry_of_the_wrong_shape_is_a_miss_logged_once(
        self, monkeypatch, redis, pool, caplog
    ):
        await redis.set(LIST_KEY, json.dumps({"first_day": "2026-10-15"}), ex=WEEK_TTL)
        with caplog.at_level(logging.WARNING, logger="app.services.cache"):
            async with _client(monkeypatch) as client:
                resp = await client.get("/api/relations")

        assert resp.status_code == 200 and resp.json()["relations"]
        assert len(pool.statements(relations.LIST_SQL)) == 1
        [line] = [r.getMessage() for r in caplog.records if "no longer fits" in r.getMessage()]
        assert line.startswith("Cached db:relations:v1:… no longer fits its model")

    @pytest.mark.asyncio
    async def test_concurrent_misses_run_the_query_once(self, monkeypatch, redis, pool):
        pool.gate = asyncio.Event()
        async with _client(monkeypatch) as client:
            requests = [asyncio.create_task(client.get("/api/relations")) for _ in range(2)]
            while not pool.statements(relations.LIST_SQL):
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)  # the second request is waiting on the first's read
            pool.gate.set()
            answers = await asyncio.gather(*requests)

        assert [r.status_code for r in answers] == [200, 200]
        assert answers[0].json() == answers[1].json()
        assert len(pool.statements(relations.LIST_SQL)) == 1


class TestDetail:
    @pytest.mark.asyncio
    async def test_answers_in_code_order_whatever_the_request_order(self, monkeypatch, redis, pool):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations/detail", params={"a": "US", "b": "IR"})

        assert resp.status_code == 200
        body = resp.json()
        assert (body["first_day"], body["last_day"], body["since"]) == (
            "2026-10-15",
            "2026-10-21",
            "2026-10-15",
        )
        assert body["a"]["iso"] == "IR" and body["b"]["iso"] == "US"
        assert [(d["from"], d["to"]) for d in body["directions"]] == [("IR", "US"), ("US", "IR")]
        assert all(set(d["quad"]) == QUAD_KEYS for d in body["directions"])
        assert [d["day"] for d in body["daily"]] == [f"2026-10-{d}" for d in range(15, 22)]
        assert [s["url"] for s in body["samples"]] == ["https://a.test/1", "https://b.test/2"]
        assert body["samples"][0]["from"] == "US" and "from_" not in body["samples"][0]
        assert (body["n"], body["from"], "reports" in body) == (5, "US", False)
        assert pool.statements(relations.DETAIL_SQL) == [("IR", "US", FIRST, LAST)]

    @pytest.mark.asyncio
    async def test_either_order_and_any_window_share_one_entry(self, monkeypatch, redis, pool):
        async with _client(monkeypatch) as client:
            await client.get("/api/relations/detail", params={"b": "US", "a": "IR"})
            await client.get("/api/relations/detail", params={"a": "US", "b": "IR"})
            await client.get(
                "/api/relations/detail", params={"a": "ir", "b": "us", "timespan": "24h"}
            )

        assert list(redis.values) == [DETAIL_KEY]
        assert redis.ttls[DETAIL_KEY] == WEEK_TTL
        assert len(pool.statements(relations.DETAIL_SQL)) == 1

    @pytest.mark.asyncio
    async def test_titles_come_from_our_articles(self, monkeypatch, redis, pool):
        pool.titles = [{"source_url": "https://a.test/1", "title": "Talks - Reuters"}]
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations/detail", params={"a": "IR", "b": "US"})

        assert [s["title"] for s in resp.json()["samples"]] == ["Talks", None]
        assert pool.statements(relations.TITLES_SQL) == [
            (["https://a.test/1", "https://b.test/2"],)
        ]

    @pytest.mark.asyncio
    async def test_a_pair_without_events_is_a_404_and_not_cached(self, monkeypatch, redis, pool):
        pool.detail = []
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations/detail", params={"a": "IR", "b": "US"})

        assert resp.status_code == 404
        assert resp.json() == NOT_FOUND
        assert redis.values == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("params", "detail"),
        [
            (
                {"a": "ZZ", "b": "US"},
                "Unknown country 'ZZ': an ISO 3166-1 alpha-2 code with a label point.",
            ),
            ({"a": "US", "b": "US"}, "a and b must be different countries."),
        ],
    )
    async def test_an_unknown_or_repeated_country_is_a_422(
        self, monkeypatch, redis, pool, params, detail
    ):
        async with _client(monkeypatch) as client:
            resp = await client.get("/api/relations/detail", params=params)

        assert resp.status_code == 422
        assert resp.json() == {"detail": detail}
        assert pool.calls == []


@pytest.mark.asyncio
async def test_both_routes_are_edge_cached(monkeypatch, redis, pool):
    async with _client(monkeypatch) as client:
        listed = await client.get("/api/relations")
        detail = await client.get("/api/relations/detail", params={"a": "IR", "b": "US"})

    assert listed.headers["cache-control"] == EDGE_CACHE_CONTROL
    assert detail.headers["cache-control"] == EDGE_CACHE_CONTROL


@pytest.mark.asyncio
async def test_a_cycles_invalidations_refresh_the_list_and_detail_together(
    monkeypatch, redis, pool
):
    """Under wk:*, outside the cycle's invalidation, the list and a pair's detail were
    cached at different times: the arc said 59 events and the inspector 65 (Russia and
    Ukraine, production, 2026-10-21). In a cycle's order: the events land, ingestion
    clears CACHE_PREFIX at once, so reads during the embeddings count the new events in
    both; then the cycle's end clears db:*, these with the rest, for the warm to refill."""
    pool.pairs = [_pair(n=5, q=(1, 0, 4, 0), from_a=1)]  # the detail's 5 events, listed
    async with _client(monkeypatch) as client:
        await client.get("/api/relations")
        await client.get("/api/relations/detail", params={"a": "IR", "b": "US"})
        assert sorted(redis.values) == [DETAIL_KEY, LIST_KEY]

        # The events step lands 6 more: the US's verbal conflict on 19 Oct.
        pool.pairs = [_pair(n=11, q=(1, 0, 10, 0), from_a=1)]
        pool.detail = [*pool.detail, _rollup("US", "IR", date(2026, 10, 19), 3, 6)]
        await invalidate(f"{relations.CACHE_PREFIX}*")  # just after ingest_events
        assert redis.values == {}

        # During the embeddings: the list and a pair's detail, read cold, agree.
        listed = await client.get("/api/relations")
        detail = await client.get("/api/relations/detail", params={"a": "IR", "b": "US"})
        assert listed.json()["relations"][0]["n"] == detail.json()["n"] == 11
        assert len(pool.statements(relations.LIST_SQL)) == 2  # once each side of the events
        assert len(pool.statements(relations.DETAIL_SQL)) == 2

    await invalidate("db:*")  # as the cycle ends
    assert redis.values == {}


class TestWarm:
    @pytest.mark.asyncio
    async def test_the_warm_caches_what_the_layers_first_request_reads(
        self, monkeypatch, redis, pool
    ):
        """warm_relations (app.warm, after each cycle's invalidation) stores the key,
        bytes and TTL the frontend's first request (every class, RELATIONS_LIMIT 40)
        would: that request is then a hit."""
        from app.routers import relations as router

        async with _client(monkeypatch) as client:
            await client.get("/api/relations", params={"kind": "all", "limit": 40})
        requested = (redis.values[LIST_KEY], redis.ttls[LIST_KEY])
        await invalidate("db:*")

        await router.warm_relations()

        assert list(redis.values) == [LIST_KEY]
        assert (redis.values[LIST_KEY], redis.ttls[LIST_KEY]) == requested
        pool.calls.clear()
        async with _client(monkeypatch) as client:
            hit = await client.get("/api/relations", params={"kind": "all", "limit": 40})
        assert hit.status_code == 200 and hit.json()["relations"]
        assert pool.calls == []

    @pytest.mark.asyncio
    async def test_the_warm_joins_a_read_a_requests_miss_has_started(
        self, monkeypatch, redis, pool
    ):
        """Right after a cycle, a visitor may miss before the warm gets there: the
        two share one read."""
        from app.routers import relations as router

        pool.gate = asyncio.Event()
        async with _client(monkeypatch) as client:
            request = asyncio.create_task(client.get("/api/relations"))
            while not pool.statements(relations.LIST_SQL):
                await asyncio.sleep(0.01)
            warm = asyncio.create_task(router.warm_relations())
            await asyncio.sleep(0.05)  # the warm is waiting on the request's read
            pool.gate.set()
            resp = await request
            await warm

        assert resp.status_code == 200
        assert len(pool.statements(relations.LIST_SQL)) == 1
        assert list(redis.values) == [LIST_KEY]


@pytest.mark.asyncio
async def test_a_class_tie_with_a_goldstein_of_zero_is_cooperation(monkeypatch, redis, pool):
    """The tie-break is the Goldstein sign, and zero isn't negative: cooperation."""
    pool.pairs = [_pair(n=20, q=(5, 5, 5, 5), goldstein=0.0)]
    async with _client(monkeypatch) as client:
        resp = await client.get("/api/relations")

    [rel] = resp.json()["relations"]
    assert (rel["kind"], rel["goldstein"]) == ("cooperation", 0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "params", "gate"),
    [
        ("/api/relations", {}, "gate"),
        ("/api/relations/detail", {"a": "IR", "b": "US"}, "detail_gate"),
    ],
)
async def test_a_read_cancelled_under_a_request_is_a_503_to_retry(
    monkeypatch, redis, pool, caplog, path, params, gate
):
    """As links' and the globe's week reads: if a cancel scope ever reaches
    relations.CACHE_PREFIX (shutdown does), a waiting request gets a 503 with
    Retry-After, not a bare 500 with a traceback."""
    from app.services import cache

    setattr(pool, gate, asyncio.Event())
    with caplog.at_level(logging.INFO):
        async with _client(monkeypatch) as client:
            request = asyncio.create_task(client.get(path, params=params))
            while not pool.calls:
                await asyncio.sleep(0.01)
            stopped = cache.cancel_flights(relations.CACHE_PREFIX)
            await asyncio.gather(*stopped, return_exceptions=True)
            resp = await asyncio.wait_for(request, 2)  # fails, not hangs, if none matched

    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "15"
    assert "cache-control" not in resp.headers  # never kept at the edge
    assert resp.json()["detail"] == "The computation for db:* was cancelled; retry shortly."
    assert not [r for r in caplog.records if r.exc_info]
    assert redis.values == {}


def test_both_routes_are_rate_limited_as_data():
    from app.middleware.security import _get_rate_group

    assert _get_rate_group("/api/relations") == "data"
    assert _get_rate_group("/api/relations/detail") == "data"
