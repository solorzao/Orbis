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

        def _dynamic_post(*args, **kwargs):
            n = len(kwargs.get("json", {}).get("titles", []))
            return _mock_response({"topics": [["general"]] * n, "timing_ms": 50})

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(side_effect=_dynamic_post)

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

        def _dynamic_post(*args, **kwargs):
            n = len(kwargs.get("json", {}).get("titles", []))
            return _mock_response({"sentiments": [0.0] * n, "timing_ms": 30})

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(side_effect=_dynamic_post)

        with patch("app.services.ml_models.settings", **_ML_SETTINGS):
            with patch("app.services.ml_models.httpx.AsyncClient", return_value=client):
                with patch("app.services.ml_models._CHUNK_SIZE", 100):
                    titles = [f"headline {i}" for i in range(250)]
                    result = await analyze_sentiment_ml(titles)

        assert len(result) == 250
        assert client.post.call_count == 3
