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


# --- Edges ------------------------------------------------------------------------


def _edge(a, b, kind, label):
    return {"a": a, "b": b, "kind": kind, "label": label}


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_edges_from_members_threads_names_cells_and_listed_pairs(conn):
    await knowledge_graph.upsert_node(conn, "PERSON", "Zzboard Ann", {})
    shared = await _thread(conn, top_entities=["Zzboard Bo"])
    other = await _thread(conn, top_entities=["Zzboard Cy"])
    first = await _article(conn, "zzboard first", hours_ago=1, country="FR")
    second = await _article(conn, "zzboard second", hours_ago=2, cell=QUIET_CELL, country="NG")
    await _member(conn, shared, article_id=first, entities=["Zzboard Ann", "Zzboard Bo"])
    await _member(conn, shared, article_id=second, entities=["Zzboard Bo"], cell=QUIET_CELL)
    await _member(conn, other, entities=["Zzboard Cy", "Zzboard Ann"])  # not pinned
    a1, a2 = f"article:{first}", f"article:{second}"
    ann, place = "entity:person:zzboard ann", "place:{}:{}".format(*CELL)

    edges = await board.board_edges(
        [board.parse_item(i) for i in (a1, a2, f"thread:{other}", ann, place)],
        {frozenset({"FR", "NG"})},
        _now(),
    )

    nigeria_france = "covered together: France and Nigeria"
    assert edges == [
        _edge(a1, a2, "same_thread", "same thread"),
        _edge(a1, a2, "shared_entity", "shared: Zzboard Bo"),
        _edge(a1, a2, "co_covered", nigeria_france),
        _edge(a1, ann, "shared_entity", "shared: Zzboard Ann"),
        _edge(a1, place, "same_place", "same place"),
        _edge(a2, place, "co_covered", nigeria_france),  # the place's newest story is French
        _edge(f"thread:{other}", ann, "shared_entity", "shared: Zzboard Ann"),
    ]


# --- Plans at production's scale ----------------------------------------------------
#
# A week of production: about 60K articles (wide rows), 100K thread members and
# 5K threads, with a few busy cells and a few names in a fifth of the members.
# No enable_seqscan here: these are the planner's own choices, custom (the
# first executions of a prepared statement) and generic (asyncpg reuses its
# prepared statements, and PostgreSQL may switch one to a generic plan).

_FILLED = ("articles", "thread_members", "threads")
_BUSY_CELLS = ((51, 0), (40, -74), (38, -77), (48, 2))
_OLD_CELL = (-70, 10)  # only stories from 3 days ago (south of the spread)
_NO_CELL = (-75, 10)  # never a story


@pytest_asyncio.fixture
async def big():
    """A connection in a transaction that is rolled back, then the filled tables
    vacuumed outside it (as tests/test_search_real_names_db.py does): ANALYZE's
    counts outlive a rollback, and later tests' plans would be made for them."""
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        try:
            await connection.execute(f"VACUUM (PARALLEL 0, ANALYZE) {', '.join(_FILLED)}")
        finally:
            await connection.close()


