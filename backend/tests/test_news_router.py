"""Tests for the news router endpoints (database-backed)."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.models.news import GlobeDataPoint, NewsArticle


def _make_globe_row(topic: str = "general", lat: float = 40.0, lng: float = -74.0, count: int = 3):
    """Create a dict matching get_globe_points() output."""
    return dict(
        lat=lat,
        lng=lng,
        weight=min(count * 10, 500),
        article_count=count,
        top_headline="Test headline",
        topic=topic,
        location_name="Test City",
    )


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
    with patch("app.routers.news.get_cached", new_callable=AsyncMock, return_value=None), \
         patch("app.routers.news.set_cached", new_callable=AsyncMock):
        yield


class TestGetGlobeData:
    @pytest.mark.asyncio
    async def test_returns_globe_points(self):
        from app.routers.news import get_globe_data

        rows = [
            _make_globe_row("conflict", lat=33.0, lng=44.0),
            _make_globe_row("economy", lat=51.0, lng=-0.1),
        ]

        with patch("app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=rows):
            points = await get_globe_data(timespan="24h", limit=100)
            assert len(points) == 2
            assert points[0].topic == "conflict"

    @pytest.mark.asyncio
    async def test_limit_caps_results(self):
        from app.routers.news import get_globe_data

        rows = [_make_globe_row(count=i + 1) for i in range(10)]

        with patch("app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=rows):
            points = await get_globe_data(timespan="24h", limit=3)
            # get_globe_points handles the limit in SQL, but we pass it through
            assert len(points) == 10  # limit is passed to DB, not post-filtered

    @pytest.mark.asyncio
    async def test_timespan_parsed_to_hours(self):
        from app.routers.news import get_globe_data

        with patch("app.routers.news.get_globe_points", new_callable=AsyncMock, return_value=[]) as mock_get:
            await get_globe_data(timespan="48h", limit=100)
            mock_get.assert_called_once_with(timespan_hours=48, limit=100)


class TestGetClusterArticles:
    @pytest.mark.asyncio
    async def test_returns_articles_from_db(self):
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row("Tehran protest", ["politics"])]

        with patch("app.routers.news.get_nearby_articles", new_callable=AsyncMock, return_value=rows):
            result = await get_cluster_articles(
                lat=35.7, lng=51.4, radius=5.0, topic=None, location_name=None,
            )
            assert len(result) == 1
            assert result[0].title == "Tehran protest"

    @pytest.mark.asyncio
    async def test_radius_converted_to_km(self):
        from app.routers.news import get_cluster_articles

        with patch("app.routers.news.get_nearby_articles", new_callable=AsyncMock, return_value=[]) as mock_nearby:
            await get_cluster_articles(
                lat=40.0, lng=-74.0, radius=5.0, topic=None, location_name=None,
            )
            # 5 degrees * 111 km/degree = 555 km
            call_kwargs = mock_nearby.call_args
            assert call_kwargs[1]["radius_km"] == pytest.approx(555.0)

    @pytest.mark.asyncio
    async def test_topic_filter_applied(self):
        from app.routers.news import get_cluster_articles

        rows = [
            _make_db_row("Economy article", ["economy"]),
            _make_db_row("Conflict article", ["conflict"]),
        ]

        with patch("app.routers.news.get_nearby_articles", new_callable=AsyncMock, return_value=rows):
            result = await get_cluster_articles(
                lat=40.0, lng=-74.0, radius=5.0, topic="conflict", location_name=None,
            )
            assert len(result) == 1
            assert result[0].title == "Conflict article"

    @pytest.mark.asyncio
    async def test_topic_filter_fallback_when_no_match(self):
        from app.routers.news import get_cluster_articles

        rows = [_make_db_row("General article", ["general"])]

        with patch("app.routers.news.get_nearby_articles", new_callable=AsyncMock, return_value=rows):
            result = await get_cluster_articles(
                lat=40.0, lng=-74.0, radius=5.0, topic="conflict", location_name=None,
            )
            # Falls back to unfiltered when topic matches nothing
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_caps_results_at_max(self):
        from app.routers.news import get_cluster_articles, _MAX_CLUSTER_ARTICLES

        rows = [_make_db_row(f"Article {i}") for i in range(50)]

        with patch("app.routers.news.get_nearby_articles", new_callable=AsyncMock, return_value=rows):
            result = await get_cluster_articles(
                lat=40.0, lng=-74.0, radius=5.0, topic=None, location_name=None,
            )
            assert len(result) == _MAX_CLUSTER_ARTICLES


class TestGetTopics:
    @pytest.mark.asyncio
    async def test_returns_topic_counts(self):
        from app.routers.news import get_topics

        counts = {"conflict": 50, "economy": 30, "health": 10}

        with patch("app.routers.news.get_topic_counts", new_callable=AsyncMock, return_value=counts):
            result = await get_topics()
            assert len(result) == 3
            assert result[0].topic == "conflict"
            assert result[0].count == 50
