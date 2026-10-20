"""The threads read SQL (app.services.thread_reads) on a real PostgreSQL, and the
cluster articles' "part of thread" (database.get_articles_in_bounds).

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied, 013 included. Every test runs in a transaction that is
rolled back. Skipped without it. NOW is far in the future: every window
reaches back from NOW, so only these rows fall in it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import database, thread_reads

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

NOW = datetime(2101, 1, 10, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    if not await connection.fetchval("SELECT to_regclass('thread_centroids') IS NOT NULL"):
        await connection.close()
        pytest.skip("thread tables are missing: apply migration 013")
    tx = connection.transaction()
    await tx.start()
    pool = _OneConnectionPool(connection)
    try:
        with (
            patch("app.services.thread_reads.get_pool", AsyncMock(return_value=pool)),
            patch("app.services.database.get_pool", AsyncMock(return_value=pool)),
        ):
            yield connection
    finally:
        await tx.rollback()
        await connection.close()


class _OneConnectionPool:
    """The test's connection as a pool: queries that would each take a pool connection
    (the detail's, gathered) take turns on it, inside the test's transaction."""

    def __init__(self, connection):
        self._connection = connection
        self._lock = asyncio.Lock()

    async def fetch(self, *args):
        async with self._lock:
            return await self._connection.fetch(*args)

    async def fetchrow(self, *args):
        async with self._lock:
            return await self._connection.fetchrow(*args)


_counter = iter(range(10**6))


async def _article(
    conn,
    published_at=NOW - HOUR,
    *,
    title=None,
    source="zz-a.test",
    lat=10.5,
    lng=20.5,
    region="Zz Alpha",
    country_code="ZA",
    topic_tags=("conflict",),
    image_url="https://zzthreads.test/a.jpg",
) -> uuid.UUID:
    n = next(_counter)
    return await conn.fetchval(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude, longitude,
                              location, region, country_code, topic_tags, image_url)
        VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_MakePoint($6, $5), 4326)::geography,
                $7, $8, $9, $10)
        RETURNING id
        """,
        title or f"Zzthread read story {n} today",
        f"https://zzthreads.test/read/{n}/{uuid.uuid4()}",
        source,
        published_at,
        lat,
        lng,
        region,
        country_code,
        list(topic_tags),
        image_url,
    )


def _places(n: int) -> str:
    return json.dumps(
        [
            {
                "lat": -60.5 + 3 * i,
                "lng": 0.5,
                "region": f"Zz Place {i}",
                "country_code": "",
                "first_seen": (NOW - 50 * HOUR + i * timedelta(minutes=1)).isoformat(),
                "n": 1,
            }
            for i in range(n)
        ]
    )


async def _thread(
    conn,
    *,
    n_stories=3,
    n_sources=3,
    velocity=0,
    first_seen=NOW - 48 * HOUR,
    last_seen=NOW - HOUR,
    topic="conflict",
    lead_article_id=None,
    lead_title="Zzthread lead title",
    title=None,
    places=None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO threads (centroid_sum, first_seen, last_seen, n_articles, n_stories,
                             n_sources, velocity, countries, places, topic, lead_article_id,
                             lead_title, title, aggregated_at)
        VALUES (array_fill(0.01, ARRAY[512])::vector, $1, $2, $3, $3, $4, $5, '{ZA}',
                $6::jsonb, $7, $8, $9, $10, $2)
        RETURNING id
        """,
        first_seen,
        last_seen,
        n_stories,
        n_sources,
        velocity,
        places or _places(1),
        topic,
        lead_article_id,
        lead_title,
        title,
    )


async def _member(
    conn,
    thread_id,
    article_id=None,
    *,
    published_at=NOW - HOUR,
    story_key=None,
    entities=(),
    tone=None,
    region="Zz Alpha",
    country_code="ZA",
) -> uuid.UUID:
    article_id = article_id or uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO thread_members (article_id, thread_id, story_key, source_name, published_at,
                                    latitude, longitude, region, country_code, entities, tone,
                                    similarity)
        VALUES ($1, $2, $3, 'zz-a.test', $4, 10.5, 20.5, $5, $6, $7, $8, 0.9)
        """,
        article_id,
        thread_id,
        story_key,
        published_at,
        region,
        country_code,
        list(entities),
        tone,
    )
    return article_id


