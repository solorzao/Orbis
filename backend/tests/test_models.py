"""Tests for Pydantic data models."""

from datetime import datetime, timezone

from app.models.news import GlobeDataPoint, NewsArticle, NewsCluster


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
