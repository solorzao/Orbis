"""Tests for surge detection: the SQL sent (pool mocked), then its results on a real database."""

import itertools
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.services import surges
from app.services.titles import dedup_title_sql

NOW = datetime(2026, 10, 12, 14, 30, tzinfo=timezone.utc)


def _sql(query: str) -> str:
    return " ".join(query.split())


@pytest.fixture
def pool():
    mock = MagicMock()
    mock.fetchval = AsyncMock(return_value=True)  # stories arrived in the last 2 hours
    mock.fetch = AsyncMock(return_value=[])
    with patch.object(surges, "get_pool", AsyncMock(return_value=mock)):
        yield mock


def _fetched(pool) -> tuple[str, list]:
    query, *args = pool.fetch.call_args.args
    return _sql(query), args


def _surge_row(**overrides):
    row = {
        "lat": -4.5,
        "lng": 15.5,
        "recent": 21,
        "baseline": 0.734939759,
        "ratio": 28.573770491,
        "politics": 4,
        "conflict": 9,
        "technology": 0,
        "environment": 0,
        "economy": 1,
        "health": 0,
        "title": "Clashes near Kinshasa",
        "source_name": "example.com",
        "published_at": datetime(2026, 10, 12, 14, 15, tzinfo=timezone.utc),
        "image_url": "https://cdn.example.com/k.jpg",
        "region": "Kinshasa, Congo (General), Congo",
        "country_code": "CD",
        "topic_tags": ["conflict", "politics"],
    }
    return {**row, **overrides}


