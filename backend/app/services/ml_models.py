"""ML-based topic classification and sentiment analysis.

Manages lazy-loaded singleton HuggingFace transformer pipelines for:
- Zero-shot topic classification (DeBERTa v3)
- Multilingual sentiment analysis (DistilBERT)

Falls back to keyword-based classification / neutral sentiment on failure.
Includes detailed performance logging for capacity planning.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.services.topic_classifier import classify_topic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label mapping: NLI hypothesis labels → Orbis topic tags
# ---------------------------------------------------------------------------
_NLI_LABELS: list[str] = [
    "armed conflict and war",
    "politics and government",
    "economy and financial markets",
    "technology and innovation",
    "health and medicine",
    "environment and climate",
    "sports",
]

_LABEL_TO_TAG: dict[str, str] = {
    "armed conflict and war": "conflict",
    "politics and government": "politics",
    "economy and financial markets": "economy",
    "technology and innovation": "technology",
    "health and medicine": "health",
    "environment and climate": "environment",
    "sports": "sports",
}

_TOPIC_THRESHOLD: float = 0.4

# ---------------------------------------------------------------------------
# Singleton pipeline holders
# ---------------------------------------------------------------------------
_topic_pipeline: Any | None = None
_sentiment_pipeline: Any | None = None
_topic_load_failed: bool = False
_sentiment_load_failed: bool = False


def _get_topic_pipeline() -> Any | None:
    """Return the zero-shot classification pipeline, loading it on first call."""
    global _topic_pipeline, _topic_load_failed
    if _topic_pipeline is not None:
        return _topic_pipeline
    if _topic_load_failed:
        return None
    try:
        from transformers import pipeline  # type: ignore[import-untyped]

        t0 = time.perf_counter()
        _topic_pipeline = pipeline(
            "zero-shot-classification",
            model=settings.ml_topic_model,
        )
        elapsed = time.perf_counter() - t0
        logger.info(
            "Topic model loaded in %.2fs  model=%s",
            elapsed,
            settings.ml_topic_model,
        )
        return _topic_pipeline
    except Exception:
        _topic_load_failed = True
        logger.exception("Failed to load topic classification model — falling back to keywords")
        return None


def _get_sentiment_pipeline() -> Any | None:
    """Return the sentiment analysis pipeline, loading it on first call."""
    global _sentiment_pipeline, _sentiment_load_failed
    if _sentiment_pipeline is not None:
        return _sentiment_pipeline
    if _sentiment_load_failed:
        return None
    try:
        from transformers import pipeline  # type: ignore[import-untyped]

        t0 = time.perf_counter()
        _sentiment_pipeline = pipeline(
            "text-classification",
            model=settings.ml_sentiment_model,
            top_k=None,
        )
        elapsed = time.perf_counter() - t0
        logger.info(
            "Sentiment model loaded in %.2fs  model=%s",
            elapsed,
            settings.ml_sentiment_model,
        )
        return _sentiment_pipeline
    except Exception:
        _sentiment_load_failed = True
        logger.exception("Failed to load sentiment model — falling back to 0.0")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_topics_ml(titles: list[str]) -> list[list[str]]:
    """Batch-classify titles into Orbis topic tags using zero-shot NLI.

    Returns a list of tag lists (one per title). Falls back to keyword-based
    classification when the ML model is unavailable or ML is disabled.
    """
    if not titles:
        return []

    if not settings.ml_classification_enabled:
        return [classify_topic(t) for t in titles]

    pipe = _get_topic_pipeline()
    if pipe is None:
        return [classify_topic(t) for t in titles]

    batch_size = settings.ml_batch_size
    all_results: list[list[str]] = []

    t0 = time.perf_counter()
    for start in range(0, len(titles), batch_size):
        batch = titles[start : start + batch_size]
        batch_t0 = time.perf_counter()
        try:
            outputs = pipe(batch, candidate_labels=_NLI_LABELS, multi_label=True)
            # Single-item input returns a dict instead of a list
            if isinstance(outputs, dict):
                outputs = [outputs]
        except Exception:
            logger.exception(
                "Topic classification failed for batch %d–%d, falling back to keywords",
                start,
                start + len(batch),
            )
            all_results.extend(classify_topic(t) for t in batch)
            continue

        batch_elapsed = time.perf_counter() - batch_t0
        logger.info(
            "Topic batch %d–%d: %d articles in %.2fs (%.1f articles/s)",
            start,
            start + len(batch),
            len(batch),
            batch_elapsed,
            len(batch) / batch_elapsed if batch_elapsed > 0 else 0,
        )

        for output in outputs:
            tags: list[str] = []
            for label, score in zip(output["labels"], output["scores"]):
                if score >= _TOPIC_THRESHOLD:
                    tag = _LABEL_TO_TAG.get(label)
                    if tag:
                        tags.append(tag)
            all_results.append(tags if tags else ["general"])

    total_elapsed = time.perf_counter() - t0
    logger.info(
        "Topic classification total: %d articles in %.2fs (%.1f articles/s)",
        len(titles),
        total_elapsed,
        len(titles) / total_elapsed if total_elapsed > 0 else 0,
    )
    return all_results


def analyze_sentiment_ml(titles: list[str]) -> list[float]:
    """Batch-analyze sentiment of titles, returning scores in [-1.0, 1.0].

    Score = P(positive) - P(negative), clamped to [-1, 1], rounded to 4 dp.
    Falls back to 0.0 when the ML model is unavailable or ML is disabled.
    """
    if not titles:
        return []

    if not settings.ml_classification_enabled:
        return [0.0] * len(titles)

    pipe = _get_sentiment_pipeline()
    if pipe is None:
        return [0.0] * len(titles)

    batch_size = settings.ml_batch_size
    all_scores: list[float] = []

    t0 = time.perf_counter()
    for start in range(0, len(titles), batch_size):
        batch = titles[start : start + batch_size]
        batch_t0 = time.perf_counter()
        try:
            outputs = pipe(batch)
        except Exception:
            logger.exception(
                "Sentiment analysis failed for batch %d–%d, falling back to 0.0",
                start,
                start + len(batch),
            )
            all_scores.extend(0.0 for _ in batch)
            continue

        batch_elapsed = time.perf_counter() - batch_t0
        logger.info(
            "Sentiment batch %d–%d: %d articles in %.2fs (%.1f articles/s)",
            start,
            start + len(batch),
            len(batch),
            batch_elapsed,
            len(batch) / batch_elapsed if batch_elapsed > 0 else 0,
        )

        for label_scores in outputs:
            prob: dict[str, float] = {}
            for item in label_scores:
                prob[item["label"].lower()] = item["score"]
            raw = prob.get("positive", 0.0) - prob.get("negative", 0.0)
            clamped = max(-1.0, min(1.0, raw))
            all_scores.append(round(clamped, 4))

    total_elapsed = time.perf_counter() - t0
    logger.info(
        "Sentiment analysis total: %d articles in %.2fs (%.1f articles/s)",
        len(titles),
        total_elapsed,
        len(titles) / total_elapsed if total_elapsed > 0 else 0,
    )
    return all_scores


def reset_pipelines() -> None:
    """Reset cached pipelines — useful for testing."""
    global _topic_pipeline, _sentiment_pipeline
    global _topic_load_failed, _sentiment_load_failed
    _topic_pipeline = None
    _sentiment_pipeline = None
    _topic_load_failed = False
    _sentiment_load_failed = False
