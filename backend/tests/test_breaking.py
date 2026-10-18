"""Tests for breaking stories: the SQL sent (pool mocked), then its results on a real database.

The database tests build 1536-d unit vectors with chosen cosines. A story of event k is
``c * e_k + sqrt(1 - c^2) * u``, with ``e_k`` the event's axis and ``u`` an axis of its own,
so two stories of one event are ``c1 * c2`` alike and stories of different events 0.
"""

import itertools
import math
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import breaking
from app.services.titles import story_key, story_key_sql

NOW = datetime(2026, 10, 18, 15, 30, tzinfo=timezone.utc)


def _sql(query: str) -> str:
    return " ".join(query.split())


@pytest.fixture
def pool():
    mock = MagicMock()
    mock.fetch = AsyncMock(return_value=[])
    with patch.object(breaking, "get_pool", AsyncMock(return_value=mock)):
        yield mock


def _fetched(pool) -> tuple[str, list]:
    query, *args = pool.fetch.call_args.args
    return _sql(query), args


def _row(**overrides):
    """A row of the breaking query: the event, its neighbourhood's counts, then its lead."""
    row = {
        "lat": 43.5,
        "lng": 5.5,
        "outlets": 10,
        "stories": 9,
        "first_seen": datetime(2026, 10, 18, 14, 5, tzinfo=timezone.utc),
        "politics": 1,
        "conflict": 9,
        "technology": 0,
        "environment": 0,
        "economy": 0,
        "health": 0,
        "headline": "Principal and teacher shot at a school in Aubagne",
        "region": "Aubagne, Provence-Alpes-Cote D'azur, France (General), France",
        "country_code": "FR",
        "event_tags": ["conflict"],
        "title": "Pupil detained after school shooting in France",
        "source_name": "example.com",
        "published_at": datetime(2026, 10, 18, 15, 15, tzinfo=timezone.utc),
        "image_url": "https://cdn.example.com/a.jpg",
        "topic_tags": ["conflict", "politics"],
    }
    return {**row, **overrides}


class TestRule:
    def test_the_rule_is_in_named_constants(self):
        assert breaking.MIN_OUTLETS == 7
        assert breaking.SAME_STORY_SIM == 0.60
        assert breaking.MIN_NEW_SHARE == 0.5
        assert (breaking.RECENT, breaking.PRIOR) == (timedelta(hours=2), timedelta(hours=24))


class TestBreakingQuery:
    @pytest.mark.asyncio
    async def test_windows_are_the_last_2_hours_and_the_22_before(self, pool):
        await breaking.get_breaking(NOW)

        query, args = _fetched(pool)
        assert args == [NOW - timedelta(hours=2), NOW - timedelta(hours=24)]
        assert "WHERE a.published_at >= $1 AND a.embedding IS NOT NULL" in query
        assert "p.published_at >= $2 AND p.published_at < $1" in query
        assert max(int(n) for n in re.findall(r"\$(\d+)", query)) == len(args)

    @pytest.mark.asyncio
    async def test_one_row_per_story_its_newest_embedded_copy(self, pool):
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        recent = query[query.index("WITH recent AS") : query.index("candidates AS (")]
        assert f"{story_key_sql('a')} AS story" in recent
        assert "SELECT DISTINCT ON (story)" in recent
        assert "ORDER BY story, published_at DESC, id" in recent
        assert "NULLIF(a.source_name, '') AS outlet" in recent

    @pytest.mark.asyncio
    async def test_candidates_are_cells_with_seven_outlets(self, pool):
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        assert "GROUP BY 1, 2 HAVING count(DISTINCT outlet) >= 7" in query

    @pytest.mark.asyncio
    async def test_neighbours_are_alike_stories_in_the_same_cell_exactly(self, pool):
        """Exact cosine distances within a cell: no index, about the sum of n^2 pairs."""
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        hood = query[query.index("neighbourhoods AS (") : query.index("events AS (")]
        assert "FROM stories s JOIN stories t" in hood
        assert "ON t.lat_cell = s.lat_cell AND t.lng_cell = s.lng_cell" in hood
        assert "AND 1 - (s.embedding <=> t.embedding) >= 0.6" in hood
        assert "count(DISTINCT t.outlet) AS outlets" in hood
        assert "count(DISTINCT t.story) AS stories" in hood
        assert "min(t.published_at) AS first_seen" in hood
        assert "halfvec" not in query

    @pytest.mark.asyncio
    async def test_a_cells_event_is_its_most_covered_story_newest_on_a_tie(self, pool):
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        events = query[query.index("events AS (") : query.index("prior AS (")]
        assert "SELECT DISTINCT ON (lat_cell, lng_cell)" in events
        assert "ORDER BY lat_cell, lng_cell, outlets DESC, published_at DESC, id" in events
        assert "WHERE best.outlets >= 7" in events  # only events big enough go on

    @pytest.mark.asyncio
    async def test_coverage_must_be_mostly_new(self, pool):
        """Outlets on it in the 22 hours before, besides those on it now, are at most as
        many as now."""
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        prior = query[query.index("prior AS (") : query.index("breaking AS (")]
        assert "count(DISTINCT p.source_name) AS prior_outlets" in prior
        assert "NOT (p.source_name = ANY (e.outlet_list))" in prior
        assert "AND 1 - (e.embedding <=> p.embedding) >= 0.6" in prior
        assert "ON FLOOR(p.latitude) = e.lat_cell AND FLOOR(p.longitude) = e.lng_cell" in prior
        assert "e.outlets >= 0.5 * (e.outlets + COALESCE(pr.prior_outlets, 0))" in query

    @pytest.mark.asyncio
    async def test_one_event_under_two_places_keeps_the_most_covered(self, pool):
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        assert (
            "WHERE NOT EXISTS ( SELECT 1 FROM breaking o "
            "WHERE (o.outlets, o.first_seen, -o.lat_cell, -o.lng_cell) "
            "> (b.outlets, b.first_seen, -b.lat_cell, -b.lng_cell) "
            "AND 1 - (o.embedding <=> b.embedding) >= 0.6 )"
        ) in query

    @pytest.mark.asyncio
    async def test_ordered_by_outlets_then_first_seen_newest_then_cell(self, pool):
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        assert query.endswith("ORDER BY d.outlets DESC, d.first_seen DESC, d.lat_cell, d.lng_cell")

    @pytest.mark.asyncio
    async def test_returns_named_columns_never_the_embedding(self, pool):
        await breaking.get_breaking(NOW)

        query, _ = _fetched(pool)
        final = query[query.rindex("SELECT d.lat_cell") : query.rindex("FROM distinct_events")]
        assert "embedding" not in final
        assert "SELECT *" not in query and ".*" not in query


