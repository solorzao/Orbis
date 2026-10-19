"""Story-thread assignment (app.services.threads) on a real PostgreSQL with pgvector.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied, 013 included. Every test runs in a transaction that is
rolled back. Skipped without it.

Embeddings are hand-built: their first 512 dimensions carry chosen unit
directions, so two stories' cosine is known exactly. NOW is far in the
future: every window reaches back from NOW, so only these rows fall in it.
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.services import threads

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
    try:
        # Only this test's threads are active (rolled back with the rest).
        await connection.execute("DELETE FROM thread_centroids")
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


def _direction(cos: float, other: int = 1) -> dict[int, float]:
    """A unit direction at cosine *cos* to dimension 0, leaning on dimension *other*."""
    return {0: cos, other: math.sqrt(1 - cos * cos)}


def _vector(weights: dict[int, float], dims: int) -> str:
    values = [0.0] * dims
    for dim, value in weights.items():
        values[dim] = value
    return "[" + ",".join(repr(v) for v in values) + "]"


_counter = iter(range(10**6))


async def _article(
    conn,
    weights: dict[int, float] | None = None,
    published_at: datetime = NOW - HOUR,
    *,
    title: str | None = None,
    story_key: int | None = None,
    source: str = "zz-a.test",
    persons: tuple[str, ...] = (),
    orgs: tuple[str, ...] = (),
    lat: float = 10.5,
    lng: float = 20.5,
    region: str = "Zz Alpha",
    country_code: str = "ZA",
    topic: str = "politics",
    image_url: str | None = None,
) -> uuid.UUID:
    """An embedded article whose 512-d prefix points along *weights* (dimension 0 by default)."""
    n = next(_counter)
    return await conn.fetchval(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude, longitude,
                              location, region, country_code, topic_tags, image_url, persons,
                              orgs, story_key, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_MakePoint($6, $5), 4326)::geography,
                $7, $8, $9, $10, $11, $12, $13, $14::vector)
        RETURNING id
        """,
        title or f"Zzthread story number {n} today",
        f"https://zzthreads.test/{n}/{uuid.uuid4()}",
        source,
        published_at,
        lat,
        lng,
        region,
        country_code,
        [topic] if topic else [],
        image_url,
        list(persons),
        list(orgs),
        story_key,
        _vector(weights or {0: 1.0}, 1536),
    )


async def _assign(conn, ids=()):
    return await threads.assign_threads(conn, list(ids), now=NOW)


async def _thread_of(conn, article_id):
    return await conn.fetchval(
        "SELECT thread_id FROM thread_members WHERE article_id = $1", article_id
    )


async def _similarity(conn, article_id) -> float:
    return await conn.fetchval(
        "SELECT similarity FROM thread_members WHERE article_id = $1", article_id
    )


async def _thread(conn, thread_id):
    return await conn.fetchrow("SELECT * FROM threads WHERE id = $1", thread_id)


async def _centroid(conn, thread_id):
    return await conn.fetchrow(
        "SELECT thread_id, last_seen, n_stories, centroid::text AS centroid"
        " FROM thread_centroids WHERE thread_id = $1",
        thread_id,
    )


async def _centroid_version(conn, thread_id):
    """The centroid row's version: any write (even of the same values) changes it.

    Each placement runs in its own savepoint, so its writes carry their own xmin."""
    row = await conn.fetchrow(
        "SELECT xmin::text, ctid::text FROM thread_centroids WHERE thread_id = $1", thread_id
    )
    return tuple(row) if row else None


async def _cos(conn, thread_id, weights) -> float:
    """The thread's unit centroid's cosine with a 512-d direction."""
    return await conn.fetchval(
        "SELECT -(centroid <#> $2::halfvec(512)) FROM thread_centroids WHERE thread_id = $1",
        thread_id,
        _vector(weights, 512),
    )


async def _plan(conn, sql, *args) -> str:
    return "\n".join(r[0] for r in await conn.fetch("EXPLAIN " + sql, *args))


# --- query plans --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_batched_score_query_uses_the_hnsw_index(conn):
    """The exact text-parameter form: vectors travel as text, cast in the LATERAL."""
    await _assign(conn, [await _article(conn)])
    await conn.execute("SET LOCAL enable_seqscan = off")
    await conn.execute("SET LOCAL hnsw.ef_search = 100")

    plan = await _plan(
        conn, threads.SCORE_SQL, [0, 1], [_vector({0: 1.0}, 512), _vector({1: 1.0}, 512)], 15
    )

    assert "idx_thread_centroids_hnsw" in plan


