# ML-Based Topic Classification & Sentiment Analysis

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace keyword-based topic classification and keyword-based sentiment estimation with local HuggingFace transformer models for significantly better accuracy.

**Architecture:** A new `ml_models` service manages lazy-loaded singleton model instances (loaded once on first use, kept in memory). The ingestion pipeline calls these instead of the keyword classifier and GDELT tone fallback. Models run on CPU with batched inference. A feature flag allows falling back to keyword-based classification if models fail to load.

**Tech Stack:** `transformers`, `torch` (CPU-only), `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` (topic), `lxyuan/distilbert-base-multilingual-cased-sentiments-student` (sentiment)

---

### Task 1: Add ML dependencies

**Files:**
- Modify: `backend/requirements.txt`

**Step 1: Add dependencies**

Add to `backend/requirements.txt`:
```
transformers>=4.40.0
torch>=2.0.0
```

**Step 2: Install**

Run: `cd backend && pip install transformers torch`

**Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add transformers and torch dependencies for ML classification"
```

---

### Task 2: Add config flags for ML models

**Files:**
- Modify: `backend/app/config.py`

**Step 1: Add settings**

Add these fields to the `Settings` dataclass after the existing AI section (~line 51):

```python
    # --- ML classification ---
    ml_topic_model: str = field(
        default_factory=lambda: _env(
            "ML_TOPIC_MODEL", "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
        )
    )
    ml_sentiment_model: str = field(
        default_factory=lambda: _env(
            "ML_SENTIMENT_MODEL",
            "lxyuan/distilbert-base-multilingual-cased-sentiments-student",
        )
    )
    ml_classification_enabled: bool = field(
        default_factory=lambda: _env("ML_CLASSIFICATION_ENABLED", "true").lower()
        in ("true", "1", "yes")
    )
    ml_batch_size: int = field(
        default_factory=lambda: _env_int("ML_BATCH_SIZE", 32)
    )
```

**Step 2: Commit**

```bash
git add backend/app/config.py
git commit -m "feat: add ML classification config flags"
```

---

### Task 3: Create the ML models service

**Files:**
- Create: `backend/app/services/ml_models.py`
- Test: `backend/tests/test_ml_models.py`

**Step 1: Write failing tests**

Create `backend/tests/test_ml_models.py`:

```python
"""Tests for ML-based topic classification and sentiment analysis."""

import pytest
from unittest.mock import patch, MagicMock


class TestClassifyTopicML:
    """Test ML topic classification."""

    def test_returns_list_of_strings(self):
        from app.services.ml_models import classify_topics_ml

        # Single title should return list of topic strings
        results = classify_topics_ml(["Oil prices surge as war intensifies"])
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], list)
        assert all(isinstance(t, str) for t in results[0])

    def test_batch_processing(self):
        from app.services.ml_models import classify_topics_ml

        titles = [
            "President signs new trade deal",
            "Earthquake hits coastal city",
            "NBA finals break viewership records",
        ]
        results = classify_topics_ml(titles)
        assert len(results) == 3

    def test_empty_input(self):
        from app.services.ml_models import classify_topics_ml

        results = classify_topics_ml([])
        assert results == []

    def test_returns_general_for_unclassifiable(self):
        from app.services.ml_models import classify_topics_ml

        results = classify_topics_ml(["asdfghjkl random noise"])
        assert len(results) == 1
        # Should have at least one tag
        assert len(results[0]) >= 1


class TestAnalyzeSentimentML:
    """Test ML sentiment analysis."""

    def test_returns_float_scores(self):
        from app.services.ml_models import analyze_sentiment_ml

        results = analyze_sentiment_ml(["Markets crash amid global fears"])
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], float)
        assert -1.0 <= results[0] <= 1.0

    def test_negative_headline_scores_negative(self):
        from app.services.ml_models import analyze_sentiment_ml

        results = analyze_sentiment_ml(["Devastating earthquake kills hundreds"])
        assert results[0] < 0

    def test_positive_headline_scores_positive(self):
        from app.services.ml_models import analyze_sentiment_ml

        results = analyze_sentiment_ml(["Peace deal signed, celebrations erupt"])
        assert results[0] > 0

    def test_batch_processing(self):
        from app.services.ml_models import analyze_sentiment_ml

        titles = ["War breaks out", "Team wins championship", "Weather is cloudy"]
        results = analyze_sentiment_ml(titles)
        assert len(results) == 3
        assert all(-1.0 <= s <= 1.0 for s in results)

    def test_empty_input(self):
        from app.services.ml_models import analyze_sentiment_ml

        results = analyze_sentiment_ml([])
        assert results == []


