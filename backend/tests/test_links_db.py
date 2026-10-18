"""The links SQL on a real PostgreSQL: stories, not syndicated copies, are counted.

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied, 012 (story_key) included (e.g. the local Docker one).
Every test runs in a transaction that is rolled back, so nothing it
inserts is ever committed; its rows are dated 2001 and titled
``zzlinks-...``. Skipped without it.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services import links
from app.services.links import TOPIC_TAGS, lift, rank_links
from app.services.titles import dedup_key, story_key

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)

START = datetime(2001, 1, 10, tzinfo=timezone.utc)
END = START + timedelta(days=1)


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


# ---------------------------------------------------------------------------
# A window with one story syndicated ten times
# ---------------------------------------------------------------------------

EARHART = "zzlinks-Amelia Earhart expedition heads to South Pacific"
GULF = "zzlinks-Gulf talks stall"
OUTLETS = ["", " | AP News", " - WTOP", " - KSL.com", " | Fox News", " - The Spokesman-Review"]
# The site each of OUTLETS' titles comes from (its source_name).
SITES = ["wire.test", "apnews.test", "wtop.test", "ksl.test", "foxnews.test", "spokesman.test"]


def _story(
    title,
    country,
    mentions,
    topic="general",
    tone=0.0,
    keyless=False,
    outlet="zzlinks.test",
    **gkg,
) -> dict:
    """An article; *keyless* if written before ingestion stored story_key.

    *outlet* is its source_name: one site for all unless a test says
    otherwise, so a pair is a link only when its test gives it three.
    """
    return {
        "title": title,
        "country_code": country,
        "mentioned_countries": mentions,
        "topic_tags": [topic],
        "sentiment_score": tone,
        "keyless": keyless,
        "outlet": outlet,
        **gkg,
    }


def _window_stories() -> list[dict]:
    """16 stories in 30 rows, 15 of them linking two countries.

    KI-UM: one story, syndicated 10 times (7 copies placed in UM, 3 in KI)
    by 6 sites. IR-US: 7 stories. 4 from the US (politics, tone 0.5); 2 from
    Iran (conflict, tone -0.5), one of them syndicated 5 times; and "Gulf
    talks", whose two copies differ: one from Iran naming the US (politics,
    0.9), one from the US naming Iran and Israel (conflict, -0.3), so IL-US
    has that one story, from one site. DE-FR: 4 stories from 4 sites; CN-US:
    3 from 3; plus a US story naming only the US (no link).
    """
    rows = [
        _story(
            EARHART + OUTLETS[i % len(OUTLETS)],
            "UM" if i < 7 else "KI",
            ["KI", "UM"],
            topic="environment",
            tone=-0.2,
            outlet=SITES[i % len(SITES)],
            persons=["Amelia Earhart"],
            themes=[
                "MARITIME",
                "TAX_FNCACT",
                "TAX_FNCACT_EXPLORER",
                "TAX_ETHNICITY",
                "TAX_WORLDLANGUAGES",
            ],
        )
        for i in range(10)
    ]
    us_iran_sites = ["reuters.test", "apnews.test", "bbc.test", "aljazeera.test"]
    rows += [
        _story(
            f"zzlinks-US and Iran story {i}",
            "US",
            ["US", "IR"],
            "politics",
            0.5,
            outlet=site,
        )
        for i, site in enumerate(us_iran_sites)
    ]
    rows += [
        _story(
            "zzlinks-Iran strikes back" + OUTLETS[i],
            "IR",
            ["IR", "US"],
            "conflict",
            -0.5,
            outlet=SITES[i],
            persons=["Abbas Araghchi"],
        )
        for i in range(5)
    ]
    rows.append(
        _story(
            "zzlinks-Iran answers Washington",
            "IR",
            ["IR", "US"],
            "conflict",
            -0.5,
            outlet="presstv.test",
            persons=["Abbas Araghchi"],
        )
    )
    rows += [
        _story(GULF + " - Reuters", "IR", ["IR", "US"], "politics", 0.9, outlet="reuters.test"),
        _story(
            GULF + " | AP News", "US", ["US", "IR", "IL"], "conflict", -0.3, outlet="apnews.test"
        ),
    ]
    rows += [
        _story(f"zzlinks-France and Germany {i}", "FR", ["FR", "DE"], outlet=site)
        for i, site in enumerate(["lemonde.test", "dw.test", "france24.test", "spiegel.test"])
    ]
    rows += [
        _story(f"zzlinks-US and China {i}", "US", ["US", "CN"], outlet=site)
        for i, site in enumerate(["scmp.test", "nytimes.test", "xinhua.test"])
    ]
    rows.append(_story("zzlinks-US only", "US", ["US"]))
    return rows


async def _insert(conn, stories: list[dict], start: datetime = START) -> None:
    """The stories as ingestion writes them: story_key from titles.story_key."""
    for i, s in enumerate(stories):
        url = f"https://zzlinks.test/{uuid.uuid4()}"
        await conn.execute(
            """
            INSERT INTO articles (
                title, source_url, source_name, published_at, latitude, longitude, location,
                country_code, topic_tags, sentiment_score, mentioned_countries, persons, themes,
                story_key
            )
            VALUES ($1, $2, $11, $3, 0, 0,
                    ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography, $4, $5, $6, $7, $8, $9, $10)
            """,
            s["title"],
            url,
            start + timedelta(minutes=i),
            s["country_code"],
            s["topic_tags"],
            s["sentiment_score"],
            s["mentioned_countries"],
            s.get("persons", []),
            s.get("themes", []),
            None if s["keyless"] else story_key(s["title"], url),
            s["outlet"],
        )


class _OneConnectionPool:
    """The pool, as the services use it, on the test's connection: one query at a time."""

    def __init__(self, connection):
        self._conn = connection
        self._lock = asyncio.Lock()

    async def fetch(self, *args):
        async with self._lock:
            return await self._conn.fetch(*args)

    async def fetchrow(self, *args):
        async with self._lock:
            return await self._conn.fetchrow(*args)


