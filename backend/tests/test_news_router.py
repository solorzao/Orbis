"""Tests for the news router endpoints (database-backed)."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.routers.news import _row_to_article
from app.services.cache import cycle_ttl, invalidate, set_cached
from tests.fake_redis import FakeRedis


def _make_globe_row(lat: float = 40.0, lng: float = -74.0, count: int = 3, topic: str = "general"):
    """Create a dict matching get_globe_points() output."""
    return {
        "lat": lat,
        "lng": lng,
        "weight": min(count * 10, 500),
        "article_count": count,
        "top_headline": "Test headline",
        "topic": topic,
        "location_name": "Test City",
    }


def _make_db_row(title: str = "Test", topic_tags=None, lat: float = 40.0, lng: float = -74.0):
    """Create a dict matching a database article row."""
    now = datetime.now(timezone.utc)
    return dict(
        id="abc-123",
        title=title,
        summary=None,
        source_url="https://example.com",
        source_name="example.com",
        source_language="en",
        published_at=now,
        ingested_at=now,
        latitude=lat,
        longitude=lng,
        country_code="US",
        region="",
        topic_tags=topic_tags or ["general"],
        sentiment_score=0.0,
        entities={},
        image_url=None,
    )


def _db_honouring_topics(rows):
    """A get_articles_in_bounds stand-in that filters on topics and limits like the SQL."""

    async def in_bounds(*_bounds, limit, topics=None, **_window):
        matching = [r for r in rows if topics is None or set(r["topic_tags"]) & set(topics)]
        return matching[:limit]

    return in_bounds


# Disable caching for all router tests
@pytest.fixture(autouse=True)
def _no_cache():
    with (
        patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=None),
        patch("app.routers.news.set_cached", new_callable=AsyncMock),
    ):
        yield


class TestGetGlobeData:
    @pytest.mark.asyncio
    async def test_returns_globe_points_from_db(self):
        from app.routers.news import get_globe_data

        rows = [
            _make_globe_row(lat=33.0, lng=44.0, count=5, topic="conflict"),
            _make_globe_row(lat=51.0, lng=-0.1, count=3, topic="economy"),
        ]

        with patch(
            "app.routers.news.get_globe_points",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            points = await get_globe_data(timespan="24h", limit=100)
            assert len(points) == 2
            assert points[0].topic == "conflict"

    @pytest.mark.asyncio
    async def test_limit_passed_to_db(self):
        from app.routers.news import get_globe_data

        with patch(
            "app.routers.news.get_globe_points",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_db:
            await get_globe_data(timespan="24h", limit=3)
            mock_db.assert_called_once_with(
                timespan_hours=24,
                cell_size=1.0,
                limit=3,
                start_time=None,
                end_time=None,
                topic=None,
            )

    @pytest.mark.asyncio
    async def test_passes_parsed_timespan_hours(self):
        from app.routers.news import get_globe_data

        with patch(
            "app.routers.news.get_globe_points",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_db:
            await get_globe_data(timespan="48h", limit=100)
            mock_db.assert_called_once_with(
                timespan_hours=48,
                cell_size=1.0,
                limit=100,
                start_time=None,
                end_time=None,
                topic=None,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("timespan", "hours"), [("168h", 168), ("169h", 168), ("9999h", 168), ("0h", 1), ("-5h", 1)]
    )
    async def test_timespan_is_one_hour_to_seven_days(self, timespan, hours):
        """The timeline's 7d preset asks for 168h; nothing asks for more."""
        from app.routers.news import get_globe_data

        with patch(
            "app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=[]
        ) as mock_db:
            await get_globe_data(timespan=timespan, limit=100)
        assert mock_db.call_args.kwargs["timespan_hours"] == hours

    @pytest.mark.asyncio
    async def test_passes_start_end_time_to_db(self):
        from app.routers.news import get_globe_data

        with patch(
            "app.routers.news.get_globe_points",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_db:
            await get_globe_data(
                timespan="24h",
                limit=100,
                start_time="2026-03-07T14:00:00Z",
                end_time="2026-03-07T18:00:00Z",
            )
            call_kwargs = mock_db.call_args[1]
            assert call_kwargs["start_time"].hour == 14
            assert call_kwargs["end_time"].hour == 18

    @pytest.mark.asyncio
    async def test_points_carry_no_topic_list(self):
        """Only the dot's own topic goes out; a cell's every tag is no longer sent."""
        from app.routers.news import get_globe_data

        with patch(
            "app.routers.news.get_globe_points",
            new_callable=AsyncMock,
            return_value=[_make_globe_row(topic="sport")],
        ):
            [point] = await get_globe_data(timespan="24h", limit=100)
        assert point.topic == "sport"
        assert "topics" not in point.model_dump()

    @pytest.mark.asyncio
    async def test_points_cached_with_a_topic_list_still_load(self):
        """Entries cached while `topics` was sent stay valid until their TTL ends."""
        from app.routers.news import get_globe_data

        cached = {**_make_globe_row(topic="conflict"), "topics": ["conflict", "sport"]}
        with patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=[cached]):
            [point] = await get_globe_data(timespan="24h", limit=100)
        assert point.topic == "conflict"
        assert "topics" not in point.model_dump()


def _make_hover_row(**overrides):
    """A get_globe_points() row with the hover card's fields."""
    return {
        **_make_globe_row(count=5, topic="politics"),
        "location_name": "London, United Kingdom",
        "country_code": "GB",
        "lead": {
            "title": "Talks resume",
            "source_name": "Reuters",
            "published_at": datetime(2026, 10, 12, 9, 45, tzinfo=timezone.utc),
            "image_url": "http://cdn.example.com/a.jpg",
            "topic": "conflict",
            "sensitive": True,
        },
        "topic_mix": {"politics": 3, "conflict": 2},
        "tone": -0.25,
        **overrides,
    }


class TestGetGlobeDataHover:
    """Each point carries what the hover card shows before any other request."""

    @pytest.mark.asyncio
    async def test_points_carry_the_lead_topic_mix_and_tone(self, monkeypatch):
        with patch(
            "app.routers.news.get_globe_points",
            new_callable=AsyncMock,
            return_value=[_make_hover_row()],
        ):
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news")

        assert resp.status_code == 200
        [point] = resp.json()
        assert point["lead"] == {
            "title": "Talks resume",
            "source_name": "Reuters",
            "published_at": "2026-10-12T09:45:00Z",
            "image_url": None,  # http: the card shows https images only
            "topic": "conflict",
            "sensitive": True,
        }
        assert point["topic_mix"] == {"politics": 3, "conflict": 2}
        assert point["tone"] == -0.25
        assert point["location_name"] == "London, United Kingdom"
        assert point["country_code"] == "GB"

    @pytest.mark.asyncio
    async def test_points_are_cached_as_json_and_served_from_it(self):
        from app.routers.news import get_globe_data

        with (
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
            patch(
                "app.routers.news.get_globe_points",
                new_callable=AsyncMock,
                return_value=[_make_hover_row()],
            ),
        ):
            [fresh] = await get_globe_data(timespan="24h", limit=100)

        key, value, _ = mock_set.await_args.args
        assert key.startswith("db:globe:v2:")  # entries without a lead are never served
        assert value[0]["lead"]["published_at"] == "2026-10-12T09:45:00Z"

        with (
            patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=value),
            patch("app.routers.news.get_globe_points", new_callable=AsyncMock) as mock_db,
        ):
            [cached] = await get_globe_data(timespan="24h", limit=100)
        mock_db.assert_not_awaited()
        assert cached == fresh


