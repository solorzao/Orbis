"""Thread synopses' SQL (app.services.thread_synopsis) on a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied, 013 included. Every test runs in a transaction that is
rolled back. Skipped without it.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import thread_synopsis

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

NOW = datetime(2101, 1, 10, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
SYNOPSIS = (
    "Strikes against the pension reform spread from Paris to Lyon and Marseille "
    "on Tuesday. Unions said rail and port workers would stay out through Friday."
)


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
        await connection.execute("DELETE FROM thread_centroids")  # only this test's are active
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def _thread(
    conn,
    *,
    n_stories=5,
    countries=("FR", "BE"),
    n_sources=3,
    summarized_n=0,
    velocity=0,
    active=True,
    last_seen=NOW - HOUR,
) -> int:
    thread_id = await conn.fetchval(
        "INSERT INTO threads (centroid_sum, first_seen, last_seen, n_stories, n_sources,"
        " countries, summarized_n, velocity, lead_title)"
        " VALUES (array_fill(0.01, ARRAY[512])::vector, $1, $1, $2, $3, $4, $5, $6, 'Zz lead')"
        " RETURNING id",
        last_seen,
        n_stories,
        n_sources,
        list(countries),
        summarized_n,
        velocity,
    )
    if active:
        await conn.execute(
            "INSERT INTO thread_centroids (thread_id, last_seen, centroid)"
            " VALUES ($1, $2, l2_normalize(array_fill(0.01, ARRAY[512])::vector)::halfvec)",
            thread_id,
            NOW - HOUR,
        )
    return thread_id


async def _eligible(conn, now=NOW) -> list[int]:
    rows = await conn.fetch(thread_synopsis.ELIGIBLE_SQL, now - thread_synopsis.ACTIVE_WINDOW, now)
    return [r["id"] for r in rows]


async def _headlines(conn, thread_id: int, n: int) -> None:
    for i in range(n):
        article = await conn.fetchval(
            "INSERT INTO articles (title, source_url, source_name, published_at, latitude,"
            " longitude, location) VALUES ($1, $2, 'zz-a.test', $3, 0, 0,"
            " ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography) RETURNING id",
            f"Zz cough syrup deaths rise in town {i} - AP",
            f"https://zzsynopsis.test/{uuid.uuid4()}",
            NOW - i * HOUR,
        )
        await conn.execute(
            "INSERT INTO thread_members (article_id, thread_id, story_key, published_at,"
            " latitude, longitude, similarity) VALUES ($1, $2, $3, $4, 0, 0, 1)",
            article,
            thread_id,
            9400 + i,
            NOW - i * HOUR,
        )


@contextmanager
def _stubbed(conn, call):
    """get_pool, Claude and the cache stubbed, for summarise_threads on *conn*."""
    with (
        patch("app.services.thread_synopsis.get_pool", AsyncMock(return_value=conn)),
        patch("app.services.thread_synopsis._call_claude", call),
        patch("app.services.thread_synopsis.invalidate", new_callable=AsyncMock),
        patch("app.routers.threads.warm_threads", new_callable=AsyncMock),
    ):
        yield


@pytest.mark.asyncio
async def test_eligibility(conn):
    two_countries = await _thread(conn)
    five_outlets = await _thread(conn, countries=("FR",), n_sources=5)
    await _thread(conn, n_stories=4)  # too few stories
    await _thread(conn, countries=("FR",), n_sources=4)  # one country, four outlets
    await _thread(conn, countries=(), n_sources=4)
    await _thread(conn, n_sources=2)  # two countries, but never listed: 2 outlets
    await _thread(conn, active=False)  # inactive
    await _thread(conn, last_seen=NOW - 73 * HOUR)  # out of the active window

    assert set(await _eligible(conn)) == {two_countries, five_outlets}


@pytest.mark.asyncio
async def test_a_summarised_thread_comes_back_once_it_grows_by_half(conn):
    grown = await _thread(conn, n_stories=6, summarized_n=4)  # 6 >= 1.5 x 4
    await _thread(conn, n_stories=5, summarized_n=4)  # 5 < 6

    assert await _eligible(conn) == [grown]


@pytest.mark.asyncio
async def test_the_fastest_six_go_first(conn):
    ids = [await _thread(conn, velocity=v) for v in (1, 9, 3, 7, 5, 2, 8, 4)]
    by_velocity = dict(zip(ids, (1, 9, 3, 7, 5, 2, 8, 4)))

    eligible = await _eligible(conn)

    assert [by_velocity[i] for i in eligible] == [9, 8, 7, 5, 4, 3]


@pytest.mark.asyncio
async def test_eligibility_reads_listed_threads_by_the_partial_index(conn):
    """Not every active thread: mostly single-story ones, never listed. The planner's
    own choice, on statistics this test sets for both tables the query reads: with
    thread_centroids' left to earlier tests, a near-empty estimate could drive the
    semi-join from it instead."""
    # Rolled back, 2000 centroids would stay in the HNSW graph as dead entries that
    # crowd later tests' nearest neighbours out (scoring then returned 13775 of
    # 16500). Dropped in this transaction (eligibility doesn't use it), the index
    # never sees them; the rollback restores it.
    await conn.execute("DROP INDEX idx_thread_centroids_hnsw")
    await conn.execute(
        """
        WITH t AS (
            INSERT INTO threads (centroid_sum, first_seen, last_seen, n_stories, n_sources)
            SELECT array_fill(0.01, ARRAY[512])::vector, $1::timestamptz,
                   $1::timestamptz - i * interval '2 minutes',
                   CASE WHEN i <= 10 THEN 6 ELSE 1 END, CASE WHEN i <= 10 THEN 6 ELSE 1 END
            FROM generate_series(1, 2000) AS i
            RETURNING id, last_seen
        )
        INSERT INTO thread_centroids (thread_id, last_seen, centroid)
        SELECT id, last_seen, l2_normalize(array_fill(0.01, ARRAY[512])::vector)::halfvec FROM t
        """,
        NOW,
    )
    await conn.execute("ANALYZE threads, thread_centroids")

    plan = "\n".join(
        r[0]
        for r in await conn.fetch(
            "EXPLAIN " + thread_synopsis.ELIGIBLE_SQL, NOW - thread_synopsis.ACTIVE_WINDOW, NOW
        )
    )

    assert "idx_threads_listed" in plan
    assert "Seq Scan on thread_centroids" not in plan


@pytest.mark.asyncio
async def test_a_synopsis_is_written_with_the_story_count_it_covers(conn):
    thread_id = await _thread(conn, n_stories=7)
    for i in range(3):
        article = await conn.fetchval(
            "INSERT INTO articles (title, source_url, source_name, published_at, latitude,"
            " longitude, location) VALUES ($1, $2, 'zz-a.test', $3, 0, 0,"
            " ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography) RETURNING id",
            f"Zz strikes spread to city {i} - AP",
            f"https://zzsynopsis.test/{uuid.uuid4()}",
            NOW - i * HOUR,
        )
        await conn.execute(
            "INSERT INTO thread_members (article_id, thread_id, story_key, published_at,"
            " latitude, longitude, similarity) VALUES ($1, $2, $3, $4, 0, 0, 1)",
            article,
            thread_id,
            9300 + i,
            NOW - i * HOUR,
        )
    reply = json.dumps({"title": "Zz strikes spread", "synopsis": SYNOPSIS})
    call = AsyncMock(return_value=reply)
    with (
        patch("app.services.thread_synopsis.get_pool", AsyncMock(return_value=conn)),
        patch("app.services.thread_synopsis._call_claude", call),
        patch("app.services.thread_synopsis.invalidate", new_callable=AsyncMock),
        patch("app.routers.threads.warm_threads", new_callable=AsyncMock),
    ):
        assert await thread_synopsis.summarise_threads(now=NOW) == 1

    prompt = call.await_args.args[0]
    assert prompt == (
        "<headlines>\n"
        "- Zz strikes spread to city 0 (zz-a.test)\n"
        "- Zz strikes spread to city 1 (zz-a.test)\n"
        "- Zz strikes spread to city 2 (zz-a.test)\n"
        "</headlines>"
    )
    row = await conn.fetchrow(
        "SELECT title, synopsis, summarized_at, summarized_n FROM threads WHERE id = $1",
        thread_id,
    )
    assert (row["title"], row["synopsis"], row["summarized_n"]) == (
        "Zz strikes spread",
        SYNOPSIS,
        7,
    )
    assert row["summarized_at"] is not None
    assert thread_id not in await _eligible(conn)  # until it reaches 11 stories


# --- backing off -------------------------------------------------------------------------

LINKED = json.dumps(
    {
        "title": "Cough syrup deaths rise",
        "synopsis": "Child deaths in several towns have been linked to a contaminated cough syrup.",
    }
)


async def _backoff(conn, thread_id):
    return tuple(
        await conn.fetchrow(
            "SELECT synopsis_failures, synopsis_retry_at FROM threads WHERE id = $1", thread_id
        )
    )


@pytest.mark.asyncio
async def test_a_rejected_reply_is_not_asked_again_until_its_backoff_ends(conn):
    """Two hours after the first failure, then four after the second; a synopsis
    clears them. Before, it was asked again every cycle, taking a slot of the six."""
    thread_id = await _thread(conn, n_stories=7)
    await _headlines(conn, thread_id, 3)
    call = AsyncMock(return_value=LINKED)

    with _stubbed(conn, call):
        assert await thread_synopsis.summarise_threads(now=NOW) == 0
        first = await _backoff(conn, thread_id)
        assert await thread_synopsis.summarise_threads(now=NOW + 15 * MINUTE) == 0
        asked_next_cycle = call.await_count
        assert await thread_synopsis.summarise_threads(now=NOW + 2 * HOUR) == 0
        second = await _backoff(conn, thread_id)
        assert await thread_synopsis.summarise_threads(now=NOW + 5 * HOUR) == 0
        asked_before_the_second_ends = call.await_count
        call.return_value = json.dumps({"title": "Zz cough syrup deaths", "synopsis": SYNOPSIS})
        assert await thread_synopsis.summarise_threads(now=NOW + 6 * HOUR) == 1

    assert first == (1, NOW + 2 * HOUR)
    assert asked_next_cycle == 1
    assert second == (2, NOW + 6 * HOUR)
    assert asked_before_the_second_ends == 2
    assert call.await_count == 3
    assert await _backoff(conn, thread_id) == (0, None)
    row = await conn.fetchrow("SELECT title, synopsis FROM threads WHERE id = $1", thread_id)
    assert tuple(row) == ("Zz cough syrup deaths", SYNOPSIS)


@pytest.mark.asyncio
async def test_a_thread_without_usable_headlines_backs_off_without_a_call(conn):
    thread_id = await _thread(conn, n_stories=7)  # no members: no headline at all
    call = AsyncMock(return_value=LINKED)

    with _stubbed(conn, call):
        assert await thread_synopsis.summarise_threads(now=NOW) == 0

    call.assert_not_awaited()
    assert await _backoff(conn, thread_id) == (1, NOW + 2 * HOUR)
    assert thread_id not in await _eligible(conn, NOW + HOUR)
    assert thread_id in await _eligible(conn, NOW + 2 * HOUR)


@pytest.mark.asyncio
async def test_the_backoff_doubles_up_to_a_day_without_overflowing(conn):
    thread_id = await _thread(conn, n_stories=7)
    await conn.execute("UPDATE threads SET synopsis_failures = 1000 WHERE id = $1", thread_id)

    row = await conn.fetchrow(thread_synopsis.FAILED_SQL, thread_id, NOW)

    assert tuple(row) == (1001, NOW + 24 * HOUR)
