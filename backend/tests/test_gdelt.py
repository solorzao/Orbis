"""Tests for GDELT response parsing with centroid and topic enrichment."""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.gdelt import _parse_doc_response, fetch_articles


def _make_raw_article(**overrides):
    """Helper to build a raw GDELT article dict."""
    base = {
        "title": "Test article headline",
        "url": "https://example.com/article-1",
        "domain": "example.com",
        "language": "English",
        "seendate": "20260228T120000Z",
        "tone": "-1.5,2.0",
        "sourcecountry": "United States",
    }
    base.update(overrides)
    return base


class TestParseDocResponse:
    def test_parses_basic_article(self):
        data = {"articles": [_make_raw_article()]}
        articles = _parse_doc_response(data)
        assert len(articles) == 1
        assert articles[0].title == "Test article headline"
        assert articles[0].source_name == "example.com"

    def test_assigns_centroid_from_full_country_name(self):
        """GDELT sends full names like 'United States', not ISO codes."""
        data = {"articles": [_make_raw_article(sourcecountry="United States")]}
        articles = _parse_doc_response(data)
        assert len(articles) == 1
        assert 30.0 < articles[0].latitude < 50.0
        assert -130.0 < articles[0].longitude < -70.0

    def test_assigns_centroid_from_iso_code(self):
        data = {"articles": [_make_raw_article(sourcecountry="US")]}
        articles = _parse_doc_response(data)
        assert 30.0 < articles[0].latitude < 50.0

    def test_normalizes_country_code(self):
        """Full country names are normalized to ISO codes."""
        data = {"articles": [_make_raw_article(sourcecountry="United Kingdom")]}
        articles = _parse_doc_response(data)
        assert articles[0].country_code == "GB"

    def test_unknown_country_gets_zero_coords(self):
        data = {"articles": [_make_raw_article(sourcecountry="ZZ")]}
        articles = _parse_doc_response(data)
        assert articles[0].latitude == 0.0
        assert articles[0].longitude == 0.0

    def test_classifies_topics_from_title(self):
        data = {"articles": [_make_raw_article(
            title="President signs military spending bill"
        )]}
        articles = _parse_doc_response(data)
        assert "politics" in articles[0].topic_tags
        assert "conflict" in articles[0].topic_tags

    def test_general_topic_when_no_keywords(self):
        data = {"articles": [_make_raw_article(
            title="Local festival draws crowds"
        )]}
        articles = _parse_doc_response(data)
        assert articles[0].topic_tags == ["general"]

    def test_skips_articles_without_title(self):
        data = {"articles": [_make_raw_article(title="")]}
        articles = _parse_doc_response(data)
        assert len(articles) == 0

    def test_handles_none_input(self):
        assert _parse_doc_response(None) == []

    def test_handles_empty_articles_list(self):
        assert _parse_doc_response({"articles": []}) == []

    def test_parses_tone_string(self):
        data = {"articles": [_make_raw_article(tone="-3.5,1.2,4.0")]}
        articles = _parse_doc_response(data)
        assert articles[0].sentiment_score == -3.5

    def test_handles_multiple_articles_different_countries(self):
        data = {"articles": [
            _make_raw_article(title="News from France", sourcecountry="France", url="https://a.com/1"),
            _make_raw_article(title="News from Japan", sourcecountry="Japan", url="https://a.com/2"),
        ]}
        articles = _parse_doc_response(data)
        assert len(articles) == 2
        assert 40.0 < articles[0].latitude < 50.0
        assert 30.0 < articles[1].latitude < 40.0


class TestFetchArticles:
    @pytest.mark.asyncio
    async def test_default_query_is_sourcelang_english(self):
        """Ensure the default query uses sourcelang:english, not '*'."""
        mock_data = {"articles": [_make_raw_article(sourcecountry="US")]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = mock_data
            articles = await fetch_articles()
            call_args = mock_fetch.call_args
            params = call_args[0][1]
            assert params["query"] == "sourcelang:english"

    @pytest.mark.asyncio
    async def test_drops_articles_without_coords(self):
        """Articles from unknown countries (no centroid) are dropped."""
        mock_data = {"articles": [
            _make_raw_article(sourcecountry="United States", url="https://a.com/1"),
            _make_raw_article(sourcecountry="ZZ", url="https://a.com/2"),
        ]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = mock_data
            articles = await fetch_articles()
            assert len(articles) == 1
            assert articles[0].country_code == "US"

    @pytest.mark.asyncio
    async def test_no_geo_api_call(self):
        """Ensure only one API call is made (DOC only, no GEO)."""
        mock_data = {"articles": [_make_raw_article(sourcecountry="US")]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = mock_data
            await fetch_articles()
            assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_cached_results(self):
        """When cache has data, return it without calling GDELT."""
        cached = [{
            "id": "abc123",
            "title": "Cached article",
            "source_url": "https://example.com/cached",
            "source_name": "example.com",
            "source_language": "en",
            "published_at": "2026-02-28T12:00:00Z",
            "ingested_at": "2026-02-28T12:00:00Z",
            "latitude": 37.09,
            "longitude": -95.71,
            "country_code": "US",
            "region": "",
            "topic_tags": ["general"],
            "sentiment_score": 0.0,
            "entities": {},
        }]

        with patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=cached), \
             patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch:
            articles = await fetch_articles()
            mock_fetch.assert_not_called()
            assert len(articles) == 1
