"""Tests for the app's startup and shutdown hooks."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_shutdown_stops_background_work_before_closing_connections():
    """A cache warm still running would otherwise reopen Redis or the pool after close."""
    from app import main

    calls: list = []

    def step(name):
        async def record(**kwargs):
            calls.append((name, kwargs) if kwargs else name)

        return record

    with (
        patch.object(main, "stop_scheduler", step("scheduler")),
        patch.object(main, "stop_background_tasks", step("background tasks")),
        patch.object(main, "close_redis", step("redis")),
        patch.object(main, "close_pool", step("pool")),
    ):
        await main.shutdown()

    # At shutdown every wk: read stops (a cycle's start leaves the relations' running).
    assert calls == ["scheduler", ("background tasks", {"shutdown": True}), "redis", "pool"]


STARTUP = ["redis", "pool", "scheduler"]
SHUTDOWN = ["stop scheduler", "stop background tasks", "close redis", "close pool"]


@pytest.fixture
def lifecycle_calls():
    """What startup and shutdown call, recorded in order instead of run."""
    from app import main

    calls: list = []

    def step(name):
        async def record(**kwargs):
            calls.append(name)

        return record

    with (
        patch.object(main, "open_redis", step("redis")),
        patch.object(main, "open_pool", step("pool")),
        patch.object(main, "run_ingestion_cycle", AsyncMock(return_value=0)),
        patch.object(main, "start_scheduler", lambda: calls.append("scheduler")),
        patch.object(main, "stop_scheduler", step("stop scheduler")),
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
