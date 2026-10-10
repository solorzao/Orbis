"""Tests for the raw GKG → PostgreSQL ingestion service."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings


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


def _common_patches(articles, ml_enabled=True):
    """Return a dict of common patches for _ingest_from_raw_gkg tests."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[_mock_db_row(a["url"]) for a in articles])

    titled = [a for a in articles if a.get("title")]

    patches = {
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
        "ml_enabled": patch.object(
            settings,
            "ml_classification_enabled",
            ml_enabled,
        ),
    }

    if ml_enabled:
        patches["classify_topics_ml"] = patch(
            "app.services.ingestion.classify_topics_ml",
            return_value=[["politics"]] * len(titled),
        )
        patches["analyze_sentiment_ml"] = patch(
            "app.services.ingestion.analyze_sentiment_ml",
            return_value=[0.5] * len(titled),
        )

    return patches


class TestIngestFromRawGkg:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        patches = _common_patches(articles)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"] as mock_invalidate,
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
            patches["classify_topics_ml"],
            patches["analyze_sentiment_ml"],
        ):
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
    async def test_carries_country_fips_through(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [
            _make_gkg_article(url="https://example.com/a", title="Story in London"),
            _make_gkg_article(url="https://example.com/b", title="Story without a country"),
        ]
        articles[0].update(country_code="GB", country_fips="UK")
        articles[1].update(country_code="", country_fips=None)
        patches = _common_patches(articles, ml_enabled=False)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
        ):
            await _ingest_from_raw_gkg()

        rows = mock_upsert.call_args[0][0]
        assert (rows[0]["country_code"], rows[0]["country_fips"]) == ("GB", "UK")
        # '' rather than NULL: NULL means "written before the FIPS to ISO switch".
        assert (rows[1]["country_code"], rows[1]["country_fips"]) == ("", "")

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
        patches = _common_patches(articles, ml_enabled=False)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
        ):
            await _ingest_from_raw_gkg()
            row = mock_upsert.call_args[0][0][0]
            assert row["sentiment_score"] == pytest.approx(-0.75)

    @pytest.mark.asyncio
    async def test_clamps_extreme_sentiment(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        articles[0]["tone"] = -15.0  # Beyond scale
        patches = _common_patches(articles, ml_enabled=False)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
        ):
            await _ingest_from_raw_gkg()
            row = mock_upsert.call_args[0][0][0]
            assert row["sentiment_score"] == -1.0