async def _listed(hours=24, topic=None, limit=20) -> list[int]:
    return [t["id"] for t in await thread_reads.list_threads(NOW, hours, topic, limit)]


# --- the list ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_thread_needs_three_stories_and_three_outlets(conn):
    listed = await _thread(conn, n_stories=3, n_sources=3)
    await _thread(conn, n_stories=3, n_sources=2)
    await _thread(conn, n_stories=2, n_sources=3)

    assert await _listed() == [listed]


@pytest.mark.asyncio
async def test_only_threads_seen_in_the_window_are_listed(conn):
    recent = await _thread(conn, last_seen=NOW - 5 * HOUR)
    day = await _thread(conn, last_seen=NOW - 23 * HOUR)
    week = await _thread(conn, last_seen=NOW - 100 * HOUR)

    assert await _listed(6) == [recent]
    assert set(await _listed(24)) == {recent, day}
    assert set(await _listed(168)) == {recent, day, week}


@pytest.mark.asyncio
async def test_fastest_first_then_most_stories_then_id(conn):
    slow_big = await _thread(conn, velocity=1, n_stories=9)
    fast = await _thread(conn, velocity=5, n_stories=3)
    slow_small_a = await _thread(conn, velocity=1, n_stories=4)
    slow_small_b = await _thread(conn, velocity=1, n_stories=4)

    assert await _listed() == [fast, slow_big, slow_small_a, slow_small_b]
    assert await _listed(limit=2) == [fast, slow_big]


@pytest.mark.asyncio
async def test_status(conn):
    emerging = await _thread(conn, first_seen=NOW - 5 * HOUR, velocity=0)
    developing = await _thread(conn, velocity=2)
    fading = await _thread(conn, velocity=1)

    statuses = {t["id"]: t["status"] for t in await thread_reads.list_threads(NOW, 24, None, 20)}

    assert statuses == {emerging: "emerging", developing: "developing", fading: "fading"}


@pytest.mark.asyncio
async def test_the_topic_filter(conn):
    climate = await _thread(conn, topic="environment")
    await _thread(conn, topic="conflict")

    assert await _listed(topic="environment") == [climate]


@pytest.mark.asyncio
async def test_list_items_carry_20_places_and_their_lead(conn):
    lead = await _article(conn, title="Zzthread quake strikes - Reuters")
    thread_id = await _thread(conn, places=_places(30), lead_article_id=lead)

    [item] = await thread_reads.list_threads(NOW, 24, None, 20)

    assert item["id"] == thread_id
    assert [p["place"] for p in item["places"]] == [f"Zz Place {i}" for i in range(20)]
    assert item["lead"] == {
        "title": "Zzthread quake strikes - Reuters",
        "source_name": "zz-a.test",
        "published_at": NOW - HOUR,
        "image_url": "https://zzthreads.test/a.jpg",
        "topic": "conflict",
        "sensitive": True,
    }
    assert item["title"] == "Zzthread lead title"


