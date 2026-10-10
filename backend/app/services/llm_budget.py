"""Global daily cap on Claude spend, shared across all AI endpoints.

Spend is counted in Redis when available, which survives restarts, and always
in process memory, which is exact only within one process. Reads take the
larger of the two, so a failed Redis read or write, an outage or a restart
never makes today's spend look lower than this process has seen. Spend whose
Redis write failed is not replayed, so a restart after a Redis outage can
undercount by that amount.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.cache import get_redis

logger = logging.getLogger(__name__)

# USD per million tokens (input, output) for prompts up to 100K tokens,
# matched by prefix so dated snapshots (claude-haiku-4-5-20251001) are found.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
}
# Unknown models fail closed at the highest current list price (Claude Fable
# 5.1), so pointing HAIKU_MODEL_ID at any model cannot overspend the cap.
_UNKNOWN_PRICE = (10.00, 50.00)

# Share of the cap for features whose answers serve one visitor (the agent,
# selection summaries); the rest is kept for the cached cluster summaries.
UNCACHED_SHARE = 0.7

# Shares of the cap that log a warning when spend crosses them, and what pauses.
_THRESHOLDS = (
    (UNCACHED_SHARE, "the agent and selection summaries pause"),
    (1.0, "all AI features pause"),
)

_memory: dict[str, float] = {}
_warned_models: set[str] = set()


def _price(model: str) -> tuple[float, float]:
    for prefix, price in _PRICES.items():
        if model.startswith(prefix):
            return price
    if model not in _warned_models:
        _warned_models.add(model)
        logger.warning("No price for model %r; charging $%s/$%s per MTok.", model, *_UNKNOWN_PRICE)
    return _UNKNOWN_PRICE


def cost_usd(usage: Any, model: str) -> float:
    input_price, output_price = _price(model)
    return (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1_000_000


def _key() -> str:
    return "llm:spend:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _spent() -> float:
    key = _key()
    r = await get_redis()
    if r is not None:
        try:
            remote = float(await r.get(key) or 0)
        except Exception:
            logger.warning("Budget read from Redis failed; using memory.", exc_info=True)
        else:
            _memory[key] = max(_memory.get(key, 0.0), remote)
    return _memory.get(key, 0.0)


async def has_budget(share: float = 1.0) -> bool:
    """Whether today's spend is below ``share`` of the daily cap."""
    return await _spent() < settings.llm_daily_budget_usd * share


async def record(usage: Any, model: str) -> None:
    """Add a response's cost to today's spend. Never raises: the response is paid for."""
    try:
        key = _key()
        amount = cost_usd(usage, model)
        for day in [k for k in _memory if k != key]:
            del _memory[day]
        total = _memory[key] = _memory.get(key, 0.0) + amount
        r = await get_redis()
        if r is not None:
            try:
                remote = float(await r.incrbyfloat(key, amount))
                await r.expire(key, 2 * 86400)
            except Exception:
                logger.warning("Budget write to Redis failed; counted in memory.", exc_info=True)
            else:
                total = max(total, remote)
                _memory[key] = max(_memory.get(key, 0.0), remote)

        logger.info(
            "Claude usage: %d input + %d output tokens on %s = $%.5f; $%.4f spent today.",
            usage.input_tokens,
            usage.output_tokens,
            model,
            amount,
            total,
        )
        cap = settings.llm_daily_budget_usd
        for share, effect in _THRESHOLDS:
            if total - amount < cap * share <= total:
                logger.warning(
                    "Claude spend reached %.0f%% of the $%.2f daily budget; %s until 00:00 UTC.",
                    share * 100,
                    cap,
                    effect,
                )
    except Exception:
        logger.error("Recording Claude usage failed.", exc_info=True)