class TestSurgesQuery:
    @pytest.mark.asyncio
    async def test_windows_are_the_last_two_hours_and_the_week_before(self, pool):
        await surges.get_surges(NOW)

        query, args = _fetched(pool)
        assert args == [NOW - timedelta(hours=2), NOW - timedelta(days=7)]
        assert "WHERE published_at >= $1 " in query  # the recent stories
        assert "a.published_at >= $2 AND a.published_at < $1" in query  # the 83 blocks before
        assert max(int(n) for n in re.findall(r"\$(\d+)", query)) == len(args)

    @pytest.mark.asyncio
    async def test_counts_distinct_stories_not_rows(self, pool):
        """Syndicated copies, outlet suffix and all, count once."""
        await surges.get_surges(NOW)

        query, _ = _fetched(pool)
        assert f"{_sql(dedup_title_sql('title'))} AS story" in query
        assert "count(DISTINCT story) AS recent" in query
        assert f"count(DISTINCT {_sql(dedup_title_sql('a.title'))}) AS stories" in query

    @pytest.mark.asyncio
    async def test_a_surge_needs_eight_stories_from_three_sources(self, pool):
        await surges.get_surges(NOW)

        query, _ = _fetched(pool)
        assert "HAVING count(DISTINCT story) >= 8 AND count(DISTINCT source_name) >= 3" in query

    @pytest.mark.asyncio
    async def test_only_those_cells_read_their_week(self, pool):
        """The baseline joins the candidate cells, so only their older stories are keyed."""
        await surges.get_surges(NOW)

        query, _ = _fetched(pool)
        before = query[query.index("before AS (") : query.index("ranked AS (")]
        assert "FROM candidates c JOIN articles a" in before
        assert "ON FLOOR(a.latitude) = c.lat_cell AND FLOOR(a.longitude) = c.lng_cell" in before

    @pytest.mark.asyncio
    async def test_ratio_against_the_blocks_held_floored_at_half_a_story(self, pool):
        await surges.get_surges(NOW)

        query, _ = _fetched(pool)
        assert "COALESCE(b.stories, 0)::float8 / span.blocks AS baseline" in query
        assert (
            "c.recent / GREATEST(COALESCE(b.stories, 0)::float8 / span.blocks, 0.5) AS ratio"
            in query
        )
        assert "WHERE ratio >= 3" in query
        assert "ORDER BY ratio DESC, recent DESC, lat_cell, lng_cell LIMIT 8" in query

    @pytest.mark.asyncio
    async def test_the_blocks_are_those_since_the_oldest_story_at_most_83(self, pool):
        """Production started 2026-10-10; a gap at the start of the week holds no stories.
        Materialised, so the oldest story is looked up once, not once per use."""
        await surges.get_surges(NOW)

        query, args = _fetched(pool)
        assert (
            "span AS MATERIALIZED ( SELECT GREATEST(1, LEAST(83, "
            "EXTRACT(EPOCH FROM $1::timestamptz - "
            "(SELECT min(published_at) FROM articles WHERE published_at >= $2)"
            ")::float8 / 7200)) AS blocks )"
        ) in query
        assert "CROSS JOIN span" in query
        assert args[:2] == [NOW - timedelta(hours=2), NOW - timedelta(days=7)]

    def test_the_week_is_the_retention(self):
        assert surges.RETENTION == timedelta(days=settings.retention_days)
        assert surges.BASELINE_BLOCKS == (surges.RETENTION - surges.RECENT) // surges.RECENT
        assert surges.BASELINE_BLOCKS == 83  # 7 days

    @pytest.mark.asyncio
    async def test_the_lead_is_the_cells_newest_imaged_recent_story(self, pool):
        """As the globe's lead: an exact published_at lookup, https images first."""
        await surges.get_surges(NOW)

        query, _ = _fetched(pool)
        lead = query[query.index("CROSS JOIN LATERAL") :]
        assert "published_at = COALESCE(top.newest_with_image, top.newest)" in lead
        assert "AND (top.newest_with_image IS NULL OR image_url LIKE 'https://%')" in lead
        assert "FLOOR(latitude) = top.lat_cell AND FLOOR(longitude) = top.lng_cell" in lead
        assert "ORDER BY (image_url LIKE 'https://%') DESC NULLS LAST, id LIMIT 1 ) lead" in lead
        assert query.endswith(
            "ORDER BY top.ratio DESC, top.recent DESC, top.lat_cell, top.lng_cell"
        )

    @pytest.mark.asyncio
    async def test_the_lead_brings_its_region_and_country_for_the_place(self, pool):
        await surges.get_surges(NOW)

        query, _ = _fetched(pool)
        assert "lead.region, lead.country_code, lead.topic_tags" in query
        assert (
            "SELECT title, source_name, published_at, image_url, region, country_code, topic_tags"
            " FROM articles WHERE published_at = COALESCE(" in query
        )

    @pytest.mark.asyncio
    async def test_reads_named_columns_never_the_embedding(self, pool):
        await surges.get_surges(NOW, "politics")

        query, _ = _fetched(pool)
        assert "embedding" not in query
        assert "SELECT *" not in query

    @pytest.mark.asyncio
    async def test_no_topic_means_no_topic_predicate(self, pool):
        await surges.get_surges(NOW)

        query, _ = _fetched(pool)
        assert "ARRAY[" not in query

    @pytest.mark.asyncio
    async def test_a_topic_filters_the_recent_stories_the_baseline_and_the_lead(self, pool):
        await surges.get_surges(NOW, "environment")

        query, args = _fetched(pool)
        assert args[2] == "environment"
        assert query.count("topic_tags && ARRAY[$3::text]") == 3
        assert "a.topic_tags && ARRAY[$3::text]" in query
        assert max(int(n) for n in re.findall(r"\$(\d+)", query)) == len(args)


class TestGetSurges:
    @pytest.mark.asyncio
    async def test_no_stories_in_two_hours_is_no_surges(self, pool):
        """A feed outage: nothing to compare, so nothing is surging (and the week isn't read)."""
        pool.fetchval.return_value = False

        assert await surges.get_surges(NOW, "politics") == []

        pool.fetch.assert_not_called()
        query, *args = pool.fetchval.call_args.args
        assert _sql(query) == "SELECT EXISTS (SELECT 1 FROM articles WHERE published_at >= $1)"
        assert args == [NOW - timedelta(hours=2)]  # any story, whatever the topic

    @pytest.mark.asyncio
    async def test_rows_become_surges(self, pool):
        pool.fetch.return_value = [_surge_row()]

        [surge] = await surges.get_surges(NOW)

        assert surge == {
            "lat": -4.5,
            "lng": 15.5,
            "place": "Kinshasa, Democratic Republic of the Congo",  # CD's name
            "recent": 21,
            "baseline": 0.73,
            "ratio": 28.57,
            "topic": "conflict",  # the most stories of the six
            "lead": {
                "title": "Clashes near Kinshasa",
                "source_name": "example.com",
                "published_at": datetime(2026, 10, 12, 14, 15, tzinfo=timezone.utc),
                "image_url": "https://cdn.example.com/k.jpg",
                "topic": "conflict",
                "sensitive": True,
            },
        }

    @pytest.mark.asyncio
    async def test_the_place_follows_the_articles_country(self, pool):
        """GDELT files Gaza under Israel; its code is PS."""
        pool.fetch.return_value = [_surge_row(region="Gaza, Israel", country_code="PS")]

        [surge] = await surges.get_surges(NOW)

        assert surge["place"] == "Gaza, Palestine"

    @pytest.mark.asyncio
    async def test_a_filtered_surge_is_the_topics(self, pool):
        pool.fetch.return_value = [_surge_row()]

        [surge] = await surges.get_surges(NOW, "politics")

        assert surge["topic"] == "politics"

    @pytest.mark.asyncio
    async def test_a_cell_without_the_six_topics_is_general(self, pool):
        pool.fetch.return_value = [
            _surge_row(politics=0, conflict=0, economy=0, topic_tags=["sport"])
        ]

        [surge] = await surges.get_surges(NOW)

        assert surge["topic"] == "general"
        assert surge["lead"]["sensitive"] is False


