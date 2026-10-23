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


async def _opened():
    """open_redis and open_pool, as a test's startup runs them: nothing to open."""


def _recording(calls: list, name: str):
    """A shutdown step that only records *name* in *calls*."""

    async def record(**kwargs):
        calls.append(name)

    return record


@pytest.mark.asyncio
async def test_a_cancelled_lifespan_still_stops_the_cycles_then_closes(monkeypatch):
    """The lifespan's task is cancelled as it serves, so shutdown runs in its finally
    with the task's cancelling() already 1: the real stops wait for the cycles they
    cancel (the scheduler's loop, startup's first cycle) and return, and the closes
    run. Re-raising whenever cancelling() was set would skip them."""
    from app import main
    from app.services import scheduler

    monkeypatch.setattr(main, "_initial_ingest_task", None)
    monkeypatch.setattr(scheduler, "_task", None)
    calls: list = []
    cycle_started, serving = asyncio.Event(), asyncio.Event()

    async def slow_cycle():
        cycle_started.set()
        await asyncio.Event().wait()  # until cancelled
        return 0

    async def serve():
        async with main.lifespan(main.app):
            serving.set()
            await asyncio.Event().wait()  # until cancelled

    with (
        patch.object(main, "open_redis", _opened),
        patch.object(main, "open_pool", _opened),
        patch.object(main, "run_ingestion_cycle", slow_cycle),
        patch.object(main, "stop_background_tasks", _recording(calls, "stop background tasks")),
        patch.object(main, "close_redis", _recording(calls, "close redis")),
        patch.object(main, "close_pool", _recording(calls, "close pool")),
    ):
        task = asyncio.create_task(serve())
        await serving.wait()
        await asyncio.wait_for(cycle_started.wait(), 1)
        cycle, loop = main._initial_ingest_task, scheduler._task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert calls == ["stop background tasks", "close redis", "close pool"]
    assert cycle.cancelled() and loop.cancelled()
    assert main._initial_ingest_task is None and scheduler._task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stopping", ["initial ingest", "scheduler"])
async def test_a_cancel_of_shutdown_while_a_cycle_stops_is_not_swallowed(monkeypatch, stopping):
    """A cancel aimed at shutdown itself while it waits on a cycle slow to stop: caught
    with the cycle's own CancelledError, it was lost, and shutdown went on as if it
    had never been cancelled."""
    from app import main
    from app.services import scheduler

    cancelled, release = asyncio.Event(), asyncio.Event()

    async def slow_to_stop():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()  # still giving its connections back
            raise

    cycle = asyncio.create_task(slow_to_stop())
    monkeypatch.setattr(
        main, "_initial_ingest_task", cycle if stopping == "initial ingest" else None
    )
    monkeypatch.setattr(scheduler, "_task", cycle if stopping == "scheduler" else None)
    calls: list = []
    with (
        patch.object(main, "stop_background_tasks", _recording(calls, "stop background tasks")),
        patch.object(main, "close_redis", _recording(calls, "close redis")),
        patch.object(main, "close_pool", _recording(calls, "close pool")),
    ):
        await asyncio.sleep(0)  # the cycle runs
        shutting_down = asyncio.create_task(main.shutdown())
        await asyncio.wait_for(cancelled.wait(), 1)
        shutting_down.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shutting_down

    assert calls == []  # it stopped where it was cancelled
    release.set()
    await asyncio.wait([cycle], timeout=1)
    assert cycle.cancelled()


@pytest.mark.asyncio
async def test_a_cycle_that_turns_the_cancel_into_an_error_holds_shutdown_a_bounded_time(
    monkeypatch, caplog
):
    """asyncpg's ROLLBACK failing on a dead connection turns the cancel into an error,
    which the cycle catches ("Ingestion cycle failed.") and then runs on to its end,
    minutes with the embeddings. Shutdown waits _STOP_TIMEOUT for it, logs, goes on."""
    from app import main
    from app.services import ingestion

    monkeypatch.setattr(main, "_initial_ingest_task", None)
    monkeypatch.setattr(ingestion, "_STOP_TIMEOUT", 0.05)
    started, release = asyncio.Event(), asyncio.Event()

    async def gkg_step_whose_rollback_fails():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("ROLLBACK failed: the connection was lost") from None

    async def events_step():
        await release.wait()  # the cycle running on

    with (
        patch.object(main, "open_redis", _opened),
        patch.object(main, "open_pool", _opened),
        patch.object(main, "start_scheduler", lambda: None),
        patch.object(ingestion, "_ingest_from_raw_gkg", gkg_step_whose_rollback_fails),
        patch.object(ingestion, "_add_events", events_step),
        patch.object(ingestion, "invalidate", AsyncMock()),
        patch.object(ingestion, "_start_cache_warm", MagicMock()),
        caplog.at_level(logging.INFO),
    ):
        await main.startup()
        cycle = main._initial_ingest_task
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(main.stop_initial_ingest(), 1)  # bounded
        assert not cycle.done()
        release.set()
        await asyncio.wait_for(cycle, 1)

    assert "Initial ingestion still stopping after 0.05 s; going on." in caplog.messages
    assert "Initial ingestion stopped." not in caplog.messages
