"""Redis cache wrapper with graceful fallback when Redis is unavailable."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import redis.asyncio as aioredis
from pydantic import ValidationError

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

_redis_client: aioredis.Redis | None = None

# Allowance for a cycle (minutes, mostly embeddings; it invalidates db:* as it
# ends) and the cache warm after it (app.warm) to finish.
_WARM_ALLOWANCE = 600

# The week-long answers (the 7-day globe and links list) are under wk:*, which
# no cycle invalidates: each refresh reads a week of stories, so app.warm
# refreshes one at its first warm once it is WEEK_REFRESH_AGE old, about hourly,
# rather than every cycle. They live WEEK_TTL: 25 minutes past the refresh age,
# a cycle's interval and then some for cycles that run long, so an hourly
# refresh lands before the entry expires.
WEEK_TTL = 80 * 60
WEEK_REFRESH_AGE = 55 * 60


def loggable_key(key: str) -> str:
    """A cache key for a log line: its first three parts (``db:search:v1:…``). Later
    parts can hold what a visitor typed: a search query, an entity's name."""
    parts = key.split(":")
    return key if len(parts) <= 3 else ":".join(parts[:3]) + ":…"


def cycle_ttl(ttl: int) -> int:
    """A TTL for a db:* key the cache warm refills: at least until the next cycle ends.

    Ingestion invalidates db:* as each cycle ends and app.warm refills the
    busiest keys after it, so a shorter TTL only lets a warmed entry expire
    before anyone asks for it. Entries change only when a cycle runs.
    """
    return max(ttl, settings.ingestion_interval_seconds + _WARM_ALLOWANCE)


async def week_fresh(key: str) -> bool:
    """Whether a week-long entry was stored under WEEK_REFRESH_AGE ago.

    A week's answer is stored for WEEK_TTL, so the time since it was stored is
    WEEK_TTL less the TTL it has left. A missing entry is never fresh, nor an
    empty answer (stored for a minute, so the next warm retries it), nor
    anything when Redis is unavailable.
    """
    r = await get_redis()
    if r is None:
        return False
    try:
        left = await r.ttl(key)
    except Exception:
        logger.warning("Redis TTL failed for key=%s", loggable_key(key), exc_info=True)
        return False
    return left > WEEK_TTL - WEEK_REFRESH_AGE


def cached_model(key: str, cached: Any, parse: Callable[[Any], T]) -> T | None:
    """*key*'s cached entry, *cached*, parsed by *parse*: or None, a miss, when it no
    longer fits its model.

    An entry cached before its model gained a required field (as #91's
    ``capped`` was) would otherwise fail every request until it expired: the
    caller recomputes it instead, and one line is logged: the key's first
    parts (loggable_key) and the first error's place and type, never the
    cached value. Other errors raise.
    """
    try:
        return parse(cached)
    except ValidationError as exc:
        first = exc.errors()[0]
        place = ".".join(str(part) for part in first["loc"]) or "the entry"
        logger.warning(
            "Cached %s no longer fits its model (%d errors, first at %s (%s)); recomputing.",
            loggable_key(key),
            exc.error_count(),
            place,
            first["type"],
        )
        return None


# The computation running for each key (single_flight).
_in_flight: dict[str, asyncio.Task[Any]] = {}


class FlightCancelled(RuntimeError):
    """A single_flight computation was cancelled under a caller still waiting on it
    (a week read stopped at a cycle's boundary, a relations read as a cycle's
    events land, or any read at shutdown). Its message names only the key's
    prefix (``wk:*``, ``db:*``)."""


async def single_flight(
    key: str, compute: Callable[[], Awaitable[T]], *, cancel_with_caller: bool = False
) -> T:
    """``compute()``'s answer, run once for concurrent callers of *key*.

    Callers that come while it runs wait for it and get its answer, or its
    error; the next caller after it lands runs it again. A caller that is
    cancelled (a browser aborting) leaves it running for the others, unless
    it passes *cancel_with_caller* (a cache warmer, whose timeout or stop must
    end its week read). A caller whose computation is cancelled under it
    (cancel_flights, or another caller's) gets FlightCancelled. A cancelled
    computation is forgotten at once, so a newcomer starts afresh.
    """
    task = _in_flight.get(key)
    if task is None:
        task = asyncio.create_task(compute())
        _in_flight[key] = task
        task.add_done_callback(functools.partial(_landed, key))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():  # this caller is cancelled
            if cancel_with_caller:
                _landed(key, task)
                task.cancel()
            raise
        raise FlightCancelled(f"The computation for {key.split(':')[0]}:* was cancelled") from None


