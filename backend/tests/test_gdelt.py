"""Tests for GDELT raw GKG file parsing and title scraping."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import io
import zipfile

from app.services.gdelt import (
    _parse_gkg_date,
    _title_from_url,
    fetch_raw_gkg,
    scrape_titles,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gkg_zip(records: list[str]) -> bytes:
    """Create a ZIP file containing a fake GKG TSV with the given records."""
    tsv_content = "\n".join(records)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.gkg.csv", tsv_content)
    return buf.getvalue()


def _make_gkg_record(
    url: str = "https://example.com/article-1",
    domain: str = "example.com",
    date: str = "20260305120000",
    locations: str = "4#Tehran, Tehran, Iran#IR#IR00#35.6944#51.4215#-3039671",
    themes: str = "TAX_FNCACT;GENERAL_GOVERNMENT",
    tone: str = "-2.5,1.0,3.5,0.5",
    image: str = "https://example.com/image.jpg",
) -> str:
    """Build a tab-delimited GKG record with city-level location.

    GKG 2.1 fields (tab-delimited, 0-indexed):
     0: GKGRECORDID, 1: DATE, 2: SOURCECOLLECTION, 3: DOMAIN,
     4: URL, 5: V1COUNTS, 6: V2.1COUNTS, 7: V1THEMES,
     8: V2ENHANCEDTHEMES, 9: V1LOCATIONS, 10: V2ENHANCEDLOCATIONS,
     11-14: PERSONS/ORGS, 15: V1.5TONE, 16: DATES, 17: GCAM,
     18: SHARINGIMAGE
    """
    fields = [""] * 19
    fields[0] = "20260305120000-T1"
    fields[1] = date
    fields[2] = "1"
    fields[3] = domain
    fields[4] = url
    fields[7] = themes
    fields[9] = locations
    fields[15] = tone
    fields[18] = image
    return "\t".join(fields)


# ---------------------------------------------------------------------------
# _parse_gkg_date
# ---------------------------------------------------------------------------


class TestParseGkgDate:
    def test_parses_standard_format(self):
        dt = _parse_gkg_date("20260305120000")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 5
        assert dt.hour == 12

    def test_returns_now_on_invalid(self):
        dt = _parse_gkg_date("garbage")
        assert dt.year >= 2026


# ---------------------------------------------------------------------------
# _title_from_url
# ---------------------------------------------------------------------------


class TestTitleFromUrl:
    def test_extracts_from_slug(self):
        title = _title_from_url("https://example.com/news/breaking-news-headline")
        assert "Breaking" in title
        assert "News" in title
        assert "Headline" in title

    def test_strips_html_extension(self):
        title = _title_from_url("https://example.com/story/big-event.html")
        assert "Big" in title
        assert ".html" not in title

    def test_falls_back_to_domain_for_short_paths(self):
        title = _title_from_url("https://example.com/123")
        assert "example.com" in title


# ---------------------------------------------------------------------------
# fetch_raw_gkg
# ---------------------------------------------------------------------------


class TestFetchRawGkg:
    @pytest.mark.asyncio
    async def test_parses_city_level_articles(self):
        record = _make_gkg_record()
        zip_bytes = _make_gkg_zip([record])

        index_text = (
            "100 abc123 http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"
        )

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 1
            assert articles[0]["url"] == "https://example.com/article-1"
            assert articles[0]["lat"] == pytest.approx(35.6944)
            assert articles[0]["lng"] == pytest.approx(51.4215)
            assert articles[0]["location_name"] == "Tehran, Tehran, Iran"
            assert articles[0]["domain"] == "example.com"
            assert articles[0]["image_url"] == "https://example.com/image.jpg"

    @pytest.mark.asyncio
    async def test_skips_country_level_locations(self):
        # Type 1 = COUNTRY (should be skipped)
        record = _make_gkg_record(
            locations="1#United States#US##37.09#-95.71#US"
        )
        zip_bytes = _make_gkg_zip([record])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 0

    @pytest.mark.asyncio
    async def test_deduplicates_by_url(self):
        record1 = _make_gkg_record(url="https://example.com/same")
        record2 = _make_gkg_record(url="https://example.com/same")
        zip_bytes = _make_gkg_zip([record1, record2])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert len(articles) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_download_failure(self):
        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            return_value=None,
        ):
            articles = await fetch_raw_gkg()
            assert articles == []

    @pytest.mark.asyncio
    async def test_parses_tone(self):
        record = _make_gkg_record(tone="-5.0,2.0,7.0,1.5")
        zip_bytes = _make_gkg_zip([record])
        index_text = "100 abc http://data.gdeltproject.org/gdeltv2/test.gkg.csv.zip"

        async def mock_download(url):
            if "lastupdate" in url:
                return index_text.encode()
            return zip_bytes

        with patch(
            "app.services.gdelt._download_bytes",
            new_callable=AsyncMock,
            side_effect=mock_download,
        ):
            articles = await fetch_raw_gkg()
            assert articles[0]["tone"] == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# scrape_titles
# ---------------------------------------------------------------------------


class TestScrapeTitles:
    @pytest.mark.asyncio
    async def test_scrapes_title_from_html(self):
        articles = [{"url": "https://example.com/story", "domain": "example.com"}]

        mock_resp = MagicMock()
        mock_resp.content = b"<html><head><title>Breaking News Story</title></head></html>"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
            assert result[0]["title"] == "Breaking News Story"

    @pytest.mark.asyncio
    async def test_falls_back_to_url_title_on_failure(self):
        articles = [{"url": "https://example.com/big-news-story", "domain": "example.com"}]

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
            assert "Big" in result[0]["title"]
            assert "News" in result[0]["title"]

    @pytest.mark.asyncio
    async def test_skips_cloudflare_titles(self):
        articles = [{"url": "https://example.com/real-article-here", "domain": "example.com"}]

        mock_resp = MagicMock()
        mock_resp.content = b"<html><title>Attention Required! | Cloudflare</title></html>"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scrape_titles(articles)
            # Should fall back to URL-derived title, not Cloudflare
            assert "cloudflare" not in result[0]["title"].lower()
