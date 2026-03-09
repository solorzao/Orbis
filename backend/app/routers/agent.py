"""Agent router: non-streaming and SSE streaming endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.middleware.security import has_injection_pattern, sanitise_text
from app.services.agent import (
    _OFF_TOPIC_ANSWER,
    _build_context,
    _collect_urls,
    _enrich_citations,
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

_UUID_RE = __import__("re").compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

_MAX_QUESTION_LENGTH = 500


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=_MAX_QUESTION_LENGTH)
    conversation_id: str | None = None


class AskResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list = []
    globe_actions: list = []
    tools_used: list = []


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_request(body: AskRequest) -> str:
    """Sanitize question and validate conversation_id. Returns clean question."""
    if not settings.agent_enabled:
        raise HTTPException(status_code=503, detail="Agent chat is temporarily disabled.")

    if body.conversation_id and not _UUID_RE.match(body.conversation_id):
        raise HTTPException(status_code=422, detail="conversation_id must be a valid UUID.")

    question = sanitise_text(body.question, max_length=_MAX_QUESTION_LENGTH)
    if not question:
        raise HTTPException(status_code=422, detail="Question is empty after sanitization.")

    if has_injection_pattern(question):
        logger.warning("Blocked prompt injection attempt: %s", question[:80])
        raise HTTPException(status_code=400, detail="Your question could not be processed.")

    return question


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
    question = _validate_request(body)
    conv_id, history = await _load_history(body.conversation_id)

    result = await ask(question, history)

    await _save_history(conv_id, history, question, result["answer"])

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
    question = _validate_request(body)

    async def event_generator() -> AsyncGenerator[dict, None]:
        conv_id, history = await _load_history(body.conversation_id)

        # Step 1: Plan
        tool_calls = await plan_retrieval(question, history)

        # Off-topic: skip retrieval + synthesis (saves 2 API calls)
        if not tool_calls:
            answer_text = _OFF_TOPIC_ANSWER
            yield {
                "event": "token",
                "data": json.dumps({"token": answer_text}),
            }
            await _save_history(conv_id, history, question, answer_text)
            yield {
                "event": "done",
                "data": json.dumps({
                    "conversation_id": conv_id,
                    "citations": [],
                    "globe_actions": [],
                    "tools_used": [],
                }),
            }
            return

        yield {
            "event": "planning",
            "data": json.dumps({"tools": [tc["name"] for tc in tool_calls]}),
        }

        # Separate read_article (second-pass) from first-pass tools
        first_pass = [tc for tc in tool_calls if tc["name"] != "read_article"]
        wants_read = any(tc["name"] == "read_article" for tc in tool_calls)

        # Step 2: Retrieve first-pass tools
        for tc in first_pass:
            yield {"event": "retrieving", "data": json.dumps({"tool": tc["name"]})}
        retrieval_results = list(await execute_retrieval(first_pass)) if first_pass else []

        # Step 2b: Read articles (second pass)
        if wants_read:
            urls = _collect_urls(retrieval_results)
            if urls:
                yield {"event": "retrieving", "data": json.dumps({"tool": "read_article"})}
                read_results = await execute_retrieval([
                    {"name": "read_article", "args": {"urls": urls[:5], "question": question}}
                ])
                retrieval_results.extend(read_results)

        # Step 3: Build context and synthesize
        context, article_index = _build_context(retrieval_results)
        result = await synthesize_answer(question, context, history)
        result["citations"] = _enrich_citations(result.get("citations", []), article_index)
        result["tools_used"] = [tc["name"] for tc in tool_calls]

        # Step 4: Stream answer text in chunks
        answer_text = result.get("answer", "")
        chunk_size = 20
        for i in range(0, len(answer_text), chunk_size):
            chunk = answer_text[i : i + chunk_size]
            yield {
                "event": "token",
                "data": json.dumps({"token": chunk}),
            }

        # Step 5: Save history
        await _save_history(conv_id, history, question, answer_text)

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
