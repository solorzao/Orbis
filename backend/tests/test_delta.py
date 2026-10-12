"""Tests for what changed since a visit: the SQL sent (pool mocked), then its results on a real
database."""

import itertools
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import delta
from app.services.titles import dedup_title_sql

SINCE = datetime(2026, 10, 12, 0, 15, tzinfo=timezone.utc)


def _sql(query: str) -> str:
    return " ".join(query.split())


@pytest.fixture
def pool():
    mock = MagicMock()
    mock.fetch = AsyncMock(return_value=[_row(None)])
    with patch.object(delta, "get_pool", AsyncMock(return_value=mock)):
        yield mock


def _fetched(pool) -> tuple[str, list]:
    query, *args = pool.fetch.call_args.args
    return _sql(query), args


def _row(lat=40.5, lng=-73.5, new=12, stories=1286, places=212, **lead):
    """A row of the delta query: the totals, then one top place (None: no place)."""
    row = {"new_stories": stories, "new_places": places, "lat": lat, "lng": lng, "new": new}
    columns = (
        "title",
        "source_name",
        "published_at",
        "image_url",
        "region",
        "country_code",
        "topic_tags",
    )
    if lat is None:
        return {**row, "new": None, **dict.fromkeys(columns)}
    return {
        **row,
        "title": "Subway reopens",
        "source_name": "example.com",
        "published_at": datetime(2026, 10, 12, 13, 45, tzinfo=timezone.utc),
        "image_url": "https://cdn.example.com/s.jpg",
        "region": "New York, New York, United States",
        "country_code": "US",
        "topic_tags": ["politics"],
        **lead,
    }


class TestDeltaQuery:
    @pytest.mark.asyncio
    async def test_reads_the_stories_since_the_visit(self, pool):
        await delta.get_delta(SINCE)

        query, args = _fetched(pool)
        assert args == [SINCE]
        assert "WHERE published_at >= $1 )" in query
        assert max(int(n) for n in re.findall(r"\$(\d+)", query)) == len(args)

    @pytest.mark.asyncio
    async def test_counts_distinct_stories_and_the_places_they_are_in(self, pool):
        await delta.get_delta(SINCE)

        query, _ = _fetched(pool)
        assert f"{_sql(dedup_title_sql('title'))} AS story" in query
        assert "count(DISTINCT story) AS new" in query  # per place
        assert "(SELECT count(DISTINCT story) FROM fresh) AS new_stories" in query
        assert "(SELECT count(*) FROM cells) AS new_places" in query

    @pytest.mark.asyncio
    async def test_the_top_five_places_by_new_stories(self, pool):
        await delta.get_delta(SINCE)

        query, _ = _fetched(pool)
        assert "ORDER BY new DESC, lat_cell, lng_cell LIMIT 5" in query
        assert query.endswith("ORDER BY top.new DESC, top.lat_cell, top.lng_cell")

    @pytest.mark.asyncio
    async def test_the_lead_brings_its_region_and_country_for_the_place(self, pool):
        await delta.get_delta(SINCE)

        query, _ = _fetched(pool)
        assert "lead.region, lead.country_code, lead.topic_tags" in query
        assert (
            "SELECT title, source_name, published_at, image_url, region, country_code, topic_tags"
            " FROM articles WHERE published_at = COALESCE(" in query
        )

    @pytest.mark.asyncio
    async def test_each_with_its_newest_imaged_story_as_lead(self, pool):
        await delta.get_delta(SINCE)

        query, _ = _fetched(pool)
        lead = query[query.index("CROSS JOIN LATERAL") :]
        assert "published_at = COALESCE(top.newest_with_image, top.newest)" in lead
        assert "AND (top.newest_with_image IS NULL OR image_url LIKE 'https://%')" in lead
        assert "FLOOR(latitude) = top.lat_cell AND FLOOR(longitude) = top.lng_cell" in lead
        assert "ORDER BY (image_url LIKE 'https://%') DESC NULLS LAST, id LIMIT 1 ) lead" in lead

    @pytest.mark.asyncio
    async def test_the_totals_come_back_without_any_place(self, pool):
        """A LEFT JOIN from the totals: no new stories is still a row."""
        await delta.get_delta(SINCE)

        query, _ = _fetched(pool)
        assert "FROM totals LEFT JOIN (top CROSS JOIN LATERAL" in query
        assert ") lead) ON true" in query

    @pytest.mark.asyncio
    async def test_reads_named_columns_never_the_embedding(self, pool):
        await delta.get_delta(SINCE)

        query, _ = _fetched(pool)
        assert "embedding" not in query
        assert "SELECT *" not in query


