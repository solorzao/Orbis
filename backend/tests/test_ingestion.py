"""Tests for the raw GKG → PostgreSQL ingestion service."""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
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
        assert [row[k] for k in ("themes", "persons", "orgs", "names", "counts")] == [[]] * 5

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
            patch("app.services.ingestion._backfill_iso_country_codes", new_callable=AsyncMock),
            patch("app.services.ingestion.get_pool", new_callable=AsyncMock),
            patch("app.services.ingestion._ingest_from_raw_gkg", new_callable=AsyncMock),
            patch("app.services.ingestion._purge_old_articles", new_callable=AsyncMock),
            patch("app.services.ingestion.generate_embeddings", new_callable=AsyncMock),
        ):
            before = time.monotonic()
            await ingestion.run_ingestion_cycle()

        assert before <= ingestion._cycle_started_at <= time.monotonic()

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
    """In-memory stand-in for the queries the backfill issues.

    ``rows`` are dicts with ``id``, ``published_at``, ``country_code`` and
    ``country_fips``. Each UPDATE is recorded in ``updates`` as
    ``(fips, iso, sorted ids)``; codes in ``fail_codes`` raise instead.
    """

    def __init__(
        self,
        rows: list[dict],
        fail_codes: frozenset[str] = frozenset(),
        after_fetch=None,
    ):
        self.rows = rows
        self.fail_codes = fail_codes
        self.after_fetch = after_fetch  # called once the SELECT has returned
        self.fetches = 0
        self.updates: list[tuple] = []

    async def fetch(self, query, budget):
        assert "WHERE country_fips IS NULL ORDER BY published_at DESC LIMIT $1" in query
        self.fetches += 1
        pending = [r for r in self.rows if r["country_fips"] is None]
        pending.sort(key=lambda r: r["published_at"], reverse=True)
        result = [{"id": r["id"], "country_code": r["country_code"]} for r in pending[:budget]]
        if self.after_fetch:
            self.after_fetch(self.rows)
        return result

    async def execute(self, query, fips, iso, ids):
        assert (
            "WHERE id = ANY($3::uuid[]) AND country_fips IS NULL "
            "AND coalesce(country_code, '') = $1"
        ) in query
        if fips in self.fail_codes:
            raise RuntimeError(f"update failed for {fips}")
        self.updates.append((fips, iso, sorted(ids)))
        n = 0
        for r in self.rows:
            if r["id"] in ids and r["country_fips"] is None and (r["country_code"] or "") == fips:
                r["country_fips"], r["country_code"] = fips, iso
                n += 1
        return f"UPDATE {n}"


def _row(row_id, country_code, country_fips=None, hours_ago=0):
    """An articles row; country_fips None means written before the ISO switch."""
    return {
        "id": row_id,
        "published_at": datetime(2026, 10, 10, tzinfo=timezone.utc) - timedelta(hours=hours_ago),
        "country_code": country_code,
        "country_fips": country_fips,
    }


def _codes(rows):
    return [(r["country_code"], r["country_fips"]) for r in rows]


