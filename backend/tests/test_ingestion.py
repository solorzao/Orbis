"""Tests for the raw GKG → PostgreSQL ingestion service."""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings


def _make_gkg_article(url="https://example.com/story", title="Test Headline"):
    """Build a dict as fetch_raw_gkg would return; *title* is GDELT's page title."""
    return {
        "url": url,
        "domain": "example.com",
        "lat": 35.7,
        "lng": 51.4,
        "location_name": "Tehran, Tehran, Iran",
        "country_code": "IR",
        "tone": -2.5,
        "page_title": title,
        "themes": ["GENERAL_GOVERNMENT"],
        "persons": [],
        "organizations": [],
        "names": [],
        "counts": [],
        "mentioned_locations": [],
        "image_url": "https://example.com/img.jpg",
        "published_at": datetime(2026, 3, 5, tzinfo=timezone.utc),
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

    titled = [a for a in articles if a.get("page_title")]

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
            patches["get_pool"] as mock_get_pool,
            patches["populate_graph"],
            patches["ml_enabled"],
        ):
            await _ingest_from_raw_gkg()

        # The KG read-back includes country_fips for LOCATION node metadata.
        kg_query = mock_get_pool.return_value.fetch.call_args[0][0]
        assert "country_code, country_fips," in kg_query
        rows = mock_upsert.call_args[0][0]
        assert (rows[0]["country_code"], rows[0]["country_fips"]) == ("GB", "UK")
        # '' rather than NULL when GKG has no country.
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


async def _scrape_only_urls_ending_scraped(batch):
    """Stand-in for scrape_titles: titles the URLs ending in /scraped, fails the rest."""
    for a in batch:
        if a["url"].endswith("/scraped"):
            a["title"] = "Scraped headline from the page"
    return batch


