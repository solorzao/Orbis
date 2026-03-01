"""Tests for the news router topic filtering."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.models.news import NewsArticle


def _make_article(title: str, topic_tags: list[str], lat: float = 40.0, lng: float = -74.0):
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
        topic_tags=topic_tags,
    )


class TestTopicFiltering:
    @pytest.mark.asyncio
    async def test_topic_filter_narrows_results(self):
        from app.routers.news import get_globe_data

        articles = [
            _make_article("War in region", ["conflict"], lat=40.0, lng=-74.0),
            _make_article("Stock market up", ["economy"], lat=51.0, lng=-0.1),
            _make_article("Missile strike", ["conflict"], lat=33.0, lng=44.0),
        ]

        with patch("app.routers.news.fetch_articles", new_callable=AsyncMock, return_value=articles):
            points = await get_globe_data(topic="conflict", timespan="24h", limit=100)
            assert all(p.topic == "conflict" for p in points)

    @pytest.mark.asyncio
    async def test_no_topic_returns_all(self):
        from app.routers.news import get_globe_data

        articles = [
            _make_article("War in region", ["conflict"], lat=40.0, lng=-74.0),
            _make_article("Stock market up", ["economy"], lat=51.0, lng=-0.1),
        ]

        with patch("app.routers.news.fetch_articles", new_callable=AsyncMock, return_value=articles):
            points = await get_globe_data(topic=None, timespan="24h", limit=100)
            assert len(points) == 2
