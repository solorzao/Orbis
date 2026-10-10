"""Global daily cap on Claude spend, shared across all AI endpoints.

Uses Redis when available (survives restarts), else an in-process counter;
the API runs as a single replica, so the in-process counter is exact.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.cache import get_redis

logger = logging.getLogger(__name__)

# Claude Haiku 5.5, prompts up to 100K tokens (USD per token)
_INPUT_PER_TOKEN = 0.10 / 1_000_000
_OUTPUT_PER_TOKEN = 0.50 / 1_000_000

_memory: dict[str, float] = {}


class LLMBudgetExceeded(RuntimeError):
    """The global daily Claude budget is spent."""


def cost_usd(usage: Any) -> float:
    return usage.input_tokens * _INPUT_PER_TOKEN + usage.output_tokens * _OUTPUT_PER_TOKEN


def _key() -> str:
    return "llm:spend:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _spent() -> float:
    key = _key()
    r = await get_redis()
    if r is not None:
        try:
            value = await r.get(key)
            return float(value or 0)
        except Exception:
            logger.warning("Budget read from Redis failed; using memory.", exc_info=True)
    return _memory.get(key, 0.0)


async def has_budget() -> bool:
    return await _spent() < settings.llm_daily_budget_usd


async def record(usage: Any) -> None:
    key = _key()
    amount = cost_usd(usage)
    _memory[key] = _memory.get(key, 0.0) + amount
    r = await get_redis()
    if r is not None:
        try:
            await r.incrbyfloat(key, amount)
            await r.expire(key, 2 * 86400)
        except Exception:
            logger.warning("Budget write to Redis failed.", exc_info=True)
