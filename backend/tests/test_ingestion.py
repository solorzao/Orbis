"""Tests for the GDELT → PostgreSQL ingestion service."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.models.news import GlobeDataPoint, NewsArticle


def _make_parsed_article(title: str, lat: float = 40.0, lng: float = -74.0):
    """Build a NewsArticle as _parse_doc_response would return."""
    now = datetime.now(timezone.utc)
    return NewsArticle(
        id="abc123",
        title=title,
        source_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        source_name="example.com",
        source_language="en",
        published_at=now,
        ingested_at=now,
        latitude=lat,
        longitude=lng,
        country_code="US",
        topic_tags=["general"],
        sentiment_score=-0.25,
    )


def _make_geo_point(lat: float = 40.0, lng: float = -74.0):
    return GlobeDataPoint(
        lat=lat, lng=lng, weight=100, article_count=5,
        top_headline="Test", topic="general", location_name="New York",
    )


class TestIngestArticles:
    @pytest.mark.asyncio
    async def test_upserts_articles(self):
        from app.services.ingestion import _ingest_articles

        articles = [_make_parsed_article("Test article")]

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value={}), \
             patch("app.services.ingestion._parse_doc_response", return_value=articles), \
             patch("app.services.ingestion.upsert_articles", new_callable=AsyncMock, return_value=1) as mock_upsert, \
             patch("app.services.ingestion.invalidate", new_callable=AsyncMock):
            count = await _ingest_articles()
            assert count == 1
            mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_filters_zero_coords(self):
        from app.services.ingestion import _ingest_articles

        articles = [
            _make_parsed_article("Good", lat=40.0, lng=-74.0),
            _make_parsed_article("Bad", lat=0.0, lng=0.0),
        ]

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value={}), \
             patch("app.services.ingestion._parse_doc_response", return_value=articles), \
             patch("app.services.ingestion.upsert_articles", new_callable=AsyncMock, return_value=1) as mock_upsert, \
             patch("app.services.ingestion.invalidate", new_callable=AsyncMock):
            await _ingest_articles()
            rows = mock_upsert.call_args[0][0]
            assert len(rows) == 1
            assert rows[0]["title"] == "Good"

    @pytest.mark.asyncio
    async def test_returns_zero_on_empty(self):
        from app.services.ingestion import _ingest_articles

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value=None), \
             patch("app.services.ingestion._parse_doc_response", return_value=[]):
            count = await _ingest_articles()
            assert count == 0


class TestIngestGeoPoints:
    @pytest.mark.asyncio
    async def test_caches_geo_points(self):
        from app.services.ingestion import _ingest_geo_points

        points = [_make_geo_point(), _make_geo_point(lat=51.0, lng=-0.1)]

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value={}), \
             patch("app.services.ingestion._parse_geo_response", return_value=points), \
             patch("app.services.ingestion.set_cached", new_callable=AsyncMock) as mock_cache:
            count = await _ingest_geo_points()
            assert count == 2
            mock_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_geo_empty(self):
        from app.services.ingestion import _ingest_geo_points

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value=None), \
             patch("app.services.ingestion._parse_geo_response", return_value=[]):
            count = await _ingest_geo_points()
            assert count == 0


class TestRunIngestionCycle:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        from app.services.ingestion import run_ingestion_cycle

        with patch("app.services.ingestion._ingest_articles", new_callable=AsyncMock, return_value=10), \
             patch("app.services.ingestion._ingest_geo_points", new_callable=AsyncMock, return_value=50):
            count = await run_ingestion_cycle()
            assert count == 10

    @pytest.mark.asyncio
    async def test_exception_does_not_crash(self):
        from app.services.ingestion import run_ingestion_cycle

        with patch("app.services.ingestion._ingest_articles", new_callable=AsyncMock, side_effect=Exception("boom")):
            count = await run_ingestion_cycle()
            assert count == 0
