"""Entity dossiers and search on a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied (013 included). Every test runs in a transaction that is
rolled back, so nothing it inserts is ever committed. Its people and orgs are
named ``Zz ...``, its articles titled ``zzentity-...``. Dossiers read
``thread_members`` rows (the fixtures insert them as thread assignment
would), names resolve through ``kg_nodes``, and search counts the same
members. Skipped without the variable.
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

from app.services import entities, search, thread_reads

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
        """For the dossier's member reads: their transaction is a savepoint in the test's."""
        async with self._lock:
            yield self._conn


@pytest_asyncio.fixture
async def pool(conn):
    stand_in = _Pool(conn)
    with contextlib.ExitStack() as stack:
        for module in ("entities", "search", "thread_reads"):
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


async def _bulk_members(conn, count: int, entities_sql: str, story: str = "g") -> None:
    """*count* members this week whose entities and story_key are *entities_sql* and
    *story* (SQL over ``g``, 1..count): by default each its own story."""
    thread = await _thread(conn)
    await conn.execute(
        f"""
        INSERT INTO thread_members (article_id, thread_id, story_key, published_at,
                                    latitude, longitude, entities, similarity)
        SELECT gen_random_uuid(), $1, {story}, now() - make_interval(mins => g), 1, 2,
               {entities_sql}, 1.0
        FROM generate_series(1, {count}) g
        """,
        thread,
    )


async def _node(conn, type_: str, name: str) -> None:
    await conn.execute(
        "INSERT INTO kg_nodes (type, name) VALUES ($1, $2) ON CONFLICT DO NOTHING", type_, name
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
    for spelling in ("Zz Epsilon", "ZZ EPSILON", "zz epsilon"):
        await _node(conn, "PERSON", spelling)
    await _node(conn, "ORG", "Zz Epsilon Fund")
    await _members(
        conn,
        [{"story": 4000 + i, "entities": ["Zz Epsilon"]} for i in range(3)]
        + [{"story": 4010, "entities": ["ZZ EPSILON"]}]
        # not this week
        + [{"story": 4020 + i, "entities": ["zz epsilon"], "hours_ago": 24 * 8} for i in range(5)],
    )
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


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_search_ranks_by_stories_this_week_and_drops_the_unmentioned(conn):
    for type_, name in [
        ("PERSON", "Zz Searchable One"),
        ("PERSON", "Zz Searchable Two"),
        ("PERSON", "Zz Searchable Old"),
        ("ORG", "Zz Searchable Org"),
    ]:
        await _node(conn, type_, name)
    await _members(
        conn,
        [
            {"story": 5001, "entities": ["Zz Searchable One", "Zz Searchable Org"]},
            {"story": 5001, "entities": ["Zz Searchable One"]},  # a copy: the same story
            {"story": 5002, "entities": ["Zz Searchable One", "Zz Searchable Two"]},
            {"entities": ["Zz Searchable One"]},  # unkeyed: a story of its own
            {"story": 5004, "entities": ["Zz Searchable Old"], "hours_ago": 24 * 8},
        ],
    )
    now = datetime.now(timezone.utc)
    result = await search.search("zz searchable", now)

    assert result["people"] == [
        {"type": "person", "name": "Zz Searchable One", "n": 3, "capped": False},
        {"type": "person", "name": "Zz Searchable Two", "n": 1, "capped": False},
    ]
    assert result["orgs"] == [{"type": "org", "name": "Zz Searchable Org", "n": 1, "capped": False}]
    # As the dossier counts them.
    dossier = await entities.get_entity_dossier("Zz Searchable One", "person", "168h", now)
    assert dossier["counts"]["d7"] == 3
    # Like-wildcards are text: "_z" would otherwise match "Zz…".
    assert (await search.search("_z", now))["people"] == []


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
async def test_search_and_the_thread_list_agree_on_which_threads_are_listed(conn):
    cases = [  # (hours since last seen, stories, outlets)
        (1, 3, 3),  # listed: at both thresholds
        (1, 2, 9),  # 2 stories
        (1, 9, 2),  # 2 outlets
        (2, 5, 4),  # listed
        (24 * 7 - 1, 3, 3),  # listed: inside the list's longest window
        (24 * 7 + 1, 3, 3),  # outside it
    ]
    ids = [
        await _thread(conn, hours, stories, outlets, 0, f"Zzentity agree {i}")
        for i, (hours, stories, outlets) in enumerate(cases)
    ]
    now = datetime.now(timezone.utc)

    found = {t["id"] for t in (await search.search("zzentity agree", now))["threads"]}
    week = await thread_reads.list_threads(now, max(thread_reads.LIST_HOURS), None, 50)
    listed = {t["id"] for t in week} & set(ids)
    assert found == listed == {ids[0], ids[3], ids[4]}


@pytest.mark.asyncio
async def test_search_reads_only_listed_threads(conn):
    """The list's partial idx_threads_listed: single-story threads are never read."""
    await conn.execute(  # a week of mostly single-story threads, and a few listed
        "INSERT INTO threads (centroid_sum, first_seen, last_seen, n_stories, n_sources, title)"
        " SELECT array_fill(0.01, ARRAY[512])::vector, now(), now() - i * interval '30 minutes',"
        " CASE WHEN i <= 3 THEN 3 ELSE 1 END, CASE WHEN i <= 3 THEN 3 ELSE 1 END,"
        " 'Zzentity ' || i"
        " FROM generate_series(1, 300) AS i"
    )
    await conn.execute("ANALYZE threads")
    await conn.execute("SET LOCAL enable_seqscan = off")
    week_ago = datetime.now(timezone.utc) - timedelta(hours=max(thread_reads.LIST_HOURS))

    plan = await _plan(conn, search._THREADS_SQL, week_ago, "%zzentity%")
    assert "idx_threads_listed" in plan, plan
    assert "Seq Scan on threads" not in plan, plan


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_search_counts_stories_among_the_capped_members_and_ranks_the_capped_first(
    conn,
):
    for name in ("Zz Cap Many", "Zz Cap Copies", "Zz Cap Under"):
        await _node(conn, "PERSON", name)
    await _bulk_members(conn, 150, "ARRAY['Zz Cap Many']")  # 150 stories
    await _bulk_members(conn, 100, "ARRAY['Zz Cap Copies']", story="g % 40")  # 40 stories
    await _bulk_members(conn, 99, "ARRAY['Zz Cap Under']")  # 99 stories, under the cap
    now = datetime.now(timezone.utc)
    result = await search.search("zz cap", now)

    assert search.SEARCH_COUNT_CAP == 100
    assert result["people"] == [
        # The cap's worth of members read: n is their distinct stories, "{n}+".
        {"type": "person", "name": "Zz Cap Many", "n": 100, "capped": True},
        {"type": "person", "name": "Zz Cap Copies", "n": 40, "capped": True},
        # Under the cap: every member read, n is the dossier's d7.
        {"type": "person", "name": "Zz Cap Under", "n": 99, "capped": False},
    ]
    dossier = await entities.get_entity_dossier("Zz Cap Under", "person", "168h", now)
    assert dossier["counts"]["d7"] == 99


