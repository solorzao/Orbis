"""Lightweight asyncio scheduler for periodic GDELT ingestion.

No external dependencies (no Celery, no APScheduler) — just an
``asyncio.sleep`` loop that fits within the 0.25 CPU container budget.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.services.ingestion import run_ingestion_cycle

logger = logging.getLogger("orbis.scheduler")

_task: asyncio.Task | None = None


async def _ingestion_loop(interval: int) -> None:
    """Run ingestion cycles forever with *interval* seconds between them."""
    while True:
        await asyncio.sleep(interval)
        await run_ingestion_cycle()


def start_scheduler() -> None:
    """Start the background ingestion loop (idempotent)."""
    global _task
    if _task is not None:
        return
    interval = settings.ingestion_interval_seconds
    _task = asyncio.get_event_loop().create_task(_ingestion_loop(interval))
    logger.info("Scheduler started — ingestion every %ds.", interval)


async def stop_scheduler() -> None:
    """Cancel the background ingestion loop."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("Scheduler stopped.")
