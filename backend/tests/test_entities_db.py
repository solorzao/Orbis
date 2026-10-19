"""Entity dossiers and search on a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (013 included). Every test runs in a transaction that is
rolled back, so nothing it inserts is ever committed. Its people and orgs are
named ``Zz ...``, its articles titled ``zzentity-...``. Dossiers read
``thread_members`` rows (the fixtures insert them as thread assignment
would), names resolve through ``kg_nodes``, and search's mention counts come
from the graph that populate_graph builds. Skipped without the variable.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import entities, search
from app.services.knowledge_graph import populate_graph

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)


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
    """The pool as the services use it, on the test's connection, one query at a time.

    ``fetches`` records each fetch's SQL and arguments.
    """

    def __init__(self, connection):
        self._conn = connection
        self._lock = asyncio.Lock()
        self.fetches: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args, timeout=None):
        self.fetches.append((sql, args))
        async with self._lock:
            return await self._conn.fetch(sql, *args, timeout=timeout)

    async def fetchrow(self, sql, *args, timeout=None):
        async with self._lock:
            return await self._conn.fetchrow(sql, *args, timeout=timeout)

    async def fetchval(self, sql, *args, timeout=None):
        async with self._lock:
            return await self._conn.fetchval(sql, *args, timeout=timeout)

    @contextlib.asynccontextmanager
    async def acquire(self):
        """For populate_graph: its transaction is a savepoint in the test's."""
        async with self._lock:
            yield self._conn


@pytest_asyncio.fixture
async def pool(conn):
    stand_in = _Pool(conn)
    with contextlib.ExitStack() as stack:
        for module in ("entities", "search", "knowledge_graph"):
            stack.enter_context(
                patch(
                    f"app.services.{module}.get_pool",
                    new_callable=AsyncMock,
                    return_value=stand_in,
                )
            )
        yield stand_in


async def _thread(conn, hours_ago=0, n_stories=0, n_sources=0, velocity=0, title=None, lead=""):
    return await conn.fetchval(
        """
        INSERT INTO threads (centroid_sum, first_seen, last_seen, n_stories, n_sources,
                             velocity, title, lead_title)
        VALUES (array_fill(0.01, ARRAY[512])::vector, now() - make_interval(hours => $1),
                now() - make_interval(hours => $1), $2, $3, $4, $5, $6)
        RETURNING id
        """,
        hours_ago,
        n_stories,
        n_sources,
        velocity,
        title,
        lead,
    )


async def _article(conn, title: str, published) -> uuid.UUID:
    return await conn.fetchval(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location)
        VALUES ($1, $2, 'zzentity.test', $3, 0, 0,
                ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography)
        RETURNING id
        """,
        title,
        f"https://zzentity.test/{uuid.uuid4()}",
        published,
    )


async def _members(conn, specs: list[dict]) -> list[uuid.UUID]:
    """Insert thread_members rows, as assignment writes them; an article too when titled."""
    thread = await _thread(conn)
    now = await conn.fetchval("SELECT now()")
    ids = []
    for i, s in enumerate(specs):
        published = now - timedelta(hours=s.get("hours_ago", 1), minutes=i)
        article_id = await _article(conn, s["title"], published) if "title" in s else uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO thread_members (article_id, thread_id, story_key, source_name,
                                        published_at, latitude, longitude, region,
                                        country_code, entities, tone, similarity)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 1.0)
            """,
            article_id,
            thread,
            s.get("story"),
            s.get("outlet", f"site{i}.test"),
            published,
            s.get("lat", 10.5),
            s.get("lng", 20.5),
            s.get("region", "Tehran, Tehran, Iran"),
            s.get("country", "IR"),
            s["entities"],
            s.get("tone", 0.0),
        )
        ids.append(article_id)
    return ids


async def _node(conn, type_: str, name: str) -> None:
    await conn.execute(
        "INSERT INTO kg_nodes (type, name) VALUES ($1, $2) ON CONFLICT DO NOTHING", type_, name
    )


async def _mentions(conn, type_: str, name: str, count: int, days_ago: int = 0) -> None:
    """*count* MENTIONED_IN edges from the node, written *days_ago* (no articles needed)."""
    node = await conn.fetchval(
        "INSERT INTO kg_nodes (type, name) VALUES ($1, $2)"
        " ON CONFLICT (type, name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        type_,
        name,
    )
    target = await conn.fetchval(
        "INSERT INTO kg_nodes (type, name) VALUES ('ARTICLE', $1) RETURNING id",
        f"zzentity-{uuid.uuid4()}",
    )
    await conn.execute(
        "INSERT INTO kg_edges (source_node_id, target_node_id, rel_type, created_at)"
        " SELECT $1, $2, 'MENTIONED_IN', now() - make_interval(days => $3)"
        " FROM generate_series(1, $4)",
        node,
        target,
        days_ago,
        count,
    )


