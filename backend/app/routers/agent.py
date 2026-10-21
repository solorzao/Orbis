"""Agent router: non-streaming and SSE streaming endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    ValidatorFunctionWrapHandler,
    field_validator,
)
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.middleware.security import has_injection_pattern, sanitise_text, strip_invisible
from app.services.agent import (
    _OFF_TOPIC_ANSWER,
    _PAUSED_ANSWER,
    ScreenScope,
    ScreenTopic,
    _build_context,
    _collect_urls,
    _collect_urls_from_history,
    _enrich_citations,
    admit_ask,
    ask,
    clean_screen_context,
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


def _none_if_invalid(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    """Drop a field that fails validation rather than reject the question."""
    try:
        return handler(value)
    except ValidationError:
        return None


class ScreenContext(BaseModel):
    """What the visitor sees: the selected place, the topic filter and the time window.

    Each field is optional, and one that fails validation is dropped (None).
    ``clean_screen_context`` then cleans the place and checks the window.
    """

    place: str | None = Field(None, max_length=100)  # the cell's place name, "Madrid, Spain"
    topic: ScreenTopic | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None

    _drop_invalid = field_validator("*", mode="wrap")(_none_if_invalid)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=_MAX_QUESTION_LENGTH)
    conversation_id: str | None = None
    context: ScreenContext | None = None

    _drop_invalid_context = field_validator("context", mode="wrap")(_none_if_invalid)


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

    # Hidden characters go first, so they can't split an injection phrase.
    question = sanitise_text(strip_invisible(body.question), max_length=_MAX_QUESTION_LENGTH)
    if not question:
        raise HTTPException(status_code=422, detail="Question is empty after sanitization.")

    if has_injection_pattern(question):
        # Its length only: the question is what a visitor typed.
        logger.warning("Blocked prompt injection attempt (%d characters).", len(question))
        raise HTTPException(status_code=400, detail="Your question could not be processed.")

    return question


def _screen_scope(body: AskRequest) -> ScreenScope | None:
    """The request's screen context, cleaned for the prompts (None if absent or empty)."""
    c = body.context
    if c is None:
        return None
    return clean_screen_context(c.place, c.topic, c.start_time, c.end_time)


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
    citations: list[dict] | None = None,
) -> None:
    """Append the latest exchange and persist to Redis (last 10 messages).

    Embeds citation URLs in the assistant message so follow-up questions
    can discover them via ``_collect_urls_from_history``. The paused answer
    is not saved: it says nothing about the conversation, and the question
    can be asked again once the budget resets.
    """
    if answer == _PAUSED_ANSWER:
        return
    history.append({"role": "user", "content": question})
    # Append citation URLs so follow-up read_article calls can find them
    answer_to_store = answer
    if citations:
        url_list = [c["url"] for c in citations if c.get("url")]
        if url_list:
            answer_to_store = answer + "\n\n[Sources: " + ", ".join(url_list) + "]"
    history.append({"role": "assistant", "content": answer_to_store})
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
    scope = _screen_scope(body)
    conv_id, history = await _load_history(body.conversation_id)

    result = await ask(question, history, scope)

    await _save_history(conv_id, history, question, result["answer"], result.get("citations"))

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
    scope = _screen_scope(body)

    async def event_generator() -> AsyncGenerator[dict, None]:
        conv_id, history = await _load_history(body.conversation_id)

        # Step 1: Plan, unless the budget is spent (an admitted ask runs to the end)
        if await admit_ask():
            tool_calls = await plan_retrieval(question, history, scope)
            fixed_answer = None if tool_calls else _OFF_TOPIC_ANSWER
        else:
            tool_calls, fixed_answer = [], _PAUSED_ANSWER

        # Paused or off-topic: skip retrieval + synthesis
        if fixed_answer:
            answer_text = fixed_answer
            yield {
                "event": "token",
                "data": json.dumps({"token": answer_text}),
            }
            await _save_history(conv_id, history, question, answer_text)
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "conversation_id": conv_id,
                        "citations": [],
                        "globe_actions": [],
                        "tools_used": [],
                    }
                ),
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
            # Fallback: use URLs from conversation history if first-pass had none
            if not urls:
                urls = _collect_urls_from_history(history)
            if urls:
                yield {"event": "retrieving", "data": json.dumps({"tool": "read_article"})}
                read_results = await execute_retrieval(
                    [{"name": "read_article", "args": {"urls": urls[:5], "question": question}}]
                )
                retrieval_results.extend(read_results)

        # Step 3: Build context and synthesize
        context, article_index = _build_context(retrieval_results)
        result = await synthesize_answer(question, context, history, scope)
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
        await _save_history(conv_id, history, question, answer_text, result.get("citations"))

        # Step 6: Done
        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "conversation_id": conv_id,
                    "citations": result.get("citations", []),
                    "globe_actions": result.get("globe_actions", []),
                    "tools_used": result.get("tools_used", []),
                }
            ),
        }

    return EventSourceResponse(event_generator())