@pytest.mark.asyncio
async def test_assignment_never_scans_the_articles_heap(conn):
    """CI's near-empty tables make seq scans cheapest, so this asserts that the index
    paths exist and are taken with seq scans off, not on pg_stat counters."""
    await conn.execute("SET LOCAL enable_seqscan = off")

    plans = {
        "backlog": await _plan(
            conn, threads.BACKLOG_SQL, NOW - 6 * HOUR, threads.MIN_TITLE_WORDS, 500, [uuid.uuid4()]
        ),
        "load": await _plan(conn, threads.LOAD_SQL, [uuid.uuid4()]),
        "lead titles": await _plan(conn, threads.LEAD_TITLES_SQL, [1, 2]),
    }

    for name, plan in plans.items():
        assert "Seq Scan on articles" not in plan, name
    assert "Seq Scan on threads" not in plans["lead titles"]
    assert "idx_articles_published_at" in plans["backlog"]
    assert "articles_pkey" in plans["load"]
    assert "articles_pkey" in plans["lead titles"]


@pytest.mark.asyncio
async def test_the_aggregate_step_finds_unaggregated_threads_by_the_partial_index(conn):
    """Most threads are aggregated; the few a failed cycle left are found by index."""
    await conn.execute(
        "INSERT INTO threads (centroid_sum, first_seen, last_seen, aggregated_at)"
        " SELECT array_fill(0.01, ARRAY[512])::vector, $1::timestamptz, $1::timestamptz,"
        " CASE WHEN i > 3 THEN $1::timestamptz END"
        " FROM generate_series(1, 300) AS i",
        NOW - HOUR,
    )
    await conn.execute("ANALYZE threads")
    await conn.execute("SET LOCAL enable_seqscan = off")

    plan = await _plan(conn, threads.AGGREGATE_SQL, [1, 2], NOW)

    assert "idx_threads_unaggregated" in plan


# --- joining --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_story_at_cosine_085_joins(conn):
    seed = await _article(conn, published_at=NOW - 2 * HOUR)
    await _assign(conn, [seed])
    story = await _article(conn, _direction(0.85))

    stats = await _assign(conn, [story])

    assert await _thread_of(conn, story) == await _thread_of(conn, seed)
    assert await _similarity(conn, story) == pytest.approx(0.85, abs=0.005)
    assert (stats.joined, stats.started) == (1, 0)


@pytest.mark.asyncio
async def test_a_story_at_cosine_070_joins_only_with_a_shared_specific_person(conn):
    seed = await _article(conn, published_at=NOW - 3 * HOUR, persons=("Zz Jane Specific",))
    await _assign(conn, [seed])
    sharing = await _article(conn, _direction(0.70), NOW - 2 * HOUR, persons=("Zz Jane Specific",))
    unrelated = await _article(conn, _direction(0.70, other=2), NOW - HOUR)

    await _assign(conn, [sharing, unrelated])

    thread = await _thread_of(conn, seed)
    assert await _thread_of(conn, sharing) == thread
    assert await _thread_of(conn, unrelated) not in (None, thread)


@pytest.mark.asyncio
async def test_a_story_at_cosine_070_sharing_only_a_generic_person_starts_a_thread(conn):
    """In more than one active thread (and more than 1% of them), a name is generic."""
    seed = await _article(conn, published_at=NOW - 3 * HOUR, persons=("Zz Generic Person",))
    other = await _article(conn, {5: 1.0}, NOW - 3 * HOUR, persons=("Zz Generic Person",))
    await _assign(conn, [seed, other])
    assert await _thread_of(conn, seed) != await _thread_of(conn, other)
    story = await _article(conn, _direction(0.70), persons=("Zz Generic Person",))

    await _assign(conn, [story])

    assert await _thread_of(conn, story) not in (
        None,
        await _thread_of(conn, seed),
        await _thread_of(conn, other),
    )


@pytest.mark.asyncio
async def test_a_copy_joins_without_changing_the_centroid(conn):
    seed = await _article(conn, published_at=NOW - 2 * HOUR, story_key=9001)
    await _assign(conn, [seed])
    thread = await _thread_of(conn, seed)
    before = await _thread(conn, thread)
    row_before = await _centroid_version(conn, thread)
    copy = await _article(conn, {3: 1.0}, NOW - HOUR, story_key=9001, source="zz-b.test")

    stats = await _assign(conn, [copy])

    after = await _thread(conn, thread)
    assert await _thread_of(conn, copy) == thread
    assert await _similarity(conn, copy) == 1.0
    assert stats.copies == 1
    assert after["centroid_sum"] == before["centroid_sum"]
    # Untouched: the same row version, so no new HNSW entry and no dead one.
    assert await _centroid_version(conn, thread) == row_before
    assert after["last_seen"] == NOW - HOUR  # the thread itself stays active and listed
    assert (after["n_articles"], after["n_stories"], after["n_sources"]) == (2, 1, 2)