class TestGetGlobeDataCache:
    @pytest.mark.asyncio
    async def test_cells_are_cached_for_the_normal_ttl(self):
        from app.config import settings
        from app.routers.news import get_globe_data

        with (
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
            patch(
                "app.routers.news.get_globe_points",
                new_callable=AsyncMock,
                return_value=[_make_globe_row()],
            ),
        ):
            await get_globe_data(timespan="24h", limit=100)

        _, value, ttl = mock_set.await_args.args
        assert len(value) == 1
        # Until the next cycle's warm replaces it: ingestion invalidates db:* anyway.
        assert ttl == cycle_ttl(settings.db_cache_ttl) > settings.ingestion_interval_seconds

    @pytest.mark.asyncio
    async def test_an_empty_window_is_cached_briefly(self):
        """An empty window (a quiet hour, a replay step) mustn't hit the database every request,
        nor stay empty for long once stories land."""
        from app.config import settings
        from app.routers.news import _EMPTY_GLOBE_TTL, get_globe_data

        with (
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
            patch("app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=[]),
        ):
            assert await get_globe_data(timespan="1h", limit=100) == []

        _, value, ttl = mock_set.await_args.args
        assert value == []
        assert ttl == _EMPTY_GLOBE_TTL == 60
        assert _EMPTY_GLOBE_TTL < settings.db_cache_ttl

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stale", [[{"lat": 1.0, "lng": 2.0}], {"points": []}])
    async def test_an_entry_that_no_longer_fits_the_model_is_recomputed(self, stale):
        """Cached before the model gained a required field (or in another shape): a miss,
        recomputed and cached again, never a 500."""
        from app.routers.news import get_globe_data

        with (
            patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=stale),
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
            patch(
                "app.routers.news.get_globe_points",
                new_callable=AsyncMock,
                return_value=[_make_globe_row()],
            ) as mock_db,
        ):
            [point] = await get_globe_data(timespan="24h", limit=100)

        assert point.lat == 40.0
        mock_db.assert_awaited_once()
        mock_set.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("path", "stale"),
        [
            ("/api/news/breaking", [{"headline": "x"}]),
            ("/api/news/volume", [{"hour": "2026-10-21T09:00:00Z"}]),
            ("/api/topics", [{"topic": "politics"}]),
        ],
    )
    async def test_other_news_entries_that_no_longer_fit_are_recomputed(
        self, monkeypatch, path, stale
    ):
        with (
            patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=stale),
            patch("app.routers.news.get_breaking", new_callable=AsyncMock, return_value=[]),
            patch("app.routers.news.get_hourly_volume", new_callable=AsyncMock, return_value=[]),
            patch("app.routers.news.get_topic_counts", new_callable=AsyncMock, return_value={}),
        ):
            async with _api_client(monkeypatch) as client:
                resp = await client.get(path)

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_a_cached_empty_window_is_served_without_the_database(self):
        from app.routers.news import get_globe_data

        with (
            patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=[]),
            patch("app.routers.news.get_globe_points", new_callable=AsyncMock) as mock_db,
        ):
            assert await get_globe_data(timespan="1h", limit=100) == []

        mock_db.assert_not_awaited()


