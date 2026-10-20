"""The 7-day globe's one pass (get_globe_points_by_topic) on a real PostgreSQL.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied. Every test runs in a transaction that is rolled back, so
nothing it inserts is ever committed. Its stories are titled ``zzglobe ...``
or ``zzweek ...``. Skipped without the variable.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import database
from app.services.database import GLOBE_TOPIC_TAGS

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

WEEK = 168
# All (None), then the six topics: the globes the warmer caches.
VARIANTS = (None, *GLOBE_TOPIC_TAGS)


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


class _Recorder:
    """The pool as database.py uses it, on the test's connection, recording each statement."""

    def __init__(self, connection):
        self._conn = connection
        self.statements: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.statements.append((sql, args))
        return await self._conn.fetch(sql, *args)


async def _globes(conn, limit: int):
    """The one pass's globes; each variant's from get_globe_points; and the statements
    each ran (the one pass's first)."""
    recorder = _Recorder(conn)
    with patch.object(database, "get_pool", AsyncMock(return_value=recorder)):
        one_pass = await database.get_globe_points_by_topic(
            timespan_hours=WEEK, cell_size=1.0, limit=limit
        )
        separate = {
            tag: await database.get_globe_points(
                timespan_hours=WEEK, cell_size=1.0, limit=limit, topic=tag
            )
            for tag in VARIANTS
        }
    return one_pass, separate, recorder.statements


# --- The same globes, field by field --------------------------------------------------

# Cells (their south-west corners) and their dots' centres.
PARIS = (48, 2)
SANTIAGO = (-34, -71)
LIMA = (-13, -78)
TIES = (10, 20)
TOKYO = (35, 139)
LONDON = (51, -1)
OLD = (60, 60)
BEFORE = (61, 61)


def _dot(cell) -> tuple[float, float]:
    return cell[0] + 0.5, cell[1] + 0.5


async def _story(
    conn,
    title: str,
    cell,
    *,
    hours_ago: float,
    tags,
    image: str | None = None,
    tone: float = 0.0,
    story_id: str | None = None,
    at: datetime,
    spot: tuple[float, float] = (0.25, 0.25),
) -> None:
    lat, lng = cell[0] + spot[0], cell[1] + spot[1]
    await conn.execute(
        """
        INSERT INTO articles (id, title, source_url, source_name, published_at, latitude,
                              longitude, location, region, country_code, topic_tags,
                              sentiment_score, image_url)
        VALUES ($1, $2, $3, 'zzglobe.test', $4, $5, $6,
                ST_SetSRID(ST_MakePoint($6, $5), 4326)::geography, 'Zzglobe Town', 'FR',
                $7, $8, $9)
        """,
        uuid.UUID(story_id) if story_id else uuid.uuid4(),
        f"zzglobe {title}",
        f"https://zzglobe.test/{uuid.uuid4()}",
        at - timedelta(hours=hours_ago),
        lat,
        lng,
        tags,
        tone,
        image,
    )


HTTPS = "https://img.zzglobe.test/a.jpg"
HTTP = "http://img.zzglobe.test/a.jpg"