class TestRunIngestionCycle:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        from app.services.ingestion import run_ingestion_cycle

        with (
            patch(
                "app.services.ingestion._backfill_iso_country_codes",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.services.ingestion._ingest_from_raw_gkg",
                new_callable=AsyncMock,
                return_value=50,
            ),
            patch(
                "app.services.ingestion._purge_old_articles",
                new_callable=AsyncMock,
            ),
        ):
            count = await run_ingestion_cycle()
            assert count == 50

    @pytest.mark.asyncio
    async def test_exception_does_not_crash(self):
        from app.services.ingestion import run_ingestion_cycle

        with (
            patch(
                "app.services.ingestion._backfill_iso_country_codes",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.services.ingestion._ingest_from_raw_gkg",
                new_callable=AsyncMock,
                side_effect=Exception("boom"),
            ),
        ):
            count = await run_ingestion_cycle()
            assert count == 0

    @pytest.mark.asyncio
    async def test_backfill_runs_first(self):
        from app.services.ingestion import run_ingestion_cycle

        calls: list[str] = []

        def _record(name, result=None):
            async def _step(*_args):
                calls.append(name)
                return result

            return _step

        with (
            patch("app.services.ingestion.get_pool", new_callable=AsyncMock),
            patch(
                "app.services.ingestion._backfill_iso_country_codes",
                side_effect=_record("backfill", 0),
            ),
            patch(
                "app.services.ingestion._ingest_from_raw_gkg",
                side_effect=_record("ingest", 5),
            ),
            patch(
                "app.services.ingestion._purge_old_articles",
                side_effect=_record("purge"),
            ),
            patch(
                "app.services.ingestion.generate_embeddings",
                side_effect=_record("embed", 0),
            ),
        ):
            assert await run_ingestion_cycle() == 5

        assert calls == ["backfill", "ingest", "purge", "embed"]

    @pytest.mark.asyncio
    async def test_backfill_failure_does_not_stop_cycle(self):
        from app.services.ingestion import run_ingestion_cycle

        with (
            patch("app.services.ingestion.get_pool", new_callable=AsyncMock),
            patch(
                "app.services.ingestion._backfill_iso_country_codes",
                new_callable=AsyncMock,
                side_effect=Exception("backfill boom"),
            ),
            patch(
                "app.services.ingestion._ingest_from_raw_gkg",
                new_callable=AsyncMock,
                return_value=7,
            ) as mock_ingest,
            patch(
                "app.services.ingestion._purge_old_articles",
                new_callable=AsyncMock,
            ) as mock_purge,
            patch(
                "app.services.ingestion.generate_embeddings",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_embed,
        ):
            count = await run_ingestion_cycle()

        assert count == 7
        mock_ingest.assert_awaited_once()
        mock_purge.assert_awaited_once()
        mock_embed.assert_awaited_once()


class _FakeArticlesPool:
    """In-memory stand-in for the two queries the backfill issues.

    ``rows`` are dicts with ``country_code`` and ``country_fips``. The UPDATE
    matches with Python ``==``, which treats None like SQL IS NOT DISTINCT FROM.
    """

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.updates: list[tuple] = []

    async def fetch(self, query, *args):
        assert "country_fips IS NULL" in query
        codes = {r["country_code"] for r in self.rows if r["country_fips"] is None}
        return [{"country_code": c} for c in sorted(codes, key=lambda c: c or "")]

    async def execute(self, query, fips, iso, original):
        assert "IS NOT DISTINCT FROM $3" in query
        self.updates.append((fips, iso, original))
        n = 0
        for r in self.rows:
            if r["country_fips"] is None and r["country_code"] == original:
                r["country_fips"], r["country_code"] = fips, iso
                n += 1
        return f"UPDATE {n}"


class TestBackfillIsoCountryCodes:
    @pytest.mark.asyncio
    async def test_converts_pre_switch_fips_rows(self):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [
            {"country_code": "UK", "country_fips": None},
            {"country_code": "UK", "country_fips": None},
            {"country_code": "CH", "country_fips": None},
            {"country_code": "ZZ", "country_fips": None},  # unknown FIPS
            {"country_code": "GB", "country_fips": "UK"},  # already converted
        ]
        pool = _FakeArticlesPool(rows)

        assert await _backfill_iso_country_codes(pool) == 4

        assert rows == [
            {"country_code": "GB", "country_fips": "UK"},
            {"country_code": "GB", "country_fips": "UK"},
            {"country_code": "CN", "country_fips": "CH"},
            {"country_code": "", "country_fips": "ZZ"},
            {"country_code": "GB", "country_fips": "UK"},
        ]

    @pytest.mark.asyncio
    async def test_converts_rows_with_null_country_code(self):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [{"country_code": None, "country_fips": None}]
        pool = _FakeArticlesPool(rows)

        assert await _backfill_iso_country_codes(pool) == 1

        # Matched on the original NULL, and marked converted with ''.
        assert pool.updates == [("", "", None)]
        assert rows == [{"country_code": "", "country_fips": ""}]

    @pytest.mark.asyncio
    async def test_is_idempotent(self):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [
            {"country_code": "SP", "country_fips": None},
            {"country_code": None, "country_fips": None},
        ]
        pool = _FakeArticlesPool(rows)

        assert await _backfill_iso_country_codes(pool) == 2
        pool.updates.clear()

        assert await _backfill_iso_country_codes(pool) == 0
        assert pool.updates == []
        assert rows == [
            {"country_code": "ES", "country_fips": "SP"},
            {"country_code": "", "country_fips": ""},
        ]


class TestMLClassificationIntegration:
    """Verify that ML classification is wired into the ingestion pipeline."""

    @pytest.mark.asyncio
    async def test_ml_classification_called_when_enabled(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        patches = _common_patches(articles, ml_enabled=True)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
            patches["classify_topics_ml"] as mock_topics,
            patches["analyze_sentiment_ml"] as mock_sent,
        ):
            await _ingest_from_raw_gkg()

            mock_topics.assert_called_once_with(["Test Headline"])
            mock_sent.assert_called_once_with(["Test Headline"])

            row = mock_upsert.call_args[0][0][0]
            assert row["topic_tags"] == ["politics"]
            assert row["sentiment_score"] == 0.5

    @pytest.mark.asyncio
    async def test_fallback_when_ml_disabled(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article()]
        articles[0]["tone"] = 5.0
        patches = _common_patches(articles, ml_enabled=False)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
        ):
            await _ingest_from_raw_gkg()

            row = mock_upsert.call_args[0][0][0]
            # Fallback uses GDELT tone normalization
            assert row["sentiment_score"] == pytest.approx(0.5)
            # Fallback uses keyword classifier (returns a list of tags)
            assert isinstance(row["topic_tags"], list)

    @pytest.mark.asyncio
    async def test_ml_results_applied_to_multiple_articles(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [
            _make_gkg_article(url="https://example.com/a", title="War breaks out"),
            _make_gkg_article(url="https://example.com/b", title="Stock market soars"),
        ]
        patches = _common_patches(articles, ml_enabled=True)
        # Override ML mocks with specific per-article results
        patches["classify_topics_ml"] = patch(
            "app.services.ingestion.classify_topics_ml",
            return_value=[["conflict"], ["economy"]],
        )
        patches["analyze_sentiment_ml"] = patch(
            "app.services.ingestion.analyze_sentiment_ml",
            return_value=[-0.8, 0.7],
        )

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
            patches["classify_topics_ml"],
            patches["analyze_sentiment_ml"],
        ):
            await _ingest_from_raw_gkg()

            rows = mock_upsert.call_args[0][0]
            assert len(rows) == 2
            assert rows[0]["topic_tags"] == ["conflict"]
            assert rows[0]["sentiment_score"] == -0.8
            assert rows[1]["topic_tags"] == ["economy"]
            assert rows[1]["sentiment_score"] == 0.7