async def _production_week(conn, now: datetime) -> dict:
    await conn.execute(
        """
        INSERT INTO threads (centroid_sum, first_seen, last_seen, n_stories, n_sources,
                             lead_title, top_entities)
        SELECT v, $1 - make_interval(hours => g % 168), $1 - make_interval(hours => g % 24),
               3, 3, 'zzplan', ARRAY['Zzplan Mid ' || (g % 500), 'Zzplan Heavy ' || (g % 5)]
        FROM generate_series(1, 5000) g,
             (SELECT array_fill(0.01::real, ARRAY[512])::vector AS v) one
        """,
        now,
    )
    await conn.execute(
        """
        INSERT INTO thread_members (article_id, thread_id, story_key, source_name,
                                    published_at, latitude, longitude, region, country_code,
                                    entities, tone, similarity)
        SELECT gen_random_uuid(), t.ids[1 + g % 5000], g / 2, 'outlet' || g % 900 || '.test',
               $1 - make_interval(secs => (100000 - g) * 6.048),
               -60 + (g::bigint * 7919 % 130000) / 1000.0,
               -170 + (g::bigint * 104729 % 340000) / 1000.0,
               'Zzplan Region', 'US',
               ARRAY['Zzplan Heavy ' || g % 5, 'Zzplan Mid ' || g * 7 % 500,
                     'Zzplan Rare ' || g * 13 % 20000, 'Zzplan Rare ' || g * 31 % 20000],
               0.0, 0.9
        FROM generate_series(1, 100000) g,
             (SELECT array_agg(id ORDER BY id) AS ids FROM threads WHERE lead_title = 'zzplan') t
        """,
        now,
    )
    busy_lats = [lat for lat, _ in _BUSY_CELLS]
    busy_lngs = [lng for _, lng in _BUSY_CELLS]
    await conn.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location, region, country_code, summary, persons,
                              orgs, themes)
        SELECT 'zzplan story ' || g, 'https://zzplan.test/' || g, 'outlet' || g % 900 || '.test',
               $1 - make_interval(secs => (60000 - g) * 10.08), p.lat, p.lng,
               ST_SetSRID(ST_MakePoint(p.lng, p.lat), 4326)::geography,
               'Zzplan Region ' || g % 1000, 'US', repeat('zzplan summary ', 60),
               ARRAY['Zzplan Heavy ' || g % 5], ARRAY['Zzplan Org'], ARRAY['TAX_FNCACT']
        FROM generate_series(1, 60000) g
        CROSS JOIN LATERAL (
            SELECT CASE WHEN g % 4 = 0
                        THEN ($2::int[])[1 + (g / 4) % 4] + (g * 37 % 100) / 100.0
                        ELSE -60 + (g::bigint * 7919 % 130000) / 1000.0 END AS lat,
                   CASE WHEN g % 4 = 0
                        THEN ($3::int[])[1 + (g / 4) % 4] + (g * 53 % 100) / 100.0
                        ELSE -170 + (g::bigint * 104729 % 340000) / 1000.0 END AS lng
        ) p
        """,
        now,
        busy_lats,
        busy_lngs,
    )
    await conn.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location, region, country_code)
        SELECT 'zzplan old ' || g, 'https://zzplan.test/old/' || g, 'old.test',
               $1 - interval '3 days', $2 + 0.5, $3 + 0.5,
               ST_SetSRID(ST_MakePoint($3 + 0.5, $2 + 0.5), 4326)::geography, 'Zzplan Old', 'AQ'
        FROM generate_series(1, 20) g
        """,
        now,
        *_OLD_CELL,
    )
    # As (auto)vacuum leaves production's: the GIN pending list merged, statistics fresh.
    await conn.execute("SELECT gin_clean_pending_list('idx_thread_members_entities'::regclass)")
    for table in _FILLED:
        await conn.execute(f"ANALYZE {table}")
    return {
        "articles": [
            str(r["id"])
            for r in await conn.fetch(
                "SELECT id FROM articles WHERE title LIKE 'zzplan story 1%' LIMIT 20"
            )
        ],
        "members": [
            str(r["article_id"])
            for r in await conn.fetch("SELECT article_id FROM thread_members LIMIT 20")
        ],
        "threads": [
            r["id"]
            for r in await conn.fetch("SELECT id FROM threads WHERE lead_title = 'zzplan' LIMIT 20")
        ],
    }


def _walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


def _summary(raw) -> dict:
    top = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
    nodes = list(_walk(top))
    return {
        "seq_scans": {n["Relation Name"] for n in nodes if n["Node Type"] == "Seq Scan"},
        "indexes": {n["Index Name"] for n in nodes if "Index Name" in n},
    }


async def _custom_plan(conn, sql: str, *args) -> dict:
    """The plan PostgreSQL runs with these values, as executed (its first runs)."""
    return _summary(await conn.fetchval("EXPLAIN (ANALYZE, FORMAT JSON) " + sql, *args))


async def _generic_plan(conn, sql: str, types: list[str], values: list[str]) -> dict:
    """The plan made without the values, which a reused prepared statement may switch to."""
    await conn.execute("SET LOCAL plan_cache_mode = force_generic_plan")
    await conn.execute(f"PREPARE zzboard_plan ({', '.join(types)}) AS {sql}")
    try:
        raw = await conn.fetchval(
            f"EXPLAIN (FORMAT JSON) EXECUTE zzboard_plan ({', '.join(values)})"
        )
    finally:
        await conn.execute("DEALLOCATE zzboard_plan")
        await conn.execute("SET LOCAL plan_cache_mode = auto")
    return _summary(raw)


