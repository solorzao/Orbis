"""Client for the GDELT DOC 2.0 and GEO 2.0 APIs."""

from __future__ import annotations

import hashlib
import html as html_mod
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.models.news import GlobeDataPoint, NewsArticle
from app.services.cache import get_cached, set_cached
from app.services.country_centroids import get_centroid, normalize_country
from app.services.topic_classifier import classify_topic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword-based sentiment estimation (fallback when GDELT omits tone)
# ---------------------------------------------------------------------------

_NEGATIVE_WORDS = {
    "killed", "dead", "death", "dies", "attack", "murder", "crash", "war",
    "bomb", "shooting", "stabbing", "victim", "fatal", "tragedy", "arrest",
    "charged", "fraud", "scandal", "crisis", "threat", "riot", "fire",
    "explosion", "collapse", "drought", "flood", "earthquake", "hurricane",
    "devastat", "destroy", "terror", "hostage", "kidnap", "abuse", "assault",
    "protest", "strike", "lawsuit", "sued", "indict", "convict", "sentence",
    "layoff", "bankrupt", "recession", "shutdown", "fail", "reject",
    "deportat", "detain", "sanction", "condemn", "flee", "refugee",
}

_POSITIVE_WORDS = {
    "win", "wins", "won", "victory", "success", "celebrate", "record",
    "breakthrough", "award", "honor", "rescue", "save", "recover", "boost",
    "surge", "grow", "growth", "profit", "deal", "launch", "achieve",
    "approve", "peace", "agreement", "cure", "champion", "hero",
    "milestone", "innovate", "discover", "partnership", "donate",
}


def _estimate_sentiment(title: str) -> float:
    """Estimate sentiment from title keywords. Returns -1.0 to 1.0."""
    words = set(title.lower().split())
    neg = sum(1 for w in words if any(w.startswith(n) for n in _NEGATIVE_WORDS))
    pos = sum(1 for w in words if any(w.startswith(p) for p in _POSITIVE_WORDS))
    if neg > pos:
        return -0.6 if neg >= 2 else -0.3
    if pos > neg:
        return 0.7 if pos >= 2 else 0.4
    return 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5  # seconds


def _cache_key(prefix: str, **kwargs: Any) -> str:
    """Build a deterministic cache key from query parameters."""
    raw = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