class TestTitlesAndGkgFields:
    """Titles come from GDELT's PAGE_TITLE first; GKG fields land on the row."""

    @pytest.mark.asyncio
    async def test_gdelt_titles_are_used_without_scraping(self, caplog):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [_make_gkg_article(title="Ceasefire talks resume in Cairo")]
        patches = _common_patches(articles, ml_enabled=False)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"] as mock_scrape,
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
            caplog.at_level(logging.INFO, logger="orbis.ingestion"),
        ):
            await _ingest_from_raw_gkg()

        mock_scrape.assert_not_awaited()
        assert mock_upsert.call_args[0][0][0]["title"] == "Ceasefire talks resume in Cairo"
        assert "Titles: 1 from GDELT, 0 scraped, 0 dropped." in caplog.text

    @pytest.mark.asyncio
    async def test_only_records_without_a_gdelt_title_are_scraped(self, caplog):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [
            _make_gkg_article(url="https://example.com/gdelt", title="Headline from GDELT"),
            _make_gkg_article(url="https://example.com/scraped", title=""),
            _make_gkg_article(url="https://example.com/failed", title=""),
        ]
        patches = _common_patches(articles, ml_enabled=False)
        patches["scrape_titles"] = patch(
            "app.services.ingestion.scrape_titles",
            new_callable=AsyncMock,
            side_effect=_scrape_only_urls_ending_scraped,
        )

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"] as mock_scrape,
            patches["upsert_articles"] as mock_upsert,
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"],
            patches["ml_enabled"],
            caplog.at_level(logging.INFO, logger="orbis.ingestion"),
        ):
            await _ingest_from_raw_gkg()

        scraped_urls = [a["url"] for a in mock_scrape.await_args.args[0]]
        assert scraped_urls == ["https://example.com/scraped", "https://example.com/failed"]
        rows = mock_upsert.call_args[0][0]
        assert [(r["source_url"], r["title"]) for r in rows] == [
            ("https://example.com/gdelt", "Headline from GDELT"),
            ("https://example.com/scraped", "Scraped headline from the page"),
        ]
        assert "Titles: 1 from GDELT, 1 scraped, 1 dropped." in caplog.text

    @pytest.mark.asyncio
    async def test_rows_carry_the_gkg_fields(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        tone_detail = {"tone": -3.2, "pos": 1.5, "neg": 4.7, "polarity": 6.2, "words": 512}
        counts = [{"type": "KILL", "n": 4, "object": "", "country": "ZA", "place": "Beitbridge"}]
        articles = [_make_gkg_article()]
        articles[0].update(
            themes=["KILL", "TERROR"],
            persons=["Benjamin Netanyahu"],
            organizations=["United Nations"],
            names=["Gaza Strip", "Yellow Line"],
            counts=counts,
            tone_detail=tone_detail,
            mentioned_countries=["IR", "US"],
        )
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
        assert row["themes"] == ["KILL", "TERROR"]
        assert row["persons"] == ["Benjamin Netanyahu"]
        assert row["orgs"] == ["United Nations"]
        assert row["names"] == ["Gaza Strip", "Yellow Line"]
        assert row["counts"] == counts
        assert row["mentioned_countries"] == ["IR", "US"]
        assert row["entities"] == {"tone": tone_detail}

    @pytest.mark.asyncio
    async def test_entities_empty_and_fields_default_when_absent(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [{"url": "https://example.com/bare", "page_title": "A bare GKG record"}]
        articles[0].update(lat=1.0, lng=2.0, published_at=datetime(2026, 3, 5, tzinfo=timezone.utc))
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
        assert row["entities"] == {}
        fields = ("themes", "persons", "orgs", "names", "counts", "mentioned_countries")
        assert [row[k] for k in fields] == [[]] * 6

    @pytest.mark.asyncio
    async def test_knowledge_graph_still_gets_people_orgs_and_locations(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        mentioned = [{"name": "Israel", "country_code": "IL", "country_fips": "IS"}]
        articles = [_make_gkg_article()]
        articles[0].update(
            persons=["Benjamin Netanyahu"],
            organizations=["United Nations"],
            mentioned_locations=mentioned,
        )
        patches = _common_patches(articles, ml_enabled=False)

        with (
            patches["fetch_raw_gkg"],
            patches["scrape_titles"],
            patches["upsert_articles"],
            patches["invalidate"],
            patches["get_pool"],
            patches["populate_graph"] as mock_graph,
            patches["ml_enabled"],
        ):
            await _ingest_from_raw_gkg()

        [graph_article] = mock_graph.await_args.args[0]
        assert graph_article["persons"] == ["Benjamin Netanyahu"]
        assert graph_article["organizations"] == ["United Nations"]
        assert graph_article["mentioned_locations"] == mentioned


class TestRunIngestionCycle:
    @pytest.fixture(autouse=True)
    def warm(self):
        """The cache warm the cycle starts, recording whether the lock was held."""
        from app.services import ingestion

        calls: list[bool] = []
        with patch(
            "app.services.ingestion._start_cache_warm",
            side_effect=lambda: calls.append(ingestion._ingestion_lock.locked()),
        ):
            yield calls

    @pytest.mark.asyncio
    async def test_warms_caches_once_the_lock_is_released(self, warm):
        from app.services.ingestion import run_ingestion_cycle

        with (
            patch("app.services.ingestion.get_pool", new_callable=AsyncMock),
            patch(
                "app.services.ingestion._ingest_from_raw_gkg",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch("app.services.ingestion._purge_old_articles", new_callable=AsyncMock),
            patch("app.services.ingestion.generate_embeddings", new_callable=AsyncMock),
        ):
            assert await run_ingestion_cycle() == 5

        assert warm == [False]  # started once, after the lock was released

    @pytest.mark.asyncio
    async def test_a_failed_cycle_still_warms(self, warm):
        """Ingestion may have invalidated the caches before it failed."""
        from app.services.ingestion import run_ingestion_cycle

        with (
            patch(
                "app.services.ingestion._ingest_from_raw_gkg",
                new_callable=AsyncMock,
                side_effect=Exception("boom"),
            ),
        ):
            assert await run_ingestion_cycle() == 0

        assert warm == [False]

    @pytest.mark.asyncio
    async def test_a_skipped_cycle_does_not_warm(self, warm):
        from app.services import ingestion

        async with ingestion._ingestion_lock:
            assert await ingestion.run_ingestion_cycle() == 0
        assert warm == []

    @pytest.mark.asyncio
    async def test_happy_path(self):
        from app.services.ingestion import run_ingestion_cycle

        with (
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
                "app.services.ingestion._ingest_from_raw_gkg",
                new_callable=AsyncMock,
                side_effect=Exception("boom"),
            ),
        ):
            count = await run_ingestion_cycle()
            assert count == 0

    @pytest.mark.asyncio
    async def test_skips_when_a_cycle_is_already_running(self, caplog, monkeypatch):
        from app.services import ingestion

        monkeypatch.setattr(ingestion, "_cycle_started_at", time.monotonic() - 42)
        with patch(
            "app.services.ingestion._ingest_from_raw_gkg",
            new_callable=AsyncMock,
            return_value=5,
        ) as mock_ingest:
            async with ingestion._ingestion_lock:
                with caplog.at_level(logging.WARNING, logger="orbis.ingestion"):
                    assert await ingestion.run_ingestion_cycle() == 0

        mock_ingest.assert_not_awaited()
        [record] = [r for r in caplog.records if "already running" in r.getMessage()]
        assert record.levelno == logging.WARNING
        assert "running for 42s" in record.getMessage()
        assert not ingestion._ingestion_lock.locked()

    @pytest.mark.asyncio
    async def test_records_when_the_running_cycle_started(self, monkeypatch):
        from app.services import ingestion

        monkeypatch.setattr(ingestion, "_cycle_started_at", None)
        with (
            patch("app.services.ingestion.get_pool", new_callable=AsyncMock),
            patch("app.services.ingestion._ingest_from_raw_gkg", new_callable=AsyncMock),
            patch("app.services.ingestion._purge_old_articles", new_callable=AsyncMock),
            patch("app.services.ingestion.generate_embeddings", new_callable=AsyncMock),
        ):
            before = time.monotonic()
            await ingestion.run_ingestion_cycle()

        assert before <= ingestion._cycle_started_at <= time.monotonic()

    @pytest.mark.asyncio
    async def test_steps_run_in_order(self):
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

        assert calls == ["ingest", "purge", "embed"]


class TestStartCacheWarm:
    @pytest.mark.asyncio
    async def test_runs_the_warmers_in_the_background(self):
        from app.services import ingestion

        with patch("app.warm.warm_caches", new_callable=AsyncMock) as warm_caches:
            ingestion._start_cache_warm()
            assert ingestion._background_tasks  # held until done
            await asyncio.gather(*ingestion._background_tasks)

        warm_caches.assert_awaited_once_with()
        assert not ingestion._background_tasks

    @pytest.mark.asyncio
    async def test_a_failure_is_a_warning(self, caplog):
        from app.services import ingestion

        with (
            patch("app.warm.warm_caches", new_callable=AsyncMock, side_effect=RuntimeError("x")),
            caplog.at_level(logging.WARNING, logger="orbis.ingestion"),
        ):
            ingestion._start_cache_warm()
            await asyncio.gather(*ingestion._background_tasks)  # does not raise

        assert "Cache warm failed; continuing." in caplog.text

    @staticmethod
    def _slow_warm():
        """A warm that runs until cancelled, and an event set once it has started."""
        started = asyncio.Event()

        async def warm_caches():
            started.set()
            await asyncio.sleep(60)

        return warm_caches, started

    @pytest.mark.asyncio
    async def test_stop_background_tasks_cancels_a_running_warm(self):
        """At shutdown: a warm must not reopen the pool or Redis after they close."""
        from app.services import ingestion

        warm_caches, started = self._slow_warm()
        with patch("app.warm.warm_caches", new=warm_caches):
            ingestion._start_cache_warm()
            [task] = ingestion._background_tasks
            await started.wait()
            await ingestion.stop_background_tasks()

        assert task.cancelled()
        assert not ingestion._background_tasks

    @pytest.mark.asyncio
    async def test_a_new_cycle_cancels_the_warm_still_running(self):
        """Its answers are about to be invalidated: it must not write them back after."""
        from app.services import ingestion

        warm_caches, started = self._slow_warm()
        running_at_ingest: list[bool] = []

        async def ingest():
            running_at_ingest.append(not old_warm.done())
            return 3

        with (
            patch("app.warm.warm_caches", new=warm_caches),
            patch("app.services.ingestion.get_pool", new_callable=AsyncMock),
            patch("app.services.ingestion._ingest_from_raw_gkg", side_effect=ingest),
            patch("app.services.ingestion._purge_old_articles", new_callable=AsyncMock),
            patch("app.services.ingestion.generate_embeddings", new_callable=AsyncMock),
        ):
            ingestion._start_cache_warm()
            [old_warm] = ingestion._background_tasks
            await started.wait()
            assert await ingestion.run_ingestion_cycle() == 3
            await ingestion.stop_background_tasks()  # the new cycle's warm

        assert running_at_ingest == [False]
        assert old_warm.cancelled()


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
