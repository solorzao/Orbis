"""Tests for the app's startup and shutdown hooks."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_shutdown_stops_background_work_before_closing_connections():
    """A cache warm still running would otherwise reopen Redis or the pool after close."""
    from app import main

    calls: list[str] = []

    def step(name):
        async def record():
            calls.append(name)

        return record

    with (
        patch.object(main, "stop_scheduler", step("scheduler")),
        patch.object(main, "stop_background_tasks", step("background tasks")),
        patch.object(main, "close_redis", step("redis")),
        patch.object(main, "close_pool", step("pool")),
    ):
        await main.shutdown()

    assert calls == ["scheduler", "background tasks", "redis", "pool"]
