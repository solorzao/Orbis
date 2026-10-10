"""Tests for the two-step agent pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent import (
    RETRIEVAL_TOOLS,
    plan_retrieval,
    synthesize_answer,
)


def _block(type_: str, **fields):
    block = MagicMock()
    block.type = type_
    for k, v in fields.items():
        setattr(block, k, v)
    return block


def _make_mock_response(text: str, *, thinking_first: bool = False, stop_reason: str = "end_turn"):
    """Build a mock Anthropic messages response.

    Haiku 5.5 thinks by default, so real responses can start with a
    ``thinking`` block (with empty text) before the answer.
    """
    content = [_block("thinking", thinking="", signature="sig")] if thinking_first else []
    if text:
        content.append(_block("text", text=text))
    response = MagicMock()
    response.content = content
    response.stop_reason = stop_reason
    return response


@pytest.mark.asyncio
async def test_plan_retrieval_returns_tool_calls():
    """plan_retrieval should parse the Haiku JSON response into tool calls."""
    haiku_json = '{"tools": [{"name": "keyword_search", "args": {"terms": "earthquake"}}]}'
    mock_response = _make_mock_response(haiku_json)

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        result = await plan_retrieval("latest earthquake news")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["name"] == "keyword_search"
    assert result[0]["args"]["terms"] == "earthquake"


@pytest.mark.asyncio
async def test_synthesize_answer_returns_structured_response():
    """synthesize_answer should return answer, citations, and globe_actions."""
    sonnet_json = (
        '{"answer": "An earthquake hit Turkey [1].", '
        '"citations": [{"index": 1, "title": "Turkey quake", "source_url": "https://example.com"}], '
        '"globe_actions": [{"lat": 38.0, "lng": 34.0, "label": "Turkey"}]}'
    )
    mock_response = _make_mock_response(sonnet_json)

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        result = await synthesize_answer(
            "What happened in Turkey?",
            "[1] Turkey quake\n  URL: https://example.com",
        )

    assert "earthquake" in result["answer"].lower()
    assert len(result["citations"]) == 1
    assert result["citations"][0]["source_url"] == "https://example.com"
    assert len(result["globe_actions"]) == 1
    assert result["globe_actions"][0]["lat"] == 38.0


def test_retrieval_tools_schema():
    """RETRIEVAL_TOOLS should contain all 5 retrieval functions."""
    names = {t["name"] for t in RETRIEVAL_TOOLS}
    expected = {
        "semantic_search",
        "graph_traverse",
        "keyword_search",
        "trending_topics",
        "entity_lookup",
        "read_article",
    }
    assert names == expected

    # Each tool should have description and parameters
    for tool in RETRIEVAL_TOOLS:
        assert "description" in tool
        assert "parameters" in tool
        assert isinstance(tool["parameters"], dict)


@pytest.mark.asyncio
async def test_plan_retrieval_reads_text_after_thinking_block():
    """A leading thinking block must not be mistaken for the answer."""
    haiku_json = '{"tools": [{"name": "keyword_search", "args": {"terms": "flood"}}]}'
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_mock_response(haiku_json, thinking_first=True)
    )

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        result = await plan_retrieval("flood news")

    assert result == [{"name": "keyword_search", "args": {"terms": "flood"}}]
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["output_config"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_synthesize_answer_reads_text_after_thinking_block():
    answer_json = '{"answer": "Floods in Spain [1].", "citations": [], "globe_actions": []}'
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_mock_response(answer_json, thinking_first=True)
    )

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        result = await synthesize_answer("Spain?", "[1] Floods")

    assert result["answer"] == "Floods in Spain [1]."


@pytest.mark.asyncio
async def test_synthesize_answer_handles_refusal():
    """A refusal (HTTP 200, stop_reason=refusal, no text) returns the polite fallback."""
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_mock_response("", thinking_first=True, stop_reason="refusal")
    )

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        result = await synthesize_answer("anything", "context")

    assert result["answer"] == "I'm sorry, I couldn't generate an answer right now."
    assert result["citations"] == []
