# Azure Functions ML Classification Migration

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move ML topic classification and sentiment analysis from in-process (container) to Azure Functions, replacing the slow zero-shot DeBERTa model with a fast single-pass NYT-trained RoBERTa model + keyword supplement for missing categories.

**Architecture:** Two HTTP-triggered Azure Functions (topic + sentiment) in a single Function App, called from the existing `ml_models.py` service via HTTP. The container stays lightweight (0.25 CPU / 0.5 Gi) while the Function App handles model inference with its own memory. Ingestion calls both functions in parallel with chunked batches for throughput.

**Tech Stack:** Azure Functions (Python v2 programming model), HuggingFace transformers, `dstefa/roberta-base_topic_classification_nyt_news` (topic), `lxyuan/distilbert-base-multilingual-cased-sentiments-student` (sentiment), `httpx` (async HTTP client, already in requirements).

---

### Task 1: Create Azure Function App project structure

**Files:**
- Create: `functions/ml-classify/function_app.py`
- Create: `functions/ml-classify/requirements.txt`
- Create: `functions/ml-classify/host.json`

**Step 1: Create the Function App entry point**

The function app has two HTTP-triggered functions. Models are lazy-loaded as singletons (same pattern as current `ml_models.py`). The topic function uses the NYT RoBERTa model (single-pass, 8 labels) + keyword supplement for conflict/environment.

```python
# functions/ml-classify/function_app.py
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
```

**Step 2: Create requirements.txt for the Function App**

```txt
# functions/ml-classify/requirements.txt
azure-functions
torch>=2.0.0
transformers>=4.40.0
```

**Step 3: Create host.json with extended timeout**

```json
{
  "version": "2.0",
  "functionTimeout": "00:10:00",
  "logging": {
    "logLevel": {
      "default": "Information",
      "Function": "Information"
    }
  },
  "extensions": {
    "http": {
      "routePrefix": "api"
    }
  }
}
```

**Step 4: Verify files exist**

Run: `ls functions/ml-classify/`
Expected: `function_app.py  host.json  requirements.txt`

**Step 5: Commit**

```bash
git add functions/ml-classify/
git commit -m "feat: add Azure Functions project for ML classification"
```

---

### Task 2: Update config.py with Function App URL setting

**Files:**
- Modify: `backend/app/config.py:53-71`

**Step 1: Write the failing test**

```python
# In backend/tests/test_config.py (or inline check)
# Verify that settings has ml_functions_url attribute
from app.config import settings
assert hasattr(settings, "ml_functions_url")
assert hasattr(settings, "ml_functions_key")
```

**Step 2: Add config fields**

Add these two fields to the `Settings` class in `backend/app/config.py`, inside the `# --- ML classification ---` section, after `ml_batch_size`:

```python
    ml_functions_url: str = field(
        default_factory=lambda: _env("ML_FUNCTIONS_URL", "")
    )
    ml_functions_key: str = field(
        default_factory=lambda: _env("ML_FUNCTIONS_KEY", "")
    )
```

The logic will be:
- If `ml_classification_enabled=True` AND `ml_functions_url` is set → call Azure Functions
- If `ml_classification_enabled=True` AND `ml_functions_url` is empty → load models locally (current behavior, for local dev)
- If `ml_classification_enabled=False` → keyword fallback (current behavior)

**Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat: add ML_FUNCTIONS_URL and ML_FUNCTIONS_KEY config settings"
```

---

### Task 3: Rewrite ml_models.py to call Azure Functions

**Files:**
- Modify: `backend/app/services/ml_models.py` (full rewrite)
- Reference: `backend/app/services/topic_classifier.py` (keyword fallback, unchanged)

**Step 1: Write the failing test for HTTP-based classification**

Add a new test class to `backend/tests/test_ml_models.py`:

```python
import httpx
from unittest.mock import AsyncMock, patch, MagicMock


