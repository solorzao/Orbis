"""Client for the GDELT DOC 2.0 API."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.models.news import NewsArticle
from app.services.cache import get_cached, set_cached
from app.services.country_centroids import get_centroid
from app.services.topic_classifier import classify_topic

logger = logging.getLogger(__name__)

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
            wait = _BACKOFF_BASE ** attempt
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
    topic: str | None = None,
) -> list[NewsArticle]:
    """Fetch articles from the GDELT DOC 2.0 API and return parsed models.

    Results are cached in Redis for ``settings.gdelt_cache_ttl`` seconds.
    """
    search_query = query or "sourcelang:english"
    if topic:
        search_query = f"{search_query} {topic}".strip()

    cache_k = _cache_key("gdelt:doc", q=search_query, ts=timespan, mr=str(max_records))
    cached = await get_cached(cache_k)
    if cached is not None:
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

    # Cache the result.
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
    for item in raw_articles:
        try:
            title = item.get("title", "").strip()
            if not title:
                continue
            url = item.get("url", "")
            source = item.get("domain", item.get("source", ""))
            lang = item.get("language", "en") or "en"
            tone = item.get("tone", 0.0)
            if isinstance(tone, str):
                try:
                    tone = float(tone.split(",")[0])
                except (ValueError, IndexError):
                    tone = 0.0

            date_str = item.get("seendate", "")
            published_at = _parse_gdelt_date(date_str) if date_str else now

            article_id = hashlib.sha256(url.encode()).hexdigest()[:16]

            # Geo: look up centroid from sourcecountry
            country_code = item.get("sourcecountry", "")
            centroid = get_centroid(country_code)
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
                    sentiment_score=float(tone) if tone else 0.0,
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