# ── Against the scratch database (skipped without ORBIS_TEST_DATABASE_URL) ──

# Far from the real data's dates, so only these rows are in either window.
DB_NOW = datetime(2031, 3, 1, 12, 0, tzinfo=timezone.utc)

_INSERT = """
    INSERT INTO articles (title, source_url, source_name, published_at, latitude, longitude,
                          location, region, country_code, topic_tags, image_url)
    VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_MakePoint($6, $5), 4326)::geography,
            $7, $8, $9, $10)
"""


_URLS = itertools.count()  # source_url is unique, across a test's inserts too


async def _insert(pg, rows: list[dict]) -> None:
    await pg.executemany(
        _INSERT,
        [
            (
                f"zzsurge-{r['title']}",
                f"https://zzsurge.example/{next(_URLS)}",
                r["source"],
                r["at"],
                r["lat"],
                r["lng"],
                r.get("region", "Testville"),
                r.get("country", "ZZ"),  # no such code: the region shows as stored
                r.get("tags", ["general"]),
                r.get("image"),
            )
            for r in rows
        ],
    )


def _stories(lat, lng, n, *, sources=4, minutes_ago=30, tags=None, prefix=None, **extra):
    """*n* distinct stories in one cell, spread over *sources* outlets."""
    prefix = prefix or f"{lat},{lng}"
    return [
        {
            "title": f"{prefix} story {i}",
            "source": f"outlet{i % sources}.example",
            "at": DB_NOW - timedelta(minutes=minutes_ago + i),
            "lat": lat,
            "lng": lng,
            "tags": tags or ["general"],
            **extra,
        }
        for i in range(n)
    ]


def _old(lat, lng, title, *, source, minutes):
    """A story *minutes* before the last 2 hours: in the baseline."""
    at = DB_NOW - surges.RECENT - timedelta(minutes=minutes)
    return {"title": title, "source": source, "at": at, "lat": lat, "lng": lng}


async def _db_surges(pg, topic=None, now=DB_NOW):
    with patch.object(surges, "get_pool", AsyncMock(return_value=pg)):
        return await surges.get_surges(now, topic)


