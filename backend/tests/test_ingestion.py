"""Tests for the GDELT → PostgreSQL ingestion service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.models.news import NewsArticle


def _make_gdelt_article(title: str, lat: float = 40.0, lng: float = -74.0):
    """Build a raw GDELT DOC response article dict."""
    return {
        "title": title,
        "url": f"https://example.com/{title.lower().replace(' ', '-')}",
        "domain": "example.com",
        "language": "en",
        "seendate": "20260303T120000Z",
        "sourcecountry": "United States",
        "tone": "-2.5",
    }


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


class TestRunIngestionCycle:
    @pytest.mark.asyncio
    async def test_happy_path_upserts_articles(self):
        from app.services.ingestion import run_ingestion_cycle

        articles = [_make_parsed_article("Test article")]

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value={"articles": []}), \
             patch("app.services.ingestion._parse_doc_response", return_value=articles), \
             patch("app.services.ingestion.upsert_articles", new_callable=AsyncMock, return_value=1) as mock_upsert, \
             patch("app.services.ingestion.invalidate", new_callable=AsyncMock) as mock_invalidate:
            count = await run_ingestion_cycle()
            assert count == 1
            mock_upsert.assert_called_once()
            mock_invalidate.assert_called_once_with("db:*")

    @pytest.mark.asyncio
    async def test_gdelt_failure_returns_zero(self):
        from app.services.ingestion import run_ingestion_cycle

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value=None), \
             patch("app.services.ingestion._parse_doc_response", return_value=[]), \
             patch("app.services.ingestion.upsert_articles", new_callable=AsyncMock) as mock_upsert:
            count = await run_ingestion_cycle()
            assert count == 0
            mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_coord_articles_filtered(self):
        from app.services.ingestion import run_ingestion_cycle

        articles = [
            _make_parsed_article("Good article", lat=40.0, lng=-74.0),
            _make_parsed_article("No location", lat=0.0, lng=0.0),
        ]

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value={}), \
             patch("app.services.ingestion._parse_doc_response", return_value=articles), \
             patch("app.services.ingestion.upsert_articles", new_callable=AsyncMock, return_value=1) as mock_upsert, \
             patch("app.services.ingestion.invalidate", new_callable=AsyncMock):
            count = await run_ingestion_cycle()
            assert count == 1
            # Only 1 article should have been passed (the geolocated one)
            rows = mock_upsert.call_args[0][0]
            assert len(rows) == 1
            assert rows[0]["title"] == "Good article"

    @pytest.mark.asyncio
    async def test_exception_does_not_crash(self):
        from app.services.ingestion import run_ingestion_cycle

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, side_effect=Exception("boom")):
            count = await run_ingestion_cycle()
            assert count == 0

    @pytest.mark.asyncio
    async def test_cache_invalidated_after_upsert(self):
        from app.services.ingestion import run_ingestion_cycle

        articles = [_make_parsed_article("Article")]

        with patch("app.services.ingestion._fetch_with_retry", new_callable=AsyncMock, return_value={}), \
             patch("app.services.ingestion._parse_doc_response", return_value=articles), \
             patch("app.services.ingestion.upsert_articles", new_callable=AsyncMock, return_value=1), \
             patch("app.services.ingestion.invalidate", new_callable=AsyncMock) as mock_invalidate:
            await run_ingestion_cycle()
            mock_invalidate.assert_called_once_with("db:*")