class TestClassifyTopicsRemote:
    """Tests for Azure Functions-based topic classification."""

    @pytest.mark.asyncio
    async def test_calls_function_url(self):
        """When ml_functions_url is set, calls the remote function."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "topics": [["politics"], ["economy"]],
            "timing_ms": 100,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.ml_models.settings") as mock_settings:
            mock_settings.ml_classification_enabled = True
            mock_settings.ml_functions_url = "https://my-func.azurewebsites.net/api"
            mock_settings.ml_functions_key = "test-key"
            mock_settings.ml_batch_size = 100

            with patch("app.services.ml_models.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                from app.services.ml_models import classify_topics_ml
                result = await classify_topics_ml(["title 1", "title 2"])

        assert result == [["politics"], ["economy"]]

    @pytest.mark.asyncio
    async def test_empty_input(self):
        from app.services.ml_models import classify_topics_ml
        result = await classify_topics_ml([])
        assert result == []

    @pytest.mark.asyncio
    async def test_falls_back_on_http_error(self):
        """When the function returns an error, fall back to keyword classifier."""
        with patch("app.services.ml_models.settings") as mock_settings:
            mock_settings.ml_classification_enabled = True
            mock_settings.ml_functions_url = "https://my-func.azurewebsites.net/api"
            mock_settings.ml_functions_key = "test-key"
            mock_settings.ml_batch_size = 100

            with patch("app.services.ml_models.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(side_effect=httpx.HTTPError("timeout"))
                mock_client_cls.return_value = mock_client

                from app.services.ml_models import classify_topics_ml
                result = await classify_topics_ml(["President signs treaty"])

        assert "politics" in result[0]
```

**Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ml_models.py::TestClassifyTopicsRemote -v`
Expected: FAIL (functions are still sync, no httpx calls)

**Step 3: Rewrite ml_models.py**

Replace the full contents of `backend/app/services/ml_models.py`:

```python
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
```

**Key changes:**
- Both functions are now `async`
- HTTP calls to Azure Functions via `httpx.AsyncClient`
- Chunked parallel calls (Option C) — splits into batches of 100, fires all in parallel
- Graceful per-chunk fallback to keyword classifier on HTTP errors
- Removed all local model loading code (`_get_topic_pipeline`, `_get_sentiment_pipeline`, `reset_pipelines`, transformers import)
- Detailed timing logs preserved

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ml_models.py -v`
Expected: New remote tests PASS, old tests need updating (next task)

**Step 5: Commit**

```bash
git add backend/app/services/ml_models.py
git commit -m "feat: rewrite ml_models to call Azure Functions via HTTP"
```

---

### Task 4: Update tests for the new async HTTP-based ml_models

**Files:**
- Modify: `backend/tests/test_ml_models.py` (full rewrite)

**Step 1: Rewrite the test file**

The old tests mocked local HuggingFace pipelines. The new tests mock `httpx.AsyncClient` since all inference is now remote. Replace the full contents of `backend/tests/test_ml_models.py`:

```python
"""Tests for ML-based topic classification and sentiment analysis.

All tests mock HTTP calls to Azure Functions so they run without
a live function app.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.ml_models import analyze_sentiment_ml, classify_topics_ml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


def _mock_client(post_return: MagicMock | Exception) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if isinstance(post_return, Exception):
        client.post = AsyncMock(side_effect=post_return)
    else:
        client.post = AsyncMock(return_value=post_return)
    return client


_ML_SETTINGS = {
    "ml_classification_enabled": True,
    "ml_functions_url": "https://my-func.azurewebsites.net/api",
    "ml_functions_key": "test-key",
    "ml_batch_size": 100,
}


# ---------------------------------------------------------------------------
# Topic classification tests
# ---------------------------------------------------------------------------


