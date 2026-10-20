"""Visitor-facing Claude calls time out in seconds, not the SDK's 10 minutes x 3 attempts.

The smallest ceiling in front of them is the frontend's /api proxy, a Vercel
function with maxDuration = 120 s (frontend/src/app/api/[...path]/route.ts);
the browser's fetches set no timeout, and Azure Container Apps' ingress allows
240 s. Each endpoint's Claude calls, every attempt and retry included, must
end well inside 120 s, leaving room for the endpoint's own queries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

from app.models.news import NewsArticle
from app.services import agent, ai_summary, links, llm_budget, thread_synopsis

PROXY_CEILING_S = 120  # the Vercel route's maxDuration
FALLBACK = "Summary generation failed."


@pytest.fixture(autouse=True)
def budget(monkeypatch):
    """The spend counter stubbed (tested in test_llm_budget.py)."""
    stub = SimpleNamespace(has_budget=AsyncMock(return_value=True), record=AsyncMock())
    monkeypatch.setattr(llm_budget, "has_budget", stub.has_budget)
    monkeypatch.setattr(llm_budget, "record", stub.record)
    return stub


def _text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    return response


def _timeout() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


@pytest.fixture
def claude(monkeypatch):
    """The Anthropic client class _call_claude builds, and the client it returns."""
    monkeypatch.setattr(ai_summary.settings, "anthropic_api_key", "test-key")
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_text_response("Summary."))
    with patch("app.services.ai_summary.anthropic.AsyncAnthropic", return_value=client) as cls:
        yield SimpleNamespace(cls=cls, client=client)


@pytest.fixture
def no_cache(monkeypatch):
    stub = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    for module in (ai_summary, links):
        monkeypatch.setattr(module, "get_cached", stub.get)
        monkeypatch.setattr(module, "set_cached", stub.set)
    return stub


def _bound(cls) -> tuple[float, int]:
    kwargs = cls.call_args.kwargs
    return kwargs["timeout"], kwargs["max_retries"]


VISITOR_BOUND = (ai_summary.CALL_TIMEOUT_S, ai_summary.CALL_MAX_RETRIES)


def _article(title: str) -> NewsArticle:
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    return NewsArticle(
        id="a",
        title=title,
        source_url="https://example.com/a",
        source_name="example.com",
        published_at=now,
        ingested_at=now,
        latitude=48.85,
        longitude=2.35,
    )


async def _cluster_summary() -> str:
    return await ai_summary.summarise_cluster(
        [_article("Strikes spread across France")], 48.85, 2.35, cell_size=1.0
    )


async def _selection_summary() -> str:
    return await ai_summary.summarise_selection(["Strikes spread across France"])


async def _link_explanation(monkeypatch) -> str:
    monkeypatch.setattr(
        links, "get_link_headlines", AsyncMock(return_value=["US and Iran trade threats"])
    )
    start = datetime(2026, 10, 18, tzinfo=timezone.utc)
    return await links.explain_link("US", "IR", start, start.replace(day=19), None)


# --- the bounds ---------------------------------------------------------------------


def _worst_case(timeout: float, retries: int) -> float:
    return timeout * (retries + 1)


def test_a_summary_call_ends_well_inside_the_proxy_ceiling():
    """Every attempt timing out still leaves half the 120 s for the endpoint's queries
    (a 7-day link explanation's headline query can take 20 s cold)."""
    assert _worst_case(*VISITOR_BOUND) <= PROXY_CEILING_S / 2


def test_an_agent_answer_ends_inside_the_proxy_ceiling():
    """Its planner and synthesis run one after the other, with retrieval between
    (page reads are 5 s each): every attempt of both timing out stays under 105 s."""
    plan = _worst_case(agent.PLAN_TIMEOUT_S, agent.CLAUDE_MAX_RETRIES)
    synthesis = _worst_case(agent.SYNTHESIS_TIMEOUT_S, agent.CLAUDE_MAX_RETRIES)
    assert plan + synthesis <= PROXY_CEILING_S - 15


def test_background_synopses_keep_their_own_longer_bound():
    assert thread_synopsis.CALL_TIMEOUT_S > ai_summary.CALL_TIMEOUT_S


# --- each visitor-facing caller passes the bound ---------------------------------------


@pytest.mark.asyncio
async def test_cluster_summaries_are_bounded(claude, no_cache):
    assert await _cluster_summary() == "Summary."
    assert _bound(claude.cls) == VISITOR_BOUND


@pytest.mark.asyncio
async def test_selection_summaries_are_bounded(claude):
    assert await _selection_summary() == "Summary."
    assert _bound(claude.cls) == VISITOR_BOUND


@pytest.mark.asyncio
async def test_link_explanations_are_bounded(claude, no_cache, monkeypatch):
    assert await _link_explanation(monkeypatch) == "Summary."
    assert _bound(claude.cls) == VISITOR_BOUND


@pytest.mark.asyncio
async def test_synopses_override_the_timeout(claude):
    await ai_summary._call_claude("<headlines>...</headlines>", timeout=30)
    assert _bound(claude.cls) == (30, ai_summary.CALL_MAX_RETRIES)


@pytest.mark.asyncio
async def test_the_agents_calls_are_bounded():
    with patch("app.services.agent.anthropic.AsyncAnthropic") as cls:
        agent._get_anthropic_client(timeout=12.5, max_retries=1)

    cls.assert_called_once_with(
        api_key=agent.settings.anthropic_api_key, timeout=12.5, max_retries=1
    )


@pytest.mark.asyncio
async def test_the_agents_planner_and_synthesis_pass_their_bounds():
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_text_response('{"answer": "Done."}'))
    with patch("app.services.agent._get_anthropic_client", return_value=client) as get:
        await agent.plan_retrieval("What is happening in France?")
        await agent.synthesize_answer("What is happening in France?", "[1] Strikes")

    assert [c.kwargs for c in get.call_args_list] == [
        {"timeout": agent.PLAN_TIMEOUT_S, "max_retries": agent.CLAUDE_MAX_RETRIES},
        {"timeout": agent.SYNTHESIS_TIMEOUT_S, "max_retries": agent.CLAUDE_MAX_RETRIES},
    ]


