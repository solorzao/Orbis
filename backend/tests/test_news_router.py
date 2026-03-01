"""Tests for the news router endpoints."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.models.news import GlobeDataPoint, NewsArticle


def _make_globe_point(topic: str = "general", lat: float = 40.0, lng: float = -74.0, **overrides):
    base = dict(
        lat=lat,
        lng=lng,
        weight=10.0,
        article_count=3,
        top_headline="Test headline",
        topic=topic,
        location_name="Test City",
    )
    base.update(overrides)
    return GlobeDataPoint(**base)


def _make_article(title: str, topic_tags: list[str], lat: float = 40.0, lng: float = -74.0, country_code: str = "US"):
    now = datetime.now(timezone.utc)
    return NewsArticle(
        id="test",
        title=title,
        source_url="https://example.com",
        source_name="example.com",
        source_language="en",
        published_at=now,
        ingested_at=now,
        latitude=lat,
        longitude=lng,
        country_code=country_code,
        topic_tags=topic_tags,
    )


class TestGetGlobeData:
    @pytest.mark.asyncio
    async def test_returns_geo_points(self):
        from app.routers.news import get_globe_data

        geo_points = [
            _make_globe_point("conflict", lat=33.0, lng=44.0),
            _make_globe_point("economy", lat=51.0, lng=-0.1),
        ]

        with patch("app.routers.news.fetch_geo_points", new_callable=AsyncMock, return_value=geo_points):
            points = await get_globe_data(topic=None, timespan="24h", limit=100)
            assert len(points) == 2

    @pytest.mark.asyncio
    async def test_topic_filter_builds_gdelt_query(self):
        from app.routers.news import get_globe_data

        geo_points = [_make_globe_point("conflict")]

        with patch("app.routers.news.fetch_geo_points", new_callable=AsyncMock, return_value=geo_points) as mock_fetch:
            await get_globe_data(topic="Conflict", timespan="24h", limit=100)
            call_args = mock_fetch.call_args
            query = call_args[1].get("query") or call_args[0][0] if call_args[0] else call_args[1]["query"]
            assert "war" in query.lower() or "conflict" in query.lower()

    @pytest.mark.asyncio
    async def test_limit_caps_results(self):
        from app.routers.news import get_globe_data

        geo_points = [_make_globe_point(article_count=i) for i in range(10)]

        with patch("app.routers.news.fetch_geo_points", new_callable=AsyncMock, return_value=geo_points):
            points = await get_globe_data(topic=None, timespan="24h", limit=3)
            assert len(points) == 3

    @pytest.mark.asyncio
    async def test_climate_maps_to_environment(self):
        """Frontend sends 'Climate' which should resolve to 'environment' topic alias."""
        from app.routers.news import get_globe_data

        with patch("app.routers.news.fetch_geo_points", new_callable=AsyncMock, return_value=[]) as mock_fetch:
            await get_globe_data(topic="Climate", timespan="24h", limit=100)
            call_args = mock_fetch.call_args
            query = call_args[1].get("query") or call_args[0][0] if call_args[0] else call_args[1]["query"]
            assert "climate" in query.lower() or "energy" in query.lower()


class TestGetClusterArticles:
    @pytest.mark.asyncio
    async def test_passes_location_name_to_gdelt_query(self):
        from app.routers.news import get_cluster_articles

        articles = [_make_article("Tehran protest", ["politics"])]

        with patch("app.routers.news.fetch_articles", new_callable=AsyncMock, return_value=articles) as mock_fetch:
            result = await get_cluster_articles(
                lat=35.7, lng=51.4, radius=5.0, topic=None,
                location_name="Tehran, Tehran, Iran",
            )
            # Should query GDELT with the city name
            query = mock_fetch.call_args[1].get("query") or mock_fetch.call_args[0][0]
            assert "Tehran" in query
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_caps_results_at_max(self):
        from app.routers.news import get_cluster_articles, _MAX_CLUSTER_ARTICLES

        articles = [_make_article(f"Article {i}", ["general"]) for i in range(50)]

        with patch("app.routers.news.fetch_articles", new_callable=AsyncMock, return_value=articles):
            result = await get_cluster_articles(
                lat=40.0, lng=-74.0, radius=5.0, topic=None, location_name="New York",
            )
            assert len(result) == _MAX_CLUSTER_ARTICLES

    @pytest.mark.asyncio
    async def test_no_location_uses_default_query(self):
        from app.routers.news import get_cluster_articles

        with patch("app.routers.news.fetch_articles", new_callable=AsyncMock, return_value=[]) as mock_fetch:
            await get_cluster_articles(
                lat=40.0, lng=-74.0, radius=5.0, topic=None, location_name=None,
            )
            query = mock_fetch.call_args[1].get("query") or mock_fetch.call_args[0][0]
            assert query == "sourcelang:english"