class TestGetGlobeDataTopic:
    """`topic` filters the cells on the server: one of the six topic pills, or All."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("topic", "tag"),
        [
            ("Politics", "politics"),
            ("politics", "politics"),
            ("CONFLICT", "conflict"),
            ("Technology", "technology"),
            ("Climate", "environment"),  # the classifier's tag for the Climate pill
            ("Economy", "economy"),
            ("Health", "health"),
            ("All", None),
            ("all", None),
        ],
    )
    async def test_topic_reaches_the_database_as_its_article_tag(self, monkeypatch, topic, tag):
        with patch(
            "app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=[]
        ) as mock_db:
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news", params={"topic": topic})

        assert resp.status_code == 200
        assert mock_db.call_args.kwargs["topic"] == tag

    @pytest.mark.asyncio
    async def test_no_topic_means_every_story(self, monkeypatch):
        with patch(
            "app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=[]
        ) as mock_db:
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news")

        assert resp.status_code == 200
        assert mock_db.call_args.kwargs["topic"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("topic", ["sport", "environment", "general", "Politics,Health"])
    async def test_an_unknown_topic_is_422(self, monkeypatch, topic):
        with patch("app.routers.news.get_globe_points", new_callable=AsyncMock) as mock_db:
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news", params={"topic": topic})

        assert resp.status_code == 422
        mock_db.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_key_includes_the_topic_tag(self, monkeypatch):
        """A topic's cells never come back from All's cache entry, nor All's from a topic's."""
        rows = [_make_globe_row(topic="environment")]
        keys = {}
        for topic in ("Climate", "All"):
            with (
                patch(
                    "app.routers.news.get_cached", new_callable=AsyncMock, return_value=None
                ) as mock_get,
                patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
                patch(
                    "app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=rows
                ),
            ):
                async with _api_client(monkeypatch) as client:
                    await client.get("/api/news", params={"topic": topic, "timespan": "6h"})
            keys[topic] = mock_get.await_args.args[0]
            assert mock_set.await_args.args[0] == keys[topic]

        assert keys["Climate"].endswith(":environment")
        assert keys["Climate"] != keys["All"]
        assert "environment" not in keys["All"]


class TestGetClusterArticles:
    @pytest.mark.asyncio
    async def test_returns_articles_from_db(self):
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row("Tehran protest", ["politics"])]

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows
        ):
            result = await get_cluster_articles(
                lat=35.7,
                lng=51.4,
                topic=None,
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
            assert len(result) == 1
            assert result[0].title == "Tehran protest"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("lat", "lng", "cell"),
        [
            (40.5, -74.5, (40.0, -75.0, 41.0, -74.0)),  # a dot's centre
            (40.9, -74.1, (40.0, -75.0, 41.0, -74.0)),  # off centre: same cell
            (-33.87, -70.65, (-34.0, -71.0, -33.0, -70.0)),  # negative: floors down
            (51.0, -0.2, (51.0, -1.0, 52.0, 0.0)),  # on an edge: the cell above it
        ],
    )
    async def test_queries_the_dots_floored_cell(self, lat, lng, cell):
        """The cell the dot (and the summary cache key) uses: FLOOR, not lat/lng +/- half."""
        from app.routers.news import get_cluster_articles

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=[]
        ) as mock_bounds:
            await get_cluster_articles(
                lat=lat,
                lng=lng,
                topic=None,
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
        assert mock_bounds.call_args.args == pytest.approx(cell)

    @pytest.mark.asyncio
    async def test_topic_filter_applied(self):
        from app.routers.news import get_cluster_articles

        rows = [
            _make_db_row("Economy article", ["economy"]),
            _make_db_row("Conflict article", ["conflict"]),
        ]

        with patch(
            "app.routers.news.get_articles_in_bounds",
            new_callable=AsyncMock,
            side_effect=_db_honouring_topics(rows),
        ):
            result = await get_cluster_articles(
                lat=40.0,
                lng=-74.0,
                topic="conflict",
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
            assert [a.title for a in result] == ["Conflict article"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("topic", "expected"),
        [("Conflict", ["conflict"]), ("Climate", ["environment"]), (None, None)],
    )
    async def test_resolved_topic_reaches_the_database(self, topic, expected):
        from app.routers.news import get_cluster_articles

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=[]
        ) as mock_bounds:
            await get_cluster_articles(
                lat=40.0,
                lng=-74.0,
                topic=topic,
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
        assert mock_bounds.call_args.kwargs["topics"] == expected

    @pytest.mark.asyncio
    async def test_topic_with_no_match_returns_nothing(self):
        """No fallback to off-topic stories: the cell has none for this topic."""
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row("General article", ["general"])]

        with patch(
            "app.routers.news.get_articles_in_bounds",
            new_callable=AsyncMock,
            side_effect=_db_honouring_topics(rows),
        ):
            result = await get_cluster_articles(
                lat=40.0,
                lng=-74.0,
                topic="conflict",
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_caps_results_at_default_limit(self):
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row(f"Article {i}") for i in range(50)]

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows
        ):
            result = await get_cluster_articles(
                lat=40.0,
                lng=-74.0,
                topic=None,
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
            assert len(result) == 10

    @pytest.mark.asyncio
    async def test_offset_skips_articles(self):
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row(f"Article {i}") for i in range(20)]

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows
        ):
            result = await get_cluster_articles(
                lat=40.0,
                lng=-74.0,
                topic=None,
                location_name=None,
                offset=5,
                limit=3,
                sentiment=None,
                search=None,
            )
            assert len(result) == 3
            assert result[0].title == "Article 5"

    @pytest.mark.asyncio
    async def test_default_offset_is_zero(self):
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row(f"Article {i}") for i in range(5)]

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows
        ):
            result = await get_cluster_articles(
                lat=40.0,
                lng=-74.0,
                topic=None,
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
            assert result[0].title == "Article 0"

    @pytest.mark.asyncio
    async def test_passes_start_end_time_to_bounds(self):
        from app.routers.news import get_cluster_articles

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=[]
        ) as mock_bounds:
            await get_cluster_articles(
                lat=40.0,
                lng=-74.0,
                topic=None,
                location_name=None,
                offset=0,
                limit=10,
                start_time="2026-03-07T10:00:00Z",
                end_time="2026-03-07T12:00:00Z",
                sentiment=None,
                search=None,
            )
            call_kwargs = mock_bounds.call_args[1]
            assert call_kwargs["start_time"].hour == 10
            assert call_kwargs["end_time"].hour == 12


class TestGetClusterSummary:
    @pytest.mark.asyncio
    async def test_window_reaches_db_and_summary(self):
        from app.routers.news import _CELL_SIZE, get_cluster_summary

        rows = [_make_db_row("Floods in Valencia")]
        with (
            patch(
                "app.routers.news.get_articles_in_bounds",
                new_callable=AsyncMock,
                return_value=rows,
            ) as mock_bounds,
            patch(
                "app.routers.news.summarise_cluster", new_callable=AsyncMock, return_value="S."
            ) as mock_summary,
        ):
            result = await get_cluster_summary(
                lat=39.5,
                lng=-0.5,
                topic=None,
                location_name=None,
                start_time="2026-03-07T10:00:00Z",
                end_time="2026-03-08T10:00:00Z",
            )

        start = datetime(2026, 3, 7, 10, tzinfo=timezone.utc)
        end = datetime(2026, 3, 8, 10, tzinfo=timezone.utc)
        assert mock_bounds.call_args.kwargs["start_time"] == start
        assert mock_bounds.call_args.kwargs["end_time"] == end
        kwargs = mock_summary.call_args.kwargs
        assert kwargs["cell_size"] == _CELL_SIZE
        assert kwargs["start_time"] == start
        assert kwargs["end_time"] == end
        assert result.summary == "S."

    @pytest.mark.asyncio
    async def test_no_window_means_live(self):
        from app.routers.news import get_cluster_summary

        with (
            patch(
                "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=[]
            ) as mock_bounds,
            patch(
                "app.routers.news.summarise_cluster", new_callable=AsyncMock, return_value=""
            ) as mock_summary,
        ):
            await get_cluster_summary(
                lat=39.5,
                lng=-0.5,
                topic=None,
                location_name=None,
                start_time=None,
                end_time=None,
            )

        assert mock_bounds.call_args.kwargs["start_time"] is None
        assert mock_bounds.call_args.kwargs["end_time"] is None
        assert mock_summary.call_args.kwargs["start_time"] is None
        assert mock_summary.call_args.kwargs["end_time"] is None

    @pytest.mark.asyncio
    async def test_fetches_only_what_the_summary_reads_on_topic(self):
        from app.routers.news import get_cluster_summary

        with (
            patch(
                "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=[]
            ) as mock_bounds,
            patch("app.routers.news.summarise_cluster", new_callable=AsyncMock, return_value=""),
        ):
            await get_cluster_summary(
                lat=39.5,
                lng=-0.5,
                topic="Climate",
                location_name=None,
                start_time=None,
                end_time=None,
            )

        assert mock_bounds.call_args.kwargs["topics"] == ["environment"]
        assert mock_bounds.call_args.kwargs["limit"] == 30

    @pytest.mark.asyncio
    async def test_topic_with_no_match_gives_an_empty_uncached_summary(self):
        """Never summarise off-topic stories, nor cache anything under the topic key."""
        from app.routers.news import get_cluster_summary

        rows = [_make_db_row("Cup final tonight", ["sport"])]
        with (
            patch(
                "app.routers.news.get_articles_in_bounds",
                new_callable=AsyncMock,
                side_effect=_db_honouring_topics(rows),
            ),
            patch("app.services.ai_summary.get_cached", new_callable=AsyncMock, return_value=None),
            patch("app.services.ai_summary.set_cached", new_callable=AsyncMock) as mock_set,
            patch(
                "app.services.ai_summary._call_claude",
                new_callable=AsyncMock,
                return_value="A summary of the cup final.",
            ) as mock_claude,
        ):
            result = await get_cluster_summary(
                lat=39.5,
                lng=-0.5,
                topic="conflict",
                location_name=None,
                start_time=None,
                end_time=None,
            )

        assert result.summary == ""
        assert result.article_count == 0
        mock_claude.assert_not_awaited()
        mock_set.assert_not_awaited()


class TestGetDensity:
    @pytest.mark.asyncio
    async def test_returns_24_hourly_buckets(self):
        from app.routers.news import get_article_density

        mock_data = {0: 5, 6: 20, 12: 50, 18: 30}

        with patch(
            "app.routers.news.get_hourly_density",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            result = await get_article_density()
            assert len(result) == 24
            assert result[0].hour == 0
            assert result[0].count == 5
            assert result[1].hour == 1
            assert result[1].count == 0  # missing hours filled with 0
            assert result[12].hour == 12
            assert result[12].count == 50


class TestGetTopics:
    @pytest.mark.asyncio
    async def test_returns_topic_counts(self):
        from app.routers.news import get_topics

        counts = {"conflict": 50, "economy": 30, "health": 10}

        with patch(
            "app.routers.news.get_topic_counts", new_callable=AsyncMock, return_value=counts
        ):
            result = await get_topics()
            assert len(result) == 3
            assert result[0].topic == "conflict"
            assert result[0].count == 50


def test_row_to_article_names_its_listed_thread():
    import json

    row = {
        "id": "1",
        "title": "t",
        "source_url": "https://s",
        "source_name": "s",
        "latitude": 1.0,
        "longitude": 2.0,
        "thread_id": 7,
        "thread_title": None,
        "thread_lead_title": "Strikes spread across France",
        "thread_places": json.dumps(
            [
                {"region": "Paris, Ile-de-France, France", "country_code": "FR"},
                {"region": "Lyon, Rhone-Alpes, France", "country_code": "FR"},
            ]
        ),
    }

    thread = _row_to_article(row).thread

    assert thread.model_dump() == {
        "id": 7,
        "title": "Strikes spread across France",
        "places": ["Paris, Ile-de-France, France", "Lyon, Rhone-Alpes, France"],
    }
    assert _row_to_article({**row, "thread_id": None}).thread is None
    assert _row_to_article(_make_db_row()).thread is None


@pytest.mark.asyncio
async def test_cluster_articles_carry_their_thread(monkeypatch):
    import json

    row = {
        **_make_db_row("Strikes spread"),
        "thread_id": 7,
        "thread_title": "French strikes widen",
        "thread_lead_title": "Strikes spread",
        "thread_places": json.dumps([{"region": "Paris, Ile-de-France, France"}]),
    }
    with patch(
        "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=[row]
    ):
        async with _api_client(monkeypatch) as client:
            resp = await client.get("/api/news/cluster", params={"lat": 40.5, "lng": -74.5})

    assert resp.status_code == 200
    [article] = resp.json()
    assert article["thread"] == {
        "id": 7,
        "title": "French strikes widen",
        "places": ["Paris, Ile-de-France, France"],
    }


def test_row_to_article_includes_image_url():
    row = {
        "id": "1",
        "title": "t",
        "source_url": "https://s",
        "source_name": "s",
        "latitude": 1.0,
        "longitude": 2.0,
        "image_url": "http://cdn.example.com/a.jpg",
    }
    assert _row_to_article(row).image_url == "https://cdn.example.com/a.jpg"


@pytest.mark.asyncio
async def test_cluster_endpoint_survives_malformed_image_url(monkeypatch):
    """One unparseable image URL must not turn the whole cell into a 500."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    rows = [
        {**_make_db_row("Good image"), "image_url": "http://img.example.com/a.jpg"},
        {**_make_db_row("Bad image"), "image_url": "https://img.example.com[1]/x.jpg"},
    ]

    with patch(
        "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows
    ):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/news/cluster", params={"lat": 40.0, "lng": -74.0})

    assert resp.status_code == 200
    images = {a["title"]: a["image_url"] for a in resp.json()}
    assert images == {"Good image": "https://img.example.com/a.jpg", "Bad image": None}


