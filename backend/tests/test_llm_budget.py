"""Tests for the global daily cap on Claude spend."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from anthropic.types import Usage

from app import config
from app.services import llm_budget

HAIKU = "claude-haiku-5-5"


def _usage(usd: float) -> SimpleNamespace:
    """Haiku 5.5 usage costing ``usd`` (output tokens at $0.50 per MTok)."""
    return SimpleNamespace(input_tokens=0, output_tokens=round(usd * 2_000_000))


class FakeRedis:
    """The slice of redis.asyncio the budget uses; operations in ``failing`` raise."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.failing: set[str] = set()

    def _run(self, op: str) -> None:
        if op in self.failing:
            raise ConnectionError(f"Redis {op} failed")

    async def get(self, key):
        self._run("get")
        return self.store.get(key)

    async def incrbyfloat(self, key, amount):
        self._run("incrbyfloat")
        value = float(self.store.get(key, 0)) + amount
        self.store[key] = str(value)
        return value

    async def expire(self, key, seconds):
        self._run("expire")
        self.ttl[key] = seconds


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    async def none():
        return None

    monkeypatch.setattr(llm_budget, "get_redis", none)
    monkeypatch.setattr(llm_budget, "_memory", {})
    monkeypatch.setattr(llm_budget, "_warned_models", set())
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", 0.01)


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()

    async def get_redis():
        return fake

    monkeypatch.setattr(llm_budget, "get_redis", get_redis)
    return fake


# --- Pricing ---------------------------------------------------------------


def test_cost_uses_haiku_5_5_prices():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
    assert llm_budget.cost_usd(usage, "claude-haiku-5-5") == pytest.approx(0.60)


def test_cost_matches_haiku_4_5_by_prefix():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
    assert llm_budget.cost_usd(usage, "claude-haiku-4-5-20251001") == pytest.approx(6.00)


def test_unknown_model_is_priced_high_and_warned_about_once(caplog):
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
    with caplog.at_level(logging.WARNING, logger=llm_budget.__name__):
        assert llm_budget.cost_usd(usage, "claude-next") == pytest.approx(60.00)
        llm_budget.cost_usd(usage, "claude-next")
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_cost_reads_the_sdk_usage_type():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert llm_budget.cost_usd(usage, HAIKU) == pytest.approx(0.60)


# --- The cap ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_blocks_after_cap():
    assert await llm_budget.has_budget()
    await llm_budget.record(SimpleNamespace(input_tokens=20_000, output_tokens=20_000), HAIKU)
    assert not await llm_budget.has_budget()  # $0.012 spent of $0.01


@pytest.mark.asyncio
async def test_spend_exactly_at_cap_is_blocked(monkeypatch):
    usage = _usage(0.01)
    cap = llm_budget.cost_usd(usage, HAIKU)
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", cap)
    await llm_budget.record(usage, HAIKU)
    assert not await llm_budget.has_budget()


@pytest.mark.asyncio
async def test_zero_budget_turns_ai_off(monkeypatch):
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", 0.0)
    assert not await llm_budget.has_budget()


@pytest.mark.asyncio
async def test_share_keeps_the_rest_of_the_cap_for_cluster_summaries(monkeypatch):
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", 1.0)
    await llm_budget.record(_usage(0.75), HAIKU)
    assert await llm_budget.has_budget()
    assert not await llm_budget.has_budget(share=llm_budget.UNCACHED_SHARE)


@pytest.mark.asyncio
async def test_spend_resets_at_midnight_utc(monkeypatch):
    now = datetime(2026, 10, 10, 23, 59, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(llm_budget, "datetime", Clock)
    await llm_budget.record(_usage(0.02), HAIKU)
    assert not await llm_budget.has_budget()

    now = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
    assert await llm_budget.has_budget()
    await llm_budget.record(_usage(0.001), HAIKU)
    assert list(llm_budget._memory) == ["llm:spend:2026-10-11"]  # earlier days pruned


# --- Redis and memory --------------------------------------------------------


@pytest.mark.asyncio
async def test_spend_is_shared_through_redis(redis):
    key = llm_budget._key()
    redis.store[key] = "0.02"  # spent by an earlier process today
    assert not await llm_budget.has_budget()

    await llm_budget.record(_usage(0.001), HAIKU)
    assert float(redis.store[key]) == pytest.approx(0.021)
    assert redis.ttl[key] == 2 * 86400


@pytest.mark.asyncio
async def test_failed_read_after_restart_uses_memory_until_a_read_succeeds(monkeypatch, redis):
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", 0.90)
    redis.store[llm_budget._key()] = "0.95"  # spent before the restart; memory is empty
    redis.failing = {"get"}
    assert await llm_budget.has_budget()  # memory alone has seen nothing

    redis.failing = set()
    assert not await llm_budget.has_budget()  # the read pulls memory up to 0.95

    redis.failing = {"get"}
    assert not await llm_budget.has_budget()  # and memory keeps it


@pytest.mark.asyncio
async def test_spend_during_a_redis_outage_counts_after_recovery(redis):
    await llm_budget.record(_usage(0.30), HAIKU)
    redis.failing = {"get", "incrbyfloat", "expire"}
    await llm_budget.record(_usage(0.60), HAIKU)
    redis.failing = set()

    assert float(redis.store[llm_budget._key()]) == pytest.approx(0.30)
    assert await llm_budget._spent() == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_cap_trips_from_memory_when_redis_writes_fail(redis):
    redis.failing = {"incrbyfloat", "expire"}
    await llm_budget.record(_usage(0.012), HAIKU)
    assert not await llm_budget.has_budget()  # Redis reads still work, and say $0


# --- Recording ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_logs_usage_and_warns_once_per_threshold(caplog):
    with caplog.at_level(logging.INFO, logger=llm_budget.__name__):
        for _ in range(4):  # totals $0.004, $0.008, $0.012, $0.016 against a $0.01 cap
            await llm_budget.record(_usage(0.004), HAIKU)

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(infos) == 4
    assert HAIKU in infos[-1] and "0.0160" in infos[-1]  # model and running total
    assert len(warnings) == 2
    assert "70%" in warnings[0] and "100%" in warnings[1]


@pytest.mark.asyncio
async def test_record_never_raises():
    """The response is already paid for; bookkeeping must not turn it into a failure."""
    await llm_budget.record(SimpleNamespace(input_tokens=None, output_tokens=None), HAIKU)


# --- The setting -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected", "warns"),
    [
        (None, 1.0, False),
        ("2.5", 2.5, False),
        ("0", 0.0, False),
        ("-1", 1.0, True),
        ("nan", 1.0, True),
        ("inf", 1.0, True),
        ("lots", 1.0, True),
    ],
)
def test_budget_setting_must_be_finite_and_not_negative(monkeypatch, caplog, raw, expected, warns):
    if raw is None:
        monkeypatch.delenv("LLM_DAILY_BUDGET_USD", raising=False)
    else:
        monkeypatch.setenv("LLM_DAILY_BUDGET_USD", raw)

    assert config.Settings().llm_daily_budget_usd == expected
    assert ("LLM_DAILY_BUDGET_USD" in caplog.text) is warns