class TestClassifyTopicsMl:
    @pytest.mark.asyncio
    async def test_empty_input(self):
        assert await classify_topics_ml([]) == []

    @pytest.mark.asyncio
    async def test_disabled_flag_uses_keyword_fallback(self):
        with patch("app.services.ml_models.settings") as s:
            s.ml_classification_enabled = False
            result = await classify_topics_ml(["President announces new policy"])
        assert "politics" in result[0]

    @pytest.mark.asyncio
    async def test_no_url_uses_keyword_fallback(self):
        with patch("app.services.ml_models.settings") as s:
            s.ml_classification_enabled = True
            s.ml_functions_url = ""
            result = await classify_topics_ml(["President announces new policy"])
        assert "politics" in result[0]

    @pytest.mark.asyncio
    async def test_calls_function_and_returns_topics(self):
        resp = _mock_response({"topics": [["politics"], ["economy"]], "timing_ms": 50})
        client = _mock_client(resp)

        with patch("app.services.ml_models.settings", **_ML_SETTINGS):
            with patch("app.services.ml_models.httpx.AsyncClient", return_value=client):
                result = await classify_topics_ml(["title 1", "title 2"])

        assert result == [["politics"], ["economy"]]

    @pytest.mark.asyncio
    async def test_http_error_falls_back_to_keywords(self):
        client = _mock_client(httpx.ConnectError("timeout"))

        with patch("app.services.ml_models.settings", **_ML_SETTINGS):
            with patch("app.services.ml_models.httpx.AsyncClient", return_value=client):
                result = await classify_topics_ml(["President signs treaty"])

        assert "politics" in result[0]

    @pytest.mark.asyncio
    async def test_chunked_parallel_calls(self):
        """Titles exceeding _CHUNK_SIZE are split into parallel HTTP calls."""
        resp = _mock_response({"topics": [["general"]] * 100, "timing_ms": 50})
        client = _mock_client(resp)

        with patch("app.services.ml_models.settings", **_ML_SETTINGS):
            with patch("app.services.ml_models.httpx.AsyncClient", return_value=client):
                with patch("app.services.ml_models._CHUNK_SIZE", 100):
                    titles = [f"headline {i}" for i in range(250)]
                    result = await classify_topics_ml(titles)

        assert len(result) == 250
        # Should have been 3 chunks: 100 + 100 + 50
        assert client.post.call_count == 3


# ---------------------------------------------------------------------------
# Sentiment analysis tests
# ---------------------------------------------------------------------------


class TestAnalyzeSentimentMl:
    @pytest.mark.asyncio
    async def test_empty_input(self):
        assert await analyze_sentiment_ml([]) == []

    @pytest.mark.asyncio
    async def test_disabled_flag_returns_zeros(self):
        with patch("app.services.ml_models.settings") as s:
            s.ml_classification_enabled = False
            result = await analyze_sentiment_ml(["Great news", "Bad news"])
        assert result == [0.0, 0.0]

    @pytest.mark.asyncio
    async def test_calls_function_and_returns_scores(self):
        resp = _mock_response({"sentiments": [0.8, -0.5], "timing_ms": 30})
        client = _mock_client(resp)

        with patch("app.services.ml_models.settings", **_ML_SETTINGS):
            with patch("app.services.ml_models.httpx.AsyncClient", return_value=client):
                result = await analyze_sentiment_ml(["Good news", "Bad news"])

        assert result == [0.8, -0.5]

    @pytest.mark.asyncio
    async def test_http_error_returns_zeros(self):
        client = _mock_client(httpx.ConnectError("timeout"))

        with patch("app.services.ml_models.settings", **_ML_SETTINGS):
            with patch("app.services.ml_models.httpx.AsyncClient", return_value=client):
                result = await analyze_sentiment_ml(["Good news", "Bad news"])

        assert result == [0.0, 0.0]

    @pytest.mark.asyncio
    async def test_chunked_parallel_calls(self):
        resp = _mock_response({"sentiments": [0.0] * 100, "timing_ms": 30})
        client = _mock_client(resp)

        with patch("app.services.ml_models.settings", **_ML_SETTINGS):
            with patch("app.services.ml_models.httpx.AsyncClient", return_value=client):
                with patch("app.services.ml_models._CHUNK_SIZE", 100):
                    titles = [f"headline {i}" for i in range(250)]
                    result = await analyze_sentiment_ml(titles)

        assert len(result) == 250
        assert client.post.call_count == 3
```

**Step 2: Run all tests**

Run: `cd backend && python -m pytest tests/test_ml_models.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add backend/tests/test_ml_models.py
git commit -m "test: update ml_models tests for async HTTP-based classification"
```

---

### Task 5: Update ingestion.py to await async ML functions

**Files:**
- Modify: `backend/app/services/ingestion.py:93-99`

**Step 1: Write the change**

The calls to `classify_topics_ml` and `analyze_sentiment_ml` are now async. Update `_ingest_from_raw_gkg` to `await` them and run both in parallel with `asyncio.gather`:

Replace lines 92-99 in `ingestion.py`:

```python
    # Batch ML classification (replaces per-article keyword matching)
    if settings.ml_classification_enabled:
        titles = [r["title"] for r in rows]
        all_topics, all_sentiments = await asyncio.gather(
            classify_topics_ml(titles),
            analyze_sentiment_ml(titles),
        )
        for row, topics, sent in zip(rows, all_topics, all_sentiments):
            row["topic_tags"] = topics
            row["sentiment_score"] = sent