@pytest.mark.asyncio
async def test_a_lead_no_longer_kept_is_null(conn):
    await _thread(conn, lead_article_id=uuid.uuid4())

    [item] = await thread_reads.list_threads(NOW, 24, None, 20)

    assert item["lead"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", [None, "conflict"])
async def test_the_list_reads_listed_threads_and_articles_by_primary_key_only(conn, topic):
    """The partial idx_threads_listed: a week's single-story threads are never read."""
    await conn.execute(  # a week of mostly single-story threads, and a few listed
        "INSERT INTO threads (centroid_sum, first_seen, last_seen, n_stories, n_sources, topic)"
        " SELECT array_fill(0.01, ARRAY[512])::vector, $1::timestamptz,"
        " $1::timestamptz - i * interval '30 minutes',"
        " CASE WHEN i <= 3 THEN 3 ELSE 1 END, CASE WHEN i <= 3 THEN 3 ELSE 1 END, 'conflict'"
        " FROM generate_series(1, 300) AS i",
        NOW,
    )
    await conn.execute("ANALYZE threads")
    await conn.execute("SET LOCAL enable_seqscan = off")
    query, args = thread_reads.list_query(NOW, 168, topic, 20)

    plan = "\n".join(r[0] for r in await conn.fetch("EXPLAIN " + query, *args))

    assert "idx_threads_listed" in plan
    assert "Seq Scan on articles" not in plan
    assert "Seq Scan on threads" not in plan


# --- the detail -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_thread_is_none(conn):
    assert await thread_reads.thread_detail(2**62, 0, NOW) is None


@pytest.mark.asyncio
async def test_the_detail_has_every_place_people_timeline_and_stories(conn):
    thread_id = await _thread(conn, places=_places(30))
    t0 = NOW - 5 * HOUR
    a1 = await _article(conn, t0, title="Zzthread first report | BBC News")
    await _member(conn, thread_id, a1, published_at=t0, story_key=1, entities=["Zz Org"], tone=-2)
    a2 = await _article(
        conn, t0 + timedelta(minutes=10), title="Zzthread first report - AP", source="zz-b.test"
    )
    await _member(  # a copy of a1's story
        conn,
        thread_id,
        a2,
        published_at=t0 + timedelta(minutes=10),
        story_key=1,
        entities=["Zz Org", "Zz Jane Specific"],
        tone=-4,
    )
    a3 = await _article(conn, t0 + 2 * HOUR, title="WATCH: Zzthread spread reaches beta")
    await _member(
        conn,
        thread_id,
        a3,
        published_at=t0 + 2 * HOUR,
        story_key=2,
        entities=["Zz Org"],
        region="Zz Beta",
        country_code="",
    )

    detail = await thread_reads.thread_detail(thread_id, 0, NOW)

    assert detail["id"] == thread_id
    assert len(detail["places"]) == 20 and len(detail["spread"]) == 30
    assert detail["entities"] == [{"name": "Zz Org", "n": 2}, {"name": "Zz Jane Specific", "n": 1}]
    assert detail["timeline"] == [
        {"hour": t0, "n": 1, "tone": pytest.approx(-3.0)},
        {"hour": t0 + 2 * HOUR, "n": 1, "tone": None},
    ]
    urls = {
        r["id"]: r["source_url"]
        for r in await conn.fetch(
            "SELECT id, source_url FROM articles WHERE id = ANY($1)", [a2, a3]
        )
    }
    assert detail["articles"] == [
        {
            "title": "Zzthread spread reaches beta",
            "source_name": "zz-a.test",
            "published_at": t0 + 2 * HOUR,
            "source_url": urls[a3],
            "place": "Zz Beta",
        },
        {  # one story, as its newest copy
            "title": "Zzthread first report",
            "source_name": "zz-b.test",
            "published_at": t0 + timedelta(minutes=10),
            "source_url": urls[a2],
            "place": "Zz Alpha",
        },
    ]


@pytest.mark.asyncio
async def test_the_detail_pages_its_stories_newest_first(conn):
    thread_id = await _thread(conn)
    times = [NOW - 30 * HOUR + i * HOUR for i in range(25)]
    for i, published_at in enumerate(times):
        article = await _article(conn, published_at, title=f"Zzthread paged story {i:02d} now")
        await _member(conn, thread_id, article, published_at=published_at, story_key=100 + i)

    first = await thread_reads.thread_detail(thread_id, 0, NOW)
    second = await thread_reads.thread_detail(thread_id, 20, NOW)

    assert [a["published_at"] for a in first["articles"]] == times[::-1][:20]
    assert [a["published_at"] for a in second["articles"]] == times[::-1][20:]
    assert second["articles"][-1]["title"] == "Zzthread paged story 00 now"


@pytest.mark.asyncio
async def test_a_story_whose_article_is_gone_is_skipped(conn):
    thread_id = await _thread(conn)
    await _member(conn, thread_id, published_at=NOW - HOUR, story_key=1)  # no article row
    kept = await _article(conn, NOW - 2 * HOUR)
    await _member(conn, thread_id, kept, published_at=NOW - 2 * HOUR, story_key=2)

    detail = await thread_reads.thread_detail(thread_id, 0, NOW)

    assert [a["published_at"] for a in detail["articles"]] == [NOW - 2 * HOUR]


# --- "part of thread" on cluster articles -----------------------------------------


@pytest.mark.asyncio
async def test_cluster_articles_name_their_listed_thread(conn):
    cell = dict(lat=-45.5, lng=-150.5)
    listed = await _thread(conn, title="Zzthread AI title", places=_places(4))
    quiet = await _thread(conn, n_sources=2)
    in_listed = await _article(conn, NOW - HOUR, **cell)
    await _member(conn, listed, in_listed)
    in_quiet = await _article(conn, NOW - 2 * HOUR, **cell)
    await _member(conn, quiet, in_quiet)
    alone = await _article(conn, NOW - 3 * HOUR, **cell)

    rows = await database.get_articles_in_bounds(-46.0, -151.0, -45.0, -150.0, limit=3)

    threads_by_article = {r["id"]: thread_reads.article_thread(r) for r in rows}
    assert threads_by_article == {
        in_listed: {
            "id": listed,
            "title": "Zzthread AI title",
            "places": ["Zz Place 0", "Zz Place 1", "Zz Place 2"],
        },
        in_quiet: None,
        alone: None,
    }
    assert [r["id"] for r in rows] == [in_listed, in_quiet, alone]


@pytest.mark.asyncio
async def test_a_merged_thread_answers_as_the_thread_it_joined(conn):
    """Share links and the UI hold thread ids: a merged id still resolves."""
    winner = await _thread(conn, title="Zzthread merged winner")
    article = await _article(conn, NOW - HOUR, title="Zzthread winner story today")
    await _member(conn, winner, article, published_at=NOW - HOUR, story_key=1)
    loser = await _thread(conn, n_stories=0, n_sources=0)
    await conn.execute("UPDATE threads SET merged_into = $1 WHERE id = $2", winner, loser)

    detail = await thread_reads.thread_detail(loser, 0, NOW)

    assert detail["id"] == winner
    assert detail["title"] == "Zzthread merged winner"
    assert [a["title"] for a in detail["articles"]] == ["Zzthread winner story today"]
    assert loser not in await _listed()


@pytest.mark.asyncio
async def test_a_chain_of_merges_answers_as_its_last_thread(conn):
    winner = await _thread(conn, title="Zzthread chain winner")
    middle = await _thread(conn, n_stories=0, n_sources=0)
    first = await _thread(conn, n_stories=0, n_sources=0)
    await conn.execute("UPDATE threads SET merged_into = $1 WHERE id = $2", winner, middle)
    await conn.execute("UPDATE threads SET merged_into = $1 WHERE id = $2", middle, first)

    assert (await thread_reads.thread_detail(first, 0, NOW))["id"] == winner
    assert (await thread_reads.thread_detail(middle, 0, NOW))["id"] == winner


@pytest.mark.asyncio
async def test_a_thread_merged_into_a_purged_one_is_unknown(conn):
    """No foreign key: the purge may delete the winner and leave the id dangling."""
    loser = await _thread(conn, n_stories=0, n_sources=0)
    await conn.execute("UPDATE threads SET merged_into = $1 WHERE id = $2", 2**62, loser)

    assert await thread_reads.thread_detail(loser, 0, NOW) is None


@pytest.mark.asyncio
async def test_a_chain_longer_than_merge_hops_is_cut_and_logged(conn, caplog):
    ids = [
        await _thread(conn, n_stories=0, n_sources=0) for _ in range(thread_reads.MERGE_HOPS + 2)
    ]
    for loser, winner in zip(ids, ids[1:]):
        await conn.execute("UPDATE threads SET merged_into = $1 WHERE id = $2", winner, loser)

    with caplog.at_level(logging.WARNING, logger="orbis.thread_reads"):
        assert await thread_reads.thread_detail(ids[0], 0, NOW) is None

    assert f"Thread {ids[0]}: merge chain cut at {thread_reads.MERGE_HOPS} hops" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="orbis.thread_reads"):
        assert (await thread_reads.thread_detail(ids[2], 0, NOW))["id"] == ids[-1]
    assert caplog.text == ""
