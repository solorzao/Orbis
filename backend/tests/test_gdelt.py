"""Tests for GDELT response parsing with centroid and topic enrichment."""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.gdelt import (
    _articles_to_globe_points,
    _extract_titles_from_html,
    _parse_doc_response,
    _parse_geo_response,
    fetch_articles,
    fetch_geo_points,
)


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
        assert articles[0].sentiment_score == -0.35  # GDELT tone / 10 → normalized to [-1, 1]

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
    async def test_does_not_cache_empty_doc_results(self):
        """Empty DOC results (GDELT outage) must NOT be cached."""
        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock) as mock_set:
            mock_fetch.return_value = None  # DOC API down
            articles = await fetch_articles()
            assert articles == []
            mock_set.assert_not_called()

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


# ---------------------------------------------------------------------------
# GEO 2.0 API tests
# ---------------------------------------------------------------------------

def _make_geo_feature(
    lat: float = 35.7,
    lng: float = 51.4,
    count: int = 100,
    name: str = "Tehran, Tehran, Iran",
    html: str = '<a href="https://example.com" target="_blank" title="Iran launches satellite">Article</a>',
):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {"count": count, "name": name, "html": html},
    }


class TestExtractTitlesFromHtml:
    def test_extracts_single_title(self):
        html = '<a href="https://ex.com" title="Breaking news headline">link</a>'
        titles = _extract_titles_from_html(html)
        assert titles == ["Breaking news headline"]

    def test_extracts_multiple_titles(self):
        html = (
            '<a title="First headline">a</a>'
            '<a title="Second headline">b</a>'
        )
        titles = _extract_titles_from_html(html)
        assert len(titles) == 2
        assert titles[0] == "First headline"
        assert titles[1] == "Second headline"

    def test_unescapes_html_entities(self):
        html = '<a title="Biden &amp; Harris discuss NATO&#39;s future">link</a>'
        titles = _extract_titles_from_html(html)
        assert titles[0] == "Biden & Harris discuss NATO's future"

    def test_returns_empty_for_no_titles(self):
        assert _extract_titles_from_html("") == []
        assert _extract_titles_from_html("<p>No titles here</p>") == []


class TestParseGeoResponse:
    def test_parses_single_feature(self):
        data = {"type": "FeatureCollection", "features": [_make_geo_feature()]}
        points = _parse_geo_response(data)
        assert len(points) == 1
        assert points[0].lat == 35.7
        assert points[0].lng == 51.4
        assert points[0].location_name == "Tehran, Tehran, Iran"

    def test_geojson_coordinate_order(self):
        """GeoJSON uses [lng, lat] — verify we don't swap them."""
        feature = _make_geo_feature(lat=51.5, lng=-0.1)
        data = {"type": "FeatureCollection", "features": [feature]}
        points = _parse_geo_response(data)
        assert points[0].lat == 51.5
        assert points[0].lng == -0.1

    def test_log_scales_count(self):
        """Raw counts are mention volumes; article_count should be log-scaled."""
        feature = _make_geo_feature(count=1024)
        data = {"type": "FeatureCollection", "features": [feature]}
        points = _parse_geo_response(data)
        assert points[0].article_count == 10  # log2(1024) = 10

    def test_minimum_article_count_is_one(self):
        feature = _make_geo_feature(count=0)
        data = {"type": "FeatureCollection", "features": [feature]}
        points = _parse_geo_response(data)
        assert points[0].article_count >= 1

    def test_uses_headline_for_topic_classification(self):
        feature = _make_geo_feature(
            html='<a title="Military strikes intensify in conflict zone">link</a>',
        )
        data = {"type": "FeatureCollection", "features": [feature]}
        points = _parse_geo_response(data)
        assert points[0].topic == "conflict"

    def test_falls_back_to_name_when_no_titles(self):
        feature = _make_geo_feature(html="", name="London, United Kingdom")
        data = {"type": "FeatureCollection", "features": [feature]}
        points = _parse_geo_response(data)
        assert points[0].top_headline == "London, United Kingdom"

    def test_skips_features_without_coordinates(self):
        feature = {"type": "Feature", "geometry": {"coordinates": []}, "properties": {}}
        data = {"type": "FeatureCollection", "features": [feature]}
        assert _parse_geo_response(data) == []

    def test_handles_none_input(self):
        assert _parse_geo_response(None) == []

    def test_handles_empty_features(self):
        assert _parse_geo_response({"features": []}) == []

    def test_parses_multiple_features(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                _make_geo_feature(lat=35.7, lng=51.4, name="Tehran"),
                _make_geo_feature(lat=51.5, lng=-0.1, name="London"),
                _make_geo_feature(lat=40.7, lng=-74.0, name="New York"),
            ],
        }
        points = _parse_geo_response(data)
        assert len(points) == 3