class TestBackfillIsoCountryCodes:
    @pytest.fixture(autouse=True)
    def _reset_backfill_state(self, monkeypatch):
        from app.services import ingestion

        monkeypatch.setattr(ingestion, "_backfill_idle_runs", 0)
        self.invalidate = AsyncMock()
        monkeypatch.setattr(ingestion, "invalidate", self.invalidate)

    @pytest.mark.asyncio
    async def test_converts_pre_switch_rows_grouped_by_code(self):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [
            _row("uk-1", "UK"),
            _row("uk-2", "UK"),
            _row("ch-1", "CH"),
            _row("zz-1", "ZZ"),  # unknown FIPS
            _row("gb-1", "GB", country_fips="UK"),  # already converted
        ]
        pool = _FakeArticlesPool(rows)

        assert await _backfill_iso_country_codes(pool) == 4

        assert sorted(pool.updates) == [
            ("CH", "CN", ["ch-1"]),
            ("UK", "GB", ["uk-1", "uk-2"]),
            ("ZZ", "", ["zz-1"]),
        ]
        assert _codes(rows) == [("GB", "UK"), ("GB", "UK"), ("CN", "CH"), ("", "ZZ"), ("GB", "UK")]
        self.invalidate.assert_awaited_once_with("db:*")

    @pytest.mark.asyncio
    async def test_null_and_empty_codes_share_one_update(self):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [_row("n-1", None), _row("n-2", None), _row("e-1", "")]
        pool = _FakeArticlesPool(rows)

        assert await _backfill_iso_country_codes(pool) == 3

        assert pool.updates == [("", "", ["e-1", "n-1", "n-2"])]
        assert _codes(rows) == [("", "")] * 3

    @pytest.mark.asyncio
    async def test_converts_newest_rows_first_within_budget(self):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [
            _row("old", "UK", hours_ago=48),
            _row("new", "UK", hours_ago=1),
            _row("mid", "SP", hours_ago=5),
        ]
        pool = _FakeArticlesPool(rows)

        assert await _backfill_iso_country_codes(pool, budget=2) == 2
        assert [r["id"] for r in rows if r["country_fips"] is None] == ["old"]

        assert await _backfill_iso_country_codes(pool, budget=2) == 1
        assert _codes(rows) == [("GB", "UK"), ("GB", "UK"), ("ES", "SP")]

    @pytest.mark.asyncio
    async def test_skips_rows_whose_code_changed_after_the_select(self):
        from app.services.ingestion import _backfill_iso_country_codes

        def old_revision_rewrites_uk_2(rows):
            rows[1]["country_code"] = "FR"  # still pre-switch: country_fips stays NULL

        rows = [_row("uk-1", "UK"), _row("uk-2", "UK")]
        pool = _FakeArticlesPool(rows, after_fetch=old_revision_rewrites_uk_2)

        assert await _backfill_iso_country_codes(pool) == 1
        # Not converted from the stale "UK"; picked up with its new code next run.
        assert _codes(rows) == [("GB", "UK"), ("FR", None)]

        pool.after_fetch = None
        assert await _backfill_iso_country_codes(pool) == 1
        assert _codes(rows) == [("GB", "UK"), ("FR", "FR")]

    @pytest.mark.asyncio
    async def test_failed_group_does_not_stop_the_others(self, caplog):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [_row("uk-1", "UK"), _row("ch-1", "CH")]
        pool = _FakeArticlesPool(rows, fail_codes=frozenset({"UK"}))

        with caplog.at_level(logging.WARNING, logger="orbis.ingestion"):
            assert await _backfill_iso_country_codes(pool) == 1

        assert _codes(rows) == [("UK", None), ("CN", "CH")]
        assert "'UK'" in caplog.text
        self.invalidate.assert_awaited_once_with("db:*")

    @pytest.mark.asyncio
    async def test_no_cache_invalidation_when_nothing_converted(self):
        from app.services.ingestion import _backfill_iso_country_codes

        pool = _FakeArticlesPool([_row("gb-1", "GB", country_fips="UK")])

        assert await _backfill_iso_country_codes(pool) == 0
        assert pool.updates == []
        self.invalidate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_switches_off_after_two_consecutive_empty_runs(self):
        from app.services.ingestion import _backfill_iso_country_codes

        rows = [_row("sp-1", "SP")]
        pool = _FakeArticlesPool(rows)

        assert await _backfill_iso_country_codes(pool) == 1
        assert await _backfill_iso_country_codes(pool) == 0  # first empty run
        # An old revision inserts a pre-switch row during the deploy overlap.
        rows.append(_row("uk-1", "UK"))
        assert await _backfill_iso_country_codes(pool) == 1  # converted; idle count resets
        assert await _backfill_iso_country_codes(pool) == 0  # first empty run
        assert await _backfill_iso_country_codes(pool) == 0  # second: switched off
        rows.append(_row("ch-1", "CH"))
        assert await _backfill_iso_country_codes(pool) == 0  # skipped, no query

        assert pool.fetches == 5
        assert len(pool.updates) == 2  # idempotent: empty runs issue no UPDATEs
        assert _codes(rows) == [("ES", "SP"), ("GB", "UK"), ("CH", None)]


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
