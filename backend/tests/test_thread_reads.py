"""The threads read queries' shaping (app.services.thread_reads), without a database.

The SQL runs in tests/test_thread_reads_db.py against a real PostgreSQL.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import thread_reads
from app.services.thread_reads import article_thread, thread_item, thread_status

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def _place(i: int, region="Paris, Ile-de-France, France", country_code="FR") -> dict:
    return {
        "lat": 48.5 + i,
        "lng": 2.5,
        "region": region,
        "country_code": country_code,
        "first_seen": (NOW - 10 * HOUR + i * timedelta(minutes=1)).isoformat(),
        "n": 1,
    }


def _row(**overrides) -> dict:
    row = {
        "id": 7,
        "title": None,
        "synopsis": None,
        "lead_title": "Strikes spread across France",
        "first_seen": NOW - 10 * HOUR,
        "last_seen": NOW - HOUR,
        "n_stories": 9,
        "n_sources": 6,
        "velocity": 1,
        "countries": ["FR"],
        "places": json.dumps([_place(0)]),
        "topic": "economy",
        "lead_article_id": uuid.uuid4(),
        "lead_article_title": "Strikes spread across France - Le Monde",
        "lead_source_name": "lemonde.fr",
        "lead_published_at": NOW - HOUR,
        "lead_image_url": "https://cdn.example.com/a.jpg",
        "lead_topic_tags": ["economy", "conflict"],
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("first_seen", "velocity", "status"),
    [
        (NOW - 6 * HOUR, 0, "emerging"),
        (NOW - 6 * HOUR - timedelta(seconds=1), 2, "developing"),
        (NOW - 30 * HOUR, 5, "developing"),
        (NOW - 6 * HOUR - timedelta(seconds=1), 1, "fading"),
        (NOW - 30 * HOUR, 0, "fading"),
    ],
)
def test_status(first_seen, velocity, status):
    assert thread_status(first_seen, velocity, NOW) == status


def test_an_item_carries_the_list_fields():
    item = thread_item(_row(), NOW)

    assert item == {
        "id": 7,
        "title": "Strikes spread across France",
        "synopsis": None,
        "status": "fading",
        "first_seen": NOW - 10 * HOUR,
        "last_seen": NOW - HOUR,
        "n_stories": 9,
        "n_sources": 6,
        "velocity": 1,
        "countries": ["FR"],
        "places": [
            {
                "lat": 48.5,
                "lng": 2.5,
                "place": "Paris, Ile-de-France, France",
                "country_code": "FR",
                "first_seen": datetime.fromisoformat(_place(0)["first_seen"]),
                "n": 1,
            }
        ],
        "topic": "economy",
        "lead": {
            "title": "Strikes spread across France - Le Monde",
            "source_name": "lemonde.fr",
            "published_at": NOW - HOUR,
            "image_url": "https://cdn.example.com/a.jpg",
            "topic": "economy",
            "sensitive": True,
        },
    }


def test_the_ai_title_and_synopsis_come_first():
    item = thread_item(_row(title="French strikes widen", synopsis="Unions walked out."), NOW)

    assert (item["title"], item["synopsis"]) == ("French strikes widen", "Unions walked out.")


def test_a_lead_no_longer_kept_is_null():
    stale = {"lead_article_title": None, "lead_source_name": None, "lead_published_at": None}
    assert (
        thread_item(_row(**stale, lead_image_url=None, lead_topic_tags=None), NOW)["lead"] is None
    )


def test_places_are_shown_names_capped_for_the_list():
    places = [_place(i, region="Gaza, Israel", country_code="PS") for i in range(30)]
    row = _row(places=json.dumps(places))

    listed = thread_item(row, NOW)["places"]
    every = thread_item(row, NOW, places_cap=None)["places"]

    assert len(listed) == 20 and len(every) == 30
    assert listed[0]["place"] == "Gaza, Palestine"
    assert [p["lat"] for p in every] == [p["lat"] for p in places]


def test_no_topic_is_general():
    assert thread_item(_row(topic=""), NOW)["topic"] == "general"


def test_article_thread_names_its_first_three_places_once_each():
    places = [
        _place(0, region="Paris, Ile-de-France, France"),
        _place(1, region="Paris, Ile-de-France, France"),
        _place(2, region="Lyon, Rhone-Alpes, France"),
        _place(3, region=""),
        _place(4, region="Brussels, Bruxelles-Capitale, Belgium", country_code="BE"),
        _place(5, region="Geneva, Geneve, Switzerland", country_code="CH"),
    ]
    row = {
        "thread_id": 7,
        "thread_title": None,
        "thread_lead_title": "Strikes spread",
        "thread_places": json.dumps(places),
    }

    assert article_thread(row) == {
        "id": 7,
        "title": "Strikes spread",
        "places": [
            "Paris, Ile-de-France, France",
            "Lyon, Rhone-Alpes, France",
            "Brussels, Bruxelles-Capitale, Belgium",
        ],
    }
    assert article_thread({**row, "thread_title": "AI title"})["title"] == "AI title"
    assert article_thread({"thread_id": None}) is None
    assert article_thread({}) is None


class FakePool:
    def __init__(self, rows=()):
        self.fetch = AsyncMock(return_value=list(rows))


@pytest.mark.asyncio
async def test_the_list_query_takes_its_thresholds_window_and_limit():
    pool = FakePool([_row()])
    with patch("app.services.thread_reads.get_pool", AsyncMock(return_value=pool)):
        items = await thread_reads.list_threads(NOW, 24, None, 20)

    query, *args = pool.fetch.await_args.args
    assert args == [NOW - 24 * HOUR, 20]
    assert "topic =" not in query
    # Constants, not parameters, so the partial idx_threads_listed matches any plan.
    assert "n_stories >= 3 AND n_sources >= 3" in " ".join(query.split())
    assert [i["id"] for i in items] == [7]


@pytest.mark.asyncio
async def test_a_topic_is_one_more_parameter():
    pool = FakePool()
    with patch("app.services.thread_reads.get_pool", AsyncMock(return_value=pool)):
        await thread_reads.list_threads(NOW, 6, "environment", 5)

    query, *args = pool.fetch.await_args.args
    assert args == [NOW - 6 * HOUR, 5, "environment"]
    assert "topic = $3" in " ".join(query.split())


def _timed_pool(row):
    """A pool whose queries each take a moment, recording their order and overlap."""
    import asyncio

    state = SimpleNamespace(running=0, most=0, calls=[])

    async def query(sql, *args):
        state.calls.append(sql)
        state.running += 1
        state.most = max(state.most, state.running)
        await asyncio.sleep(0.01)
        state.running -= 1
        return row if "FROM one" in sql else []

    return SimpleNamespace(fetch=query, fetchrow=query), state


@pytest.mark.asyncio
async def test_an_unknown_thread_is_one_query():
    """A 404 doesn't take four pool connections."""
    pool, state = _timed_pool(None)
    with patch("app.services.thread_reads.get_pool", AsyncMock(return_value=pool)):
        assert await thread_reads.thread_detail(7, 0, NOW) is None

    assert state.calls == [thread_reads.DETAIL_SQL]


@pytest.mark.asyncio
async def test_a_thread_is_read_then_its_three_parts_at_once():
    """Each part on its own pool connection (Pool.fetch acquires one per call)."""
    pool, state = _timed_pool(_row())
    with patch("app.services.thread_reads.get_pool", AsyncMock(return_value=pool)):
        detail = await thread_reads.thread_detail(7, 0, NOW)

    assert detail["id"] == 7
    assert state.calls[0] == thread_reads.DETAIL_SQL
    assert set(state.calls[1:]) == {
        thread_reads.ENTITIES_SQL,
        thread_reads.TIMELINE_SQL,
        thread_reads.ARTICLES_SQL,
    }
    assert state.most == 3