class TestGetDelta:
    @pytest.mark.asyncio
    async def test_rows_become_the_totals_and_the_top_places(self, pool):
        pool.fetch.return_value = [_row(), _row(lat=51.5, lng=-0.5, new=7, topic_tags=["conflict"])]

        result = await delta.get_delta(SINCE)

        assert result["new_stories"] == 1286
        assert result["new_places"] == 212
        assert result["top"][0] == {
            "lat": 40.5,
            "lng": -73.5,
            "place": "New York, New York, United States",
            "new": 12,
            "lead": {
                "title": "Subway reopens",
                "source_name": "example.com",
                "published_at": datetime(2026, 10, 12, 13, 45, tzinfo=timezone.utc),
                "image_url": "https://cdn.example.com/s.jpg",
                "topic": "politics",
                "sensitive": False,
            },
        }
        assert [(p["lat"], p["new"], p["lead"]["sensitive"]) for p in result["top"]] == [
            (40.5, 12, False),
            (51.5, 7, True),
        ]

    @pytest.mark.asyncio
    async def test_the_place_follows_the_articles_country(self, pool):
        """GDELT files Gaza under Israel; its code is PS."""
        pool.fetch.return_value = [_row(region="Gaza, Israel", country_code="PS")]

        [place] = (await delta.get_delta(SINCE))["top"]

        assert place["place"] == "Gaza, Palestine"

    @pytest.mark.asyncio
    async def test_nothing_new_is_zeros_and_no_places(self, pool):
        pool.fetch.return_value = [_row(None, stories=0, places=0)]

        assert await delta.get_delta(SINCE) == {"new_stories": 0, "new_places": 0, "top": []}


# ── Against the scratch database (skipped without ORBIS_TEST_DATABASE_URL) ──

DB_NOW = datetime(2031, 3, 1, 12, 0, tzinfo=timezone.utc)
DB_SINCE = DB_NOW - timedelta(hours=14)

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
                f"https://zzsurge.example/delta/{next(_URLS)}",
                r.get("source", "outlet.example"),
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


def _new(lat, lng, n, *, hours_ago=1, prefix=None, **extra):
    prefix = prefix or f"{lat},{lng}"
    return [
        {
            "title": f"{prefix} story {i}",
            "at": DB_NOW - timedelta(hours=hours_ago, minutes=i),
            "lat": lat,
            "lng": lng,
            **extra,
        }
        for i in range(n)
    ]


async def _db_delta(pg, since=DB_SINCE):
    with patch.object(delta, "get_pool", AsyncMock(return_value=pg)):
        return await delta.get_delta(since)


class TestDeltaOnPostgres:
    @pytest.mark.asyncio
    async def test_counts_distinct_new_stories_and_their_places(self, pg):
        rows = _new(40.7, -74.0, 6, region="New York, United States")
        # Syndicated copies with outlet names: the same 6 stories.
        rows += [{**r, "title": f"{r['title']} | Outlet{i}"} for i, r in enumerate(rows[:3])]
        rows += _new(40.7, -74.0, 4, hours_ago=20, prefix="before the visit")
        rows += _new(51.5, -0.1, 2)
        # The same story placed in a second place: one story, two places.
        rows += [{**rows[0], "lat": 48.8, "lng": 2.3}]
        await _insert(pg, rows)

        result = await _db_delta(pg)

        assert result["new_stories"] == 8  # 6 + 2; the copies and the Paris one are repeats
        assert result["new_places"] == 3
        assert [(p["lat"], p["lng"], p["new"]) for p in result["top"]] == [
            (40.5, -73.5, 6),
            (51.5, -0.5, 2),
            (48.5, 2.5, 1),
        ]
        assert result["top"][0]["place"] == "New York, United States"

    @pytest.mark.asyncio
    async def test_the_top_is_five_places(self, pg):
        rows = []
        for i in range(7):
            rows += _new(10 + i, 20, 1 + i, prefix=f"cell{i}")
        await _insert(pg, rows)

        result = await _db_delta(pg)

        assert result["new_places"] == 7
        assert [p["new"] for p in result["top"]] == [7, 6, 5, 4, 3]

    @pytest.mark.asyncio
    async def test_the_lead_is_the_newest_story_with_an_https_image(self, pg):
        rows = _new(40.7, -74.0, 5, tags=["conflict"])
        rows[0]["image"] = "http://cdn.example/newest.jpg"
        rows[2]["image"] = "https://cdn.example/lead.jpg"
        await _insert(pg, rows)

        [place] = (await _db_delta(pg))["top"]

        assert place["lead"]["title"] == "zzsurge-40.7,-74.0 story 2"
        assert place["lead"]["sensitive"] is True

    @pytest.mark.asyncio
    async def test_the_place_follows_the_articles_country(self, pg):
        await _insert(pg, _new(31.5, 34.45, 2, region="Gaza, Israel", country="PS"))

        [place] = (await _db_delta(pg))["top"]

        assert place["place"] == "Gaza, Palestine"

    @pytest.mark.asyncio
    async def test_a_story_published_exactly_at_since_counts(self, pg):
        await _insert(
            pg,
            [
                {"title": "at the visit", "at": DB_SINCE, "lat": 40.7, "lng": -74.0},
                {
                    "title": "just before",
                    "at": DB_SINCE - timedelta(microseconds=1),
                    "lat": 40.7,
                    "lng": -74.0,
                },
            ],
        )

        result = await _db_delta(pg)

        assert (result["new_stories"], result["new_places"]) == (1, 1)
        assert result["top"][0]["lead"]["title"] == "zzsurge-at the visit"

    @pytest.mark.asyncio
    async def test_nothing_new(self, pg):
        await _insert(pg, _new(40.7, -74.0, 3, hours_ago=20))

        assert await _db_delta(pg) == {"new_stories": 0, "new_places": 0, "top": []}
