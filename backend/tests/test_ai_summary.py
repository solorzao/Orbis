"""Tests for the Claude call used by cluster and selection summaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import ai_summary


def _response(blocks: list[tuple[str, str]], stop_reason: str = "end_turn"):
    content = []
    for type_, text in blocks:
        block = MagicMock()
        block.type = type_
        if type_ == "text":
            block.text = text
        else:
            block.thinking = text
        content.append(block)
    response = MagicMock()
    response.content = content
    response.stop_reason = stop_reason
    return response


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ai_summary.settings, "anthropic_api_key", "test-key")
    mock = MagicMock()
    mock.messages.create = AsyncMock()
    with patch("app.services.ai_summary.anthropic.AsyncAnthropic", return_value=mock):
        yield mock


@pytest.mark.asyncio
async def test_returns_text_after_thinking_block(client):
    client.messages.create.return_value = _response(
        [("thinking", ""), ("text", "  Protests continue in the capital.  ")]
    )

    assert await ai_summary._call_claude("Headlines: ...") == "Protests continue in the capital."
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["output_config"] == {"effort": "low"}
    assert kwargs["max_tokens"] >= 1024  # room for thinking plus the summary


@pytest.mark.asyncio
async def test_refusal_returns_fallback(client):
    client.messages.create.return_value = _response([("thinking", "")], stop_reason="refusal")

    assert await ai_summary._call_claude("Headlines: ...") == "Summary generation failed."


def _article(title: str):
    from datetime import datetime, timezone

    from app.models.news import NewsArticle

    now = datetime.now(timezone.utc)
    return NewsArticle(
        id="1",
        title=title,
        source_url="https://example.com/a",
        source_name="Example",
        published_at=now,
        ingested_at=now,
        latitude=38.9,
        longitude=-77.0,
    )


@pytest.mark.asyncio
async def test_cluster_summary_without_place_name_sends_no_coordinates(monkeypatch):
    """Haiku 5.5 narrates working out raw coordinates; send none."""
    sent = {}

    async def fake_call(user_message, system=None):
        sent["msg"] = user_message
        return "Summary."

    async def no_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr(ai_summary, "_call_claude", fake_call)
    monkeypatch.setattr(ai_summary, "get_cached", no_cache)
    monkeypatch.setattr(ai_summary, "set_cached", no_cache)

    await ai_summary.summarise_cluster(
        [_article("City official killed in Southeast DC")], 38.5, -77.5
    )

    assert "°" not in sent["msg"]
    assert "Location:" not in sent["msg"]
    assert "City official killed" in sent["msg"]


@pytest.mark.asyncio
async def test_cluster_summary_cache_key_is_versioned(monkeypatch):
    keys = []

    async def get_cached(key):
        keys.append(key)
        return "cached"

    monkeypatch.setattr(ai_summary, "get_cached", get_cached)
    await ai_summary.summarise_cluster([_article("x")], 38.5, -77.5, location_name="Washington")
    assert keys[0].startswith("summary:v2:")
