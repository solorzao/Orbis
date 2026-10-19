"""Tests for the caches refilled after each ingestion cycle (app.warm)."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app import warm
from app.config import settings
from app.routers.links import warm_links_7d, warm_links_24h
from app.routers.news import warm_breaking, warm_globe, warm_volume
from app.routers.threads import warm_threads
from app.services.cache import cycle_ttl


@pytest.fixture(autouse=True)
def redis_up():
    """Redis answers, unless a test says otherwise."""
    with patch("app.warm.get_redis", new_callable=AsyncMock, return_value=object()) as mock:
        yield mock


def test_the_first_visit_is_warmed_globe_first_then_the_links_layer_then_breaking():
    """The globe is on the first visit's critical path; links only once the layer is on;
    breaking stories (one list for every topic) for the ticker and the delta; then the
    threads rail's default list (24 hours, all topics, 20)."""
    assert warm.WARMERS == (
        warm_globe,
        warm_volume,
        warm_links_24h,
        warm_links_7d,
        warm_breaking,
        warm_threads,
    )
    assert warm.WARM_TIMEOUT == 30


def test_a_cycles_entries_last_until_the_next_cycle_ends():
    """Ingestion invalidates db:* at the end of each cycle (minutes long, mostly
    embeddings) and the warm refills it; a warmed entry must outlive the wait for
    the next cycle plus that cycle itself."""
    interval = settings.ingestion_interval_seconds
    assert cycle_ttl(300) == interval + 600 > interval  # globe, volume
    assert cycle_ttl(600) == interval + 600  # links
    assert cycle_ttl(interval + 900) == interval + 900  # longer already: kept


@pytest.mark.asyncio
async def test_no_redis_no_warm(redis_up, caplog):
    """Nothing to fill: one line, not four queries and four connect tracebacks."""
    redis_up.return_value = None
    warmer = AsyncMock()
    warmer.__name__ = "warmer"

    with caplog.at_level(logging.INFO, logger="orbis.warm"):
        await warm.warm_caches((warmer,), timeout=5)

    warmer.assert_not_called()
    assert [r.getMessage() for r in caplog.records] == ["Cache warm skipped: no Redis."]


@pytest.mark.asyncio
async def test_each_warmer_runs_in_turn_and_its_time_is_logged(caplog):
    calls = []

    async def first():
        calls.append("first")

    async def second():
        calls.append("second")

    with caplog.at_level(logging.INFO, logger="orbis.warm"):
        await warm.warm_caches((first, second), timeout=5)

    assert calls == ["first", "second"]
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("Cache warm first took ") for m in messages)
    assert any(m.startswith("Cache warm second took ") for m in messages)
    assert messages[-1].startswith("Cache warm: 2 of 2 in ")


@pytest.mark.asyncio
async def test_a_slow_or_failing_warmer_is_a_warning_and_the_rest_still_run(caplog):
    calls = []

    async def slow():
        await asyncio.sleep(5)
        calls.append("slow finished")  # never: cut off by the timeout

    async def failing():
        raise RuntimeError("database gone")

    async def last():
        calls.append("last")

    with caplog.at_level(logging.INFO, logger="orbis.warm"):
        await warm.warm_caches((slow, failing, last), timeout=0.05)  # does not raise

    assert calls == ["last"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(w.startswith("Cache warm slow timed out after 0.05 s") for w in warnings)
    assert any(w.startswith("Cache warm failing failed after ") for w in warnings)
    assert caplog.records[-1].getMessage().startswith("Cache warm: 1 of 3 in ")