async def _cells_with_every_lead_rule(conn, now: datetime) -> None:
    """Cells whose counts, ranking ties and leads each test a rule of the globe query."""

    async def story(title, cell, **kw):
        await _story(conn, title, cell, at=now, **kw)

    # Paris: All's lead is its newest https story (health); Politics' is its own newest
    # https story, older than a newer one without an image. A duplicated tag counts once;
    # stories without a topic (sport, none, NULL) count for All only.
    await story("p1", PARIS, hours_ago=5, tags=["politics"], image=HTTPS, tone=0.5)
    await story("p2", PARIS, hours_ago=0.5, tags=["politics", "conflict"], tone=-0.25)
    await story("p3", PARIS, hours_ago=6, tags=["politics", "politics"], image=HTTP, tone=0.25)
    await story("p4", PARIS, hours_ago=1, tags=["health"], image=HTTPS, tone=0.125)
    await story("p5", PARIS, hours_ago=2, tags=["health", "economy"])
    await story("p6", PARIS, hours_ago=3, tags=["sport"], image=HTTPS)
    await story("p7", PARIS, hours_ago=4, tags=[])
    await story("p8", PARIS, hours_ago=4, tags=None)
    # Santiago (south and west: negative cells): no https image; at its newest time a
    # non-null image (LIKE false) comes before a NULL one (LIKE NULL).
    for title, image in (("s1", HTTP), ("s2", None)):
        await story(title, SANTIAGO, hours_ago=2, tags=["conflict"], image=image, tone=-0.5)
    await story("s3", SANTIAGO, hours_ago=7, tags=["conflict"])
    await story("s4", SANTIAGO, hours_ago=9, tags=["economy"], image="ftp://img.zzglobe.test")
    # Lima: without an https image, the newest story leads, even with no image at all.
    await story("l1", LIMA, hours_ago=1, tags=["economy"])
    await story("l2", LIMA, hours_ago=3, tags=["economy"], image=HTTP)
    # A cell on a whole degree; two image-less stories at one time: the lower id leads.
    for title, story_id in (("t1", "0000000b"), ("t2", "0000000a")):
        await story(
            title,
            TIES,
            hours_ago=3,
            tags=["economy"],
            story_id=f"00000000-0000-4000-8000-0000{story_id}",
            spot=(0.0, 0.999),
        )
    # Tokyo: two https stories at one time (the lower id leads), and one stamped in the
    # future, which the live window (no end) counts.
    for title, story_id in (("k1", "0000001b"), ("k2", "0000001a")):
        await story(
            title,
            TOKYO,
            hours_ago=4,
            tags=["technology"],
            image=HTTPS,
            story_id=f"00000000-0000-4000-8000-0000{story_id}",
        )
    await story("k3", TOKYO, hours_ago=-0.5, tags=["technology"])
    # London: two topics tie for its colour; its lead's tag breaks the tie.
    await story("n1", LONDON, hours_ago=2, tags=["environment"], image=HTTPS, tone=0.75)
    await story("n2", LONDON, hours_ago=1, tags=["environment"])
    await story("n3", LONDON, hours_ago=5, tags=["economy"], tone=-0.75)
    await story("n4", LONDON, hours_ago=6, tags=["economy"])
    # Outside the window: 8 days ago, and an hour before it opens.
    await story("old", OLD, hours_ago=24 * 8, tags=["politics"], image=HTTPS)
    await story("before", BEFORE, hours_ago=WEEK + 1, tags=["health"], image=HTTPS)


def _leads(globe) -> dict:
    return {(p["lat"], p["lng"]): p["lead"]["title"].removeprefix("zzglobe ") for p in globe}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [500, 3])
async def test_the_one_pass_globes_equal_get_globe_points_for_all_and_each_topic(conn, limit):
    await _cells_with_every_lead_rule(conn, datetime.now(timezone.utc))

    one_pass, separate, _ = await _globes(conn, limit)

    assert list(one_pass) == list(VARIANTS)
    for tag in VARIANTS:
        assert one_pass[tag] == separate[tag], tag  # every field of every point, in order
    if limit == 3:
        # The busiest three, ties by the cell (south first): 2-story Lima, Ties and London
        # ahead of the 1-story cells.
        assert [(p["lat"], p["lng"]) for p in one_pass["economy"]] == [
            _dot(LIMA),
            _dot(TIES),
            _dot(LONDON),
        ]
        return

    every = _leads(one_pass[None])
    assert every[_dot(PARIS)] == "p4"
    assert every[_dot(SANTIAGO)] == "s1"
    assert every[_dot(LIMA)] == "l1"
    assert every[_dot(TIES)] == "t2"
    assert every[_dot(TOKYO)] == "k2"
    assert _dot(OLD) not in every and _dot(BEFORE) not in every
    assert _leads(one_pass["politics"]) == {_dot(PARIS): "p1"}
    [paris] = one_pass["politics"]
    assert paris["article_count"] == 3  # the duplicated tag once
    assert paris["topic_mix"] == {"politics": 3, "conflict": 1}
    assert paris["topic"] == "politics"
    paris_all = next(p for p in one_pass[None] if (p["lat"], p["lng"]) == _dot(PARIS))
    assert paris_all["article_count"] == 8
    assert paris_all["topic"] == "politics"
    [tokyo] = one_pass["technology"]
    assert tokyo["article_count"] == 3  # the story stamped in the future too
    london = next(p for p in one_pass[None] if (p["lat"], p["lng"]) == _dot(LONDON))
    assert london["topic"] == "environment"
    assert [(p["lat"], p["lng"]) for p in one_pass["health"]] == [_dot(PARIS)]