@pytest.mark.asyncio
async def test_cluster_endpoint_pages_past_50_within_a_window(monkeypatch):
    """Load more keeps going past the 50th article of a day's window."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    rows = [_make_db_row(f"Article {i}") for i in range(120)]

    async def in_bounds(*_bounds, limit, **_window):
        return rows[:limit]  # the database honours the limit

    with patch(
        "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, side_effect=in_bounds
    ) as mock_bounds:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/news/cluster",
                params={
                    "lat": 40.5,
                    "lng": -74.5,
                    "start_time": "2026-03-07T10:00:00Z",
                    "end_time": "2026-03-08T10:00:00Z",
                    "offset": 50,
                    "limit": 20,
                },
            )

    assert resp.status_code == 200
    assert [a["title"] for a in resp.json()] == [f"Article {i}" for i in range(50, 70)]
    kwargs = mock_bounds.call_args.kwargs
    assert kwargs["start_time"] == datetime(2026, 3, 7, 10, tzinfo=timezone.utc)
    assert kwargs["end_time"] == datetime(2026, 3, 8, 10, tzinfo=timezone.utc)


def _api_client(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()  # each test starts under the per-minute limit
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


class TestGetVolume:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("days", [0, 8])
    async def test_days_outside_one_to_seven_is_422(self, monkeypatch, days):
        with patch("app.routers.news.get_hourly_volume", new_callable=AsyncMock) as mock_db:
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news/volume", params={"days": days})

        assert resp.status_code == 422
        mock_db.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_days_and_serialises_hours_as_iso_utc(self, monkeypatch):
        rows = [
            {"hour": datetime(2026, 10, 11, 13, tzinfo=timezone.utc), "count": 0},
            {"hour": datetime(2026, 10, 11, 14, tzinfo=timezone.utc), "count": 31},
        ]
        with patch(
            "app.routers.news.get_hourly_volume", new_callable=AsyncMock, return_value=rows
        ) as mock_db:
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news/volume", params={"days": 3})

        assert resp.status_code == 200
        mock_db.assert_awaited_once_with(3)
        # Zero hours stay in, oldest first.
        assert resp.json() == [
            {"hour": "2026-10-11T13:00:00Z", "count": 0},
            {"hour": "2026-10-11T14:00:00Z", "count": 31},
        ]

    @pytest.mark.asyncio
    async def test_defaults_to_seven_days_and_caches_by_days(self, monkeypatch):
        from app.config import settings

        rows = [{"hour": datetime(2026, 10, 11, 14, tzinfo=timezone.utc), "count": 5}]
        with (
            patch(
                "app.routers.news.get_hourly_volume", new_callable=AsyncMock, return_value=rows
            ) as mock_db,
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
        ):
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news/volume")

        assert resp.status_code == 200
        mock_db.assert_awaited_once_with(7)
        key, value, ttl = mock_set.await_args.args
        assert key == "db:volume:7"
        assert value == [{"hour": "2026-10-11T14:00:00Z", "count": 5}]
        assert ttl == cycle_ttl(settings.db_cache_ttl) > settings.ingestion_interval_seconds

    @pytest.mark.asyncio
    async def test_serves_the_cached_volume(self, monkeypatch):
        cached = [{"hour": "2026-10-11T14:00:00Z", "count": 5}]
        with (
            patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=cached),
            patch("app.routers.news.get_hourly_volume", new_callable=AsyncMock) as mock_db,
        ):
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news/volume", params={"days": 2})

        assert resp.json() == cached
        mock_db.assert_not_awaited()


# ── Cache warmers: the first visit's requests, refilled after ingestion ──


class TestFirstLoadWarmers:
    """Each warmer stores the key and bytes the frontend's first-load request would."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("warmer", "path", "params", "db_function", "rows", "key"),
        [
            (  # useGlobePoints: DEFAULT_WINDOW 24h, GLOBE_LIMIT 500, topic All
                "warm_globe",
                "/api/news",
                {"timespan": "24h", "limit": "500"},
                "get_globe_points",
                [_make_globe_row(lat=33.0, lng=44.0, count=5, topic="conflict")],
                "db:globe:v2:24::500:",
            ),
            (  # TimelineCapsule: fetchVolume(CHART_DAYS = 7)
                "warm_volume",
                "/api/news/volume",
                {"days": "7"},
                "get_hourly_volume",
                [{"hour": datetime(2026, 10, 11, 14, tzinfo=timezone.utc), "count": 5}],
                "db:volume:7",
            ),
        ],
    )
    async def test_a_warmed_entry_is_what_the_first_load_request_would_cache(
        self, monkeypatch, warmer, path, params, db_function, rows, key
    ):
        import app.routers.news as news

        with (
            patch(f"app.routers.news.{db_function}", new_callable=AsyncMock, return_value=rows),
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
        ):
            async with _api_client(monkeypatch) as client:
                miss = await client.get(path, params=params)
            await getattr(news, warmer)()

        (requested_key, requested, ttl), (warmed_key, warmed, warmed_ttl) = [
            c.args for c in mock_set.await_args_list
        ]
        assert warmed_key == requested_key == key
        assert (warmed, warmed_ttl) == (requested, ttl)
        # Warmed after one cycle, it lasts until the next cycle's warm.
        assert warmed_ttl > settings.ingestion_interval_seconds

        with patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=warmed):
            async with _api_client(monkeypatch) as client:
                hit = await client.get(path, params=params)
        assert hit.status_code == miss.status_code == 200
        assert hit.content == miss.content


# ── /api/news/preview: the hover card's dwell data ──────────────────────