async def _dossier(name, type_="person", timespan="168h"):
    now = datetime.now(timezone.utc)
    stored = await entities.resolve_entity(type_, name, now)
    assert stored is not None, name
    return await entities.get_entity_dossier(stored, type_, timespan, now)


async def _plan(conn, sql: str, *args) -> str:
    return "\n".join(r[0] for r in await conn.fetch("EXPLAIN " + sql, *args))


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_places_counts_and_co_mentions_count_stories_not_copies(conn):
    await _node(conn, "PERSON", "Zz Alpha")
    await _node(conn, "PERSON", "Zz Beta")
    await _node(conn, "PERSON", "Zz Gamma")
    await _node(conn, "ORG", "Zz Gamma")  # a person and an org of one name
    alpha_beta = ["Zz Alpha", "Zz Beta"]
    await _members(
        conn,
        [
            # story 1001: three copies in the (10, 20) cell, one naming Gamma too
            {"story": 1001, "entities": alpha_beta, "title": "zzentity-Quake - Reuters"},
            {"story": 1001, "entities": alpha_beta + ["Zz Gamma"]},
            {"story": 1001, "entities": alpha_beta},
            # four stories in the (35, 51) cell: two keyed, two unkeyed (each its own)
            {"story": 1002, "entities": alpha_beta, "lat": 35.6, "lng": 51.3},
            {"story": 1003, "entities": ["Zz Alpha"], "lat": 35.2, "lng": 51.8, "country": "US"},
            {"entities": ["Zz Alpha"], "lat": 35.1, "lng": 51.1},
            {"entities": ["Zz Alpha"], "lat": 35.9, "lng": 51.9},
            # not about Alpha
            {"story": 1004, "entities": ["Zz Beta", "Zz Gamma"]},
        ],
    )
    dossier = await _dossier("zz alpha")  # any case: the stored spelling from then on

    assert dossier["name"] == "Zz Alpha"
    assert dossier["counts"] == {"h24": 5, "d7": 5}
    assert [(p["lat"] // 1, p["lng"] // 1, p["n"]) for p in dossier["places"]] == [
        (35, 51, 4),
        (10, 20, 1),
    ]
    assert dossier["countries"] == [
        {"country_code": "IR", "n": 4},
        {"country_code": "US", "n": 1},
    ]
    assert dossier["co_mentions"] == [
        {"name": "Zz Beta", "n": 2, "types": ["person"]},
        {"name": "Zz Gamma", "n": 1, "types": ["person", "org"]},
    ]
    assert [h["title"] for h in dossier["headlines"]] == ["zzentity-Quake"]  # the one article
    assert dossier["capped"] is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_the_window_bounds_members_counts_and_trend(conn):
    await _node(conn, "ORG", "Zz Delta Org")
    hours = [1, 1, 1, 30, 30, 24 * 8]  # today, yesterday, last week
    await _members(
        conn,
        [
            {"story": 2000 + i, "entities": ["Zz Delta Org"], "hours_ago": h}
            for i, h in enumerate(hours)
        ],
    )
    day = await _dossier("Zz Delta Org", type_="org", timespan="24h")
    week = await _dossier("Zz Delta Org", type_="org", timespan="168h")

    assert day["counts"] == week["counts"] == {"h24": 3, "d7": 5}
    assert day["trend"] == week["trend"] == 1.5  # 3 against 2
    assert len(day["timeline"]) == 24 and len(week["timeline"]) == 7
    assert sum(b["n"] for b in day["timeline"]) == 3
    assert sum(b["n"] for b in week["timeline"]) == 5
    assert day["countries"] == [{"country_code": "IR", "n": 3}]
    assert week["countries"] == [{"country_code": "IR", "n": 5}]
    oldest = await conn.fetchval("SELECT now() - interval '8 days'")
    assert week["since"] <= oldest  # the earliest member of all: the ramp


@pytest.mark.asyncio
async def test_a_heavy_entity_is_capped(conn, pool):
    await _node(conn, "PERSON", "Zz Heavy")
    thread = await _thread(conn)
    await conn.execute(
        """
        INSERT INTO thread_members (article_id, thread_id, story_key, published_at,
                                    latitude, longitude, entities, similarity)
        SELECT gen_random_uuid(), $1, -1000000 - g, now() - make_interval(mins => g),
               10.5, 20.5, ARRAY['Zz Heavy', 'Zz Sidekick'], 1.0
        FROM generate_series(1, 3000) g
        """,
        thread,
    )
    pool.fetches.clear()
    dossier = await _dossier("Zz Heavy")

    assert (dossier["capped"], dossier["cap"]) == (True, 2000)
    assert dossier["counts"]["d7"] == 3000  # every match is counted
    assert sum(p["n"] for p in dossier["places"]) == 2000  # the rest: the newest 2,000
    assert dossier["co_mentions"] == [{"name": "Zz Sidekick", "n": 2000, "types": []}]
    [(_, (ids,))] = [f for f in pool.fetches if "FROM articles" in f[0]]
    assert len(ids) == 10


@pytest.mark.asyncio
async def test_members_are_read_through_the_entity_index(conn, pool):
    await _node(conn, "PERSON", "Zz Target")
    thread = await _thread(conn)
    await conn.execute(
        """
        INSERT INTO thread_members (article_id, thread_id, story_key, published_at,
                                    latitude, longitude, entities, similarity)
        SELECT gen_random_uuid(), $1, g, now() - make_interval(mins => g), 1, 2,
               ARRAY['Zz Other ' || (g % 200)], 1.0
        FROM generate_series(1, 2000) g
        """,
        thread,
    )
    await _members(conn, [{"story": 1, "entities": ["Zz Target"]}])
    await conn.execute("ANALYZE thread_members")
    await conn.execute("SET LOCAL enable_seqscan = off")
    now = datetime.now(timezone.utc)
    week, day = now - timedelta(days=7), now - timedelta(hours=24)

    summary = await _plan(
        conn, entities._SUMMARY_SQL, "Zz Target", week, day, now - timedelta(hours=48), week
    )
    members = await _plan(conn, entities._MEMBERS_SQL, "Zz Target", week, 2001)
    for plan in (summary, members):
        assert "idx_thread_members_entities" in plan, plan
        assert "Seq Scan on thread_members" not in plan, plan

    # asyncpg reuses prepared statements, and after five runs PostgreSQL may keep a
    # generic plan, made without the values: on this table one reads the week by
    # published_at and filters on the entity. So the dossier's member reads run in
    # a transaction that plans every statement with its values, however often
    # the connection has run it.
    for _ in range(6):
        await _dossier("Zz Target")
    # Here its transaction is a savepoint in the test's, so its SET LOCAL outlives it.
    assert await conn.fetchval("SHOW plan_cache_mode") == "force_custom_plan"
    await conn.execute("PREPARE zz_members (text, timestamptz, bigint) AS " + entities._MEMBERS_SQL)
    week_ago = "now() - interval '7 days'"
    for _ in range(6):
        await conn.fetch(f"EXECUTE zz_members('Zz Target', {week_ago}, 2001)")
    plan = await _plan(conn, f"EXECUTE zz_members('Zz Target', {week_ago}, 2001)")
    assert "$1" not in plan, plan  # planned with the values
    assert "idx_thread_members_entities" in plan, plan


@pytest.mark.asyncio
async def test_articles_are_read_only_by_primary_key_for_the_ten_headlines(conn, pool):
    await _node(conn, "PERSON", "Zz Reader")
    ids = await _members(
        conn,
        [
            {"story": 3000 + i, "entities": ["Zz Reader"], "title": f"zzentity-Story {i}"}
            for i in range(12)
        ],
    )
    pool.fetches.clear()
    dossier = await _dossier("Zz Reader")

    [(sql, (read,))] = [f for f in pool.fetches if "FROM articles" in f[0]]
    assert read == ids[:10]  # the ten newest stories
    assert [h["title"] for h in dossier["headlines"]] == [f"zzentity-Story {i}" for i in range(10)]

    await conn.execute("SET LOCAL enable_seqscan = off")
    plan = await _plan(conn, sql, read)
    assert "articles_pkey" in plan, plan
    assert "Seq Scan" not in plan, plan


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_a_name_resolves_to_one_stored_spelling_whatever_the_case_asked(conn):
    await _mentions(conn, "PERSON", "Zz Epsilon", 3)
    await _mentions(conn, "PERSON", "ZZ EPSILON", 1)
    await _mentions(conn, "PERSON", "zz epsilon", 5, days_ago=8)  # not this week
    await _node(conn, "ORG", "Zz Epsilon Fund")
    now = datetime.now(timezone.utc)

    for asked in ("zz epsilon", "ZZ EPSILON", "Zz Epsilon"):
        assert await entities.resolve_entity("person", asked, now) == "Zz Epsilon"  # most mentioned
    # Tied (no mentions): by name, the same answer for every case.
    await _node(conn, "ORG", "Zz Tie")
    await _node(conn, "ORG", "ZZ TIE")
    answers = {await entities.resolve_entity("org", asked, now) for asked in ("zz tie", "ZZ TIE")}
    assert len(answers) == 1 and answers <= {"Zz Tie", "ZZ TIE"}

    assert await entities.resolve_entity("person", "Zz Epsilo", now) is None
    assert await entities.resolve_entity("org", "Zz Epsilon", now) is None  # wrong type
    assert await entities.resolve_entity("person", "Zz_Epsilon", now) is None  # _ is literal


# ── search ──────────────────────────────────────────────────────────────


async def _graph(conn, specs: list[dict]) -> list[dict]:
    """Insert articles, then build their graph with populate_graph, as ingestion does."""
    now = await conn.fetchval("SELECT now()")
    rows = []
    for i, s in enumerate(specs):
        published = now - timedelta(hours=1, minutes=i)
        article_id = await _article(conn, s["title"], published)
        rows.append(
            {
                "id": article_id,
                "title": s["title"],
                "source_url": "",
                "latitude": 0.0,
                "longitude": 0.0,
                "published_at": published,
                "persons": s.get("persons", []),
                "organizations": s.get("orgs", []),
                "region": "",
                "topic_tags": [],
                "mentioned_locations": [],
            }
        )
    await populate_graph(rows)
    return rows


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_search_ranks_by_mentions_and_drops_the_unmentioned(conn):
    rows = await _graph(
        conn,
        [
            {
                "title": "zzentity-S1",
                "persons": ["Zz Searchable One"],
                "orgs": ["Zz Searchable Org"],
            },
            {"title": "zzentity-S2", "persons": ["Zz Searchable One", "Zz Searchable Two"]},
            {"title": "zzentity-S3", "persons": ["Zz Searchable One"]},
            {"title": "zzentity-S4", "persons": ["Zz Searchable Old"]},
        ],
    )
    await conn.execute(  # no mentions this week
        "UPDATE kg_edges SET created_at = now() - interval '8 days' WHERE article_id = $1",
        rows[3]["id"],
    )
    result = await search.search("zz searchable", datetime.now(timezone.utc))

    assert result["people"] == [
        {"type": "person", "name": "Zz Searchable One", "n": 3},
        {"type": "person", "name": "Zz Searchable Two", "n": 1},
    ]
    assert result["orgs"] == [{"type": "org", "name": "Zz Searchable Org", "n": 1}]
    # Like-wildcards are text: "_z" would otherwise match "Zz…".
    assert (await search.search("_z", datetime.now(timezone.utc)))["people"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_search_lists_threads_by_title_or_lead_title(conn):
    titled = await _thread(conn, 1, 5, 4, 2, "Zzentity talks thread", "Talks resume")
    by_lead = await _thread(conn, 2, 3, 3, 1, None, "Zzentity lead headline")
    await _thread(conn, 1, 5, 2, 9, "Zzentity two outlets")  # not listed: 2 outlets
    await _thread(conn, 24 * 8, 5, 5, 9, "Zzentity last week")  # not listed: too old
    now = datetime.now(timezone.utc)

    assert (await search.search("zzentity", now))["threads"] == [
        {"id": titled, "title": "Zzentity talks thread"},
        {"id": by_lead, "title": "Zzentity lead headline"},
    ]
    assert (await search.search("zzentity_talks", now))["threads"] == []  # _ is literal


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_search_counts_mentions_up_to_the_cap(conn):
    await _mentions(conn, "PERSON", "Zz Capped Person", 150)
    result = await search.search("zz capped", datetime.now(timezone.utc))
    assert result["people"] == [
        {"type": "person", "name": "Zz Capped Person", "n": search.SEARCH_COUNT_CAP}
    ]


@pytest.mark.asyncio
async def test_search_counts_through_the_recency_index(conn):
    await _mentions(conn, "PERSON", "Zz Planned", 5)
    await conn.execute("SET LOCAL enable_seqscan = off")
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    plan = await _plan(conn, search._CANDIDATES_SQL, "zz planned", "zz planned%", week_ago, 100)
    assert re.search(r"Index (Only )?Scan using idx_kg_edges_source_recent", plan), plan


@pytest.mark.asyncio
async def test_kg_edges_are_vacuumed_after_one_percent_new_rows(conn):
    options = await conn.fetchval("SELECT reloptions FROM pg_class WHERE relname = 'kg_edges'")
    assert "autovacuum_vacuum_insert_scale_factor=0.01" in (options or [])
