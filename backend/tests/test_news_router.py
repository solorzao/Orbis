"""Tests for the news router endpoints (database-backed)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.news import _row_to_article


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
    async def test_returns_every_topic_in_the_cell(self):
        from app.routers.news import get_globe_data

        row = {**_make_globe_row(topic="sport"), "topics": ["conflict", "sport"]}
        with patch("app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=[row]):
            [point] = await get_globe_data(timespan="24h", limit=100)
        assert point.topic == "sport"
        assert point.topics == ["conflict", "sport"]

    @pytest.mark.asyncio
    async def test_cached_points_without_topics_still_load(self):
        """Entries cached before `topics` existed stay valid until their TTL ends."""
        from app.routers.news import get_globe_data

        with patch(
            "app.routers.news.get_cached",
            new_callable=AsyncMock,
            return_value=[_make_globe_row(topic="conflict")],
        ):
            [point] = await get_globe_data(timespan="24h", limit=100)
        assert point.topics == []


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


def _volume_client(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    monkeypatch.setattr(security.settings, "api_key", "")
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


class TestGetVolume:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("days", [0, 8])
    async def test_days_outside_one_to_seven_is_422(self, monkeypatch, days):
        with patch("app.routers.news.get_hourly_volume", new_callable=AsyncMock) as mock_db:
            async with _volume_client(monkeypatch) as client:
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
            async with _volume_client(monkeypatch) as client:
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
            async with _volume_client(monkeypatch) as client:
                resp = await client.get("/api/news/volume")

        assert resp.status_code == 200
        mock_db.assert_awaited_once_with(7)
        key, value, ttl = mock_set.await_args.args
        assert key == "db:volume:7"
        assert value == [{"hour": "2026-10-11T14:00:00Z", "count": 5}]
        assert ttl == settings.db_cache_ttl

    @pytest.mark.asyncio
    async def test_serves_the_cached_volume(self, monkeypatch):
        cached = [{"hour": "2026-10-11T14:00:00Z", "count": 5}]
        with (
            patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=cached),
            patch("app.routers.news.get_hourly_volume", new_callable=AsyncMock) as mock_db,
        ):
            async with _volume_client(monkeypatch) as client:
                resp = await client.get("/api/news/volume", params={"days": 2})

        assert resp.json() == cached
        mock_db.assert_not_awaited()
