"""Grid-based spatial clustering for globe data points."""

from __future__ import annotations

import logging
from collections import defaultdict

from app.config import settings
from app.models.news import GlobeDataPoint, NewsArticle, NewsCluster

logger = logging.getLogger(__name__)


def _cell_key(lat: float, lng: float, resolution: float) -> tuple[int, int]:
    """Return the grid-cell index for a given coordinate pair."""
    return (
        int(lat // resolution),
        int(lng // resolution),
    )


def cluster_articles(
    articles: list[NewsArticle],
    resolution: float | None = None,
) -> list[NewsCluster]:
    """Group articles into spatial clusters using a simple grid.

    Each cell spans *resolution* degrees on each axis (default from settings).
    Returns a list of ``NewsCluster`` objects.
    """
    res = resolution or settings.cluster_resolution_deg
    buckets: dict[tuple[int, int], list[NewsArticle]] = defaultdict(list)

    for article in articles:
        key = _cell_key(article.latitude, article.longitude, res)
        buckets[key].append(article)

    clusters: list[NewsCluster] = []
    for _key, arts in buckets.items():
        center_lat = sum(a.latitude for a in arts) / len(arts)
        center_lng = sum(a.longitude for a in arts) / len(arts)
        avg_sentiment = sum(a.sentiment_score for a in arts) / len(arts)

        # Dominant topic: pick the most common tag across all articles.
        topic = _dominant_topic(arts)

        clusters.append(
            NewsCluster(
                center_lat=center_lat,
                center_lng=center_lng,
                articles=arts,
                topic=topic,
                avg_sentiment=avg_sentiment,
            )
        )

    return clusters


def clusters_to_globe_points(clusters: list[NewsCluster]) -> list[GlobeDataPoint]:
    """Convert clusters into lightweight data points for the globe."""
    points: list[GlobeDataPoint] = []
    for c in clusters:
        top_headline = c.articles[0].title if c.articles else ""
        points.append(
            GlobeDataPoint(
                lat=c.center_lat,
                lng=c.center_lng,
                weight=abs(c.avg_sentiment) * len(c.articles),
                article_count=len(c.articles),
                top_headline=top_headline,
                topic=c.topic,
            )
        )
    return points


def articles_near(
    articles: list[NewsArticle],
    lat: float,
    lng: float,
    radius: float,
) -> list[NewsArticle]:
    """Return articles within *radius* degrees of (*lat*, *lng*).

    Uses a simple bounding-box check (not Haversine) for speed.
    """
    return [
        a for a in articles if abs(a.latitude - lat) <= radius and abs(a.longitude - lng) <= radius
    ]


def _dominant_topic(articles: list[NewsArticle]) -> str:
    """Return the most frequent topic tag, or 'general'."""
    counts: dict[str, int] = defaultdict(int)
    for a in articles:
        for tag in a.topic_tags:
            counts[tag] += 1
    if not counts:
        return "general"
    return max(counts, key=counts.get)  # type: ignore[arg-type]