# --- At production's scale: one read of the week, by index ------------------------------
#
# A week of production: about 60K wide articles in GDELT's 15-minute batches (each
# batch's stories share one time), a quarter in four busy cells and the rest at 4,000
# places, ingested oldest first; and a purge's lag of stories just older than the week.
# With 7-day retention the 7-day window is the whole table. No enable_seqscan here:
# these are the planner's own choices, custom (a statement's first runs) and generic
# (asyncpg reuses its prepared statements, and PostgreSQL may switch one to a generic
# plan).

_BATCHES = 672  # every 15 minutes for a week
_PER_BATCH = 90
_BUSY_CELLS = ((51, 0), (40, -74), (38, -77), (48, 2))


@pytest_asyncio.fixture
async def big():
    """A connection in a transaction that is rolled back, then articles vacuumed
    outside it (as tests/test_search_real_names_db.py does): ANALYZE's counts outlive
    a rollback, and later tests' plans would be made for them."""
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        try:
            await connection.execute("VACUUM (PARALLEL 0, ANALYZE) articles")
        finally:
            await connection.close()


async def _production_week(conn, now: datetime) -> None:
    busy_lats = [lat for lat, _ in _BUSY_CELLS]
    busy_lngs = [lng for _, lng in _BUSY_CELLS]
    await conn.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location, region, country_code, summary, topic_tags,
                              sentiment_score, image_url, persons, orgs, themes, entities)
        SELECT 'zzweek story ' || g, 'https://zzweek.test/' || g, 'outlet' || g % 900 || '.test',
               $1::timestamptz - make_interval(mins => 15 * ($4::int - 1 - g / $5::int) + 5),
               p.lat, p.lng, ST_SetSRID(ST_MakePoint(p.lng, p.lat), 4326)::geography,
               'Zzweek Region ' || g % 1000, 'US', repeat('zzweek summary ', 60),
               CASE (g / 4) % 10
                    WHEN 0 THEN ARRAY['politics']
                    WHEN 1 THEN ARRAY['conflict', 'politics']
                    WHEN 2 THEN ARRAY['technology']
                    WHEN 3 THEN ARRAY['economy', 'technology']
                    WHEN 4 THEN ARRAY['environment']
                    WHEN 5 THEN ARRAY['health']
                    WHEN 6 THEN ARRAY['conflict']
                    WHEN 7 THEN ARRAY['sport']
                    WHEN 8 THEN ARRAY['economy']
                    ELSE ARRAY[]::text[] END,
               ((g % 9) - 4) / 8.0,
               CASE WHEN (g / 3) % 7 < 4 THEN 'https://img.zzweek.test/' || g || '.jpg'
                    WHEN (g / 3) % 7 = 4 THEN 'http://img.zzweek.test/' || g || '.jpg' END,
               ARRAY['Zzweek Person ' || g % 500, 'Zzweek Person ' || g % 37],
               ARRAY['Zzweek Org ' || g % 300],
               ARRAY['TAX_FNCACT', 'WB_' || g % 50],
               jsonb_build_object('persons', ARRAY['Zzweek Person ' || g % 500],
                                  'locations', ARRAY['Zzweek Region ' || g % 1000])
        FROM generate_series(0, $4::int * $5::int - 1) g
        CROSS JOIN LATERAL (
            SELECT CASE WHEN g % 4 = 0
                        THEN ($2::int[])[1 + (g / 4) % 4] + (g * 37 % 100) / 100.0
                        ELSE -55 + (g * 7919 % 4000) % 110 + 0.37 END AS lat,
                   CASE WHEN g % 4 = 0
                        THEN ($3::int[])[1 + (g / 4) % 4] + (g * 53 % 100) / 100.0
                        ELSE -170 + (g * 7919 % 4000) / 110 * 9.4 + 0.41 END AS lng
        ) p
        """,
        now,
        busy_lats,
        busy_lngs,
        _BATCHES,
        _PER_BATCH,
    )
    await conn.execute(
        """
        INSERT INTO articles (title, source_url, source_name, published_at, latitude,
                              longitude, location, region, country_code, topic_tags)
        SELECT 'zzweek old ' || g, 'https://zzweek.test/old/' || g, 'old.test',
               $1::timestamptz - make_interval(hours => $2::int, mins => 10), 20.5, 30.5,
               ST_SetSRID(ST_MakePoint(30.5, 20.5), 4326)::geography, 'Zzweek Old', 'EG',
               ARRAY['politics']
        FROM generate_series(1, 300) g
        """,
        now,
        WEEK,
    )
    await conn.execute("ANALYZE articles")


def _walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


def _summary(raw) -> dict:
    top = json.loads(raw) if isinstance(raw, str) else raw
    plan = top[0]["Plan"]
    nodes = list(_walk(plan))
    return {
        "seq_scans": {n["Relation Name"] for n in nodes if n["Node Type"] == "Seq Scan"},
        "indexes": {n["Index Name"] for n in nodes if "Index Name" in n},
        "buffers": plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0),
        "temp": plan.get("Temp Read Blocks", 0) + plan.get("Temp Written Blocks", 0),
        "ms": top[0].get("Execution Time"),
    }


async def _executed(conn, sql: str, args) -> dict:
    """The plan PostgreSQL runs with these values (a statement's first runs), as run."""
    return _summary(await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, *args))


