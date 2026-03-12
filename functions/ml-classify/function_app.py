"""Azure Functions for ML-based topic classification and sentiment analysis.

Two HTTP-triggered functions:
- classify_topics: Single-pass RoBERTa (NYT-trained) + keyword supplement
- analyze_sentiment: DistilBERT multilingual sentiment
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton model holders
# ---------------------------------------------------------------------------
_topic_pipeline: Any | None = None
_sentiment_pipeline: Any | None = None
_topic_load_failed: bool = False
_sentiment_load_failed: bool = False

TOPIC_MODEL = "dstefa/roberta-base_topic_classification_nyt_news"
SENTIMENT_MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"

# ---------------------------------------------------------------------------
# NYT model label → Orbis tag mapping
# ---------------------------------------------------------------------------
_NYT_LABEL_TO_TAG: dict[str, str] = {
    "Politics": "politics",
    "Business and Finance": "economy",
    "Science and Technology": "technology",
    "Health and Wellness": "health",
    "Sports": "sports",
    "Crime": "conflict",  # partial match — supplemented by keywords
    "Arts/Culture/Entertainment": "general",
    "Lifestyle/Fashion": "general",
}

# ---------------------------------------------------------------------------
# Keyword supplement for categories the NYT model doesn't cover well
# ---------------------------------------------------------------------------
_CONFLICT_KEYWORDS: list[str] = [
    "war", "attack", "military", "troops", "bomb", "missile", "fighting",
    "armed", "strike", "soldier", "killed", "casualties", "battle",
    "invasion", "combat", "airstrike", "shelling", "ceasefire", "siege",
]
_ENVIRONMENT_KEYWORDS: list[str] = [
    "climate", "environment", "carbon", "emission", "pollution", "renewable",
    "wildfire", "flood", "drought", "hurricane", "earthquake", "deforestation",
    "glacier", "biodiversity", "ecosystem", "fossil fuel",
]


def _keyword_match(title: str, keywords: list[str]) -> bool:
    """Check if any keyword matches in the title using word boundaries."""
    title_lower = title.lower()
    for kw in keywords:
        if " " in kw:
            if kw in title_lower:
                return True
        else:
            if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
                return True
    return False


# ---------------------------------------------------------------------------
# Model loaders
# ---------------------------------------------------------------------------

def _get_topic_pipeline() -> Any | None:
    global _topic_pipeline, _topic_load_failed
    if _topic_pipeline is not None:
        return _topic_pipeline
    if _topic_load_failed:
        return None
    try:
        from transformers import pipeline

        t0 = time.perf_counter()
        _topic_pipeline = pipeline(
            "text-classification",
            model=TOPIC_MODEL,
            top_k=None,
        )
        elapsed = time.perf_counter() - t0
        logger.info("Topic model loaded in %.2fs  model=%s", elapsed, TOPIC_MODEL)
        return _topic_pipeline
    except Exception:
        _topic_load_failed = True
        logger.exception("Failed to load topic model")
        return None


def _get_sentiment_pipeline() -> Any | None:
    global _sentiment_pipeline, _sentiment_load_failed
    if _sentiment_pipeline is not None:
        return _sentiment_pipeline
    if _sentiment_load_failed:
        return None
    try:
        from transformers import pipeline

        t0 = time.perf_counter()
        _sentiment_pipeline = pipeline(
            "text-classification",
            model=SENTIMENT_MODEL,
            top_k=None,
        )
        elapsed = time.perf_counter() - t0
        logger.info("Sentiment model loaded in %.2fs  model=%s", elapsed, SENTIMENT_MODEL)
        return _sentiment_pipeline
    except Exception:
        _sentiment_load_failed = True
        logger.exception("Failed to load sentiment model")
        return None


# ---------------------------------------------------------------------------
# HTTP-triggered functions
# ---------------------------------------------------------------------------

@app.route(route="classify-topics", methods=["POST"])
def classify_topics(req: func.HttpRequest) -> func.HttpResponse:
    """Classify a batch of article titles into Orbis topic tags.

    Request body: {"titles": ["headline 1", "headline 2", ...]}
    Response body: {"topics": [["politics", "economy"], ["sports"], ...],
                    "timing_ms": 1234}
    """
    t0 = time.perf_counter()

    try:
        body = req.get_json()
        titles: list[str] = body.get("titles", [])
    except (ValueError, AttributeError):
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json",
        )

    if not titles:
        return func.HttpResponse(
            json.dumps({"topics": [], "timing_ms": 0}),
            mimetype="application/json",
        )

    pipe = _get_topic_pipeline()
    all_topics: list[list[str]] = []

    if pipe is None:
        # Model failed to load — return empty tags, let caller use keyword fallback
        all_topics = [["general"]] * len(titles)
    else:
        try:
            outputs = pipe(titles, batch_size=32)
            # Single item returns a list of dicts, not list of list of dicts
            if titles and isinstance(outputs[0], dict):
                outputs = [outputs]
        except Exception:
            logger.exception("Topic inference failed")
            all_topics = [["general"]] * len(titles)
            outputs = None

        if outputs is not None:
            for title, output in zip(titles, outputs):
                tags: list[str] = []

                # Get the top prediction from the NYT model
                if output:
                    # output is a list of {"label": ..., "score": ...} sorted desc
                    top = output[0]
                    tag = _NYT_LABEL_TO_TAG.get(top["label"], "general")
                    if tag != "general" and top["score"] >= 0.5:
                        tags.append(tag)

                # Keyword supplement: check conflict and environment
                if _keyword_match(title, _CONFLICT_KEYWORDS) and "conflict" not in tags:
                    tags.append("conflict")
                if _keyword_match(title, _ENVIRONMENT_KEYWORDS) and "environment" not in tags:
                    tags.append("environment")

                all_topics.append(tags if tags else ["general"])

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    logger.info("classify_topics: %d titles in %dms", len(titles), elapsed_ms)

    return func.HttpResponse(
        json.dumps({"topics": all_topics, "timing_ms": elapsed_ms}),
        mimetype="application/json",
    )


@app.route(route="analyze-sentiment", methods=["POST"])
def analyze_sentiment(req: func.HttpRequest) -> func.HttpResponse:
    """Analyze sentiment of a batch of article titles.

    Request body: {"titles": ["headline 1", "headline 2", ...]}
    Response body: {"sentiments": [0.5, -0.3, ...], "timing_ms": 1234}
    """
    t0 = time.perf_counter()

    try:
        body = req.get_json()
        titles: list[str] = body.get("titles", [])
    except (ValueError, AttributeError):
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json",
        )

    if not titles:
        return func.HttpResponse(
            json.dumps({"sentiments": [], "timing_ms": 0}),
            mimetype="application/json",
        )

    pipe = _get_sentiment_pipeline()
    all_scores: list[float] = []

    if pipe is None:
        all_scores = [0.0] * len(titles)
    else:
        try:
            outputs = pipe(titles, batch_size=32)
        except Exception:
            logger.exception("Sentiment inference failed")
            all_scores = [0.0] * len(titles)
            outputs = None

        if outputs is not None:
            for label_scores in outputs:
                prob: dict[str, float] = {}
                for item in label_scores:
                    prob[item["label"].lower()] = item["score"]
                raw = prob.get("positive", 0.0) - prob.get("negative", 0.0)
                clamped = max(-1.0, min(1.0, raw))
                all_scores.append(round(clamped, 4))

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    logger.info("analyze_sentiment: %d titles in %dms", len(titles), elapsed_ms)

    return func.HttpResponse(
        json.dumps({"sentiments": all_scores, "timing_ms": elapsed_ms}),
        mimetype="application/json",
    )
