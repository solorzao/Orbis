"""Tests for the two-step agent pipeline."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.agent import AskRequest, ask_stream_endpoint
from app.services import llm_budget
from app.services.agent import (
    RETRIEVAL_TOOLS,
    _normalize_globe_actions,
    ask,
    plan_retrieval,
    synthesize_answer,
)

_PAUSED = "AI answers are paused until 00:00 UTC (daily limit reached)."


@pytest.fixture(autouse=True)
def budget(monkeypatch):
    """Stub the spend counter (tested in test_llm_budget.py) so no test touches Redis."""
    stub = SimpleNamespace(has_budget=AsyncMock(return_value=True), record=AsyncMock())
    monkeypatch.setattr(llm_budget, "has_budget", stub.has_budget)
    monkeypatch.setattr(llm_budget, "record", stub.record)
    return stub


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
    assert result["globe_actions"][0] == {
        "type": "flyTo",
        "lat": 38.0,
        "lng": 34.0,
        "label": "Turkey",
    }


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


@pytest.mark.asyncio
async def test_ask_over_budget_skips_claude_and_retrieval(budget):
    budget.has_budget.return_value = False
    mock_client = AsyncMock()

    with (
        patch("app.services.agent._get_anthropic_client", return_value=mock_client),
        patch("app.services.agent.execute_retrieval", new_callable=AsyncMock) as retrieve,
    ):
        result = await ask("latest earthquake news")

    assert result == {"answer": _PAUSED, "citations": [], "globe_actions": [], "tools_used": []}
    mock_client.messages.create.assert_not_called()
    retrieve.assert_not_called()
    budget.has_budget.assert_awaited_once_with(share=llm_budget.UNCACHED_SHARE)


@pytest.mark.asyncio
async def test_admitted_ask_synthesizes_even_if_planning_spent_the_budget(budget):
    budget.has_budget.side_effect = [True, False]  # a second check would refuse
    plan = _make_mock_response('{"tools": [{"name": "keyword_search", "args": {"terms": "x"}}]}')
    answer = _make_mock_response('{"answer": "Floods [1].", "citations": [], "globe_actions": []}')
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=[plan, answer])

    with (
        patch("app.services.agent._get_anthropic_client", return_value=mock_client),
        patch("app.services.agent.execute_retrieval", new_callable=AsyncMock, return_value=[]),
    ):
        result = await ask("flood news")

    assert result["answer"] == "Floods [1]."
    assert mock_client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_stream_over_budget_skips_claude_and_retrieval(budget):
    budget.has_budget.return_value = False
    mock_client = AsyncMock()

    with (
        patch("app.services.agent._get_anthropic_client", return_value=mock_client),
        patch("app.routers.agent.execute_retrieval", new_callable=AsyncMock) as retrieve,
        patch("app.routers.agent.get_redis", new_callable=AsyncMock, return_value=None),
    ):
        response = await ask_stream_endpoint(AskRequest(question="latest earthquake news"))
        events = [event async for event in response.body_iterator]

    assert [e["event"] for e in events] == ["token", "done"]  # no planning or retrieving
    assert json.loads(events[0]["data"]) == {"token": _PAUSED}
    done = json.loads(events[1]["data"])
    assert set(done) == {"conversation_id", "citations", "globe_actions", "tools_used"}
    assert done["citations"] == done["globe_actions"] == done["tools_used"] == []
    mock_client.messages.create.assert_not_called()
    retrieve.assert_not_called()
    budget.has_budget.assert_awaited_once_with(share=llm_budget.UNCACHED_SHARE)


@pytest.mark.asyncio
async def test_plan_retrieval_records_usage(budget):
    response = _make_mock_response('{"tools": [{"name": "keyword_search", "args": {}}]}')
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=response)

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        await plan_retrieval("flood news")

    budget.record.assert_awaited_once_with(response.usage, response.model)


@pytest.mark.asyncio
async def test_synthesize_answer_records_usage_of_a_refusal(budget):
    """A refusal is billed, so it counts against the budget too."""
    response = _make_mock_response("", thinking_first=True, stop_reason="refusal")
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=response)

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        await synthesize_answer("anything", "context")

    budget.record.assert_awaited_once_with(response.usage, response.model)


def test_normalize_globe_actions_adds_fly_to_type():
    raw = [{"lat": 6.45, "lng": 3.39, "label": "Lagos"}]
    assert _normalize_globe_actions(raw) == [
        {"type": "flyTo", "lat": 6.45, "lng": 3.39, "label": "Lagos"}
    ]


def test_normalize_globe_actions_drops_invalid_and_caps_at_three():
    raw = [
        {"lat": 95, "lng": 0},  # latitude out of range
        {"lat": "x", "lng": 1},  # not a number
        "Lagos",  # not an object
        {"lat": 1, "lng": 1},
        {"lat": 2, "lng": 2},
        {"lat": 3, "lng": 3},
        {"lat": 4, "lng": 4},
    ]
    result = _normalize_globe_actions(raw)
    assert [a["lat"] for a in result] == [1, 2, 3]
    assert all(a["type"] == "flyTo" and a["label"] == "" for a in result)


def test_normalize_globe_actions_handles_non_list():
    assert _normalize_globe_actions(None) == []
    assert _normalize_globe_actions({"lat": 1}) == []


def test_normalize_globe_actions_rejects_bools_and_non_finite():
    raw = json.loads(
        '[{"lat": true, "lng": 1}, {"lat": NaN, "lng": 0},'
        ' {"lat": 0, "lng": Infinity}, {"lat": 0, "lng": 181}]'
    )
    assert _normalize_globe_actions(raw) == []


def test_normalize_globe_actions_strips_unknown_keys_and_non_string_label():
    raw = [{"lat": 1, "lng": 2, "label": 5, "zoom": 0.001, "type": "highlight"}]
    assert _normalize_globe_actions(raw) == [{"type": "flyTo", "lat": 1, "lng": 2, "label": ""}]


def test_normalize_globe_actions_collapses_and_truncates_label():
    label = "Lagos,\n  Nigeria\n" + "x" * 200
    [action] = _normalize_globe_actions([{"lat": 6.45, "lng": 3.39, "label": label}])
    assert action["label"] == ("Lagos, Nigeria " + "x" * 200)[:80]
    assert len(action["label"]) == 80


def test_normalize_globe_actions_drops_template_placeholder():
    assert _normalize_globe_actions([{"lat": 0.0, "lng": 0.0, "label": "..."}]) == []