def cancel_flights(prefix: str) -> list[asyncio.Task[Any]]:
    """Cancel the running computations whose keys start with *prefix*, forgetting
    them at once; return them, for the caller to wait on. Their callers get
    FlightCancelled."""
    tasks = []
    for key, task in list(_in_flight.items()):
        if key.startswith(prefix):
            del _in_flight[key]
            task.cancel()
            tasks.append(task)
    return tasks


def _landed(key: str, task: asyncio.Task[Any]) -> None:
    """Forget a finished computation, so the next caller runs a new one."""
    if _in_flight.get(key) is task:
        del _in_flight[key]


async def get_redis() -> aioredis.Redis | None:
    """Return the shared Redis connection, or None if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        logger.warning("REDIS_URL not configured — caching disabled.")
        return None
    try:
        # RESP2 on the wire, as before redis-py 8 made RESP3 its default: the
        # protocol Upstash has always been spoken to with here.
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            protocol=2,
        )
        # Ping to verify connectivity.
        await _redis_client.ping()
        logger.info("Connected to Redis.")
        return _redis_client
    except Exception:
        logger.warning("Could not connect to Redis — caching disabled.", exc_info=True)
        _redis_client = None
        return None


async def close_redis() -> None:
    """Close the Redis connection pool on shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed.")


async def get_cached(key: str) -> Any | None:
    """Retrieve a JSON-serialised value from Redis.

    Returns ``None`` on cache miss or if Redis is unavailable.
    """
    r = await get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.warning("Redis GET failed for key=%s", loggable_key(key), exc_info=True)
        return None


async def set_cached(key: str, data: Any, ttl: int) -> None:
    """Store a JSON-serialisable value in Redis with a TTL in seconds."""
    r = await get_redis()
    if r is None:
        return
    try:
        await r.set(key, json.dumps(data, default=str), ex=ttl)
    except Exception:
        logger.warning("Redis SET failed for key=%s", loggable_key(key), exc_info=True)


async def get_many(keys: list[str]) -> list[Any | None]:
    """The JSON values of *keys*, in order, in one round trip (MGET): None for a miss,
    a value that isn't JSON, or when Redis is unavailable. A cached JSON null reads
    as None too, so wrap a value that may be null."""
    if not keys:
        return []
    r = await get_redis()
    if r is None:
        return [None] * len(keys)
    try:
        raws = await r.mget(keys)
    except Exception:
        logger.warning("Redis MGET failed for %d keys.", len(keys), exc_info=True)
        return [None] * len(keys)
    values: list[Any | None] = []
    for raw in raws:
        try:
            values.append(None if raw is None else json.loads(raw))
        except ValueError:
            values.append(None)
    return values


async def set_many(data: dict[str, Any], ttl: int) -> None:
    """Store each JSON-serialisable value under its key with a TTL in seconds, in one
    round trip (a pipeline, not a transaction). Never raises."""
    if not data:
        return
    r = await get_redis()
    if r is None:
        return
    try:
        async with r.pipeline(transaction=False) as pipe:
            for key, value in data.items():
                pipe.set(key, json.dumps(value, default=str), ex=ttl)
            await pipe.execute()
    except Exception:
        logger.warning("Redis SET of %d keys failed.", len(data), exc_info=True)


async def invalidate(pattern: str) -> None:
    """Delete all keys matching *pattern* (supports ``*`` glob)."""
    r = await get_redis()
    if r is None:
        return
    try:
        cursor: int = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        logger.warning(
            "Redis INVALIDATE failed for pattern=%s", loggable_key(pattern), exc_info=True
        )
