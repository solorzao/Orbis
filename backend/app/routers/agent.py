"""Agent router: non-streaming and SSE streaming endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.services.agent import (
    _build_context,
    ask,
    execute_retrieval,
    plan_retrieval,
    synthesize_answer,
)
from app.services.cache import get_redis

logger = logging.getLogger("orbis.agent.router")

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None


class AskResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list = []
    globe_actions: list = []
    tools_used: list = []


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

def _conv_key(conversation_id: str) -> str:
    return f"agent:conv:{conversation_id}"


async def _load_history(conversation_id: str | None) -> tuple[str, list[dict]]:
    """Load conversation history from Redis. Returns (id, history)."""
    if not conversation_id:
        return str(uuid.uuid4()), []

    r = await get_redis()
    if r is None:
        return conversation_id, []

    try:
        raw = await r.get(_conv_key(conversation_id))
        if raw:
            return conversation_id, json.loads(raw)
    except Exception:
        logger.warning("Failed to load conversation history.", exc_info=True)

    return conversation_id, []


async def _save_history(
    conversation_id: str,
    history: list[dict],
    question: str,
    answer: str,
) -> None:
    """Append the latest exchange and persist to Redis (last 10 messages)."""
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    # Keep last 10 messages (5 exchanges)
    history = history[-10:]

    r = await get_redis()
    if r is None:
        return
    try:
        await r.set(
            _conv_key(conversation_id),
            json.dumps(history),
            ex=settings.agent_conversation_ttl,
        )
    except Exception:
        logger.warning("Failed to save conversation history.", exc_info=True)


# ---------------------------------------------------------------------------
# Non-streaming endpoint
# ---------------------------------------------------------------------------

@router.post("/ask", response_model=AskResponse)
async def ask_endpoint(body: AskRequest) -> AskResponse:
    """Answer a question using the full agent pipeline."""
    conv_id, history = await _load_history(body.conversation_id)

    result = await ask(body.question, history)

    await _save_history(conv_id, history, body.question, result["answer"])

    return AskResponse(
        conversation_id=conv_id,
        answer=result["answer"],
        citations=result.get("citations", []),
        globe_actions=result.get("globe_actions", []),
        tools_used=result.get("tools_used", []),
    )


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------

@router.post("/ask/stream")
async def ask_stream_endpoint(body: AskRequest) -> EventSourceResponse:
    """Stream the agent pipeline as SSE events."""

    async def event_generator() -> AsyncGenerator[dict, None]:
        conv_id, history = await _load_history(body.conversation_id)

        # Step 1: Plan
        tool_calls = await plan_retrieval(body.question, history)
        yield {
            "event": "planning",
            "data": json.dumps({"tools": [tc["name"] for tc in tool_calls]}),
        }

        # Step 2: Retrieve (emit one event per tool)
        for tc in tool_calls:
            yield {
                "event": "retrieving",
                "data": json.dumps({"tool": tc["name"]}),
            }
        retrieval_results = await execute_retrieval(tool_calls)

        # Step 3: Build context and synthesize
        context = _build_context(retrieval_results)
        result = await synthesize_answer(body.question, context, history)
        result["tools_used"] = [tc["name"] for tc in tool_calls]

        # Step 4: Stream answer text in chunks
        answer_text = result.get("answer", "")
        chunk_size = 20
        for i in range(0, len(answer_text), chunk_size):
            chunk = answer_text[i : i + chunk_size]
            yield {
                "event": "token",
                "data": json.dumps({"text": chunk}),
            }

        # Step 5: Save history
        await _save_history(conv_id, history, body.question, answer_text)

        # Step 6: Done
        yield {
            "event": "done",
            "data": json.dumps({
                "conversation_id": conv_id,
                "citations": result.get("citations", []),
                "globe_actions": result.get("globe_actions", []),
                "tools_used": result.get("tools_used", []),
            }),
        }

    return EventSourceResponse(event_generator())