def _ts(value: datetime) -> str:
    return f"'{value.isoformat()}'::timestamptz"


@pytest.mark.asyncio
async def test_at_production_scale_pins_are_read_by_primary_key(big):
    now = _now()
    ids = await _production_week(big, now)

    articles = await _custom_plan(big, board.ARTICLES_SQL, ids["articles"])
    members = await _custom_plan(big, board.MEMBERS_SQL, ids["members"])
    threads = await _custom_plan(big, board.THREADS_SQL, ids["threads"])

    assert articles == {"seq_scans": set(), "indexes": {"articles_pkey"}}
    assert members == {"seq_scans": set(), "indexes": {"thread_members_pkey"}}
    assert threads == {"seq_scans": set(), "indexes": {"threads_pkey"}}


@pytest.mark.asyncio
async def test_at_production_scale_a_place_reads_its_cell_never_the_articles_heap(big):
    now = _now()
    await _production_week(big, now)
    cells = {
        "busy": _BUSY_CELLS[0],
        "spread": (10, 20),  # about one story a week, as most cells
        "old": _OLD_CELL,
        "none": _NO_CELL,
    }
    types = ["float8"] * 8 + ["timestamptz"]
    for name, (lat, lng) in cells.items():
        _, box = board._cell_box(lat, lng, lat + 1, lng + 1)
        for window in board.PLACE_WINDOWS:
            args = [*box, now - window]
            custom = await _custom_plan(big, board.PLACE_SQL, *args)
            generic = await _generic_plan(
                big, board.PLACE_SQL, types, [repr(float(v)) for v in box] + [_ts(args[-1])]
            )
            for mode, plan in (("custom", custom), ("generic", generic)):
                assert "articles" not in plan["seq_scans"], (name, window, mode, plan)
                assert plan["indexes"] & {"idx_articles_location", "idx_articles_published_at"}, (
                    name,
                    window,
                    mode,
                    plan,
                )

    # And the ladder finds what each cell has.
    _, box = board._cell_box(*_OLD_CELL, _OLD_CELL[0] + 1, _OLD_CELL[1] + 1)
    assert await big.fetch(board.PLACE_SQL, *box, now - timedelta(hours=6)) == []
    [old] = await big.fetch(board.PLACE_SQL, *box, now - timedelta(days=7))
    assert old["region"] == "Zzplan Old"


@pytest.mark.asyncio
async def test_at_production_scale_names_are_read_through_the_member_indexes(big):
    now = _now()
    ids = await _production_week(big, now)
    names = ["Zzplan Heavy 0", "Zzplan Mid 3", "Zzplan Rare 77", "Zzplan Nobody"]
    week = now - board.ENTITY_WINDOW

    sample = await _custom_plan(big, board.ENTITY_SAMPLE_SQL, names, week, board.ENTITY_SAMPLE)
    sample_generic = await _generic_plan(
        big,
        board.ENTITY_SAMPLE_SQL,
        ["text[]", "timestamptz", "int"],
        [
            "ARRAY[" + ", ".join(f"'{n}'" for n in names) + "]::text[]",
            _ts(week),
            str(board.ENTITY_SAMPLE),
        ],
    )
    mentions = await _custom_plan(big, board.MENTIONS_SQL, names, ids["threads"][:10])

    for plan in (sample, sample_generic):
        assert "thread_members" not in plan["seq_scans"], plan
        assert "idx_thread_members_entities" in plan["indexes"], plan
    assert "thread_members" not in mentions["seq_scans"], mentions
    assert mentions["indexes"] & {"idx_thread_members_thread", "idx_thread_members_entities"}

    # The sample is capped per name.
    rows = await big.fetch(board.ENTITY_SAMPLE_SQL, names, week, board.ENTITY_SAMPLE)
    per_name = {n: sum(r["name"] == n for r in rows) for n in names}
    assert per_name["Zzplan Heavy 0"] == board.ENTITY_SAMPLE
    assert per_name["Zzplan Nobody"] == 0