@pytest.mark.asyncio
async def test_a_copy_reactivates_an_inactive_thread(conn):
    seed = await _article(conn, published_at=NOW - 26 * HOUR, story_key=9002)
    await threads.assign_threads(conn, [seed], now=NOW - 25 * HOUR)
    thread = await _thread_of(conn, seed)
    centroid = (await _centroid(conn, thread))["centroid"]
    await _assign(conn)  # a singleton 26 hours old: inactive
    assert await _centroid(conn, thread) is None
    copy = await _article(conn, {3: 1.0}, NOW - HOUR, story_key=9002, source="zz-b.test")

    await _assign(conn, [copy])

    assert await _thread_of(conn, copy) == thread
    row = await _centroid(conn, thread)
    assert row is not None
    assert row["centroid"] == centroid  # the story's own vector, not the copy's


@pytest.mark.asyncio
async def test_an_article_already_a_member_changes_nothing(conn):
    seed = await _article(conn)
    await _assign(conn, [seed])
    thread = await _thread_of(conn, seed)
    before = await _thread(conn, thread)

    stats = await _assign(conn, [seed])

    after = await _thread(conn, thread)
    assert stats.assigned == 0
    assert after["centroid_sum"] == before["centroid_sum"]
    assert after["n_articles"] == 1


@pytest.mark.asyncio
async def test_the_centroid_decays_toward_the_newer_topic(conn):
    """Ten stories on one topic, then ten on a nearby one: the sum is DECAY-weighted,
    so the thread ends closer to the newer topic (an even mix would be equidistant)."""
    old, new = {0: 1.0}, _direction(0.82)
    ids = [
        await _article(conn, old if i < 10 else new, NOW - 5 * HOUR + i * timedelta(minutes=5))
        for i in range(20)
    ]

    stats = await _assign(conn, ids)

    [thread] = {await _thread_of(conn, i) for i in ids}
    assert (stats.started, stats.joined) == (1, 19)
    expected = [0.0] * 512
    for i in range(20):
        v = _vector(old if i < 10 else new, 512)
        vector = threads.parse_vector(v)
        expected = vector if i == 0 else threads.decayed_sum(expected, vector)
    stored = threads.parse_vector((await _thread(conn, thread))["centroid_sum"])
    assert stored == pytest.approx(expected, abs=0.02)
    assert await _cos(conn, thread, new) > await _cos(conn, thread, old) + 0.02


# --- aggregates -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_aggregates_count_stories_outlets_places_entities_and_the_lead(conn):
    a1 = await _article(
        conn,
        published_at=NOW - 5 * HOUR,
        story_key=9101,
        persons=("Zz Jane Specific",),
        orgs=("Zz Org",),
    )
    a2 = await _article(  # a copy of a1, in the same 1-degree cell
        conn,
        published_at=NOW - 4 * HOUR,
        story_key=9101,
        source="zz-b.test",
        lat=10.6,
        lng=20.6,
        persons=("Zz Jane Specific",),
        image_url="https://zzthreads.test/a2.jpg",
    )
    a3 = await _article(
        conn,
        published_at=NOW - 3 * HOUR,
        title="Zzthread lead story breaks - Reuters",
        story_key=9102,
        source="zz-c.test",
        lat=-5.5,
        lng=30.2,
        region="Zz Beta",
        country_code="ZB",
        topic="conflict",
        persons=("Zz Kim Other",),
        orgs=("Zz Org",),
        image_url="https://zzthreads.test/a3.jpg",
    )
    a4 = await _article(  # no story_key: a story of its own
        conn,
        published_at=NOW - 2 * HOUR,
        lat=10.9,
        lng=20.1,
        orgs=("Zz Org",),
        image_url="http://zzthreads.test/insecure.jpg",
    )

    await _assign(conn, [a1, a2, a3, a4])

    [thread_id] = {await _thread_of(conn, a) for a in (a1, a2, a3, a4)}
    t = await _thread(conn, thread_id)
    assert (t["n_articles"], t["n_stories"], t["n_sources"]) == (4, 3, 3)
    assert t["countries"] == ["ZA", "ZB"]
    assert (t["first_seen"], t["last_seen"]) == (NOW - 5 * HOUR, NOW - 2 * HOUR)
    places = json.loads(t["places"])
    assert [(p["lat"], p["lng"], p["region"], p["country_code"], p["n"]) for p in places] == [
        (10.5, 20.5, "Zz Alpha", "ZA", 2),
        (-5.5, 30.2, "Zz Beta", "ZB", 1),
    ]
    assert [datetime.fromisoformat(p["first_seen"]) for p in places] == [
        NOW - 5 * HOUR,
        NOW - 3 * HOUR,
    ]
    assert t["top_entities"] == ["Zz Org", "Zz Jane Specific", "Zz Kim Other"]
    assert t["topic"] == "politics"
    assert t["lead_article_id"] == a3  # the newest with an https image
    assert t["lead_title"] == "Zzthread lead story breaks"
    assert t["velocity"] == 3
    assert t["aggregated_at"] == NOW


