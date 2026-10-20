"""The investigation board's reads on a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (017 included). Every test runs in a transaction that is
rolled back, so nothing it inserts is ever committed. Its articles are titled
``zzboard ...`` on ``zzboard.test`` and placed in the empty South Pacific;
its people and organisations are named ``Zzboard ...``. Skipped without the
variable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import board, knowledge_graph

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

# Cells no other fixture uses: open ocean.
CELL = (-47, -121)
QUIET_CELL = (-48, -122)
EMPTY_CELL = (-49, -123)


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


class _Pool:
    """The pool as the services use it, on the test's connection, one query at a time."""

    def __init__(self, connection):
        self._conn = connection
        self._lock = asyncio.Lock()

    async def fetch(self, sql, *args, timeout=None):
        async with self._lock:
            return await self._conn.fetch(sql, *args, timeout=timeout)

    async def fetchrow(self, sql, *args, timeout=None):
        async with self._lock:
            return await self._conn.fetchrow(sql, *args, timeout=timeout)

    async def fetchval(self, sql, *args, timeout=None):
        async with self._lock:
            return await self._conn.fetchval(sql, *args, timeout=timeout)


@pytest_asyncio.fixture
async def pool(conn):
    stand_in = _Pool(conn)
    with contextlib.ExitStack() as stack:
        for module in ("board", "entities"):
            stack.enter_context(
                patch(
                    f"app.services.{module}.get_pool",
                    new_callable=AsyncMock,
                    return_value=stand_in,
                )
            )
        yield stand_in


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _article(
    conn,
    title="zzboard story",
    *,
    hours_ago: float = 1,
    cell=CELL,
    region="Zzboard Town, France",
    country="FR",
    url=None,
) -> str:
    lat, lng = cell[0] + 0.25, cell[1] + 0.25
    return str(
        await conn.fetchval(
            """
            INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                                  longitude, location, region, country_code)
            VALUES ($1, $2, 'zzboard.test', now() - make_interval(secs => $3), $4, $5,
                    ST_SetSRID(ST_MakePoint($5, $4), 4326)::geography, $6, $7)
            RETURNING id
            """,
            title,
            url or f"https://zzboard.test/{uuid.uuid4()}",
            hours_ago * 3600,
            lat,
            lng,
            region,
            country,
        )
    )


async def _thread(conn, *, title=None, lead="zzboard lead", places=(), top_entities=()):
    return await conn.fetchval(
        """
        INSERT INTO threads (centroid_sum, first_seen, last_seen, n_stories, n_sources,
                             title, lead_title, places, top_entities)
        VALUES (array_fill(0.01, ARRAY[512])::vector, now() - interval '5 hours',
                now() - interval '1 hour', 3, 3, $1, $2, $3::jsonb, $4)
        RETURNING id
        """,
        title,
        lead,
        json.dumps(list(places)),
        list(top_entities),
    )


async def _member(conn, thread, *, article_id=None, entities=(), cell=CELL, hours_ago=1, **kw):
    article_id = article_id or str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO thread_members (article_id, thread_id, story_key, source_name,
                                    published_at, latitude, longitude, region,
                                    country_code, entities, tone, similarity)
        VALUES ($1::uuid, $2, $3, 'zzboard.test', now() - make_interval(secs => $4), $5, $6,
                $7, $8, $9, -0.2, 1.0)
        """,
        article_id,
        thread,
        kw.get("story"),
        hours_ago * 3600,
        cell[0] + 0.25,
        cell[1] + 0.25,
        kw.get("region", "Zzboard Town, France"),
        kw.get("country", "FR"),
        list(entities),
    )
    return article_id


async def _resolve(*ids: str) -> list[dict | None]:
    return await board.resolve_items([board.parse_item(i) for i in ids], _now())


# --- Resolve ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_an_article_resolves_to_its_headline_place_and_link(conn):
    article = await _article(
        conn, "zzboard strikes spread - Reuters", url="https://zzboard.test/strikes"
    )

    snapshot, missing = await _resolve(f"article:{article}", f"article:{uuid.uuid4()}")

    assert snapshot["title"] == "zzboard strikes spread"
    assert snapshot["place"] == "Zzboard Town, France"
    assert (snapshot["lat"], snapshot["lng"]) == (CELL[0] + 0.25, CELL[1] + 0.25)
    assert snapshot["url"] == "https://zzboard.test/strikes"
    assert _now() - timedelta(hours=2) < snapshot["time"] < _now()
    assert missing is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_a_thread_resolves_to_its_title_and_first_place(conn):
    places = [
        {"lat": -47.7, "lng": -120.6, "region": "Zzboard First, France", "country_code": "FR"},
        {"lat": -46.7, "lng": -119.6, "region": "Zzboard Later, Spain", "country_code": "ES"},
    ]
    thread = await _thread(conn, title="zzboard pension strikes", places=places)
    untitled = await _thread(conn, lead="zzboard lead headline")

    titled, fallback, gone = await _resolve(
        f"thread:{thread}", f"thread:{untitled}", "thread:9223372036854775807"
    )

    assert titled["title"] == "zzboard pension strikes"
    assert (titled["place"], titled["lat"], titled["lng"]) == (
        "Zzboard First, France",
        -47.7,
        -120.6,
    )
    assert fallback["title"] == "zzboard lead headline"
    assert fallback["place"] is None
    assert gone is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_a_place_resolves_to_its_newest_storys_place_name(conn):
    await _article(conn, hours_ago=50, region="Zzboard Old, France")
    await _article(conn, hours_ago=2, region="Zzboard New, France")
    await _article(
        conn, hours_ago=1, region="Zzboard Elsewhere, Chile", cell=(CELL[0] + 1, CELL[1])
    )
    await _article(conn, hours_ago=30, cell=QUIET_CELL, region="Zzboard Quiet, France")
    await _article(conn, hours_ago=24 * 9, cell=EMPTY_CELL, region="Zzboard Purged, France")

    busy, quiet, empty = await _resolve(
        "place:{}:{}".format(*CELL),
        "place:{}:{}".format(*QUIET_CELL),
        "place:{}:{}".format(*EMPTY_CELL),
    )

    assert busy["title"] == busy["place"] == "Zzboard New, France"
    assert (busy["lat"], busy["lng"]) == (CELL[0] + 0.5, CELL[1] + 0.5)
    assert quiet["title"] == "Zzboard Quiet, France"  # found in the week's window
    assert empty is None  # its only story is older than the week


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_an_entity_resolves_to_its_stored_name_and_top_place(conn):
    await knowledge_graph.upsert_node(conn, "PERSON", "Zzboard Person", {})
    await knowledge_graph.upsert_node(conn, "ORG", "Zzboard Org", {})
    thread = await _thread(conn)
    for story in range(3):
        await _member(conn, thread, entities=["Zzboard Person"], story=story)
    await _member(
        conn,
        thread,
        entities=["Zzboard Person"],
        cell=QUIET_CELL,
        region="Zzboard Quiet, France",
    )

    person, org, unknown, wrong_type = await _resolve(
        "entity:person:zzboard person",
        "entity:org:Zzboard Org",
        "entity:person:Zzboard Nobody",
        "entity:org:Zzboard Person",
    )

    assert person["title"] == "Zzboard Person"  # the stored spelling
    assert person["place"] == "Zzboard Town, France"  # 3 stories there, 1 elsewhere
    assert org["title"] == "Zzboard Org"
    assert org["place"] is None  # no stories this week
    assert unknown is None
    assert wrong_type is None
