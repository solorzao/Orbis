"""Tests for the two-step agent pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent import (
    RETRIEVAL_TOOLS,
    plan_retrieval,
    synthesize_answer,
)


def _make_mock_response(text: str):
    """Build a mock Anthropic messages response."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
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