class TestGetBreaking:
    @pytest.mark.asyncio
    async def test_rows_become_breaking_stories(self, pool):
        pool.fetch.return_value = [_row()]

        [story] = await breaking.get_breaking(NOW)

        assert story == {
            "headline": "Principal and teacher shot at a school in Aubagne",
            "place": "Aubagne, Provence-Alpes-Cote D'azur, France",
            "lat": 43.5,
            "lng": 5.5,
            "outlets": 10,
            "stories": 9,
            "first_seen": datetime(2026, 10, 18, 14, 5, tzinfo=timezone.utc),
            "topic": "conflict",  # the most neighbours of the six
            "lead": {
                "title": "Pupil detained after school shooting in France",
                "source_name": "example.com",
                "published_at": datetime(2026, 10, 18, 15, 15, tzinfo=timezone.utc),
                "image_url": "https://cdn.example.com/a.jpg",
                "topic": "conflict",
                "sensitive": True,
            },
        }

    @pytest.mark.asyncio
    async def test_the_headline_is_one_clean_line(self, pool):
        pool.fetch.return_value = [_row(headline="  Quake\u200b hits\n\nKathmandu\x07  " + "x" * 300)]

        [story] = await breaking.get_breaking(NOW)

        assert story["headline"].startswith("Quake hits Kathmandu xxx")
        assert len(story["headline"]) <= 200

    @pytest.mark.asyncio
    async def test_the_place_follows_the_articles_country(self, pool):
        pool.fetch.return_value = [_row(region="Gaza, Israel", country_code="PS")]

        [story] = await breaking.get_breaking(NOW)

        assert story["place"] == "Gaza, Palestine"

    @pytest.mark.asyncio
    async def test_a_tie_between_topics_goes_to_the_events_own_tags(self, pool):
        pool.fetch.return_value = [_row(politics=4, conflict=4, event_tags=["politics"])]

        [story] = await breaking.get_breaking(NOW)

        assert story["topic"] == "politics"

    @pytest.mark.asyncio
    async def test_none_of_the_six_topics_is_general(self, pool):
        pool.fetch.return_value = [_row(politics=0, conflict=0, event_tags=["sport"])]

        [story] = await breaking.get_breaking(NOW)

        assert story["topic"] == "general"


# ── Against the scratch database (skipped without ORBIS_TEST_DATABASE_URL) ──

# Far from the real data's dates, so only these rows are in either window.
DB_NOW = datetime(2031, 3, 1, 12, 0, tzinfo=timezone.utc)
DIMS = 1536

_INSERT = """
    INSERT INTO articles (title, source_url, source_name, published_at, latitude, longitude,
                          location, region, country_code, topic_tags, image_url, story_key,
                          embedding)
    VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_MakePoint($6, $5), 4326)::geography,
            $7, $8, $9, $10, $11, $12::text::vector)
"""

