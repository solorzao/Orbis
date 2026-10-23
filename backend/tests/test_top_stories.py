"""retrieval.top_stories: Orbis's cached rankings for broad questions (Phase 6, 21d)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import retrieval
from tests.fake_redis import FakeRedis


def _thread(i, n_sources=12, countries=("NG", "GB")):
    """A thread as /api/threads answers it (JSON), trimmed to what top_stories reads."""
    return {
        "id": i,
        "title": f"Story {i}",
        "synopsis": f"What happened in story {i}.",
        "status": "developing",
        "first_seen": "2026-10-23T06:00:00Z",
        "last_seen": "2026-10-23T11:00:00Z",
        "n_stories": 9,
        "n_sources": n_sources,
        "velocity": 3,
        "countries": list(countries),
        "places": [
            {
                "lat": 6.45,
                "lng": 3.39,
                "place": "Lagos, Nigeria",
                "first_seen": "2026-10-23T06:00:00Z",
                "n": 4,
            }
        ],
        "topic": "politics",
        "lead": {
            "title": f"Lead {i}",
            "source_name": "Punch",
            "published_at": "2026-10-23T10:00:00Z",
            "topic": "politics",
        },
    }


def _breaking(n=1, topic="environment"):
    """A breaking event as /api/news/breaking answers it (JSON)."""
    return {
        "headline": f"Storm hits coast {n}",
        "place": "Valencia, Spain",
        "lat": 39.5,
        "lng": -0.5,
        "outlets": 9,
        "stories": 4,
        "first_seen": "2026-10-23T10:00:00Z",
        "topic": topic,
        "lead": {
            "title": f"Storm {n}",
            "source_name": "EFE",
            "published_at": "2026-10-23T10:30:00Z",
            "topic": topic,
        },
    }


@pytest.fixture
def redis():
    """Redis faked for every module that caches through app.services.cache."""
    fake = FakeRedis()
    with patch("app.services.cache.get_redis", AsyncMock(return_value=fake)):
        yield fake


@pytest.fixture
def listed(monkeypatch):
    """The threads rail's list (threads.cached_threads, its own cache path), eight threads."""
    from app.models.threads import ThreadSummary
    from app.routers import threads

    mock = AsyncMock(return_value=[ThreadSummary.model_validate(_thread(i)) for i in range(1, 9)])
    monkeypatch.setattr(threads, "cached_threads", mock)
    return mock


@pytest.fixture
def pool(monkeypatch):
    """The lead-link read: thread 1's lead is a javascript: link, the others https."""
    rows = [{"id": 1, "source_url": "javascript:x"}] + [
        {"id": i, "source_url": f"https://a.com/{i}"} for i in range(2, 9)
    ]
    stub = SimpleNamespace(fetch=AsyncMock(return_value=rows))
    monkeypatch.setattr(retrieval, "get_pool", AsyncMock(return_value=stub))
    return stub


@pytest.fixture
def breaking_query():
    """The breaking query: top_stories must never run it, nor wait on it."""
    with patch("app.routers.news.get_breaking", AsyncMock(return_value=[])) as mock:
        yield mock


def test_coverage_words():
    assert retrieval.coverage_words(12, 1, "emerging") == "12 outlets, 1 country, emerging"
    assert retrieval.coverage_words(3, 4, "fading") == "3 outlets, 4 countries, fading"


def test_rows_rank_by_outlets_then_countries_and_cap():
    threads = [_thread(1, 3), _thread(2, 12, ("NG",)), _thread(3, 12)] + [
        _thread(i, 5) for i in range(4, 9)
    ]
    rows = retrieval.top_story_rows(retrieval.by_breadth(threads), [], {3: "https://a.com/3"})
    assert [r["title"] for r in rows] == ["Story 3", "Story 2", "Story 4", "Story 5", "Story 6"]
    assert rows[0]["coverage"] == "12 outlets, 2 countries, developing"
    assert rows[0]["summary"] == "What happened in story 3."
    assert (rows[0]["latitude"], rows[0]["longitude"]) == (6.45, 3.39)
    assert rows[0]["source_url"] == "https://a.com/3" and rows[1]["source_url"] == ""


def test_breaking_events_follow_the_threads_with_no_link():
    rows = retrieval.top_story_rows([_thread(1)], [_breaking(n) for n in range(5)], {})
    assert len(rows) == 1 + retrieval.TOP_BREAKING
    assert rows[-1] == {
        "title": "Storm hits coast 2",
        "summary": None,
        "source_url": "",
        "source_name": "EFE",
        "latitude": 39.5,
        "longitude": -0.5,
        "coverage": "breaking: 9 outlets in the last 2 hours, Valencia, Spain",
    }


@pytest.mark.asyncio
async def test_a_cached_answer_is_returned_as_is(redis, listed, pool):
    redis.values["db:copilot:top:v1:24h:"] = json.dumps([{"title": "T"}])
    assert await retrieval.top_stories(24) == [{"title": "T"}]
    listed.assert_not_awaited()
    pool.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_miss_reads_the_cached_lists_and_five_links_then_caches(
    redis, listed, pool, breaking_query
):
    redis.values["db:breaking:v1"] = json.dumps([_breaking(1, "environment")])

    rows = await retrieval.top_stories(24, "Politics")

    listed.assert_awaited_once_with(24, "politics", 20)  # the rail's own list and key
    assert len(rows) == 5  # the breaking event is environment, not politics
    assert pool.fetch.await_args.args[0] == retrieval._LEAD_URLS_SQL
    assert sorted(pool.fetch.await_args.args[1]) == [1, 2, 3, 4, 5]  # by primary key
    assert rows[0]["source_url"] == ""  # http(s) only
    assert rows[1]["source_url"] == "https://a.com/2"
    assert json.loads(redis.values["db:copilot:top:v1:24h:politics"]) == rows
    breaking_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_topic_pill_is_its_article_tag(redis, listed, pool, breaking_query):
    redis.values["db:breaking:v1"] = json.dumps([_breaking(1, "environment")])

    rows = await retrieval.top_stories(6, "Climate")

    listed.assert_awaited_once_with(6, "environment", 20)
    assert rows[-1]["title"] == "Storm hits coast 1"
    assert "db:copilot:top:v1:6h:environment" in redis.values


@pytest.mark.asyncio
async def test_breaking_comes_from_the_last_good_list_when_the_fresh_one_is_gone(
    redis, listed, pool, breaking_query
):
    redis.values["last:breaking:v1"] = json.dumps([_breaking(n, "politics") for n in range(4)])

    rows = await retrieval.top_stories(24)

    assert [r["title"] for r in rows[5:]] == [f"Storm hits coast {n}" for n in range(3)]
    breaking_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_with_no_cached_breaking_list_it_never_starts_or_waits_on_the_query(
    redis, listed, pool, breaking_query
):
    """The breaking query outlasts its 15 s limit on production: a co-pilot answer
    takes the threads alone rather than start it, or wait on one a miss started."""
    from app.routers import news

    rows = await retrieval.top_stories(24)

    assert [r["title"] for r in rows] == [f"Story {i}" for i in range(1, 6)]
    breaking_query.assert_not_awaited()
    assert news._breaking_in_flight == {}


@pytest.mark.asyncio
async def test_no_threads_reads_no_links(redis, listed, pool, breaking_query):
    listed.return_value = []
    assert await retrieval.top_stories(24) == []
    pool.fetch.assert_not_awaited()