PREVIEW_NOW = datetime(2026, 10, 12, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def preview_db(monkeypatch):
    """The preview's two queries and its brief lookup, stubbed; the clock frozen."""
    import app.routers.news as news

    monkeypatch.setattr(news, "_now", lambda: PREVIEW_NOW)
    spark = AsyncMock(return_value=[0] * 23 + [4])
    entities = AsyncMock(return_value=[])
    with (
        patch("app.routers.news.get_cell_spark", spark),
        patch("app.routers.news.get_cell_entities", entities),
        patch("app.routers.news.cached_summary", AsyncMock(return_value=None)) as brief,
    ):
        yield SimpleNamespace(spark=spark, entities=entities, brief=brief)


async def _preview(monkeypatch, **params):
    async with _api_client(monkeypatch) as client:
        return await client.get("/api/news/preview", params={"lat": 40.7, "lng": -74.0, **params})


class TestGetPlacePreview:
    @pytest.mark.asyncio
    async def test_live_window_reads_the_cell_over_the_last_hours(self, monkeypatch, preview_db):
        resp = await _preview(monkeypatch, timespan="6h")

        assert resp.status_code == 200
        assert resp.json() == {"spark": [0] * 23 + [4], "entities": [], "brief": None}
        cell = (40.0, -74.0, 41.0, -73.0)  # the dot's 1° cell, floored
        preview_db.spark.assert_awaited_once_with(*cell, end_time=PREVIEW_NOW, topic=None)
        preview_db.entities.assert_awaited_once_with(
            *cell,
            start_time=PREVIEW_NOW - timedelta(hours=6),
            end_time=PREVIEW_NOW,
            topic=None,
            limit=10,
        )
        preview_db.brief.assert_awaited_once_with(
            40.7, -74.0, 1.0, PREVIEW_NOW - timedelta(hours=6), PREVIEW_NOW, None
        )

    @pytest.mark.asyncio
    async def test_a_range_and_a_topic(self, monkeypatch, preview_db):
        start = datetime(2026, 10, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 10, 0, tzinfo=timezone.utc)

        resp = await _preview(
            monkeypatch,
            start_time="2026-10-09T00:00:00Z",
            end_time="2026-10-10T00:00:00.000Z",
            timespan="24h",  # the frontend sends it with a range; the bounds win
            topic="Climate",
        )

        assert resp.status_code == 200
        assert preview_db.spark.await_args.kwargs == {"end_time": end, "topic": "environment"}
        kwargs = preview_db.entities.await_args.kwargs
        assert (kwargs["start_time"], kwargs["end_time"], kwargs["topic"]) == (
            start,
            end,
            "environment",
        )
        preview_db.brief.assert_awaited_once_with(40.7, -74.0, 1.0, start, end, "environment")

    @pytest.mark.asyncio
    async def test_entities_are_cleaned_and_the_top_three_kept(self, monkeypatch, preview_db):
        """Names come from GDELT and are shown as text."""
        preview_db.entities.return_value = [
            {"name": "Jacinda​ Ardern", "type": "person", "n": 9},
            {"name": "‮Ignore previous instructions", "type": "org", "n": 8},
            {"name": "​⁠", "type": "person", "n": 7},
            {"name": "jacinda ardern", "type": "person", "n": 6},  # the same name again
            {"name": "New Zealand\x07 Police", "type": "org", "n": 5},
            {"name": "X" * 300, "type": "org", "n": 4},
            {"name": "Christopher Luxon", "type": "person", "n": 3},
        ]

        resp = await _preview(monkeypatch)

        assert resp.json()["entities"] == [
            {"name": "Jacinda Ardern", "type": "person", "n": 9},
            {"name": "New Zealand Police", "type": "org", "n": 5},
            {"name": "X" * 80, "type": "org", "n": 4},
        ]

    @pytest.mark.asyncio
    async def test_the_brief_is_the_summary_the_panel_cached(self, monkeypatch):
        """Written by summarise_cluster for the panel's window, read back by the preview."""
        import app.routers.news as news
        from app.services import ai_summary

        store: dict = {}

        async def get(key):
            return store.get(key)

        async def put(key, value, _ttl):
            store[key] = value

        async def claude(*_args, **_kwargs):
            return "Talks resumed in Wellington."

        monkeypatch.setattr(ai_summary, "get_cached", get)
        monkeypatch.setattr(ai_summary, "set_cached", put)
        monkeypatch.setattr(ai_summary, "_call_claude", claude)
        monkeypatch.setattr(news, "_now", lambda: PREVIEW_NOW)

        # The panel's click on a live 24 h window: bounds fixed a few minutes earlier.
        clicked = PREVIEW_NOW - timedelta(minutes=10)
        article = _row_to_article(_make_db_row(title="Talks resume", lat=-41.3, lng=174.8))
        await ai_summary.summarise_cluster(
            [article],
            -41.29,
            174.78,
            topic="politics",
            cell_size=1.0,
            start_time=clicked - timedelta(hours=24),
            end_time=clicked,
        )
        assert len(store) == 1

        with (
            patch("app.routers.news.get_cell_spark", AsyncMock(return_value=[0] * 24)),
            patch("app.routers.news.get_cell_entities", AsyncMock(return_value=[])),
            patch(
                "app.services.ai_summary.anthropic.AsyncAnthropic",
                side_effect=AssertionError("Claude called on hover"),
            ),
        ):
            async with _api_client(monkeypatch) as client:
                params = {"lat": -41.2, "lng": 174.9, "timespan": "24h", "topic": "Politics"}
                hit = await client.get("/api/news/preview", params=params)
                other_topic = await client.get(
                    "/api/news/preview", params={**params, "topic": "Health"}
                )

        assert hit.json()["brief"] == "Talks resumed in Wellington."
        assert other_topic.json()["brief"] is None

    @pytest.mark.asyncio
    async def test_never_constructs_an_anthropic_client(self, monkeypatch):
        import app.routers.news as news
        from app.services import ai_summary

        monkeypatch.setattr(ai_summary.settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(ai_summary, "get_cached", AsyncMock(return_value=None))
        monkeypatch.setattr(news, "_now", lambda: PREVIEW_NOW)
        with (
            patch("app.routers.news.get_cell_spark", AsyncMock(return_value=[0] * 24)),
            patch("app.routers.news.get_cell_entities", AsyncMock(return_value=[])),
            patch(
                "app.services.ai_summary.anthropic.AsyncAnthropic",
                side_effect=AssertionError("Claude called on hover"),
            ) as client_cls,
        ):
            resp = await _preview(monkeypatch)

        assert resp.status_code == 200
        assert resp.json()["brief"] is None
        client_cls.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"lat": 91},
            {"lat": -90.5},
            {"lng": 180.5},
            {"lng": -181},
            {"lat": "north"},
            {"topic": "sport"},
            {"topic": "Politics,Health"},
            {"timespan": "2h"},  # not one of the timeline's presets
            {"timespan": "169h"},
            {"timespan": "a day"},
            {"start_time": "2026-10-09T00:00:00Z"},  # no end
            {"end_time": "2026-10-09T00:00:00Z"},
            {"start_time": "yesterday", "end_time": "2026-10-10T00:00:00Z"},
            {"start_time": "2026-10-10T00:00:00Z", "end_time": "2026-10-09T00:00:00Z"},
            {"start_time": "2026-10-09T00:00:00Z", "end_time": "2026-10-09T00:00:00Z"},
            {"start_time": "2026-09-01T00:00:00Z", "end_time": "2026-10-10T00:00:00Z"},
        ],
    )
    async def test_invalid_input_is_422(self, monkeypatch, preview_db, params):
        resp = await _preview(monkeypatch, **params)

        assert resp.status_code == 422
        preview_db.spark.assert_not_awaited()
        preview_db.entities.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lat_and_lng_are_required(self, monkeypatch, preview_db):
        async with _api_client(monkeypatch) as client:
            resp = await client.get("/api/news/preview", params={"lat": 1})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cached_for_five_minutes_by_cell_hour_and_topic(self, monkeypatch, preview_db):
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            await _preview(monkeypatch, topic="Climate")

        key, value, ttl = mock_set.await_args.args
        # 24 h back from 14:30, each bound floored to the hour.
        assert key == "preview:v1:40:-74:2026101114-2026101214:environment"
        assert value == {"spark": [0] * 23 + [4], "entities": [], "brief": None}
        assert ttl == 300

    @pytest.mark.asyncio
    async def test_points_in_one_cell_and_hour_share_an_entry(self, monkeypatch, preview_db):
        import app.routers.news as news

        keys = []
        for lat, lng, minute in [(40.1, -74.9, 30), (40.9, -74.1, 59)]:
            monkeypatch.setattr(news, "_now", lambda m=minute: PREVIEW_NOW.replace(minute=m))
            with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
                await _preview(monkeypatch, lat=lat, lng=lng)
            keys.append(mock_set.await_args.args[0])
        assert keys[0] == keys[1] == "preview:v1:40:-75:2026101114-2026101214"

    @pytest.mark.asyncio
    async def test_a_cached_preview_is_served_without_the_database(self, monkeypatch, preview_db):
        cached = {"spark": [1] * 24, "entities": [], "brief": "Cached."}
        with patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=cached):
            resp = await _preview(monkeypatch)

        assert resp.json() == cached
        preview_db.spark.assert_not_awaited()
        preview_db.entities.assert_not_awaited()
        preview_db.brief.assert_not_awaited()

    def test_is_in_the_data_rate_limit_group(self):
        from app.middleware.security import _get_rate_group

        assert _get_rate_group("/api/news/preview") == "data"


# ── Edge caching: Vercel's CDN may serve public reads for a minute ──────

EDGE = "public, s-maxage=60, stale-while-revalidate=300"


class TestEdgeCaching:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/news?timespan=24h&limit=500",
            "/api/news/volume?days=7",
            "/api/news/preview?lat=40.7&lng=-74.0",
            "/api/topics",
        ],
    )
    async def test_public_reads_are_edge_cached_for_a_minute(self, monkeypatch, path):
        import app.routers.news as news

        monkeypatch.setattr(news, "_now", lambda: datetime(2026, 10, 12, 14, tzinfo=timezone.utc))
        with (
            patch("app.routers.news.get_globe_points", AsyncMock(return_value=[])),
            patch("app.routers.news.get_hourly_volume", AsyncMock(return_value=[])),
            patch("app.routers.news.get_cell_spark", AsyncMock(return_value=[0] * 24)),
            patch("app.routers.news.get_cell_entities", AsyncMock(return_value=[])),
            patch("app.routers.news.cached_summary", AsyncMock(return_value=None)),
            patch("app.routers.news.get_topic_counts", AsyncMock(return_value={"politics": 3})),
        ):
            async with _api_client(monkeypatch) as client:
                resp = await client.get(path)

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == EDGE

    @pytest.mark.asyncio
    async def test_a_cached_answer_is_edge_cached_too(self, monkeypatch):
        with patch("app.routers.news.get_cached", AsyncMock(return_value=[])):
            async with _api_client(monkeypatch) as client:
                resp = await client.get("/api/news")

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == EDGE

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/news?topic=sport",  # the endpoint's own 422
            "/api/news/volume?days=9",  # FastAPI's validation
            "/api/news/preview?lat=91&lng=0",
        ],
    )
    async def test_errors_are_never_edge_cached(self, monkeypatch, path):
        async with _api_client(monkeypatch) as client:
            resp = await client.get(path)

        assert resp.status_code == 422
        assert "s-maxage" not in resp.headers.get("cache-control", "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path", ["/api/news/cluster?lat=40.7&lng=-74.0", "/api/news/summary?lat=40.7&lng=-74.0"]
    )
    async def test_a_places_articles_and_summary_are_not(self, monkeypatch, path):
        with (
            patch("app.routers.news.get_articles_in_bounds", AsyncMock(return_value=[])),
            patch("app.routers.news.summarise_cluster", AsyncMock(return_value="")),
        ):
            async with _api_client(monkeypatch) as client:
                resp = await client.get(path)

        assert resp.status_code == 200
        assert "cache-control" not in resp.headers


# ── /api/news/breaking: events many outlets have just started covering ─────

LEAD = {
    "title": "Pupil detained after school shooting in France",
    "source_name": "example.com",
    "published_at": datetime(2026, 10, 12, 14, 15, tzinfo=timezone.utc),
    "image_url": "https://cdn.example.com/a.jpg",
    "topic": "conflict",
    "sensitive": True,
}