def _literal(value) -> str:
    """*value* as an SQL literal of unknown type, which EXECUTE coerces to the parameter's."""
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        items = ",".join("NULL" if v is None else f'"{_text(v)}"' for v in value)
        return "'{" + items + "}'"
    return "'" + _text(value).replace("'", "''") + "'"


def _text(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


async def _generic(conn, sql: str, args) -> dict:
    """The plan made without the values, which a reused prepared statement may switch to."""
    await conn.execute("SET LOCAL plan_cache_mode = force_generic_plan")
    await conn.execute(f"PREPARE zzglobe_week AS {sql}")
    try:
        raw = await conn.fetchval(
            f"EXPLAIN (FORMAT JSON) EXECUTE zzglobe_week ({', '.join(_literal(a) for a in args)})"
        )
    finally:
        await conn.execute("DEALLOCATE zzglobe_week")
        await conn.execute("SET LOCAL plan_cache_mode = auto")
    return _summary(raw)


@pytest.mark.asyncio
async def test_at_production_scale_one_pass_reads_the_week_once_by_index(big):
    await _production_week(big, datetime.now(timezone.utc))

    one_pass, separate, statements = await _globes(big, 500)

    assert one_pass == separate
    assert len(one_pass[None]) == 500 and all(one_pass[tag] for tag in VARIANTS)
    (sql, args), seven = statements[0], statements[1:]
    custom = await _executed(big, sql, args)
    generic = await _generic(big, sql, args)
    for plan in (custom, generic):
        assert "articles" not in plan["seq_scans"], plan
        assert "idx_articles_published_at" in plan["indexes"], plan
    each = [await _executed(big, s, a) for s, a in seven]
    # One read of the week, against seven.
    assert custom["buffers"] < sum(p["buffers"] for p in each) / 2, (custom, each)
