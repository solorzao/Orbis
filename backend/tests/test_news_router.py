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
    async def test_uses_grid_cell_bounds(self):
        from app.routers.news import _CELL_SIZE, get_cluster_articles

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=[]
        ) as mock_bounds:
            await get_cluster_articles(
                lat=40.5,
                lng=-74.5,
                topic=None,
                location_name=None,
                offset=0,
                limit=10,
                sentiment=None,
                search=None,
            )
            args = mock_bounds.call_args[0]
            half = _CELL_SIZE / 2.0
            assert args[0] == pytest.approx(40.5 - half)  # min_lat
            assert args[1] == pytest.approx(-74.5 - half)  # min_lng
            assert args[2] == pytest.approx(40.5 + half)  # max_lat
            assert args[3] == pytest.approx(-74.5 + half)  # max_lng

    @pytest.mark.asyncio
    async def test_topic_filter_applied(self):
        from app.routers.news import get_cluster_articles

        rows = [
            _make_db_row("Economy article", ["economy"]),
            _make_db_row("Conflict article", ["conflict"]),
        ]

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows
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
            assert len(result) == 1
            assert result[0].title == "Conflict article"

    @pytest.mark.asyncio
    async def test_topic_filter_fallback_when_no_match(self):
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row("General article", ["general"])]

        with patch(
            "app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows
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
            # Falls back to unfiltered when topic matches nothing
            assert len(result) == 1

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
