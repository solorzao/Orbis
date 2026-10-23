"""Tests for the app's startup and shutdown hooks."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_shutdown_stops_background_work_before_closing_connections():
    """A cycle or a cache warm still running would otherwise reach Redis or the pool
    after close. The cycles stop first, so neither starts a warm once the warms are
    stopped."""
    from app import main

    calls: list = []

    def step(name):
        async def record(**kwargs):
            calls.append((name, kwargs) if kwargs else name)

        return record

    with (
        patch.object(main, "stop_scheduler", step("scheduler")),
        patch.object(main, "stop_initial_ingest", step("initial ingest")),
        patch.object(main, "stop_background_tasks", step("background tasks")),
        patch.object(main, "close_redis", step("redis")),
        patch.object(main, "close_pool", step("pool")),
    ):
        await main.shutdown()

    # At shutdown every wk: read stops (a cycle's start leaves the relations' running).
    assert calls == [
        "scheduler",
        "initial ingest",
        ("background tasks", {"shutdown": True}),
        "redis",
        "pool",
    ]


@pytest.mark.asyncio
async def test_shutdown_during_the_first_cycle_stops_it_before_the_pool_closes(monkeypatch, caplog):
    """A replica shut down during its first ingestion cycle ran the cycle on past
    close_pool, to fail there ("Ingestion cycle failed." at ERROR, a traceback), its
    closing db:* invalidation a no-op. Now it is cancelled first: nothing at ERROR,
    no invalidation or cache warm, the cycle's lock released."""
    from app import main
    from app.services import cache, database, ingestion

    # Redis and the pool as a fresh process has them; the closed flags restored after.
    monkeypatch.setattr(main, "_initial_ingest_task", None)
    monkeypatch.setattr(cache, "_redis_client", None)
    monkeypatch.setattr(cache, "_redis_closed", False)
    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database, "_pool_closed", False)

    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def slow_gkg_step():
        started.set()
        try:
            await release.wait()  # a download or the title scrapes, slow
        except asyncio.CancelledError:
            cancelled.set()
            raise
        await database.get_pool()  # the upsert's: once close_pool has run, RuntimeError
        return 0

    async def opened():
        return None

    invalidate, warm = AsyncMock(), MagicMock()
    with (
        patch.object(main, "open_redis", opened),
        patch.object(main, "open_pool", opened),
        patch.object(main, "start_scheduler", lambda: None),
        patch.object(ingestion, "_ingest_from_raw_gkg", slow_gkg_step),
        patch.object(ingestion, "_add_events", AsyncMock()),
        patch.object(ingestion, "invalidate", invalidate),
        patch.object(ingestion, "_start_cache_warm", warm),
        caplog.at_level(logging.INFO),
    ):
        await main.startup()
        cycle = main._initial_ingest_task
        await asyncio.wait_for(started.wait(), 1)
        await main.shutdown()
        release.set()  # a cycle still running goes on now
        await asyncio.wait([cycle], timeout=1)

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert cycle.cancelled() and cancelled.is_set()
    assert main._initial_ingest_task is None
    assert not ingestion._ingestion_lock.locked()
    invalidate.assert_not_awaited()
    warm.assert_not_called()
    assert "Initial ingestion stopped." in caplog.messages


@pytest.mark.asyncio
async def test_shutdown_after_the_first_cycle_has_ended_waits_on_nothing(monkeypatch, caplog):
    """The usual case: the first cycle ended long before, so nothing is stopped."""
    from app import main

    async def ended():
        return None

    monkeypatch.setattr(main, "_initial_ingest_task", asyncio.create_task(ended()))
    await asyncio.sleep(0)

    with caplog.at_level(logging.INFO):
        await main.stop_initial_ingest()

    assert main._initial_ingest_task is None
    assert "Initial ingestion stopped." not in caplog.messages


STARTUP = ["redis", "pool", "scheduler"]
SHUTDOWN = [
    "stop scheduler",
    "stop initial ingest",
    "stop background tasks",
    "close redis",
    "close pool",
]


@pytest.fixture
def lifecycle_calls(monkeypatch):
    """What startup and shutdown call, recorded in order instead of run."""
    from app import main

    calls: list = []

    def step(name):
        async def record(**kwargs):
            calls.append(name)

        return record

    monkeypatch.setattr(main, "_initial_ingest_task", None)  # restored after
    with (
        patch.object(main, "open_redis", step("redis")),
        patch.object(main, "open_pool", step("pool")),
        patch.object(main, "run_ingestion_cycle", AsyncMock(return_value=0)),
        patch.object(main, "start_scheduler", lambda: calls.append("scheduler")),
        patch.object(main, "stop_scheduler", step("stop scheduler")),
        patch.object(main, "stop_initial_ingest", step("stop initial ingest")),
        patch.object(main, "stop_background_tasks", step("stop background tasks")),
        patch.object(main, "close_redis", step("close redis")),
        patch.object(main, "close_pool", step("close pool")),
    ):
        yield calls


def test_the_servers_lifespan_runs_startup_then_shutdown(lifecycle_calls):
    """Through the ASGI lifespan, as uvicorn drives it: startup warms Redis and the
    pool and starts the scheduler as the server starts, shutdown runs as it stops."""
    from fastapi.testclient import TestClient

    from app import main

    with TestClient(main.app):
        started = list(lifecycle_calls)

    assert started == STARTUP
    assert lifecycle_calls[len(started) :] == SHUTDOWN


@pytest.mark.asyncio
async def test_a_cancelled_lifespan_still_shuts_down(lifecycle_calls):
    from app import main

    serving = asyncio.Event()

    async def serve():
        async with main.lifespan(main.app):
            serving.set()
            await asyncio.Event().wait()  # until cancelled

    task = asyncio.create_task(serve())
    await serving.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert lifecycle_calls == STARTUP + SHUTDOWN