# --- a timeout is the friendly fallback, recorded as nothing ----------------------------


@pytest.mark.asyncio
async def test_a_timed_out_summary_is_the_fallback_and_costs_nothing_recorded(
    claude, no_cache, budget, monkeypatch, caplog
):
    claude.client.messages.create.side_effect = _timeout()

    assert await _cluster_summary() == FALLBACK
    assert await _selection_summary() == FALLBACK
    assert await _link_explanation(monkeypatch) == FALLBACK

    budget.record.assert_not_awaited()  # no response, no usage to record
    no_cache.set.assert_not_awaited()  # a fallback is never cached
    assert "Claude timed out" in caplog.text


@pytest.mark.asyncio
async def test_a_timed_out_summary_is_a_200_with_the_fallback(claude, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.middleware import security

    claude.client.messages.create.side_effect = _timeout()
    monkeypatch.setattr(security.settings, "api_key", "")
    security._rate_buckets.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        resp = await http.post(
            "/api/news/summarize-selection", json={"headlines": ["Strikes spread across France"]}
        )

    assert resp.status_code == 200
    assert resp.json()["summary"] == FALLBACK


@pytest.mark.asyncio
async def test_a_timed_out_agent_answers_politely(budget):
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=_timeout())
    with patch("app.services.agent._get_anthropic_client", return_value=client):
        plan = await agent.plan_retrieval("What is happening in France?")
        answer = await agent.synthesize_answer("What is happening in France?", "[1] Strikes")

    assert plan  # the keyword-search fallback, no Claude
    assert answer["answer"] == "I'm sorry, I couldn't generate an answer right now."
    budget.record.assert_not_awaited()
