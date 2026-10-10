from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import llm_budget


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    async def none():
        return None

    monkeypatch.setattr(llm_budget, "get_redis", none)
    llm_budget._memory.clear()
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", 0.01)


def test_cost_uses_haiku_5_5_prices():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
    assert llm_budget.cost_usd(usage) == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_budget_blocks_after_cap():
    assert await llm_budget.has_budget()
    await llm_budget.record(SimpleNamespace(input_tokens=20_000, output_tokens=20_000))  # $0.012
    assert not await llm_budget.has_budget()


@pytest.mark.asyncio
async def test_zero_budget_turns_ai_off(monkeypatch):
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", 0.0)
    assert not await llm_budget.has_budget()


@pytest.mark.asyncio
async def test_spend_lives_in_redis_when_available(monkeypatch):
    redis = AsyncMock()
    redis.get.return_value = "0.02"  # spent by an earlier process today

    async def get_redis():
        return redis

    monkeypatch.setattr(llm_budget, "get_redis", get_redis)

    assert not await llm_budget.has_budget()
    await llm_budget.record(SimpleNamespace(input_tokens=1_000, output_tokens=0))
    key = redis.get.call_args.args[0]
    assert key.startswith("llm:spend:")
    redis.incrbyfloat.assert_awaited_once_with(key, pytest.approx(0.0001))
    redis.expire.assert_awaited_once_with(key, 2 * 86400)