class TestFallback:
    """Test graceful fallback when models unavailable."""

    @patch("app.services.ml_models._get_topic_pipeline", return_value=None)
    def test_topic_falls_back_to_keyword(self, _mock):
        from app.services.ml_models import classify_topics_ml

        results = classify_topics_ml(["President signs new law"])
        assert len(results) == 1
        # Should still return valid tags via keyword fallback
        assert isinstance(results[0], list)

    @patch("app.services.ml_models._get_sentiment_pipeline", return_value=None)
    def test_sentiment_falls_back_to_zero(self, _mock):
        from app.services.ml_models import analyze_sentiment_ml

        results = analyze_sentiment_ml(["Some headline"])
        assert len(results) == 1
        assert isinstance(results[0], float)
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ml_models.py -v`
Expected: FAIL — module not found

**Step 3: Implement ml_models.py**

Create `backend/app/services/ml_models.py`:

```python
"""ML-based topic classification and sentiment analysis.

Uses HuggingFace transformers models loaded locally on CPU.
Models are lazy-loaded as singletons on first use.
Falls back to keyword-based classification if models fail to load.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.topic_classifier import classify_topic as _keyword_classify

logger = logging.getLogger("orbis.ml_models")

# Singleton pipeline instances (lazy-loaded)
_topic_pipeline: Any | None = None
_sentiment_pipeline: Any | None = None
_topic_load_attempted = False
_sentiment_load_attempted = False

# Topic labels matching existing Orbis categories
TOPIC_LABELS = [
    "armed conflict and war",
    "politics and government",
    "economy and financial markets",
    "technology and innovation",
    "health and medicine",
    "environment and climate",
    "sports",
]

# Map from descriptive label → Orbis tag
_LABEL_TO_TAG = {
    "armed conflict and war": "conflict",
    "politics and government": "politics",
    "economy and financial markets": "economy",
    "technology and innovation": "technology",
    "health and medicine": "health",
    "environment and climate": "environment",
    "sports": "sports",
}

_TOPIC_THRESHOLD = 0.4  # Minimum confidence to assign a topic


def _get_topic_pipeline() -> Any | None:
    """Lazy-load the zero-shot topic classification pipeline."""
    global _topic_pipeline, _topic_load_attempted
    if _topic_load_attempted:
        return _topic_pipeline
    _topic_load_attempted = True

    if not settings.ml_classification_enabled:
        logger.info("ML classification disabled via config.")
        return None

    try:
        from transformers import pipeline

        logger.info("Loading topic model: %s …", settings.ml_topic_model)
        _topic_pipeline = pipeline(
            "zero-shot-classification",
            model=settings.ml_topic_model,
            device=-1,  # CPU
        )
        logger.info("Topic model loaded.")
        return _topic_pipeline
    except Exception:
        logger.warning("Failed to load topic model — falling back to keywords.", exc_info=True)
        return None


def _get_sentiment_pipeline() -> Any | None:
    """Lazy-load the sentiment analysis pipeline."""
    global _sentiment_pipeline, _sentiment_load_attempted
    if _sentiment_load_attempted:
        return _sentiment_pipeline
    _sentiment_load_attempted = True

    if not settings.ml_classification_enabled:
        logger.info("ML classification disabled via config.")
        return None

    try:
        from transformers import pipeline

        logger.info("Loading sentiment model: %s …", settings.ml_sentiment_model)
        _sentiment_pipeline = pipeline(
            "text-classification",
            model=settings.ml_sentiment_model,
            top_k=None,  # Return all class probabilities
            device=-1,  # CPU
        )
        logger.info("Sentiment model loaded.")
        return _sentiment_pipeline
    except Exception:
        logger.warning("Failed to load sentiment model.", exc_info=True)
        return None


def classify_topics_ml(titles: list[str]) -> list[list[str]]:
    """Classify a batch of titles into topic tags.

    Returns a list of tag lists, one per title.
    Falls back to keyword classification if the ML model is unavailable.
    """
    if not titles:
        return []

    pipe = _get_topic_pipeline()
    if pipe is None:
        return [_keyword_classify(t) for t in titles]

    try:
        results = pipe(
            titles,
            candidate_labels=TOPIC_LABELS,
            multi_label=True,
            batch_size=settings.ml_batch_size,
        )
        # Single input returns a dict, not a list
        if isinstance(results, dict):
            results = [results]

        all_tags: list[list[str]] = []
        for result in results:
            tags = []
            for label, score in zip(result["labels"], result["scores"]):
                if score >= _TOPIC_THRESHOLD:
                    tag = _LABEL_TO_TAG.get(label)
                    if tag:
                        tags.append(tag)
            all_tags.append(tags if tags else ["general"])
        return all_tags

    except Exception:
        logger.error("ML topic classification failed — falling back to keywords.", exc_info=True)
        return [_keyword_classify(t) for t in titles]


def analyze_sentiment_ml(titles: list[str]) -> list[float]:
    """Analyze sentiment for a batch of titles.

    Returns a list of scores from -1.0 (negative) to 1.0 (positive).
    Falls back to 0.0 if the ML model is unavailable.
    """
    if not titles:
        return []

    pipe = _get_sentiment_pipeline()
    if pipe is None:
        return [0.0] * len(titles)

    try:
        results = pipe(titles, batch_size=settings.ml_batch_size)

        scores: list[float] = []
        for result in results:
            # result is a list of dicts: [{"label": "positive", "score": 0.8}, ...]
            prob = {item["label"]: item["score"] for item in result}
            pos = prob.get("positive", 0.0)
            neg = prob.get("negative", 0.0)
            score = pos - neg  # Range: -1.0 to 1.0
            scores.append(round(max(-1.0, min(1.0, score)), 4))
        return scores

    except Exception:
        logger.error("ML sentiment analysis failed.", exc_info=True)
        return [0.0] * len(titles)
```

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_ml_models.py -v`
Expected: PASS (note: first run will download models, ~1GB total)

**Step 5: Commit**

```bash
git add backend/app/services/ml_models.py backend/tests/test_ml_models.py
git commit -m "feat: add ML-based topic classification and sentiment analysis service"
```

---

### Task 4: Integrate ML models into ingestion pipeline

**Files:**
- Modify: `backend/app/services/ingestion.py`
- Modify: `backend/tests/test_ingestion.py`

**Step 1: Write failing test**

Add to `backend/tests/test_ingestion.py`:

```python
class TestMLClassificationIntegration:
    @pytest.mark.asyncio
    async def test_uses_ml_classification_when_enabled(self):
        from app.services.ingestion import _ingest_from_raw_gkg

        articles = [
            _make_gkg_article(url="https://example.com/1", title="Oil prices surge as war intensifies"),
            _make_gkg_article(url="https://example.com/2", title="President signs new trade agreement"),
        ]
        patches = _common_patches(articles)

        with patches["fetch_raw_gkg"], patches["scrape_titles"], \
             patches["upsert_articles"] as mock_upsert, \
             patches["invalidate"], patches["get_pool"], \
             patches["populate_graph"], \
             patch("app.services.ingestion.classify_topics_ml",
                   return_value=[["conflict", "economy"], ["politics"]]) as mock_ml_topic, \
             patch("app.services.ingestion.analyze_sentiment_ml",
                   return_value=[-0.7, 0.2]) as mock_ml_sentiment, \
             patch("app.services.ingestion.settings") as mock_settings:
            mock_settings.ml_classification_enabled = True
            mock_settings.retention_days = 7
            await _ingest_from_raw_gkg()

            mock_ml_topic.assert_called_once()
            mock_ml_sentiment.assert_called_once()
            rows = mock_upsert.call_args[0][0]
            assert rows[0]["topic_tags"] == ["conflict", "economy"]
            assert rows[0]["sentiment_score"] == -0.7
            assert rows[1]["topic_tags"] == ["politics"]
            assert rows[1]["sentiment_score"] == 0.2
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ingestion.py::TestMLClassificationIntegration -v`
Expected: FAIL

**Step 3: Modify ingestion.py**

Replace the per-article classification with batch ML classification. The key changes to `_ingest_from_raw_gkg()`:

1. Add import at top of file:
```python
from app.services.ml_models import classify_topics_ml, analyze_sentiment_ml
```

2. Replace the per-article loop logic. After building the deduplicated `rows` list (using temporary placeholder values for `topic_tags` and `sentiment_score`), add batch ML classification:

Change the loop body (lines 63-68) from:
```python
        # Sentiment from GKG tone (scale is roughly -10 to +10)
        tone = a.get("tone", 0.0)
        sentiment = max(-1.0, min(1.0, tone / 10.0))

        # Topic classification from title
        topic_tags = classify_topic(title)
```

To:
```python
        # Placeholders — will be overwritten by batch ML below
        topic_tags = ["general"]
        sentiment = 0.0
```

Then after the `rows` list is built and before the `if not rows:` check, add:

```python
    # Batch ML classification (replaces per-article keyword matching)
    if settings.ml_classification_enabled:
        titles = [r["title"] for r in rows]
        all_topics = classify_topics_ml(titles)
        all_sentiments = analyze_sentiment_ml(titles)
        for row, topics, sent in zip(rows, all_topics, all_sentiments):
            row["topic_tags"] = topics
            row["sentiment_score"] = sent
    else:
        # Fallback: keyword topic + GDELT tone
        for row, a in zip(rows, [a for a in articles if a.get("title")]):
            row["topic_tags"] = classify_topic(row["title"])
            tone = a.get("tone", 0.0)
            row["sentiment_score"] = max(-1.0, min(1.0, tone / 10.0))
```

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_ingestion.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/services/ingestion.py backend/tests/test_ingestion.py
git commit -m "feat: integrate ML classification into ingestion pipeline"
```

---

### Task 5: Update existing topic classifier tests

**Files:**
- Modify: `backend/tests/test_topic_classifier.py`

**Step 1: Ensure keyword tests still pass**

The keyword classifier still exists as a fallback, so existing tests should still pass unchanged.

Run: `cd backend && python -m pytest tests/test_topic_classifier.py -v`
Expected: ALL PASS

**Step 2: Commit (if any changes needed)**

No commit expected unless tests needed fixing.

---

### Task 6: Add model preloading to startup (optional optimization)

**Files:**
- Modify: `backend/app/main.py`

**Step 1: Add model warm-up to startup**

In `backend/app/main.py`, add after the existing startup logic:

```python
    # Pre-load ML models in background so first ingestion isn't slow
    async def _warmup_ml():
        try:
            from app.services.ml_models import classify_topics_ml, analyze_sentiment_ml
            classify_topics_ml(["warmup"])
            analyze_sentiment_ml(["warmup"])
            logger.info("ML models warmed up.")
        except Exception:
            logger.warning("ML model warmup failed — will retry on first use.")

    asyncio.create_task(_warmup_ml())
```

**Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: pre-load ML models on startup for faster first ingestion"
```

---

### Task 7: End-to-end manual verification

**Step 1: Start the backend**

Run: `cd backend && uvicorn app.main:app --reload`

Watch logs for:
- `"Loading topic model: MoritzLaurer/deberta-v3-base-zeroshot-v2.0 …"`
- `"Topic model loaded."`
- `"Loading sentiment model: lxyuan/distilbert-base-multilingual-cased-sentiments-student …"`
- `"Sentiment model loaded."`

**Step 2: Wait for ingestion cycle**

Watch for: `"GKG ingestion: upserted N articles"`

**Step 3: Spot-check via database**

Run a query to verify topic_tags and sentiment_score look reasonable:
```sql
SELECT title, topic_tags, sentiment_score
FROM articles
ORDER BY ingested_at DESC
LIMIT 10;
```

Expect: More accurate topic assignments (e.g., an article about "Iran attacks oil facilities" should get both `conflict` and `economy`, not just `conflict`). Sentiment scores should be more nuanced than the old -0.3/-0.6/0.4/0.7 buckets.

**Step 4: Verify performance**

Check ingestion cycle duration in logs. Should complete within ~3-4 minutes total (scraping + ML classification + embedding).

---

## Architecture Notes

**Memory footprint:** ~950MB combined (DeBERTa ~700MB + DistilBERT ~250MB). Both stay resident after first load.

**Fallback chain:**
1. If `ML_CLASSIFICATION_ENABLED=false` → keyword classifier + GDELT tone (old behavior)
2. If model fails to load → keyword classifier + 0.0 sentiment (logged warning)
3. If batch inference fails → keyword classifier + 0.0 sentiment (logged error)

**Performance budget (1000 articles on CPU):**
- Sentiment (DistilBERT, batch_size=32): ~15 seconds
- Topic (DeBERTa zero-shot, 7 labels, batch_size=32): ~1-3 minutes
- Total ML overhead: ~1.5-3.5 minutes (within budget)

**Future optimizations if needed:**
- ONNX export via `optimum` for ~30% CPU speedup
- INT8 dynamic quantization for ~2x speedup
- Reduce topic labels (fewer NLI forward passes)