@pytest.mark.asyncio
async def test_names_are_matched_among_people_and_orgs_and_counted_from_members(conn):
    # Headlines (ARTICLE nodes) that carry the name, which the full trigram index
    # would match and recheck one by one, and many people.
    await conn.execute(
        "INSERT INTO kg_nodes (type, name)"
        " SELECT 'ARTICLE', 'Markets fell sharply on Monday after Zzplanned spoke, report '"
        " || g FROM generate_series(1, 2000) g"
    )
    await conn.execute(
        "INSERT INTO kg_nodes (type, name)"
        " SELECT 'PERSON', 'Bulkperson ' || g FROM generate_series(1, 50000) g"
    )
    await _node(conn, "PERSON", "Zzplanned Person")
    await _bulk_members(conn, 2000, "ARRAY['Zz Other ' || (g % 200)]")
    # New GIN entries wait in a pending list that every scan reads in full, until
    # (auto)vacuum or autoanalyze merges them; merge them now, as production's are.
    for index in ("idx_kg_nodes_name_trgm", "idx_kg_nodes_entity_name_trgm"):
        await conn.execute(f"SELECT gin_clean_pending_list('{index}')")
    await conn.execute("ANALYZE kg_nodes")
    await conn.execute("ANALYZE thread_members")
    await conn.execute("SET LOCAL enable_seqscan = off")
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    candidates = await _plan(conn, search._CANDIDATES_SQL, "zzplanned", "zzplanned%", week_ago, 100)
    resolve = await _plan(conn, entities._RESOLVE_SQL, "PERSON", "zzplanned person", week_ago, 100)
    for plan in (candidates, resolve):
        assert "idx_kg_nodes_entity_name_trgm" in plan, plan
        assert not re.search(r"\bidx_kg_nodes_name_trgm\b", plan), plan
        # Each name's count: thread members through the entity index.
        assert "idx_thread_members_entities" in plan, plan
        assert "kg_edges" not in plan, plan

    # Plans made without the values (asyncpg reuses prepared statements, and
    # after five runs PostgreSQL may keep a generic plan) can use the partial
    # index only because each query names its predicate literally.
    await conn.execute(
        "PREPARE zz_candidates (text, text, timestamptz, bigint) AS " + search._CANDIDATES_SQL
    )
    await conn.execute(
        "PREPARE zz_resolve (text, text, timestamptz, bigint) AS " + entities._RESOLVE_SQL
    )
    await conn.execute("SET LOCAL plan_cache_mode = force_generic_plan")
    for statement in (
        "EXECUTE zz_candidates('zzplanned', 'zzplanned%', now(), 100)",
        "EXECUTE zz_resolve('PERSON', 'zzplanned person', now(), 100)",
    ):
        plan = await _plan(conn, statement)
        assert "$2" in plan, plan  # generic: planned without the values
        assert "idx_kg_nodes_entity_name_trgm" in plan, plan
        assert not re.search(r"\bidx_kg_nodes_name_trgm\b", plan), plan


@pytest.mark.asyncio
async def test_kg_edges_are_vacuumed_after_one_percent_new_rows(conn):
    options = await conn.fetchval("SELECT reloptions FROM pg_class WHERE relname = 'kg_edges'")
    assert "autovacuum_vacuum_insert_scale_factor=0.01" in (options or [])