_URLS = itertools.count()  # source_url is unique, across a test's inserts too


def _vector(event: int, own: int, c: float) -> str:
    """``c`` along event axis *event*, the rest along axis *own*: a unit vector, as text."""
    v = [0.0] * DIMS
    v[event] = c
    v[own] = math.sqrt(1 - c * c)
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class _Feed:
    """Builds a test's rows; every story gets an axis of its own (from 400 up)."""

    def __init__(self):
        self.rows: list[dict] = []
        self._axes = itertools.count(400)

    def story(self, lat, lng, title, *, outlet, event, c=0.9, minutes=10, **extra):
        """A story *minutes* before DB_NOW (negative: after), about *event* (an axis < 400)."""
        row = {
            "title": title,
            "source": outlet,
            "at": DB_NOW - timedelta(minutes=minutes),
            "lat": lat,
            "lng": lng,
            "vector": _vector(event, next(self._axes), c),
            **extra,
        }
        self.rows.append(row)
        return row

    def event(self, lat, lng, n, *, event, prefix, minutes=10, c=0.9, **extra):
        """*n* stories of one event in one cell, each from its own outlet, a minute apart."""
        return [
            self.story(
                lat,
                lng,
                f"{prefix} {i}",
                outlet=f"{prefix}-outlet{i}.example",
                event=event,
                c=c,
                minutes=minutes + i,
                **extra,
            )
            for i in range(n)
        ]

    async def insert(self, pg):
        args = []
        for r in self.rows:
            title = f"zzbreak-{r['title']}"
            url = f"https://zzbreak.example/{next(_URLS)}"
            args.append(
                (
                    title,
                    url,
                    r["source"],
                    r["at"],
                    r["lat"],
                    r["lng"],
                    r.get("region", "Testville"),
                    r.get("country", "ZZ"),  # no such code: the region shows as stored
                    r.get("tags", ["general"]),
                    r.get("image"),
                    story_key(title, url),
                    None if r.get("unembedded") else r["vector"],
                )
            )
        await pg.executemany(_INSERT, args)


async def _db_breaking(pg, now=DB_NOW):
    with patch.object(breaking, "get_pool", AsyncMock(return_value=pg)):
        return await breaking.get_breaking(now)


