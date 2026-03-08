"""Tests for the raw GKG → PostgreSQL ingestion service."""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


def _mock_db_row(source_url="https://example.com/story"):
    """Build a fake asyncpg Record-like dict for pool.fetch results."""
    return {
        "id": uuid.uuid4(),
        "title": "Test Headline",
        "source_url": source_url,
        "latitude": 35.7,
        "longitude": 51.4,
        "region": "Tehran, Tehran, Iran",
        "country_code": "IR",
        "topic_tags": ["politics"],
        "published_at": datetime(2026, 3, 5, tzinfo=timezone.utc),
    }


def _common_patches(articles):
    """Return a dict of common patches for _ingest_from_raw_gkg tests."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[_mock_db_row(a["url"]) for a in articles])

    return {
        "fetch_raw_gkg": patch(
            "app.services.ingestion.fetch_raw_gkg",
            new_callable=AsyncMock,
            return_value=articles,
        ),
        "scrape_titles": patch(
            "app.services.ingestion.scrape_titles",
            new_callable=AsyncMock,
            return_value=articles,
        ),
        "upsert_articles": patch(
            "app.services.ingestion.upsert_articles",
            new_callable=AsyncMock,
            return_value=len(articles),
        ),
        "invalidate": patch(
            "app.services.ingestion.invalidate",
            new_callable=AsyncMock,
        ),
        "get_pool": patch(
            "app.services.ingestion.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
        "populate_graph": patch(
            "app.services.ingestion.populate_graph",
            new_callable=AsyncMock,
            return_value=0,
        ),
    }


class TestIngestFromRawGkg:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        patches = _common_patches(articles)

        with patches["fetch_raw_gkg"], patches["scrape_titles"], \
             patches["upsert_articles"] as mock_upsert, \
             patches["invalidate"] as mock_invalidate, \
             patches["get_pool"], patches["populate_graph"]:
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
        patches = _common_patches(articles)

        with patches["fetch_raw_gkg"], patches["scrape_titles"], \
             patches["upsert_articles"] as mock_upsert, \
             patches["invalidate"], patches["get_pool"], \
             patches["populate_graph"]:
            await _ingest_from_raw_gkg()
            row = mock_upsert.call_args[0][0][0]
            assert row["sentiment_score"] == pytest.approx(-0.75)

    @pytest.mark.asyncio
    async def test_clamps_extreme_sentiment(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        articles[0]["tone"] = -15.0  # Beyond scale
        patches = _common_patches(articles)

        with patches["fetch_raw_gkg"], patches["scrape_titles"], \
             patches["upsert_articles"] as mock_upsert, \
             patches["invalidate"], patches["get_pool"], \
             patches["populate_graph"]:
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
        ), patch(
            "app.services.ingestion._purge_old_articles",
            new_callable=AsyncMock,
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