class TestFetchGeoPoints:
    @pytest.mark.asyncio
    async def test_calls_geo_api_with_correct_params(self):
        geo_data = {"type": "FeatureCollection", "features": [_make_geo_feature()]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = geo_data
            points = await fetch_geo_points()
            call_args = mock_fetch.call_args
            params = call_args[0][1]
            assert params["mode"] == "PointData"
            assert params["format"] == "GeoJSON"
            assert len(points) == 1

    @pytest.mark.asyncio
    async def test_default_query_is_sourcelang_english(self):
        geo_data = {"type": "FeatureCollection", "features": [_make_geo_feature()]}

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock):
            mock_fetch.return_value = geo_data
            await fetch_geo_points()
            params = mock_fetch.call_args[0][1]
            assert params["query"] == "sourcelang:english"

    @pytest.mark.asyncio
    async def test_returns_cached_results(self):
        cached = [{
            "lat": 35.7, "lng": 51.4, "weight": 100,
            "article_count": 7, "top_headline": "Cached",
            "topic": "general", "location_name": "Tehran",
        }]

        with patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=cached), \
             patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch:
            points = await fetch_geo_points()
            mock_fetch.assert_not_called()
            assert len(points) == 1
            assert points[0].location_name == "Tehran"

    @pytest.mark.asyncio
    async def test_does_not_cache_empty_results(self):
        """Empty GEO results (GDELT outage) must NOT be cached."""
        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock) as mock_set, \
             patch("app.services.gdelt.fetch_articles", new_callable=AsyncMock, return_value=[]):
            mock_fetch.return_value = None  # GEO API down
            await fetch_geo_points()
            mock_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_doc_api_when_geo_returns_empty(self):
        """When GEO API returns nothing, fall back to DOC-derived points."""
        doc_articles = _parse_doc_response({
            "articles": [
                _make_raw_article(sourcecountry="United States", url="https://a.com/1"),
                _make_raw_article(sourcecountry="France", url="https://a.com/2"),
            ]
        })

        with patch("app.services.gdelt._fetch_with_retry", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.gdelt.get_cached", new_callable=AsyncMock, return_value=None), \
             patch("app.services.gdelt.set_cached", new_callable=AsyncMock), \
             patch("app.services.gdelt.fetch_articles", new_callable=AsyncMock, return_value=doc_articles):
            mock_fetch.return_value = None  # GEO API down
            points = await fetch_geo_points()
            assert len(points) == 2  # One per country


class TestArticlesToGlobePoints:
    def test_groups_by_location(self):
        articles = _parse_doc_response({
            "articles": [
                _make_raw_article(sourcecountry="US", url="https://a.com/1", title="Story A"),
                _make_raw_article(sourcecountry="US", url="https://a.com/2", title="Story B"),
                _make_raw_article(sourcecountry="France", url="https://a.com/3", title="Story C"),
            ]
        })
        points = _articles_to_globe_points(articles)
        assert len(points) == 2  # US + France
        us_point = next(p for p in points if p.article_count == 2)
        assert us_point.article_count == 2

    def test_skips_zero_coord_articles(self):
        articles = _parse_doc_response({
            "articles": [_make_raw_article(sourcecountry="ZZ")]
        })
        points = _articles_to_globe_points(articles)
        assert len(points) == 0

    def test_empty_input(self):
        assert _articles_to_globe_points([]) == []