async def _fetch_with_retry(url: str, params: dict[str, Any]) -> dict | list | None:
    """GET *url* with exponential back-off.  Returns parsed JSON or None."""
    import asyncio

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError, Exception) as exc:
            wait = _BACKOFF_BASE**attempt
            logger.warning(
                "GDELT request attempt %d/%d failed (%s). Retrying in %.1fs …",
                attempt,
                _MAX_RETRIES,
                exc,
                wait,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(wait)
    logger.error("GDELT request failed after %d attempts.", _MAX_RETRIES)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_articles(
    query: str = "",
    timespan: str = "24h",
    max_records: int = 250,
) -> list[NewsArticle]:
    """Fetch articles from the GDELT DOC 2.0 API and return parsed models.

    Results are cached in Redis for ``settings.gdelt_cache_ttl`` seconds.
    Topic filtering is handled by the router via post-filtering on
    classified ``topic_tags``, not via the GDELT query.
    """
    search_query = query or "sourcelang:english"

    cache_k = _cache_key("gdelt:doc", q=search_query, ts=timespan, mr=str(max_records))
    cached = await get_cached(cache_k)
    if cached:
        return [NewsArticle(**a) for a in cached]

    params: dict[str, Any] = {
        "query": search_query,
        "mode": "ArtList",
        "maxrecords": max_records,
        "format": "json",
        "timespan": timespan,
    }

    data = await _fetch_with_retry(settings.gdelt_doc_base_url, params)
    articles = _parse_doc_response(data)

    # Drop articles without a valid location — they cannot be plotted.
    articles = [a for a in articles if a.latitude != 0.0 or a.longitude != 0.0]

    # Only cache non-empty results — a transient GDELT outage should not
    # poison the cache for hours.
    if articles:
        await set_cached(cache_k, [a.model_dump() for a in articles], settings.gdelt_cache_ttl)
    return articles


def _parse_doc_response(data: Any) -> list[NewsArticle]:
    """Parse the raw JSON from GDELT DOC 2.0 into NewsArticle models."""
    if data is None:
        return []

    raw_articles: list[dict] = []
    if isinstance(data, dict):
        raw_articles = data.get("articles", [])
    elif isinstance(data, list):
        raw_articles = data

    now = datetime.now(timezone.utc)
    articles: list[NewsArticle] = []
    if raw_articles:
        logger.info("GDELT DOC sample article keys: %s", list(raw_articles[0].keys()))
    for item in raw_articles:
        try:
            title = item.get("title", "").strip()
            if not title:
                continue
            url = item.get("url", "")
            source = item.get("domain", item.get("source", ""))
            lang = item.get("language", "en") or "en"
            raw_tone = item.get("tone")
            tone: float = 0.0
            has_tone = False
            if raw_tone is not None:
                if isinstance(raw_tone, str) and raw_tone.strip():
                    try:
                        tone = float(raw_tone.split(",")[0])
                        has_tone = True
                    except (ValueError, IndexError):
                        pass
                elif isinstance(raw_tone, (int, float)):
                    tone = float(raw_tone)
                    has_tone = True

            date_str = item.get("seendate", "")
            published_at = _parse_gdelt_date(date_str) if date_str else now

            article_id = hashlib.sha256(url.encode()).hexdigest()[:16]

            # Geo: look up centroid from sourcecountry
            raw_country = item.get("sourcecountry", "")
            country_code = normalize_country(raw_country)
            centroid = get_centroid(raw_country)
            lat = centroid[0] if centroid else 0.0
            lng = centroid[1] if centroid else 0.0

            # Topics: classify from title
            topic_tags = classify_topic(title)

            articles.append(
                NewsArticle(
                    id=article_id,
                    title=title,
                    source_url=url,
                    source_name=source,
                    source_language=lang,
                    published_at=published_at,
                    ingested_at=now,
                    latitude=lat,
                    longitude=lng,
                    country_code=country_code,
                    sentiment_score=max(-1.0, min(1.0, tone / 10.0)) if has_tone else _estimate_sentiment(title),
                    topic_tags=topic_tags,
                )
            )
        except Exception:
            logger.debug("Skipping unparseable article: %s", item, exc_info=True)
    return articles


def _parse_gdelt_date(date_str: str) -> datetime:
    """Parse GDELT's ``YYYYMMDDTHHmmSS`` or similar date formats."""
    stripped = date_str.strip()
    # Try ISO-style formats first against the original string.
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(stripped, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # GDELT's compact format: 20240101T120000Z -> 20240101120000
    compact = stripped.replace("T", "").replace("Z", "")
    try:
        return datetime.strptime(compact, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# GEO 2.0 API — city-level globe points
# ---------------------------------------------------------------------------


def _extract_titles_from_html(raw_html: str) -> list[str]:
    """Extract article titles from GDELT GEO html property."""
    titles = re.findall(r'title="([^"]+)"', raw_html)
    return [html_mod.unescape(t) for t in titles if t]


def _parse_geo_response(data: Any) -> list[GlobeDataPoint]:
    """Parse GeoJSON from GDELT GEO 2.0 into GlobeDataPoint models."""
    if not isinstance(data, dict):
        return []

    features = data.get("features", [])
    points: list[GlobeDataPoint] = []

    for feature in features:
        try:
            geom = feature.get("geometry", {})
            props = feature.get("properties", {})
            coords = geom.get("coordinates", [])

            if len(coords) < 2:
                continue

            lng, lat = float(coords[0]), float(coords[1])
            raw_count = props.get("count", 0)
            name = props.get("name", "")
            raw_html = props.get("html", "")

            # Extract headlines and classify topic
            titles = _extract_titles_from_html(raw_html)
            top_headline = titles[0] if titles else name
            topic_tags = classify_topic(top_headline)
            topic = topic_tags[0] if topic_tags else "general"

            # Scale count: raw values are mention volumes (up to 200K+), use log
            article_count = max(1, int(math.log2(max(1, raw_count))))

            points.append(
                GlobeDataPoint(
                    lat=lat,
                    lng=lng,
                    weight=min(raw_count, 500),
                    article_count=article_count,
                    top_headline=top_headline,
                    topic=topic,
                    location_name=name,
                )
            )
        except Exception:
            logger.debug("Skipping unparseable GEO feature: %s", feature, exc_info=True)

    return points


def _articles_to_globe_points(articles: list[NewsArticle]) -> list[GlobeDataPoint]:
    """Convert DOC API articles into GlobeDataPoints grouped by location.

    Used as a fallback when the GEO API is unavailable.  Groups articles
    by their (lat, lng) centroid and produces one point per location.
    """
    from collections import defaultdict

    buckets: dict[tuple[float, float], list[NewsArticle]] = defaultdict(list)
    for a in articles:
        if a.latitude == 0.0 and a.longitude == 0.0:
            continue
        buckets[(a.latitude, a.longitude)].append(a)

    points: list[GlobeDataPoint] = []
    for (lat, lng), group in buckets.items():
        top = group[0]
        topic_tags = top.topic_tags
        points.append(
            GlobeDataPoint(
                lat=lat,
                lng=lng,
                weight=min(len(group) * 10, 500),
                article_count=len(group),
                top_headline=top.title,
                topic=topic_tags[0] if topic_tags else "general",
                location_name=top.country_code,
            )
        )
    return points


async def fetch_geo_points(
    query: str = "",
    timespan: str = "24h",
) -> list[GlobeDataPoint]:
    """Fetch globe points from the GDELT GEO 2.0 API.

    Returns city-level GeoJSON data with coordinates and article counts.
    Results are cached in Redis for ``settings.gdelt_cache_ttl`` seconds.

    Falls back to DOC API articles (country-level) when GEO API is down.
    """
    search_query = query or "sourcelang:english"

    cache_k = _cache_key("gdelt:geo", q=search_query, ts=timespan)
    cached = await get_cached(cache_k)
    if cached:
        return [GlobeDataPoint(**p) for p in cached]

    params: dict[str, Any] = {
        "query": search_query,
        "mode": "PointData",
        "format": "GeoJSON",
        "timespan": timespan,
    }

    data = await _fetch_with_retry(settings.gdelt_geo_base_url, params)
    points = _parse_geo_response(data)

    # Fallback: when GEO API is down, derive globe points from DOC API
    # articles.  Drop the sourcelang:english filter so we get global
    # coverage (65+ languages) instead of mostly US sources.
    if not points:
        logger.warning("GEO API returned 0 points — falling back to DOC API.")
        articles = await fetch_articles(
            query="",  # no language filter → global coverage
            timespan=timespan,
            max_records=250,
        )
        points = _articles_to_globe_points(articles)

    # Only cache non-empty results — a transient GDELT outage should not
    # poison the cache for hours.
    if points:
        await set_cached(cache_k, [p.model_dump() for p in points], settings.gdelt_geo_cache_ttl)
    return points
