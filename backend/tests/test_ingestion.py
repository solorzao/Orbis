"""Tests for the raw GKG → PostgreSQL ingestion service."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone


def _make_gkg_article(url="https://example.com/story", title="Test Headline"):
    """Build a dict as fetch_raw_gkg would return."""
    return {
        "url": url,
        "domain": "example.com",
        "lat": 35.7,
        "lng": 51.4,
        "location_name": "Tehran, Tehran, Iran",
        "country_code": "IR",
        "tone": -2.5,
        "themes": "GENERAL_GOVERNMENT",
        "image_url": "https://example.com/img.jpg",
        "published_at": datetime(2026, 3, 5, tzinfo=timezone.utc),
        "title": title,
    }


class TestIngestFromRawGkg:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]

        with patch(
            "app.services.ingestion.fetch_raw_gkg",
            new_callable=AsyncMock,
            return_value=articles,
        ), patch(
            "app.services.ingestion.scrape_titles",
            new_callable=AsyncMock,
            return_value=articles,
        ), patch(
            "app.services.ingestion.upsert_articles",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_upsert, patch(
            "app.services.ingestion.invalidate",
            new_callable=AsyncMock,
        ) as mock_invalidate:
            count = await _ingest_from_raw_gkg()
            assert count == 1
            mock_upsert.assert_called_once()
            mock_invalidate.assert_called_once_with("db:*")

            # Verify upsert row format
            rows = mock_upsert.call_args[0][0]
            assert len(rows) == 1
            row = rows[0]
            assert row["title"] == "Test Headline"
            assert row["source_url"] == "https://example.com/story"
            assert row["latitude"] == 35.7
            assert row["longitude"] == 51.4
            assert row["region"] == "Tehran, Tehran, Iran"
            assert row["image_url"] == "https://example.com/img.jpg"

    @pytest.mark.asyncio
    async def test_returns_zero_on_empty_gkg(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        with patch(
            "app.services.ingestion.fetch_raw_gkg",
            new_callable=AsyncMock,
            return_value=[],
        ):
            count = await _ingest_from_raw_gkg()
            assert count == 0

    @pytest.mark.asyncio
    async def test_normalizes_sentiment(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        articles[0]["tone"] = -7.5

        with patch(
            "app.services.ingestion.fetch_raw_gkg",
            new_callable=AsyncMock,
            return_value=articles,
        ), patch(
            "app.services.ingestion.scrape_titles",
            new_callable=AsyncMock,
            return_value=articles,
        ), patch(
            "app.services.ingestion.upsert_articles",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_upsert, patch(
            "app.services.ingestion.invalidate",
            new_callable=AsyncMock,
        ):
            await _ingest_from_raw_gkg()
            row = mock_upsert.call_args[0][0][0]
            assert row["sentiment_score"] == pytest.approx(-0.75)

    @pytest.mark.asyncio
    async def test_clamps_extreme_sentiment(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        articles[0]["tone"] = -15.0  # Beyond scale

        with patch(
            "app.services.ingestion.fetch_raw_gkg",
            new_callable=AsyncMock,
            return_value=articles,
        ), patch(
            "app.services.ingestion.scrape_titles",
            new_callable=AsyncMock,
            return_value=articles,
        ), patch(
            "app.services.ingestion.upsert_articles",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_upsert, patch(
            "app.services.ingestion.invalidate",
            new_callable=AsyncMock,
        ):
            await _ingest_from_raw_gkg()
            row = mock_upsert.call_args[0][0][0]
            assert row["sentiment_score"] == -1.0


class TestRunIngestionCycle:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        from app.services.ingestion import run_ingestion_cycle

        with patch(
            "app.services.ingestion._ingest_from_raw_gkg",
            new_callable=AsyncMock,
            return_value=50,
        ):
            count = await run_ingestion_cycle()
            assert count == 50

    @pytest.mark.asyncio
    async def test_exception_does_not_crash(self):
        from app.services.ingestion import run_ingestion_cycle

        with patch(
            "app.services.ingestion._ingest_from_raw_gkg",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            count = await run_ingestion_cycle()
            assert count == 0