def _story(n: int, topic: str = "conflict", outlets: int = 10) -> dict:
    return {
        "headline": f"Breaking story {n}",
        "place": "Aubagne, France",
        "lat": 43.5,
        "lng": 5.5 + n,
        "outlets": outlets,
        "stories": 9,
        "first_seen": datetime(2026, 10, 12, 13, 50, tzinfo=timezone.utc),
        "topic": topic,
        "lead": LEAD,
    }


def _json(story: dict) -> dict:
    return {
        **story,
        "first_seen": "2026-10-12T13:50:00Z",
        "lead": {**story["lead"], "published_at": "2026-10-12T14:15:00Z"},
    }


STORY = _story(0)
STORY_JSON = _json(STORY)


@pytest.fixture
def breaking_db(monkeypatch):
    """The breaking query stubbed; the clock frozen."""
    import app.routers.news as news

    monkeypatch.setattr(news, "_now", lambda: PREVIEW_NOW)
    with patch("app.routers.news.get_breaking", AsyncMock(return_value=[STORY])) as mock:
        yield mock


async def _get(monkeypatch, path, **params):
    async with _api_client(monkeypatch) as client:
        return await client.get(path, params=params)


class TestGetBreaking:
    @pytest.mark.asyncio
    async def test_returns_the_breaking_stories_as_of_now(self, monkeypatch, breaking_db):
        resp = await _get(monkeypatch, "/api/news/breaking")

        assert resp.status_code == 200
        assert resp.json() == [STORY_JSON]
        breaking_db.assert_awaited_once_with(PREVIEW_NOW)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("topic", "kept"),
        [("Conflict", [0, 2]), ("climate", [1]), ("Health", []), ("All", [0, 1, 2, 3])],
    )
    async def test_a_topic_keeps_the_events_whose_dominant_topic_it_is(
        self, monkeypatch, breaking_db, topic, kept
    ):
        """One query serves every topic: an event is an event, the topic its neighbours'."""
        topics = ["conflict", "environment", "conflict", "politics"]
        breaking_db.return_value = [_story(i, t) for i, t in enumerate(topics)]

        resp = await _get(monkeypatch, "/api/news/breaking", topic=topic)

        assert [s["headline"] for s in resp.json()] == [f"Breaking story {i}" for i in kept]
        breaking_db.assert_awaited_once_with(PREVIEW_NOW)

    @pytest.mark.asyncio
    async def test_at_most_eight_most_outlets_first(self, monkeypatch, breaking_db):
        breaking_db.return_value = [_story(i, outlets=20 - i) for i in range(11)]

        resp = await _get(monkeypatch, "/api/news/breaking")

        assert [s["outlets"] for s in resp.json()] == [20, 19, 18, 17, 16, 15, 14, 13]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("topic", ["sport", "Politics,Health"])
    async def test_an_unknown_topic_is_422_and_not_edge_cached(
        self, monkeypatch, breaking_db, topic
    ):
        resp = await _get(monkeypatch, "/api/news/breaking", topic=topic)

        assert resp.status_code == 422
        assert "s-maxage" not in resp.headers.get("cache-control", "")
        breaking_db.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_every_breaking_story_is_cached_once_until_the_next_warm(
        self, monkeypatch, breaking_db
    ):
        """Uncapped and for every topic: each request then filters and caps it. Kept a
        cycle and more (the warm refills it after each ingestion), not 300 s; and as the
        last good list, outside db:*, for an hour."""
        breaking_db.return_value = [_story(i) for i in range(9)]
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            await _get(monkeypatch, "/api/news/breaking", topic="Climate")

        stored = [_json(_story(i)) for i in range(9)]
        assert [c.args for c in mock_set.await_args_list] == [
            ("db:breaking:v1", stored, cycle_ttl(300)),
            ("last:breaking:v1", stored, 3600),
        ]

    @pytest.mark.asyncio
    async def test_none_breaking_is_cached_too(self, monkeypatch, breaking_db):
        breaking_db.return_value = []
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            resp = await _get(monkeypatch, "/api/news/breaking")

        assert resp.json() == []
        assert [c.args for c in mock_set.await_args_list] == [
            ("db:breaking:v1", [], cycle_ttl(300)),
            ("last:breaking:v1", [], 3600),
        ]

    @pytest.mark.asyncio
    async def test_the_warmer_caches_what_the_first_request_would(self, monkeypatch, breaking_db):
        """app.warm refills it after each ingestion cycle, with the request's keys and bytes."""
        import app.routers.news as news

        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            await _get(monkeypatch, "/api/news/breaking")
            await news.warm_breaking()

        stored = [
            ("db:breaking:v1", [STORY_JSON], cycle_ttl(300)),
            ("last:breaking:v1", [STORY_JSON], 3600),
        ]
        assert [c.args for c in mock_set.await_args_list] == stored * 2  # request's, warm's

    @pytest.mark.asyncio
    async def test_cached_stories_are_served_without_the_database(self, monkeypatch, breaking_db):
        with patch("app.routers.news.get_cached", AsyncMock(return_value=[STORY_JSON])):
            resp = await _get(monkeypatch, "/api/news/breaking", topic="Conflict")

        assert resp.json() == [STORY_JSON]
        breaking_db.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_is_edge_cached(self, monkeypatch, breaking_db):
        resp = await _get(monkeypatch, "/api/news/breaking")

        assert resp.headers["cache-control"] == EDGE

    def test_is_in_the_data_rate_limit_group(self):
        from app.middleware.security import _get_rate_group

        assert _get_rate_group("/api/news/breaking") == "data"

    @pytest.mark.asyncio
    async def test_place_surges_are_gone(self, monkeypatch, breaking_db):
        resp = await _get(monkeypatch, "/api/news/surges")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_a_database_error_is_a_500_and_nothing_is_cached(self, monkeypatch, breaking_db):
        breaking_db.side_effect = RuntimeError("connection reset")
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            resp = await _get(monkeypatch, "/api/news/breaking")

        assert resp.status_code == 500
        assert "s-maxage" not in resp.headers.get("cache-control", "")
        mock_set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_query_that_times_out_with_no_last_good_list_is_a_503_to_retry(
        self, monkeypatch, breaking_db, caplog
    ):
        """Not a 500 and a traceback (110 in four days on production): the ticker asks
        again after Retry-After. Never kept at the edge, and nothing is cached."""
        import app.routers.news as news

        monkeypatch.setattr(news, "_BREAKING_QUERY_TIMEOUT", 0.01)

        async def hung(*_args):
            await asyncio.Event().wait()  # never set

        breaking_db.side_effect = hung
        with (
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
            caplog.at_level(logging.INFO),
        ):
            resp = await _get(monkeypatch, "/api/news/breaking", topic="Conflict")

        assert resp.status_code == 503
        assert resp.headers["retry-after"] == "15"
        assert "cache-control" not in resp.headers
        assert resp.json()["detail"] == "The breaking query took over 0.01 s; retry shortly."
        mock_set.assert_not_awaited()
        assert not [r for r in caplog.records if r.exc_info]
        assert "Breaking query failed (TimeoutError: The breaking query took over 0.01 s)" in (
            caplog.text
        )