class TestBreakingOnPostgres:
    @pytest.mark.asyncio
    async def test_ten_outlets_on_one_event_is_breaking(self, pg):
        """Aubagne: ten outlets, each its own story of one school shooting."""
        feed = _Feed()
        stories = feed.event(
            43.3, 5.6, 10, event=1, prefix="aubagne", tags=["conflict"], region="Aubagne, France"
        )
        stories[3]["image"] = "https://cdn.example/aubagne.jpg"
        await feed.insert(pg)

        [story] = await _db_breaking(pg)

        assert (story["lat"], story["lng"], story["place"]) == (43.5, 5.5, "Aubagne, France")
        assert (story["outlets"], story["stories"]) == (10, 10)
        assert story["headline"] == "zzbreak-aubagne 0"  # the newest of the most covered
        assert story["first_seen"] == DB_NOW - timedelta(minutes=19)  # the earliest neighbour
        assert story["topic"] == "conflict"
        assert story["lead"]["image_url"] == "https://cdn.example/aubagne.jpg"
        assert story["lead"]["sensitive"] is True

    @pytest.mark.asyncio
    async def test_one_outlets_eight_stories_are_not_breaking(self, pg):
        """Bonita Springs: one local outlet's crawl batch, unrelated items."""
        feed = _Feed()
        for i in range(8):
            feed.story(26.3, -81.8, f"local item {i}", outlet="winknews.example", event=10 + i)
        await feed.insert(pg)

        assert await _db_breaking(pg) == []

    @pytest.mark.asyncio
    async def test_a_hub_with_forty_outlets_on_forty_stories_is_not_breaking(self, pg):
        """Kew Gardens (London): many outlets, each on something else; the most any story
        has is 6 outlets."""
        feed = _Feed()
        for i in range(40):
            feed.story(51.5, -0.3, f"london item {i}", outlet=f"paper{i}.example", event=20 + i)
        feed.event(51.5, -0.3, 6, event=80, prefix="london event")
        await feed.insert(pg)

        assert await _db_breaking(pg) == []

    @pytest.mark.asyncio
    async def test_an_ongoing_story_more_covered_before_is_not_breaking(self, pg):
        """8 outlets now, 12 others in the 22 hours before: 40% new."""
        feed = _Feed()
        feed.event(22.6, 88.4, 8, event=2, prefix="now")
        feed.event(22.6, 88.4, 12, event=2, prefix="before", minutes=600)
        await feed.insert(pg)

        assert await _db_breaking(pg) == []

    @pytest.mark.asyncio
    async def test_half_new_is_enough_and_the_outlets_on_it_now_dont_count_before(self, pg):
        """8 outlets now and 8 others before is 50%: breaking. The 8 now filed before too,
        and a day and more ago 30 others: neither counts against it."""
        feed = _Feed()
        now = feed.event(22.6, 88.4, 8, event=2, prefix="now")
        feed.event(22.6, 88.4, 8, event=2, prefix="before", minutes=600)
        for i, r in enumerate(now):
            feed.story(22.6, 88.4, f"earlier {i}", outlet=r["source"], event=2, minutes=300)
        feed.event(22.6, 88.4, 30, event=2, prefix="yesterday", minutes=26 * 60)
        await feed.insert(pg)

        [story] = await _db_breaking(pg)

        assert story["outlets"] == 8

    @pytest.mark.asyncio
    async def test_one_event_in_two_cells_is_one_story(self, pg):
        """The same event filed under Paris and under France's centroid: the cell more
        outlets cover keeps it. A different event elsewhere stays."""
        feed = _Feed()
        feed.event(48.8, 2.3, 10, event=3, prefix="paris")
        feed.event(46.2, 2.2, 8, event=3, prefix="france")
        feed.event(41.9, 12.5, 7, event=4, prefix="rome")
        await feed.insert(pg)

        result = await _db_breaking(pg)

        assert [(s["lat"], s["lng"], s["outlets"]) for s in result] == [
            (48.5, 2.5, 10),
            (41.5, 12.5, 7),
        ]

    @pytest.mark.asyncio
    async def test_unembedded_rows_are_ignored(self, pg):
        """Rows ingestion hasn't embedded yet: 10 outlets, but only 6 embedded."""
        feed = _Feed()
        stories = feed.event(29.4, -98.6, 10, event=5, prefix="utsa")
        for r in stories[6:]:
            r["unembedded"] = True
        await feed.insert(pg)

        assert await _db_breaking(pg) == []

    @pytest.mark.asyncio
    async def test_copies_of_one_story_are_one_story_and_its_newest_outlet(self, pg):
        """8 outlets running one wire copy word for word: one story, one outlet."""
        feed = _Feed()
        for i in range(8):
            feed.story(36.1, -95.9, "one wire story", outlet=f"o{i}.example", event=6)
        await feed.insert(pg)

        assert await _db_breaking(pg) == []

    @pytest.mark.asyncio
    async def test_seven_outlets_are_enough_and_six_are_not(self, pg):
        feed = _Feed()
        feed.event(48.2, 16.4, 7, event=7, prefix="vienne")
        feed.event(41.4, 2.2, 6, event=8, prefix="barcelona")
        await feed.insert(pg)

        result = await _db_breaking(pg)

        assert [(s["lat"], s["outlets"]) for s in result] == [(48.5, 7)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("c", "outlets"), [(0.672, 7), (0.661, 6)])
    async def test_alike_means_a_cosine_of_at_least_0_6(self, pg, c, outlets):
        """Six stories 0.81 alike, and a seventh 0.9 * c alike to each: 0.605 counts it,
        0.595 doesn't."""
        feed = _Feed()
        feed.event(13.7, 100.5, 6, event=9, prefix="bangkok")
        feed.story(13.7, 100.5, "edge", outlet="edge.example", event=9, c=c, minutes=30)
        feed.story(13.7, 100.5, "other", outlet="other.example", event=99, minutes=31)
        await feed.insert(pg)

        result = await _db_breaking(pg)

        assert [s["outlets"] for s in result] == ([7] if outlets == 7 else [])

    @pytest.mark.asyncio
    async def test_the_topic_is_the_neighbours_dominant_one(self, pg):
        feed = _Feed()
        feed.event(45.4, -75.7, 6, event=11, prefix="ottawa", tags=["conflict"])
        feed.story(
            45.4, -75.7, "ottawa newest", outlet="x.example", event=11, minutes=1, tags=["politics"]
        )
        await feed.insert(pg)

        [story] = await _db_breaking(pg)

        assert story["headline"] == "zzbreak-ottawa newest"
        assert story["topic"] == "conflict"  # 6 of 7 neighbours, not the event's own tag

    @pytest.mark.asyncio
    async def test_ordered_by_outlets_then_newest_first_seen(self, pg):
        feed = _Feed()
        feed.event(10.2, 20.2, 7, event=12, prefix="older", minutes=60)
        feed.event(12.2, 20.2, 7, event=13, prefix="newer", minutes=10)
        feed.event(14.2, 20.2, 9, event=14, prefix="bigger", minutes=90)
        await feed.insert(pg)

        result = await _db_breaking(pg)

        assert [(s["lat"], s["outlets"]) for s in result] == [(14.5, 9), (12.5, 7), (10.5, 7)]