@pytest_asyncio.fixture
async def pool(conn):
    """The services' pool, on the test's connection."""
    with patch(
        "app.services.links.get_pool",
        new_callable=AsyncMock,
        return_value=_OneConnectionPool(conn),
    ):
        yield


@pytest_asyncio.fixture
async def window(conn, pool):
    await _insert(conn, _window_stories())


def _by_pair(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["a"], r["b"]): r for r in rows}


@pytest.mark.usefixtures("window")
class TestDistinctStories:
    @pytest.mark.asyncio
    async def test_a_syndicated_story_counts_once(self):
        pairs = _by_pair(await links.get_link_pairs(START, END, None))
        assert pairs["KI", "UM"]["n"] == 1
        assert pairs["IR", "US"]["n"] == 7
        assert (pairs["DE", "FR"]["n"], pairs["CN", "US"]["n"]) == (4, 3)

    @pytest.mark.asyncio
    async def test_lift_counts_stories_everywhere(self):
        pairs = _by_pair(await links.get_link_pairs(START, END, None))
        ki_um, ir_us = pairs["KI", "UM"], pairs["IR", "US"]
        # 15 linking stories; the US is in 10 (7 with Iran, 3 with China), Iran in 7.
        assert {r["total"] for r in pairs.values()} == {15}
        assert (ki_um["n_a"], ki_um["n_b"]) == (1, 1)
        assert (ir_us["n_a"], ir_us["n_b"]) == (7, 10)
        assert lift(ir_us["n"], ir_us["n_a"], ir_us["n_b"], ir_us["total"]) == 7 * 15 / (7 * 10)

    @pytest.mark.asyncio
    async def test_one_syndicated_story_does_not_rank_by_lift(self):
        rows = await links.get_link_pairs(START, END, None)
        by_lift = rank_links(rows, "lift", 40)
        assert [(r["a"]["iso"], r["b"]["iso"], r["n"], r["lift"]) for r in by_lift] == [
            ("IR", "US", 7, 1.5)
        ]
        by_count = rank_links(rows, "count", 40)
        assert [(r["a"]["iso"], r["b"]["iso"], r["n"]) for r in by_count] == [
            ("IR", "US", 7),
            ("DE", "FR", 4),
            ("CN", "US", 3),
            ("KI", "UM", 1),  # one wire story on six sites: no site's alone
            # IL-US: one copy, so one outlet, under MIN_LINK_OUTLETS.
        ]
        pairs = _by_pair(rows)
        assert (pairs["KI", "UM"]["outlets"], pairs["KI", "UM"]["top_exclusive_stories"]) == (6, 0)
        assert pairs["IL", "US"]["outlets"] == 1
        # IR-US: apnews.test carried 3 of its 7 stories, but 2 were on other sites too.
        assert pairs["IR", "US"]["top_exclusive_stories"] == 1

    @pytest.mark.asyncio
    async def test_topic_tone_and_origin_are_per_story(self):
        rows = await links.get_link_pairs(START, END, None)
        pairs = _by_pair(rows)
        ir_us, ki_um = pairs["IR", "US"], pairs["KI", "UM"]
        # Copies would make it 5 politics to 7 conflict, 0.05 and from Iran (7 of 12 rows).
        assert (ir_us["politics"], ir_us["conflict"]) == (5, 3)
        assert round(ir_us["tone"], 4) == round((4 * 0.5 + 2 * -0.5 + 0.3) / 7, 4)
        assert ir_us["from_iso"] == "US"
        assert (ki_um["environment"], ki_um["from_iso"]) == (1, "UM")
        [link] = [r for r in rank_links(rows, "count", 40) if r["a"]["iso"] == "IR"]
        assert (link["topic"], link["tone"], link["from"]) == ("politics", 0.19, "US")

    @pytest.mark.asyncio
    async def test_a_storys_copies_can_differ(self):
        """Gulf talks: a politics copy from Iran, a conflict copy from the US naming Israel too."""
        pairs = _by_pair(await links.get_link_pairs(START, END, None))
        ir_us, il_us = pairs["IR", "US"], pairs["IL", "US"]
        # A story links a pair, and has a topic, if any of its copies does.
        assert (ir_us["n"], ir_us["politics"], ir_us["conflict"]) == (7, 5, 3)
        assert (il_us["n"], il_us["politics"], il_us["conflict"]) == (1, 0, 1)
        # The US is in Gulf talks once, though in two of its pairs.
        assert ir_us["n_b"] == il_us["n_b"] == 10
        assert il_us["n_a"] == 1
        # Its copies' tones average first (0.9 and -0.3: 0.3), then the pair's stories.
        assert round(ir_us["tone"], 4) == round((4 * 0.5 + 2 * -0.5 + (0.9 - 0.3) / 2) / 7, 4)
        assert round(il_us["tone"], 4) == -0.3
        # The inspector agrees, though only one of the story's copies links IL-US.
        il_us_detail = await links.get_link_detail("IL", "US", START, END, None)
        assert (il_us_detail["n"], il_us_detail["lift"], il_us_detail["tone"]) == (1, 1.5, -0.3)
        assert il_us_detail["topic_mix"] == {tag: int(tag == "conflict") for tag in TOPIC_TAGS}
        ir_us_detail = await links.get_link_detail("IR", "US", START, END, None)
        assert (ir_us_detail["n"], ir_us_detail["lift"]) == (7, 1.5)
        assert (ir_us_detail["topic_mix"]["politics"], ir_us_detail["topic_mix"]["conflict"]) == (
            5,
            3,
        )
        assert ir_us_detail["tone"] == round(ir_us["tone"], 2)

    @pytest.mark.asyncio
    async def test_a_topic_filter_counts_that_topics_stories(self):
        pairs = _by_pair(await links.get_link_pairs(START, END, "conflict"))
        # Gulf talks' conflict copy only: it names Israel too.
        assert sorted(pairs) == [("IL", "US"), ("IR", "US")]
        assert (pairs["IR", "US"]["n"], pairs["IR", "US"]["total"]) == (3, 3)
        assert pairs["IL", "US"]["n"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("topic", [None, "conflict"])
    async def test_detail_stats_agree_with_links(self, topic):
        for row in await links.get_link_pairs(START, END, topic):
            detail = await links.get_link_detail(row["a"], row["b"], START, END, topic)
            assert detail["n"] == row["n"]
            assert detail["lift"] == round(lift(row["n"], row["n_a"], row["n_b"], row["total"]), 2)
            assert detail["tone"] == round(row["tone"], 2)
            assert detail["topic_mix"] == {tag: row[tag] for tag in TOPIC_TAGS}
            assert detail["outlets"] == row["outlets"]
            share = round(row["top_exclusive_stories"] / row["n"], 2)
            assert detail["top_exclusive_share"] == share

    @pytest.mark.asyncio
    async def test_detail_names_and_themes_count_stories(self):
        ki_um = await links.get_link_detail("KI", "UM", START, END, None)
        assert (ki_um["n"], ki_um["lift"]) == (1, 15.0)
        # In ten copies of one story: not shared by two stories.
        assert ki_um["shared"] == []
        # Functional actors, ethnicities and languages, bare family codes included,
        # are not fetched.
        assert ki_um["themes"] == ["Maritime"]
        pool = await links.get_pool()  # the test's connection
        rows = await pool.fetch(*links.detail_themes_query("KI", "UM", START, END, None, 25))
        assert [r["theme"] for r in rows] == ["MARITIME"]
        ir_us = await links.get_link_detail("IR", "US", START, END, None)
        assert ir_us["shared"] == [{"name": "Abbas Araghchi", "type": "person", "n": 2}]


@pytest.mark.asyncio
async def test_unkeyed_articles_count_by_their_exact_title(conn):
    """Written before ingestion stored story_key: counted, exact-title copies once."""
    start = datetime(2001, 2, 10, tzinfo=timezone.utc)
    floods = "zzlinks-Monsoon floods Dhaka"
    await _insert(
        conn,
        [
            _story(floods + " - Reuters", "BD", ["BD", "IN"], keyless=True),
            _story(floods + " - REUTERS", "BD", ["BD", "IN"], keyless=True),  # same, any case
            _story(floods + " | BBC News", "BD", ["BD", "IN"], keyless=True),  # not stripped
            _story(floods + " - Reuters", "BD", ["BD", "IN"]),  # keyed copies: one story
            _story(floods + " | BBC News", "IN", ["IN", "BD"]),
        ],
        start,
    )
    end = start + timedelta(days=1)

    [row] = await conn.fetch(*links.links_query(start, end, None))
    assert (row["a"], row["b"], row["n"], row["n_a"], row["n_b"], row["total"]) == (
        "BD",
        "IN",
        3,
        3,
        3,
        3,
    )
    stats = await conn.fetchrow(*links.detail_stats_query("BD", "IN", start, end, None))
    assert (stats["n"], stats["total"]) == (3, 3)


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_a_syndicated_story_takes_one_place_in_the_inspector(conn):
    """12 copies of the newest story do not crowd the 10 older stories out."""
    start = datetime(2001, 3, 10, tzinfo=timezone.utc)
    others = [f"zzlinks-Nepal and India story {i}" for i in range(10)]
    quake = "zzlinks-Quake hits Kathmandu"
    await _insert(
        conn,
        [_story(title, "NP", ["NP", "IN"]) for title in others]  # oldest first
        + [_story(quake + OUTLETS[i % len(OUTLETS)], "IN", ["IN", "NP"]) for i in range(12)],
        start,
    )
    end = start + timedelta(days=1)
    newest_first = [dedup_key(quake)] + [dedup_key(t) for t in reversed(others)]

    detail = await links.get_link_detail("IN", "NP", start, end, None)
    assert [dedup_key(r["title"]) for r in detail["articles"]] == newest_first
    # Each story's newest copy.
    assert detail["articles"][0]["title"] == quake + OUTLETS[11 % len(OUTLETS)]

    headlines = await links.get_link_headlines("IN", "NP", start, end, None, 25)
    assert [dedup_key(t) for t in headlines] == newest_first


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_one_outlet_does_not_make_a_link(conn):
    """srilankamirror.com tagged the BVI on every page: six unrelated stories, one site."""
    start = datetime(2001, 4, 10, tzinfo=timezone.utc)
    site = "srilankamirror.com"
    titles = ["Port compensation", "Cinema weapons find", "France protests", "Stress among wives"]
    stories = [_story(f"zzlinks-{t}", "LK", ["LK", "VG"], outlet=site) for t in titles]
    stories += [_story(f"zzlinks-More news {i}", "LK", ["LK", "VG"], outlet=site) for i in range(2)]
    stories.append(_story("zzlinks-Port compensation", "LK", ["LK", "VG"], outlet=""))  # no site
    await _insert(conn, stories, start)
    end = start + timedelta(days=1)

    [row] = await links.get_link_pairs(start, end, None)
    assert (row["a"], row["b"], row["n"], row["outlets"]) == ("LK", "VG", 6, 1)
    assert rank_links([row], "lift", 40) == rank_links([row], "count", 40) == []
    # The inspector still answers for it, and says why it is not listed.
    detail = await links.get_link_detail("LK", "VG", start, end, None)
    assert (detail["n"], detail["outlets"]) == (6, 1)


async def _lk_vg(conn, day: int, stories_by_outlet: dict[str, list[str]]):
    """LK-VG stories on 2001-06-<day>, by site; a title under two sites is one story twice.

    The calling test needs the ``pool`` fixture, for the services' queries.
    """
    start = datetime(2001, 6, day, tzinfo=timezone.utc)
    stories = [
        _story(f"zzlinks-{title}", "LK", ["LK", "VG"], outlet=site)
        for site, titles in stories_by_outlet.items()
        for title in titles
    ]
    await _insert(conn, stories, start)
    end = start + timedelta(days=1)
    [row] = await links.get_link_pairs(start, end, None)
    detail = await links.get_link_detail("LK", "VG", start, end, None)
    return row, detail


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_one_outlet_with_most_of_the_stories_is_not_a_link(conn):
    """LK-VG, live: srilankamirror.com's four mis-tagged stories beside two genuine ones."""
    row, detail = await _lk_vg(
        conn,
        10,
        {
            "srilankamirror.com": ["Port compensation", "Cinema weapons", "Protests", "Wives"],
            "slguardian.org": ["China Merchants port settlement"],
            "sundaytimes.lk": ["Port settlement reached"],
        },
    )
    assert (row["n"], row["outlets"], row["top_exclusive_stories"]) == (6, 3, 4)
    assert rank_links([row], "lift", 40) == rank_links([row], "count", 40) == []
    # The inspector answers, and says why: 4 of 6 on that site alone.
    assert (detail["n"], detail["outlets"], detail["top_exclusive_share"]) == (6, 3, 0.67)


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_a_wire_services_stories_reposted_elsewhere_are_a_link(conn):
    """apnews carries every AP story it wrote, but msn and yahoo carry them too."""
    ap = ["AP 1", "AP 2", "AP 3", "AP 4"]
    row, detail = await _lk_vg(
        conn,
        13,
        {
            "apnews.test": ap,
            "msn.test": ap,
            "yahoo.test": ap,
            "local1.test": ["Local 1"],
            "local2.test": ["Local 2"],
        },
    )
    assert (row["n"], row["outlets"], row["top_exclusive_stories"]) == (6, 5, 1)
    [link] = rank_links([row], "lift", 40)
    assert link["top_exclusive_share"] == 0.17  # was apnews' 4 of 6, any site counted
    assert detail["top_exclusive_share"] == 0.17


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_an_even_spread_is_a_link(conn):
    row, detail = await _lk_vg(
        conn,
        11,
        {
            "a.zzlinks.test": ["Story 1", "Story 2"],
            "b.zzlinks.test": ["Story 3", "Story 4"],
            "c.zzlinks.test": ["Story 5", "Story 6"],
        },
    )
    assert (row["n"], row["outlets"], row["top_exclusive_stories"]) == (6, 3, 2)
    [link] = rank_links([row], "lift", 40)
    assert (link["outlets"], link["top_exclusive_share"]) == (3, 0.33)
    assert detail["top_exclusive_share"] == 0.33


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool")
async def test_exactly_half_alone_is_a_link(conn):
    """3 of 6 on one site alone is not more than half. A story also on another site
    is no site's alone (Story 5: b and c), and copies on one site are one story."""
    row, detail = await _lk_vg(
        conn,
        12,
        {
            "a.zzlinks.test": ["Story 1", "Story 1 - Wire", "Story 2", "Story 3"],
            "b.zzlinks.test": ["Story 4", "Story 5"],
            "c.zzlinks.test": ["Story 5 | C News", "Story 6"],
        },
    )
    assert (row["n"], row["outlets"], row["top_exclusive_stories"]) == (6, 3, 3)
    [link] = rank_links([row], "count", 40)
    assert link["top_exclusive_share"] == 0.5
    assert (detail["n"], detail["top_exclusive_share"]) == (6, 0.5)