class TestBreakingSingleFlight:
    """Concurrent misses share one query (the delta asks too)."""

    @pytest.mark.asyncio
    async def test_two_concurrent_misses_run_the_query_once(self, monkeypatch, breaking_db):
        import asyncio

        import app.routers.news as news

        release = asyncio.Event()

        async def slow(*_args):
            await release.wait()
            return [STORY]

        breaking_db.side_effect = slow
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            first = asyncio.create_task(news._cached_breaking())
            second = asyncio.create_task(news._cached_breaking())
            await asyncio.sleep(0)
            release.set()
            a, b = await asyncio.gather(first, second)

        assert a == b
        assert breaking_db.await_count == 1
        assert mock_set.await_count == 2  # once each: the cycle's key and the last good one
        assert news._breaking_in_flight == {}

    @pytest.mark.asyncio
    async def test_an_error_reaches_every_waiter_and_nothing_is_cached(
        self, monkeypatch, breaking_db
    ):
        import asyncio

        import app.routers.news as news

        release = asyncio.Event()

        async def failing(*_args):
            await release.wait()
            raise RuntimeError("connection reset")

        breaking_db.side_effect = failing
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            waiters = [asyncio.create_task(news._cached_breaking()) for _ in range(2)]
            await asyncio.sleep(0)
            release.set()
            results = await asyncio.gather(*waiters, return_exceptions=True)

        assert [type(r) for r in results] == [RuntimeError, RuntimeError]
        assert breaking_db.await_count == 1
        mock_set.assert_not_awaited()
        assert news._breaking_in_flight == {}

        breaking_db.side_effect = None
        breaking_db.return_value = [STORY]
        assert len(await news._cached_breaking()) == 1
        assert breaking_db.await_count == 2

    @pytest.mark.asyncio
    async def test_a_waiter_cancelled_leaves_the_query_to_the_others(
        self, monkeypatch, breaking_db
    ):
        import asyncio

        import app.routers.news as news

        release = asyncio.Event()

        async def slow(*_args):
            await release.wait()
            return [STORY]

        breaking_db.side_effect = slow
        first = asyncio.create_task(news._cached_breaking())
        second = asyncio.create_task(news._cached_breaking())
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)
        release.set()

        assert len(await second) == 1
        assert first.cancelled()
        assert breaking_db.await_count == 1

    @pytest.mark.asyncio
    async def test_a_hung_query_times_out_for_every_waiter(self, monkeypatch, breaking_db):
        """A query that never returns can't hold up every later breaking or delta request:
        it gives up, nothing is cached, and the next miss retries."""
        import asyncio

        import app.routers.news as news

        assert news._BREAKING_QUERY_TIMEOUT == 15
        monkeypatch.setattr(news, "_BREAKING_QUERY_TIMEOUT", 0.01)

        async def hung(*_args):
            await asyncio.Event().wait()  # never set

        breaking_db.side_effect = hung
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            waiters = [asyncio.create_task(news._cached_breaking()) for _ in range(2)]
            results = await asyncio.wait_for(
                asyncio.gather(*waiters, return_exceptions=True), timeout=5
            )

        assert [type(r) for r in results] == [TimeoutError, TimeoutError]
        assert breaking_db.await_count == 1
        mock_set.assert_not_awaited()
        assert news._breaking_in_flight == {}

        breaking_db.side_effect = None
        breaking_db.return_value = [STORY]
        assert len(await news._cached_breaking()) == 1
        assert breaking_db.await_count == 2


@pytest.fixture
def redis():
    """Redis faked, with a clock, in place of the router's no-cache stubs."""
    from app.services import cache

    fake = FakeRedis()
    with (
        patch("app.services.cache.get_redis", AsyncMock(return_value=fake)),
        patch("app.routers.news.get_cached", cache.get_cached),
        patch("app.routers.news.set_cached", cache.set_cached),
    ):
        yield fake


def _held(mock: AsyncMock, answer: list[dict]) -> asyncio.Event:
    """Make the breaking query wait until the event returned is set, then give *answer*."""
    release = asyncio.Event()

    async def held(*_args):
        await release.wait()
        return answer

    mock.side_effect = held
    return release


class TestBreakingLastGood:
    """The last good list (last:breaking:v1), outside the db:* each cycle invalidates: a
    miss serves it at once while one query refills both keys, rather than wait 11-14 s
    for that query or fail when it times out."""

    @pytest.mark.asyncio
    async def test_a_miss_serves_the_last_good_list_at_once_and_starts_one_query(
        self, monkeypatch, redis, breaking_db
    ):
        import app.routers.news as news

        await news.warm_breaking()  # a cycle's warm
        await invalidate("db:*")  # the next cycle ends; visitors come before its warm
        release = _held(breaking_db, [_story(1)])

        async with _api_client(monkeypatch) as client:
            answers = [
                await asyncio.wait_for(client.get("/api/news/breaking", params=params), 1)
                for params in ({}, {"topic": "Conflict"}, {"topic": "Health"})
            ]

        assert [a.status_code for a in answers] == [200, 200, 200]
        assert [a.json() for a in answers] == [[STORY_JSON], [STORY_JSON], []]
        assert all(a.headers["cache-control"] == EDGE for a in answers)  # a minute, as ever
        assert breaking_db.await_count == 2  # the warm's, then one for the three misses
        refill = news._breaking_in_flight["db:breaking:v1"]

        release.set()
        assert await refill == [news.BreakingStory(**_story(1))]
        for key in ("db:breaking:v1", "last:breaking:v1"):
            assert json.loads(redis.values[key]) == [_json(_story(1))], key
        resp = await _get(monkeypatch, "/api/news/breaking")
        assert resp.json() == [_json(_story(1))]
        assert breaking_db.await_count == 2

    @pytest.mark.asyncio
    async def test_the_cycles_invalidation_leaves_the_last_good_list_for_an_hour(
        self, redis, breaking_db
    ):
        """Four cycles: a list an hour old still names events that broke within three
        hours (breaking is about the last two). Older, it is never served."""
        import app.routers.news as news

        await news.warm_breaking()
        await invalidate("db:*")  # as each ingestion cycle ends

        assert "db:breaking:v1" not in redis.values
        assert json.loads(redis.values["last:breaking:v1"]) == [STORY_JSON]
        assert redis.ttls["last:breaking:v1"] == news._BREAKING_LAST_TTL == 60 * 60
        redis.elapse(60 * 60)
        assert "last:breaking:v1" not in redis.values

    @pytest.mark.asyncio
    async def test_the_warm_refills_both_keys_and_never_settles_for_the_last_good_list(
        self, redis, breaking_db
    ):
        import app.routers.news as news

        await set_cached("last:breaking:v1", [_json(_story(7))], 3600)  # an older list

        await news.warm_breaking()

        breaking_db.assert_awaited_once_with(PREVIEW_NOW)
        assert json.loads(redis.values["db:breaking:v1"]) == [STORY_JSON]
        assert json.loads(redis.values["last:breaking:v1"]) == [STORY_JSON]
        assert redis.ttls["db:breaking:v1"] == cycle_ttl(300)
        assert redis.ttls["last:breaking:v1"] == 3600
        assert news._breaking_in_flight == {}  # waited for, not left running

        await news.warm_breaking()  # refilled already (by a miss, say): no second query
        breaking_db.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_the_warm_joins_a_refill_a_miss_started(self, monkeypatch, redis, breaking_db):
        import app.routers.news as news

        await set_cached("last:breaking:v1", [_json(_story(7))], 3600)
        release = _held(breaking_db, [STORY])
        resp = await _get(monkeypatch, "/api/news/breaking")
        assert resp.json() == [_json(_story(7))]

        warm = asyncio.create_task(news.warm_breaking())
        await asyncio.sleep(0)
        assert not warm.done()  # waits for the refill, not the last good list
        release.set()
        await asyncio.wait_for(warm, 1)

        breaking_db.assert_awaited_once()
        assert json.loads(redis.values["db:breaking:v1"]) == [STORY_JSON]

    @pytest.mark.asyncio
    async def test_a_failed_refill_is_one_log_line_and_the_last_good_list_is_kept(
        self, monkeypatch, redis, breaking_db, caplog
    ):
        """No caller waits on it to raise to: the line is all that says it failed."""
        import app.routers.news as news

        await set_cached("last:breaking:v1", [STORY_JSON], 3600)
        release = asyncio.Event()

        async def failing(*_args):
            await release.wait()
            raise RuntimeError("connection reset")

        breaking_db.side_effect = failing
        with caplog.at_level(logging.WARNING, logger="app.routers.news"):
            resp = await _get(monkeypatch, "/api/news/breaking")
            refill = news._breaking_in_flight["db:breaking:v1"]
            release.set()
            await asyncio.gather(refill, return_exceptions=True)

        assert resp.status_code == 200
        assert resp.json() == [STORY_JSON]
        assert [r.getMessage() for r in caplog.records] == [
            "Breaking query failed (RuntimeError: connection reset); the next miss retries."
        ]
        assert json.loads(redis.values["last:breaking:v1"]) == [STORY_JSON]
        assert "db:breaking:v1" not in redis.values
        assert news._breaking_in_flight == {}


# ── /api/news/delta: what changed since a visit ─────────────────────────

CHANGES = {
    "new_stories": 1286,
    "new_places": 212,
    "top": [
        {
            "lat": STORY["lat"],
            "lng": STORY["lng"],
            "place": STORY["place"],
            "new": 31,
            "lead": STORY["lead"],
        }
    ],
}


@pytest.fixture
def delta_db(monkeypatch):
    """The delta and breaking queries stubbed; the clock frozen at 14:30."""
    import app.routers.news as news

    monkeypatch.setattr(news, "_now", lambda: PREVIEW_NOW)
    with (
        patch("app.routers.news.get_delta", AsyncMock(return_value=CHANGES)) as changes,
        patch("app.routers.news.get_breaking", AsyncMock(return_value=[STORY, STORY])) as found,
    ):
        yield SimpleNamespace(changes=changes, breaking=found)


