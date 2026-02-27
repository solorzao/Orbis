"""Tests for the spatial clustering service."""

from datetime import datetime, timezone

from app.models.news import NewsArticle
from app.services.clustering import (
    articles_near,
    cluster_articles,
    clusters_to_globe_points,
)


def _make_article(lat: float, lng: float, tags: list[str] | None = None, **kw) -> NewsArticle:
    return NewsArticle(
        id=f"art-{lat}-{lng}",
        title=f"Article at {lat},{lng}",
        source_url=f"https://example.com/{lat}/{lng}",
        source_name="Test",
        published_at=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        latitude=lat,
        longitude=lng,
        topic_tags=tags or ["general"],
        sentiment_score=kw.get("sentiment", 0.0),
    )


class TestClusterArticles:
    def test_nearby_articles_cluster_together(self):
        # All coords within the same 2° grid cell (lat 40-42, lng 10-12)
        articles = [
            _make_article(41.1, 10.1),
            _make_article(41.5, 10.5),
            _make_article(41.3, 10.3),
        ]
        clusters = cluster_articles(articles, resolution=2.0)
        assert len(clusters) == 1
        assert len(clusters[0].articles) == 3

    def test_distant_articles_separate(self):
        articles = [
            _make_article(40.0, -74.0),   # New York area
            _make_article(51.5, -0.1),     # London
            _make_article(-33.9, 151.2),   # Sydney
        ]
        clusters = cluster_articles(articles, resolution=2.0)
        assert len(clusters) == 3

    def test_cluster_center_is_average(self):
        articles = [
            _make_article(40.0, -74.0),
            _make_article(42.0, -74.0),
        ]
        clusters = cluster_articles(articles, resolution=5.0)
        assert len(clusters) == 1
        assert clusters[0].center_lat == 41.0
        assert clusters[0].center_lng == -74.0

    def test_dominant_topic(self):
        articles = [
            _make_article(40.0, -74.0, tags=["politics"]),
            _make_article(40.1, -74.0, tags=["politics"]),
            _make_article(40.05, -74.0, tags=["technology"]),
        ]
        clusters = cluster_articles(articles, resolution=2.0)
        assert clusters[0].topic == "politics"

    def test_empty_input(self):
        clusters = cluster_articles([], resolution=2.0)
        assert clusters == []


class TestClustersToGlobePoints:
    def test_converts_to_points(self):
        articles = [_make_article(40.0, -74.0, sentiment=0.5)]
        clusters = cluster_articles(articles, resolution=2.0)
        points = clusters_to_globe_points(clusters)
        assert len(points) == 1
        assert points[0].article_count == 1
        assert points[0].top_headline == "Article at 40.0,-74.0"


class TestArticlesNear:
    def test_finds_nearby(self):
        articles = [
            _make_article(40.0, -74.0),
            _make_article(40.5, -74.0),
            _make_article(51.5, -0.1),
        ]
        nearby = articles_near(articles, lat=40.0, lng=-74.0, radius=1.0)
        assert len(nearby) == 2

    def test_excludes_distant(self):
        articles = [_make_article(51.5, -0.1)]
        nearby = articles_near(articles, lat=40.0, lng=-74.0, radius=1.0)
        assert len(nearby) == 0

    def test_empty_input(self):
        nearby = articles_near([], lat=0, lng=0, radius=10)
        assert nearby == []