@pytest.mark.asyncio
async def test_places_keep_the_first_30_cells_in_report_order(conn):
    ids = [
        await _article(
            conn,
            published_at=NOW - 5 * HOUR + i * timedelta(minutes=1),
            lat=-60.5 + 3 * i,
            lng=0.5,
        )
        for i in range(32)
    ]

    await _assign(conn, ids)

    [thread_id] = {await _thread_of(conn, i) for i in ids}
    places = json.loads((await _thread(conn, thread_id))["places"])
    assert [p["lat"] for p in places] == [-60.5 + 3 * i for i in range(30)]


@pytest.mark.asyncio
async def test_a_thread_left_unaggregated_by_a_failed_cycle_is_repaired(conn):
    seed = await _article(conn, published_at=NOW - 2 * HOUR)
    await _assign(conn, [seed])
    thread = await _thread_of(conn, seed)
    story = await _article(conn, _direction(0.9), NOW - 3 * HOUR)  # older than the last run
    # A cycle that placed the story, then failed before its aggregate step:
    articles = [threads._Article.from_row(r) for r in await conn.fetch(threads.LOAD_SQL, [story])]
    await threads._assign(conn, articles, threads.ThreadStats(), time.monotonic())

    await _assign(conn)

    t = await _thread(conn, thread)
    assert await _thread_of(conn, story) == thread
    assert (t["n_articles"], t["first_seen"], t["aggregated_at"]) == (2, NOW - 3 * HOUR, NOW)


# --- velocity, deactivation, retention ----------------------------------------------


async def _bare_thread(conn, last_seen, *, velocity=0, n_stories=1, active=False) -> int:
    thread_id = await conn.fetchval(
        "INSERT INTO threads (centroid_sum, first_seen, last_seen, velocity, n_stories,"
        " aggregated_at) VALUES ($1::vector, $2, $2, $3, $4, $5) RETURNING id",
        _vector({7: 1.0}, 512),
        last_seen,
        velocity,
        n_stories,
        NOW,
    )
    if active:
        await conn.execute(
            "INSERT INTO thread_centroids (thread_id, last_seen, n_stories, centroid)"
            " VALUES ($1, $2, $3, $4::halfvec(512))",
            thread_id,
            last_seen,
            n_stories,
            _vector({7: 1.0}, 512),
        )
    return thread_id


async def _bare_member(conn, thread_id, published_at, story_key=None) -> uuid.UUID:
    article_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO thread_members (article_id, thread_id, story_key, published_at, latitude,"
        " longitude, similarity) VALUES ($1, $2, $3, $4, 1, 2, 1)",
        article_id,
        thread_id,
        story_key,
        published_at,
    )
    return article_id


@pytest.mark.asyncio
async def test_velocity_updates_only_the_rows_that_change(conn):
    steady = await _bare_thread(conn, NOW - HOUR, velocity=1)
    await _bare_member(conn, steady, NOW - HOUR)
    rising = await _bare_thread(conn, NOW - HOUR)
    await _bare_member(conn, rising, NOW - 2 * HOUR, story_key=9201)
    await _bare_member(conn, rising, NOW - HOUR, story_key=9201)  # a copy counts once
    await _bare_member(conn, rising, NOW - HOUR, story_key=9202)
    stale = await _bare_thread(conn, NOW - 10 * HOUR, velocity=3)
    await _bare_member(conn, stale, NOW - 10 * HOUR)
    quiet = await _bare_thread(conn, NOW - 10 * HOUR)

    status = await conn.execute(threads.VELOCITY_SQL, NOW - 6 * HOUR, NOW - 72 * HOUR)

    assert status == "UPDATE 2"
    velocities = {
        r["id"]: r["velocity"]
        for r in await conn.fetch(
            "SELECT id, velocity FROM threads WHERE id = ANY($1::bigint[])",
            [steady, rising, stale, quiet],
        )
    }
    assert velocities == {steady: 1, rising: 2, stale: 0, quiet: 0}


