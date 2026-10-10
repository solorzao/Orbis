"""Tests for Pydantic data models."""

from datetime import datetime, timezone

import pytest

from app.models.news import GlobeDataPoint, NewsArticle, NewsCluster, https_image_url


def _make_article(**overrides) -> NewsArticle:
    defaults = {
        "id": "test-1",
        "title": "Test Article",
        "source_url": "https://example.com/article",
        "source_name": "Test Source",
        "published_at": datetime.now(timezone.utc),
        "ingested_at": datetime.now(timezone.utc),
        "latitude": 40.7128,
        "longitude": -74.0060,
        "topic_tags": ["technology"],
        "sentiment_score": 0.5,
    }
    defaults.update(overrides)
    return NewsArticle(**defaults)


def test_article_creation():
    article = _make_article()
    assert article.id == "test-1"
    assert article.title == "Test Article"
    assert article.latitude == 40.7128


def test_article_defaults():
    article = _make_article()
    assert article.summary is None
    assert article.source_language == "en"
    assert article.country_code == ""
    assert article.entities == {}


def test_article_with_all_fields():
    article = _make_article(
        summary="A test summary",
        country_code="US",
        region="North America",
        entities={"people": ["Alice"], "organizations": ["Acme"]},
    )
    assert article.summary == "A test summary"
    assert article.country_code == "US"
    assert article.entities["people"] == ["Alice"]


def test_cluster_creation():
    articles = [_make_article(id=f"art-{i}") for i in range(3)]
    cluster = NewsCluster(
        center_lat=40.0,
        center_lng=-74.0,
        articles=articles,
        topic="technology",
        avg_sentiment=0.3,
    )
    assert len(cluster.articles) == 3
    assert cluster.topic == "technology"


def test_globe_data_point():
    point = GlobeDataPoint(
        lat=51.5074,
        lng=-0.1278,
        weight=3.5,
        article_count=7,
        top_headline="Breaking news",
        topic="politics",
    )
    assert point.article_count == 7
    assert point.topic == "politics"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # Upgrade http, keep https, reject everything that isn't a web URL.
        ("http://cdn.example.com/a.jpg", "https://cdn.example.com/a.jpg"),
        ("https://cdn.example.com/a.jpg", "https://cdn.example.com/a.jpg"),
        ("javascript:alert(1)", None),
        ("", None),
        (None, None),
        (123, None),
        # urlsplit raises ValueError on these; they must not escape.
        ("http://[cdn.example.com/a.jpg", None),
        ("http://[example.com]/a.jpg", None),
        ("http://ex\u2100ample.com/", None),
        ("http://cdn.example.com:abc/a.jpg", None),
        # Missing host or scheme.
        ("http:host", None),
        ("https:///x", None),
        ("//host/x", None),
        ("data:image/png;base64,AA==", None),
        # Normalisation.
        ("HTTP://cdn.example.com/a.jpg", "https://cdn.example.com/a.jpg"),
        ("  http://cdn.example.com/a.jpg\n", "https://cdn.example.com/a.jpg"),
        # Control characters and oversized values.
        ("http://cdn.example.com/a\x00.jpg", None),
        pytest.param("https://cdn.example.com/" + "a" * 3000, None, id="too-long"),
        # Userinfo, including the "trusted.com@evil" trick.
        ("http://user:pass@cdn.example.com/a.jpg", None),
        ("https://cnn.com@evil.example/a.jpg", None),
        # IP literals and local-network names.
        ("https://127.0.0.1/a", None),
        ("https://[::1]/a", None),
        ("https://localhost:8080/a", None),
        ("https://printer.local/a", None),
        ("https://intranet/a", None),
        ("https://localhost./a", None),
        # Shorthand IPv4 that browsers parse because the last label is a number.
        ("https://127.1/a", None),
        ("https://0x7f.0.0.1/a", None),
        ("https://2130706433/a", None),
        ("https://10.1/a", None),
        ("https://cdn1.example.com/a", "https://cdn1.example.com/a"),
        ("https://example.co.uk/a", "https://example.co.uk/a"),
        # Ports: http's default port is dropped, other explicit ports are kept.
        ("http://cdn.example.com:80/a.jpg", "https://cdn.example.com/a.jpg"),
        ("https://cdn.example.com:8443/a.jpg", "https://cdn.example.com:8443/a.jpg"),
    ],
)
def test_https_image_url(url, expected):
    assert https_image_url(url) == expected


def test_article_image_url_upgraded_to_https():
    article = _make_article(image_url="http://cdn.example.com/a.jpg")
    assert article.image_url == "https://cdn.example.com/a.jpg"


def test_article_malformed_image_url_becomes_none():
    article = _make_article(image_url="http://[cdn.example.com/a.jpg")
    assert article.image_url is None


def test_article_image_url_defaults_to_none():
    assert _make_article().image_url is None