class TestGetDelta:
    @pytest.mark.asyncio
    async def test_the_breaking_count_is_at_most_eight_as_the_ticker_lists(
        self, monkeypatch, delta_db
    ):
        delta_db.breaking.return_value = [_story(i) for i in range(11)]

        resp = await _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:20:00Z")

        assert resp.json()["breaking"] == 8

    @pytest.mark.asyncio
    async def test_new_stories_places_breaking_stories_and_the_top_places(
        self, monkeypatch, delta_db
    ):
        resp = await _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:20:00Z")

        assert resp.status_code == 200
        assert resp.json() == {
            "new_stories": 1286,
            "new_places": 212,
            "breaking": 2,  # the breaking list, as the ticker shows it
            "top": [{**CHANGES["top"][0], "lead": STORY_JSON["lead"]}],
        }
        delta_db.breaking.assert_awaited_once_with(PREVIEW_NOW)  # every topic

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("since", "start"),
        [
            # Up to 24 hours back: floored to the quarter hour, in UTC.
            ("2026-10-12T00:20:00Z", datetime(2026, 10, 12, 0, 15, tzinfo=timezone.utc)),
            ("2026-10-12T05:44:59.999+05:30", datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)),
            ("2026-10-12T14:30:00", datetime(2026, 10, 12, 14, 30, tzinfo=timezone.utc)),
            ("2026-10-11T14:30:00Z", datetime(2026, 10, 11, 14, 30, tzinfo=timezone.utc)),
            # Up to 72 hours: to the hour.
            ("2026-10-11T14:29:59Z", datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)),
            ("2026-10-09T14:30:00Z", datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)),
            # Beyond: to 6 hours (00, 06, 12, 18 UTC).
            ("2026-10-09T14:29:59Z", datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)),
            ("2026-10-07T05:59:59Z", datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)),
            # Clamped to the last 7 days, then floored.
            ("2026-09-01T00:00:00Z", datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)),
            ("0001-01-01T00:00:00+01:00", datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)),
            # A fast clock, up to 15 minutes ahead: now.
            ("2026-10-12T14:31:00Z", datetime(2026, 10, 12, 14, 30, tzinfo=timezone.utc)),
            ("2026-10-12T14:45:00Z", datetime(2026, 10, 12, 14, 30, tzinfo=timezone.utc)),
        ],
    )
    async def test_since_is_floored_coarser_the_older_it_is_and_clamped_to_7_days(
        self, monkeypatch, delta_db, since, start
    ):
        resp = await _get(monkeypatch, "/api/news/delta", since=since)

        assert resp.status_code == 200
        delta_db.changes.assert_awaited_once_with(start)

    def test_a_week_of_visits_shares_163_starts_not_673(self, monkeypatch):
        import app.routers.news as news

        starts = {
            news._delta_start((PREVIEW_NOW - timedelta(minutes=m)).isoformat(), PREVIEW_NOW)
            for m in range(0, 7 * 24 * 60 + 1)
        }
        # 97 quarter hours, 49 hours and 17 six-hour blocks, each tier's ends included.
        assert len(starts) == 97 + 49 + 17
        assert news._MAX_DELTA == timedelta(days=settings.retention_days)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {},  # since is required
            {"since": ""},
            {"since": "yesterday"},
            {"since": "2026-10-12T25:00:00Z"},
            {"since": "2026-10-12T14:45:00.001Z"},  # more than 15 minutes ahead
            {"since": "9999-12-31T00:00:00Z"},
        ],
    )
    async def test_invalid_or_future_since_is_422(self, monkeypatch, delta_db, params):
        resp = await _get(monkeypatch, "/api/news/delta", **params)

        assert resp.status_code == 422
        assert "s-maxage" not in resp.headers.get("cache-control", "")
        delta_db.changes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cached_for_five_minutes_by_the_floored_since(self, monkeypatch, delta_db):
        """v2: surging became breaking; a v1 entry cached before the deploy would fail."""
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            await _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:29:59Z")

        key, value, ttl = mock_set.await_args_list[-1].args
        assert key == "db:delta:v2:202610120015"
        assert value["new_stories"] == 1286 and value["breaking"] == 2
        assert value["top"][0]["lead"]["published_at"] == "2026-10-12T14:15:00Z"
        assert ttl == 300

    @pytest.mark.asyncio
    async def test_visits_in_one_quarter_hour_share_an_entry(self, monkeypatch, delta_db):
        keys = []
        for since in ["2026-10-12T00:15:00Z", "2026-10-12T00:29:59Z"]:
            with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
                await _get(monkeypatch, "/api/news/delta", since=since)
            keys.append(mock_set.await_args_list[-1].args[0])
        assert keys[0] == keys[1]

    @pytest.mark.asyncio
    async def test_a_cached_delta_is_served_without_the_database(self, monkeypatch, delta_db):
        cached = {"new_stories": 3, "new_places": 1, "breaking": 0, "top": []}
        with patch("app.routers.news.get_cached", AsyncMock(return_value=cached)):
            resp = await _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:20:00Z")

        assert resp.json() == cached
        delta_db.changes.assert_not_awaited()
        delta_db.breaking.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_is_edge_cached(self, monkeypatch, delta_db):
        resp = await _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:20:00Z")

        assert resp.headers["cache-control"] == EDGE

    def test_has_its_own_tighter_rate_limit_group(self):
        from app.middleware.security import _RATE_LIMITS, _get_rate_group

        assert _get_rate_group("/api/news/delta") == "delta"
        assert _RATE_LIMITS["delta"] == (60, 10)

    @pytest.mark.asyncio
    async def test_the_eleventh_delta_in_a_minute_is_429_but_other_reads_go_on(
        self, monkeypatch, delta_db
    ):
        from httpx import ASGITransport, AsyncClient

        from app.main import app
        from app.middleware import security

        monkeypatch.setattr(security.settings, "api_key", "")
        security._rate_buckets.clear()
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        params = {"since": "2026-10-12T00:20:00Z"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            codes = [(await client.get("/api/news/delta", params=params)).status_code]
            codes += [
                (await client.get("/api/news/delta", params=params)).status_code for _ in range(10)
            ]
            breaking = await client.get("/api/news/breaking")

        assert codes == [200] * 10 + [429]
        assert breaking.status_code == 200

    @pytest.mark.asyncio
    async def test_a_database_error_is_a_500_and_nothing_is_cached(self, monkeypatch, delta_db):
        delta_db.changes.side_effect = RuntimeError("connection reset")
        with patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set:
            resp = await _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:20:00Z")

        assert resp.status_code == 500
        assert "s-maxage" not in resp.headers.get("cache-control", "")
        assert [c.args[0] for c in mock_set.await_args_list if "delta" in c.args[0]] == []

    @pytest.mark.asyncio
    async def test_a_breaking_query_that_times_out_is_a_503_not_a_500(
        self, monkeypatch, delta_db, caplog
    ):
        """With no last good list to count: as the ticker's, a 503 the client may retry,
        never kept at the edge nor cached (a count of 0 would be wrong for 5 minutes)."""
        import app.routers.news as news

        monkeypatch.setattr(news, "_BREAKING_QUERY_TIMEOUT", 0.01)

        async def hung(*_args):
            await asyncio.Event().wait()  # never set

        delta_db.breaking.side_effect = hung
        with (
            patch("app.routers.news.set_cached", new_callable=AsyncMock) as mock_set,
            caplog.at_level(logging.INFO),
        ):
            resp = await _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:20:00Z")

        assert resp.status_code == 503
        assert resp.headers["retry-after"] == "15"
        assert "cache-control" not in resp.headers
        assert resp.json()["detail"] == "The breaking query took over 0.01 s; retry shortly."
        mock_set.assert_not_awaited()
        assert not [r for r in caplog.records if r.exc_info]

    @pytest.mark.asyncio
    async def test_a_breaking_miss_counts_the_last_good_list_rather_than_wait(
        self, monkeypatch, redis, delta_db
    ):
        import app.routers.news as news

        await set_cached("last:breaking:v1", [STORY_JSON, _json(_story(1))], 3600)
        release = _held(delta_db.breaking, [STORY])

        resp = await asyncio.wait_for(
            _get(monkeypatch, "/api/news/delta", since="2026-10-12T00:20:00Z"), 1
        )

        assert resp.status_code == 200
        assert resp.json()["breaking"] == 2
        release.set()
        await news._breaking_in_flight["db:breaking:v1"]
        assert json.loads(redis.values["db:breaking:v1"]) == [STORY_JSON]