@pytest.mark.asyncio
async def test_threads_go_inactive_after_24_hours_alone_or_72_hours(conn):
    fresh_singleton = await _bare_thread(conn, NOW - 23 * HOUR, active=True)
    old_singleton = await _bare_thread(conn, NOW - 25 * HOUR, active=True)
    fresh_thread = await _bare_thread(conn, NOW - 71 * HOUR, n_stories=2, active=True)
    old_thread = await _bare_thread(conn, NOW - 73 * HOUR, n_stories=2, active=True)
    # The centroid row's own last_seen and n_stories are informational (set at insert):
    # a thread that grew, and was seen since, stays active whatever its row says.
    grown = await _bare_thread(conn, NOW - 30 * HOUR, n_stories=2, active=True)
    await conn.execute(
        "UPDATE thread_centroids SET n_stories = 1, last_seen = $2 WHERE thread_id = $1",
        grown,
        NOW - 80 * HOUR,
    )

    stats = await _assign(conn)

    active = {r["thread_id"] for r in await conn.fetch("SELECT thread_id FROM thread_centroids")}
    assert active == {fresh_singleton, fresh_thread, grown}
    assert stats.active == 3
    left = await conn.fetchval(
        "SELECT count(*) FROM threads WHERE id = ANY($1::bigint[])",
        [fresh_singleton, old_singleton, fresh_thread, old_thread, grown],
    )
    assert left == 5  # inactive, not deleted


@pytest.mark.asyncio
async def test_retention_deletes_old_members_and_old_threads(conn):
    current = await _bare_thread(conn, NOW - 24 * HOUR)
    old_member = await _bare_member(conn, current, NOW - 31 * 24 * HOUR)
    new_member = await _bare_member(conn, current, NOW - 24 * HOUR)
    old = await _bare_thread(conn, NOW - 31 * 24 * HOUR, active=True)
    await _bare_member(conn, old, NOW - 31 * 24 * HOUR)

    await threads.purge_threads(conn, 30, now=NOW)

    members = {
        r["article_id"]
        for r in await conn.fetch(
            "SELECT article_id FROM thread_members WHERE thread_id = ANY($1::bigint[])",
            [current, old],
        )
    }
    assert members == {new_member}
    assert old_member not in members
    assert await _thread(conn, old) is None
    assert await _centroid(conn, old) is None
    assert await _thread(conn, current) is not None


# --- the backlog ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_titles_cannot_starve_the_backlog(conn):
    """600 older short titles, filtered in SQL, don't fill the 500 cap (oldest first)."""
    good = await _article(conn, published_at=NOW - HOUR)
    await conn.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude, longitude,
                              location, embedding)
        SELECT 'Zz short ' || i, 'https://zzthreads.test/short/' || i || '/' || $2, 'zz-a.test',
               $1, 0, 0, ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography, $3::vector
        FROM generate_series(1, 600) AS i
        """,
        NOW - 2 * HOUR,
        str(uuid.uuid4()),
        _vector({0: 1.0}, 1536),
    )

    stats = await _assign(conn)

    assert await _thread_of(conn, good) is not None
    assert stats.assigned == 1


@pytest.mark.asyncio
async def test_articles_left_by_a_time_budget_cut_are_assigned_next_cycle(conn, monkeypatch):
    """The backlog skips the cycle's own ids and takes the oldest first, so newer
    articles can't keep crowding the leftovers out until they age past 6 hours."""
    left = await _article(conn, {0: 1.0}, NOW - 5 * HOUR)
    monkeypatch.setattr(threads, "TIME_BUDGET_S", -1)  # out of time before the first
    cut = await _assign(conn, [left])
    assert (cut.assigned, cut.deferred) == (0, 1)
    assert await _thread_of(conn, left) is None

    monkeypatch.setattr(threads, "TIME_BUDGET_S", 60)
    monkeypatch.setattr(threads, "BACKLOG_LIMIT", 2)
    newer = [await _article(conn, {i: 1.0}, NOW - HOUR) for i in (5, 6, 7)]
    stats = await _assign(conn, newer)

    assert await _thread_of(conn, left) is not None
    assert stats.assigned == 4
