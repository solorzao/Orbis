"""An in-memory stand-in for the Redis client app.services.cache uses, with a clock.

Holds what ``set`` stores with its TTL; ``elapse`` moves time on, so keys age
and expire. ``scan``'s match is a glob, as Redis's is.
"""

from __future__ import annotations

from fnmatch import fnmatchcase


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, float] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is None:
            self.ttls.pop(key, None)
        else:
            self.ttls[key] = ex

    async def ttl(self, key: str) -> int:
        """Seconds left, as Redis answers: -2 for no such key, -1 for no expiry."""
        if key not in self.values:
            return -2
        return int(self.ttls[key]) if key in self.ttls else -1

    async def scan(self, cursor: int = 0, match: str = "*", count: int = 10):
        return 0, [key for key in self.values if fnmatchcase(key, match)]

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self.values.pop(key, None) is not None:
                deleted += 1
            self.ttls.pop(key, None)
        return deleted

    def elapse(self, seconds: float) -> None:
        """Move the clock on: every TTL shrinks, and keys whose TTL runs out are gone."""
        for key in list(self.ttls):
            self.ttls[key] -= seconds
            if self.ttls[key] <= 0:
                del self.ttls[key]
                del self.values[key]