```

Also add `import asyncio` at the top of the file (after `import re`).

**Step 2: Run ingestion tests**

Run: `cd backend && python -m pytest tests/ -v -k ingestion`
Expected: PASS (or no ingestion-specific tests — verify manually)

**Step 3: Commit**

```bash
git add backend/app/services/ingestion.py
git commit -m "feat: await async ML functions and run topic+sentiment in parallel"
```

---

### Task 6: Remove torch/transformers from container requirements

**Files:**
- Modify: `backend/requirements.txt` (remove lines 58-60)

**Step 1: Remove the heavy dependencies**

Remove these two lines from `backend/requirements.txt`:

```
torch>=2.0.0
transformers>=4.40.0
```

This saves ~2GB from the Docker image. The models now run in the Azure Function, not the container.

**Step 2: Verify no remaining local imports**

Run: `grep -r "from transformers" backend/app/`
Expected: No matches (all transformers usage is now in `functions/ml-classify/`)

Run: `grep -r "import torch" backend/app/`
Expected: No matches

**Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: remove torch/transformers from container (moved to Azure Functions)"
```

---

### Task 7: Add Azure environment variables and deploy instructions

**Files:**
- Modify: `backend/app/config.py` (already done in Task 2)

**Step 1: Document the required Azure setup**

After deploying the Function App, the container needs two new env vars:

| Variable | Value | Source |
|---|---|---|
| `ML_FUNCTIONS_URL` | `https://<your-func-app>.azurewebsites.net/api` | Azure Portal → Function App → Overview |
| `ML_FUNCTIONS_KEY` | The default function key | Azure Portal → Function App → App Keys → default |
| `ML_CLASSIFICATION_ENABLED` | `true` | Already set |

**Step 2: Deploy the Azure Function**

Run from the `functions/ml-classify/` directory:

```bash
# Create the Function App (Consumption plan, Python 3.12)
az functionapp create \
  --resource-group rg-orbis \
  --consumption-plan-location eastus \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --name orbis-ml-classify \
  --storage-account <your-storage-account>

# Deploy the function code
cd functions/ml-classify
func azure functionapp publish orbis-ml-classify
```

**Step 3: Test the deployed functions**

```bash
# Test topic classification
curl -X POST "https://orbis-ml-classify.azurewebsites.net/api/classify-topics?code=<function-key>" \
  -H "Content-Type: application/json" \
  -d '{"titles": ["President signs new trade deal", "Oil prices surge on Iran tensions"]}'

# Expected response:
# {"topics": [["politics"], ["economy"]], "timing_ms": ...}

# Test sentiment analysis
curl -X POST "https://orbis-ml-classify.azurewebsites.net/api/analyze-sentiment?code=<function-key>" \
  -H "Content-Type: application/json" \
  -d '{"titles": ["Great victory for peace", "War devastates the region"]}'

# Expected response:
# {"sentiments": [0.75, -0.8], "timing_ms": ...}
```

**Step 4: Set env vars in Azure Container App**

In Azure Portal → orbis-api → Containers → Environment variables:
- Add `ML_FUNCTIONS_URL` = `https://orbis-ml-classify.azurewebsites.net/api`
- Add `ML_FUNCTIONS_KEY` = (the function key from Azure Portal)
- Set `ML_CLASSIFICATION_ENABLED` = `true`

**Step 5: Commit**

```bash
git add .
git commit -m "docs: add Azure Functions deployment instructions for ML classification"
```

---

## Summary of changes

| Component | Before | After |
|---|---|---|
| Topic model | DeBERTa zero-shot (7 NLI passes, ~700MB) | RoBERTa NYT single-pass (~500MB) + keyword supplement |
| Sentiment model | DistilBERT (in-process) | DistilBERT (Azure Function) |
| Container size | 0.25 CPU / 0.5 Gi (OOM with models) | 0.25 CPU / 0.5 Gi (no models, just HTTP calls) |
| Inference time (500 articles) | ~4-8 min (DeBERTa zero-shot) | ~1-1.5 min (single-pass + parallel chunks) |
| Cost | ~$78/month (1 CPU / 2 Gi container) | ~$29/month (small container + consumption functions) |
| Docker image | ~3GB (with torch) | ~1GB (no torch) |
| Fallback | Keyword classifier (in-process) | Keyword classifier (in-process, unchanged) |
