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
