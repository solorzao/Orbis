"""The Claude and OpenAI requests as the real SDKs send them.

Elsewhere AsyncAnthropic and AsyncOpenAI are replaced by mocks, so an SDK that
renamed a parameter or changed its request would still pass. Here the real
clients are built from the app's own arguments, over a transport that records
each request and answers it: an SDK upgrade that changes the JSON, the
endpoint or the API version header fails here.
"""

from __future__ import annotations

import base64
import json
import struct
import uuid
from unittest.mock import AsyncMock, patch

import anthropic
import httpx2
import openai
import pytest

from app.config import settings
from app.services import ai_summary, embeddings, llm_budget


def _transport(seen: list, answer) -> httpx2.MockTransport:
    """A transport that records each request and returns answer(request)."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return answer(request)

    return httpx2.MockTransport(handle)


@pytest.fixture
def budget(monkeypatch):
    """The spend counter stubbed (tested in test_llm_budget.py)."""
    monkeypatch.setattr(llm_budget, "has_budget", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_budget, "record", AsyncMock())


SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


@pytest.mark.asyncio
async def test_call_claude_sends_the_messages_request_the_api_expects(monkeypatch, budget):
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": settings.haiku_model_id,
                "content": [{"type": "text", "text": "A summary."}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 4},
            },
        )

    real = anthropic.AsyncAnthropic

    def build(**kwargs):
        http = anthropic.DefaultAsyncHttpxClient(transport=_transport(seen, answer))
        return real(**kwargs, http_client=http)

    monkeypatch.setattr(ai_summary.settings, "anthropic_api_key", "test-key")
    with patch("app.services.ai_summary.anthropic.AsyncAnthropic", side_effect=build):
        text = await ai_summary._call_claude(
            "Three headlines.", system="Summarise them.", json_schema=SCHEMA
        )

    assert text == "A summary."
    [request] = seen
    assert request.method == "POST"
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == "test-key"
    # The API version the SDK pins: a new one (anthropic 2.x moves to 2026-10-21)
    # changes what the API accepts, so it should be a deliberate update here.
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert json.loads(request.content) == {
        "model": settings.haiku_model_id,
        "max_tokens": 1024,
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        "system": "Summarise them.",
        "messages": [{"role": "user", "content": "Three headlines."}],
    }
    llm_budget.record.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_co_pilots_answer_is_the_structured_output_request(monkeypatch, budget):
    """Phase 6 (21b): synthesis asks for SYNTHESIS_SCHEMA, at medium effort, with no
    sampling parameters and no prefill; the reply's JSON is read from its text block."""
    from app.services import agent

    seen: list[httpx2.Request] = []
    reply = {"answer": "Floods hit Valencia [1].", "globe_actions": []}

    def answer(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": settings.haiku_model_id,
                "content": [{"type": "text", "text": json.dumps(reply)}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 40, "output_tokens": 12},
            },
        )

    real = anthropic.AsyncAnthropic

    def build(**kwargs):
        http = anthropic.DefaultAsyncHttpxClient(transport=_transport(seen, answer))
        return real(**kwargs, http_client=http)

    monkeypatch.setattr(agent.settings, "anthropic_api_key", "test-key")
    with patch("app.services.agent.anthropic.AsyncAnthropic", side_effect=build):
        result = await agent.synthesize_answer("What happened in Valencia?", "[1] Floods")

    assert result == {
        "answer": "Floods hit Valencia [1].",
        "citations": [{"index": 1}],
        "globe_actions": [],
    }
    [request] = seen
    assert request.url.path == "/v1/messages"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert json.loads(request.content) == {
        "model": settings.haiku_model_id,
        "max_tokens": 8192,
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": agent.SYNTHESIS_SCHEMA},
        },
        "system": agent._SYNTHESIS_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": "Question: What happened in Valencia?\n\n<news>\n[1] Floods\n</news>",
            }
        ],
    }
    llm_budget.record.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_embeddings_sends_the_request_openai_expects(monkeypatch):
    seen: list[httpx2.Request] = []
    vector = [0.25, -0.5, 1.0]  # exact in float32

    def answer(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        # The SDK asks for base64 unless told otherwise, and decodes it to floats.
        packed = base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode()
        embedding = packed if body.get("encoding_format") == "base64" else vector
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": embedding}
                    for i in range(len(body["input"]))
                ],
                "model": body["model"],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    real = openai.AsyncOpenAI

    def build(**kwargs):
        http = openai.DefaultAsyncHttpxClient(transport=_transport(seen, answer))
        return real(**kwargs, http_client=http)

    rows = [{"id": uuid.uuid4(), "title": title} for title in ("Headline A", "Headline B")]
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=rows)
    pool.executemany = AsyncMock()
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    with (
        patch("openai.AsyncOpenAI", side_effect=build),
        patch("app.services.embeddings.get_pool", new_callable=AsyncMock, return_value=pool),
    ):
        embedded = await embeddings.generate_embeddings()

    assert embedded == [r["id"] for r in rows]
    [request] = seen
    assert request.method == "POST"
    assert request.url.path == "/v1/embeddings"
    assert request.headers["authorization"] == "Bearer test-key"
    assert json.loads(request.content) == {
        "model": settings.embedding_model,
        "input": ["Headline A", "Headline B"],
        "encoding_format": "base64",
    }
    _, updates = pool.executemany.call_args.args
    assert updates == [("[0.25,-0.5,1]", rows[0]["id"]), ("[0.25,-0.5,1]", rows[1]["id"])]