class TestSurgesOnPostgres:
    @pytest.mark.asyncio
    async def test_the_spec_cells(self, pg):
        """A surging cell (10 distinct titles, 4 sources, 2 in the week before) surges;
        a syndicated one (12 copies of one title, 1 source) doesn't."""
        surging = _stories(-4.3, 15.3, 10, tags=["conflict"], region="Kinshasa, Congo")
        assert len({s["source"] for s in surging}) == 4
        week = [
            {
                "title": f"old {i}",
                "source": "outlet0.example",
                "at": DB_NOW - timedelta(days=d),
                "lat": -4.3,
                "lng": 15.3,
            }
            for i, d in enumerate([1, 3])
        ]
        syndicated = [
            {
                "title": "One wire story",
                "source": "wire.example",
                "at": DB_NOW - timedelta(minutes=5 + i),
                "lat": 51.5,
                "lng": -0.1,
            }
            for i in range(12)
        ]
        await _insert(pg, surging + week + syndicated)

        result = await _db_surges(pg)

        assert [(s["lat"], s["lng"]) for s in result] == [(-4.5, 15.5)]
        [surge] = result
        assert surge["recent"] == 10
        # The oldest story is 3 days old: 35 blocks of 2 hours before the last 2.
        assert surge["baseline"] == round(2 / 35, 2)
        assert surge["ratio"] == 20.0  # 10 / max(0.057, 0.5)
        assert surge["topic"] == "conflict"
        assert surge["place"] == "Kinshasa, Congo"
        assert surge["lead"]["sensitive"] is True

    @pytest.mark.asyncio
    async def test_copies_of_seven_stories_are_seven_not_a_surge(self, pg):
        """Fails only the 8-story threshold: 28 rows from 5 sources, but each of the 7
        stories four times over, outlet names tacked on."""
        stories = _stories(-33.9, 18.4, 7, sources=5)
        copies = [
            {**s, "title": f"{s['title']}{suffix}", "source": f"copy{i}.example"}
            for s in stories
            for i, suffix in enumerate([" - Reuters", " | BBC News", " : AP"])
        ]
        await _insert(pg, stories + copies)

        assert await _db_surges(pg) == []

        # One more story and it surges, copies counted once: 8 / 0.5.
        await _insert(pg, _stories(-33.9, 18.4, 1, sources=5, prefix="one more"))
        [surge] = await _db_surges(pg)
        assert (surge["recent"], surge["ratio"]) == (8, 16.0)

    @pytest.mark.asyncio
    async def test_the_place_follows_the_articles_country(self, pg):
        await _insert(pg, _stories(31.5, 34.45, 8, sources=3, region="Gaza, Israel", country="PS"))

        [surge] = await _db_surges(pg)

        assert surge["place"] == "Gaza, Palestine"

    @pytest.mark.asyncio
    async def test_three_sources_are_needed(self, pg):
        await _insert(pg, _stories(30.2, 31.2, 12, sources=2))

        assert await _db_surges(pg) == []

    @pytest.mark.asyncio
    async def test_steady_coverage_is_not_a_surge(self, pg):
        """9 stories in 2 hours against 4 per 2 hours since the oldest story: 2.3×."""
        recent = _stories(35.5, 139.5, 9, sources=3)
        week = [
            {
                "title": f"tokyo week {i}",
                "source": f"outlet{i % 5}.example",
                "at": DB_NOW - timedelta(hours=3, minutes=i * 30),
                "lat": 35.5,
                "lng": 139.5,
            }
            for i in range(300)
        ]
        await _insert(pg, recent + week)

        assert await _db_surges(pg) == []

    @pytest.mark.asyncio
    async def test_two_days_of_history_are_divided_by_their_24_blocks(self, pg):
        """A steady place (10 stories every 2 hours) doesn't surge; a quiet one with a
        burst (1, then 12) does. Divided by 83 blocks, the steady place would be 3.5×."""
        steady = [
            _old(-26.2, 28.0, f"steady {k}", source=f"outlet{k % 3}.example", minutes=12 * k)
            for k in range(1, 241)
        ]
        burst = [
            _old(-1.3, 36.8, f"quiet {k}", source="outlet0.example", minutes=120 * k)
            for k in range(1, 25)
        ]
        await _insert(
            pg,
            steady
            + burst
            + _stories(-26.2, 28.0, 10, sources=3, prefix="steady now")
            + _stories(-1.3, 36.8, 12, sources=3, prefix="burst now"),
        )

        result = await _db_surges(pg)

        assert [(s["lat"], s["recent"], s["baseline"], s["ratio"]) for s in result] == [
            (-1.5, 12, 1.0, 12.0)
        ]

    @pytest.mark.asyncio
    async def test_a_ratio_of_exactly_3_surges(self, pg):
        """6 stories over 2 blocks is 3 a block: 9 now is 3.0×; 7 before would be 2.57×."""
        await _insert(
            pg,
            [_old(6.5, 3.4, f"lagos {k}", source="o.example", minutes=40 * k) for k in range(1, 7)]
            + [
                _old(9.1, 7.5, f"abuja {k}", source="o.example", minutes=30 * k)
                for k in range(1, 8)
            ]
            + _stories(6.5, 3.4, 9, sources=3, prefix="lagos now")
            + _stories(9.1, 7.5, 9, sources=3, prefix="abuja now"),
        )

        [surge] = await _db_surges(pg)

        assert (surge["lat"], surge["baseline"], surge["ratio"]) == (6.5, 3.0, 3.0)

    @pytest.mark.asyncio
    async def test_equal_ratios_rank_by_recent_then_by_cell(self, pg):
        """20 now against 1 a block, and 10 now against none, are both 20×."""
        rows = [
            _old(9.2, 40.2, f"old {k}", source="o.example", minutes=120 * k) for k in (1, 2, 3, 4)
        ]
        rows += _stories(9.2, 40.2, 20, sources=3, prefix="busier")
        for lat in (7.2, 5.2, 3.2):
            rows += _stories(lat, 40.2, 10, sources=3, prefix=f"cell {lat}")
        await _insert(pg, rows)

        result = await _db_surges(pg)

        assert [(s["lat"], s["recent"], s["ratio"]) for s in result] == [
            (9.5, 20, 20.0),
            (3.5, 10, 20.0),
            (5.5, 10, 20.0),
            (7.5, 10, 20.0),
        ]

    @pytest.mark.asyncio
    async def test_a_cold_start_has_baseline_zero_and_a_finite_ratio(self, pg):
        await _insert(pg, _stories(48.8, 2.3, 8, sources=3))

        [surge] = await _db_surges(pg)

        assert (surge["recent"], surge["baseline"], surge["ratio"]) == (8, 0.0, 16.0)

    @pytest.mark.asyncio
    async def test_the_topic_filter_counts_its_stories_only(self, pg):
        await _insert(
            pg,
            _stories(-4.3, 15.3, 10, tags=["conflict"])
            + _stories(48.8, 2.3, 8, sources=3, tags=["politics", "economy"])
            + _stories(48.8, 2.3, 4, sources=3, tags=["health"], prefix="paris health"),
        )

        [surge] = await _db_surges(pg, "politics")

        assert (surge["lat"], surge["lng"], surge["recent"]) == (48.5, 2.5, 8)
        assert surge["topic"] == "politics"
        assert await _db_surges(pg, "health") == []  # 4 health stories: too few

    @pytest.mark.asyncio
    async def test_ranked_by_ratio_then_recent_and_capped_at_eight(self, pg):
        rows = []
        for i in range(9):
            rows += _stories(10 + i, 20, 8 + i, sources=3, prefix=f"cell{i}")
        await _insert(pg, rows)

        result = await _db_surges(pg)

        assert [s["recent"] for s in result] == [16, 15, 14, 13, 12, 11, 10, 9]

    @pytest.mark.asyncio
    async def test_the_lead_is_the_newest_story_with_an_https_image(self, pg):
        rows = _stories(-4.3, 15.3, 10)
        rows[0]["image"] = "http://cdn.example/newest.jpg"  # newest, but not https
        rows[3]["image"] = "https://cdn.example/lead.jpg"
        await _insert(pg, rows)

        [surge] = await _db_surges(pg)

        assert surge["lead"]["title"] == "zzsurge--4.3,15.3 story 3"
        assert surge["lead"]["image_url"] == "https://cdn.example/lead.jpg"

    @pytest.mark.asyncio
    async def test_an_outage_is_no_surges_and_the_week_is_not_read(self, pg):
        """Nothing in the last 2 hours: a burst 3 hours ago, which surged in its own window."""
        await _insert(pg, _stories(-4.3, 15.3, 10, minutes_ago=180))
        assert len(await _db_surges(pg, now=DB_NOW - timedelta(hours=2))) == 1

        conn = _Recorder(pg)
        with patch.object(surges, "get_pool", AsyncMock(return_value=conn)):
            assert await surges.get_surges(DB_NOW) == []

        # The recent window is the clock's, as the guard's is, so the guard can't change
        # the answer: what it saves is the surge query, which never runs.
        assert conn.fetched == []


class _Recorder:
    """A connection that records the queries sent through ``fetch``."""

    def __init__(self, conn):
        self.conn = conn
        self.fetched: list[str] = []

    async def fetchval(self, query, *args):
        return await self.conn.fetchval(query, *args)

    async def fetch(self, query, *args):
        self.fetched.append(query)
        return await self.conn.fetch(query, *args)
