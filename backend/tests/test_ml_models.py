"""Tests for ML-based topic classification and sentiment analysis.

All tests mock the HuggingFace pipelines so they run fast without
downloading models.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.ml_models import (
    _LABEL_TO_TAG,
    _NLI_LABELS,
    analyze_sentiment_ml,
    classify_topics_ml,
    reset_pipelines,
)


@pytest.fixture(autouse=True)
def _reset():
    """Ensure singleton pipelines are clean before each test."""
    reset_pipelines()
    yield
    reset_pipelines()


# ---------------------------------------------------------------------------
# Helpers — fake pipeline callables
# ---------------------------------------------------------------------------


def _make_topic_output(labels: list[str], scores: list[float]) -> dict:
    return {"labels": labels, "scores": scores}


def _fake_topic_pipeline(texts, *, candidate_labels=None, multi_label=False):
    """Return a plausible zero-shot output for each text."""
    results = []
    for text in (texts if isinstance(texts, list) else [texts]):
        text_lower = text.lower()
        scores = []
        for label in _NLI_LABELS:
            # Give 0.8 to any label whose Orbis tag appears in the title
            tag = _LABEL_TO_TAG[label]
            scores.append(0.8 if tag in text_lower else 0.1)
        results.append({"labels": _NLI_LABELS, "scores": scores})
    return results


def _fake_sentiment_pipeline(texts):
    """Return fake sentiment scores based on keywords."""
    results = []
    for text in texts:
        text_lower = text.lower()
        if any(w in text_lower for w in ("great", "victory", "peace", "wonderful")):
            scores = [
                {"label": "positive", "score": 0.85},
                {"label": "neutral", "score": 0.10},
                {"label": "negative", "score": 0.05},
            ]
        elif any(w in text_lower for w in ("war", "crisis", "disaster", "killed")):
            scores = [
                {"label": "positive", "score": 0.05},
                {"label": "neutral", "score": 0.10},
                {"label": "negative", "score": 0.85},
            ]
        else:
            scores = [
                {"label": "positive", "score": 0.33},
                {"label": "neutral", "score": 0.34},
                {"label": "negative", "score": 0.33},
            ]
        results.append(scores)
    return results


# ---------------------------------------------------------------------------
# Topic classification tests
# ---------------------------------------------------------------------------


class TestClassifyTopicsMl:
    def test_empty_input(self):
        assert classify_topics_ml([]) == []

    @patch("app.services.ml_models._get_topic_pipeline")
    def test_returns_correct_types_and_shapes(self, mock_get):
        mock_get.return_value = _fake_topic_pipeline
        titles = ["conflict in the region", "new technology unveiled", "some random headline"]
        result = classify_topics_ml(titles)

        assert len(result) == 3
        for tags in result:
            assert isinstance(tags, list)
            for tag in tags:
                assert isinstance(tag, str)

    @patch("app.services.ml_models._get_topic_pipeline")
    def test_assigns_matching_topic(self, mock_get):
        mock_get.return_value = _fake_topic_pipeline
        result = classify_topics_ml(["conflict escalates in the region"])
        assert result == [["conflict"]]

    @patch("app.services.ml_models._get_topic_pipeline")
    def test_assigns_general_when_no_match(self, mock_get):
        """When no label exceeds threshold, fall back to 'general'."""

        def pipeline_low_scores(texts, *, candidate_labels=None, multi_label=False):
            return [{"labels": _NLI_LABELS, "scores": [0.1] * len(_NLI_LABELS)} for _ in texts]

        mock_get.return_value = pipeline_low_scores
        result = classify_topics_ml(["a completely ambiguous headline"])
        assert result == [["general"]]

    @patch("app.services.ml_models._get_topic_pipeline")
    def test_fallback_when_pipeline_is_none(self, mock_get):
        """When the pipeline fails to load (returns None), use keyword fallback."""
        mock_get.return_value = None
        result = classify_topics_ml(["President signs new legislation"])
        assert "politics" in result[0]

    @patch("app.services.ml_models._get_topic_pipeline")
    def test_batch_processing_multiple_batches(self, mock_get):
        """Titles exceeding batch_size are split into multiple batches."""
        mock_get.return_value = _fake_topic_pipeline
        titles = [f"headline {i}" for i in range(50)]
        with patch("app.services.ml_models.settings") as mock_settings:
            mock_settings.ml_classification_enabled = True
            mock_settings.ml_batch_size = 10
            result = classify_topics_ml(titles)
        assert len(result) == 50

    def test_disabled_flag_uses_keyword_fallback(self):
        """When ml_classification_enabled is False, use keyword classifier."""
        with patch("app.services.ml_models.settings") as mock_settings:
            mock_settings.ml_classification_enabled = False
            result = classify_topics_ml(["President announces new policy"])
        assert "politics" in result[0]


# ---------------------------------------------------------------------------
# Sentiment analysis tests
# ---------------------------------------------------------------------------


class TestAnalyzeSentimentMl:
    def test_empty_input(self):
        assert analyze_sentiment_ml([]) == []

    @patch("app.services.ml_models._get_sentiment_pipeline")
    def test_returns_correct_types_and_shapes(self, mock_get):
        mock_get.return_value = _fake_sentiment_pipeline
        titles = ["Great news", "War erupts", "Weather today"]
        result = analyze_sentiment_ml(titles)

        assert len(result) == 3
        for score in result:
            assert isinstance(score, float)
            assert -1.0 <= score <= 1.0

    @patch("app.services.ml_models._get_sentiment_pipeline")
    def test_positive_headline_scores_positive(self, mock_get):
        mock_get.return_value = _fake_sentiment_pipeline
        result = analyze_sentiment_ml(["Great victory for peace"])
        assert result[0] > 0.0

    @patch("app.services.ml_models._get_sentiment_pipeline")
    def test_negative_headline_scores_negative(self, mock_get):
        mock_get.return_value = _fake_sentiment_pipeline
        result = analyze_sentiment_ml(["War and disaster strike the region"])
        assert result[0] < 0.0

    @patch("app.services.ml_models._get_sentiment_pipeline")
    def test_neutral_headline_near_zero(self, mock_get):
        mock_get.return_value = _fake_sentiment_pipeline
        result = analyze_sentiment_ml(["Some ordinary headline"])
        assert abs(result[0]) < 0.1

    @patch("app.services.ml_models._get_sentiment_pipeline")
    def test_scores_rounded_to_four_decimal_places(self, mock_get):
        mock_get.return_value = _fake_sentiment_pipeline
        result = analyze_sentiment_ml(["Great news"])
        for score in result:
            # Check that string representation has at most 4 decimal places
            parts = str(score).split(".")
            if len(parts) == 2:
                assert len(parts[1]) <= 4

    @patch("app.services.ml_models._get_sentiment_pipeline")
    def test_fallback_when_pipeline_is_none(self, mock_get):
        """When the pipeline fails to load, return 0.0 for all."""
        mock_get.return_value = None
        result = analyze_sentiment_ml(["Terrible disaster", "Great victory"])
        assert result == [0.0, 0.0]

    @patch("app.services.ml_models._get_sentiment_pipeline")
    def test_batch_processing_multiple_batches(self, mock_get):
        mock_get.return_value = _fake_sentiment_pipeline
        titles = [f"headline {i}" for i in range(50)]
        with patch("app.services.ml_models.settings") as mock_settings:
            mock_settings.ml_classification_enabled = True
            mock_settings.ml_batch_size = 10
            result = analyze_sentiment_ml(titles)
        assert len(result) == 50

    def test_disabled_flag_returns_zeros(self):
        with patch("app.services.ml_models.settings") as mock_settings:
            mock_settings.ml_classification_enabled = False
            result = analyze_sentiment_ml(["Great news", "Bad news"])
        assert result == [0.0, 0.0]
