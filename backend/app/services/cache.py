"""Redis cache wrapper with graceful fallback when Redis is unavailable."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None

# Allowance for a cycle (minutes, mostly embeddings; it invalidates db:* as it
# ends) and the cache warm after it (app.warm) to finish.
_WARM_ALLOWANCE = 600


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


async def get_redis() -> aioredis.Redis | None:
    """Return the shared Redis connection, or None if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        logger.warning("REDIS_URL not configured — caching disabled.")
        return None
    try:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
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
