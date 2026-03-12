"""ML-based topic classification and sentiment analysis.

When ML_FUNCTIONS_URL is configured, calls Azure Functions for inference.
Otherwise falls back to keyword-based classification / neutral sentiment.
Includes detailed performance logging for capacity planning.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.services.topic_classifier import classify_topic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CHUNK_SIZE = 100  # Max titles per HTTP request (Option C: chunked parallel)
_HTTP_TIMEOUT = 120.0  # seconds — generous for cold starts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _call_function(
    endpoint: str,
    titles: list[str],
) -> dict[str, Any] | None:
    """POST titles to an Azure Function endpoint, return parsed JSON or None."""
    url = f"{settings.ml_functions_url.rstrip('/')}/{endpoint}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.ml_functions_key:
        headers["x-functions-key"] = settings.ml_functions_key

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json={"titles": titles}, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.exception(
            "ML function call failed  endpoint=%s  titles=%d", endpoint, len(titles)
        )
        return None


async def _call_chunked(
    endpoint: str,
    titles: list[str],
) -> list[dict[str, Any] | None]:
    """Split titles into chunks and call the function in parallel."""
    chunks = [titles[i : i + _CHUNK_SIZE] for i in range(0, len(titles), _CHUNK_SIZE)]
    results = await asyncio.gather(
        *[_call_function(endpoint, chunk) for chunk in chunks]
    )
    return list(results)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def classify_topics_ml(titles: list[str]) -> list[list[str]]:
    """Classify titles into Orbis topic tags.

    Routes to Azure Functions when ml_functions_url is set,
    otherwise falls back to keyword classifier.
    """
    if not titles:
        return []

    if not settings.ml_classification_enabled:
        return [classify_topic(t) for t in titles]

    if not settings.ml_functions_url:
        logger.warning("ML enabled but ML_FUNCTIONS_URL not set — using keyword fallback")
        return [classify_topic(t) for t in titles]

    t0 = time.perf_counter()
    chunk_results = await _call_chunked("classify-topics", titles)

    all_topics: list[list[str]] = []
    chunk_start = 0
    for i, result in enumerate(chunk_results):
        chunk_end = min(chunk_start + _CHUNK_SIZE, len(titles))
        chunk_titles = titles[chunk_start:chunk_end]

        if result is not None and "topics" in result:
            all_topics.extend(result["topics"])
            logger.info(
                "Topic chunk %d: %d titles, function reported %dms",
                i,
                len(chunk_titles),
                result.get("timing_ms", 0),
            )
        else:
            # Fallback to keyword classifier for this chunk
            logger.warning("Topic chunk %d failed — using keyword fallback for %d titles", i, len(chunk_titles))
            all_topics.extend(classify_topic(t) for t in chunk_titles)

        chunk_start = chunk_end

    total_ms = round((time.perf_counter() - t0) * 1000)
    logger.info(
        "Topic classification total: %d titles in %dms (%.1f titles/s)",
        len(titles),
        total_ms,
        len(titles) / (total_ms / 1000) if total_ms > 0 else 0,
    )
    return all_topics


async def analyze_sentiment_ml(titles: list[str]) -> list[float]:
    """Analyze sentiment of titles, returning scores in [-1.0, 1.0].

    Routes to Azure Functions when ml_functions_url is set,
    otherwise returns 0.0 for all titles.
    """
    if not titles:
        return []

    if not settings.ml_classification_enabled:
        return [0.0] * len(titles)

    if not settings.ml_functions_url:
        logger.warning("ML enabled but ML_FUNCTIONS_URL not set — returning 0.0 fallback")
        return [0.0] * len(titles)

    t0 = time.perf_counter()
    chunk_results = await _call_chunked("analyze-sentiment", titles)

    all_scores: list[float] = []
    chunk_start = 0
    for i, result in enumerate(chunk_results):
        chunk_end = min(chunk_start + _CHUNK_SIZE, len(titles))
        chunk_titles = titles[chunk_start:chunk_end]

        if result is not None and "sentiments" in result:
            all_scores.extend(result["sentiments"])
            logger.info(
                "Sentiment chunk %d: %d titles, function reported %dms",
                i,
                len(chunk_titles),
                result.get("timing_ms", 0),
            )
        else:
            logger.warning("Sentiment chunk %d failed — returning 0.0 for %d titles", i, len(chunk_titles))
            all_scores.extend(0.0 for _ in chunk_titles)

        chunk_start = chunk_end

    total_ms = round((time.perf_counter() - t0) * 1000)
    logger.info(
        "Sentiment analysis total: %d titles in %dms (%.1f titles/s)",
        len(titles),
        total_ms,
        len(titles) / (total_ms / 1000) if total_ms > 0 else 0,
    )
    return all_scores
