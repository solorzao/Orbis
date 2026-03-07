"""Security middleware: API-key gate, per-IP rate limiting, input sanitisation."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API-key gate
# ---------------------------------------------------------------------------
# Paths that are always open (health checks, CORS preflight).
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json"}


def _check_api_key(request: Request) -> bool:
    """Return True if the request carries a valid API key (or none is configured)."""
    expected = settings.api_key
    if not expected:
        # No key configured → open access (dev mode).
        return True
    provided = request.headers.get("X-API-Key", "")
    return provided == expected


# ---------------------------------------------------------------------------
# Per-IP sliding-window rate limiter (in-memory, resets on restart)
# ---------------------------------------------------------------------------
class _RateBucket:
    """Track request timestamps for a single IP."""

    __slots__ = ("timestamps",)

    def __init__(self) -> None:
        self.timestamps: list[float] = []

    def allow(self, now: float, window: int, max_requests: int) -> bool:
        # Prune old entries.
        cutoff = now - window
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        if len(self.timestamps) >= max_requests:
            return False
        self.timestamps.append(now)
        return True


# IP → bucket, keyed by endpoint group.
_rate_buckets: dict[str, dict[str, _RateBucket]] = defaultdict(lambda: defaultdict(_RateBucket))

# Endpoint group → (window_seconds, max_requests)
_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "ai": (60, 10),       # 10 AI summary calls per minute per IP
    "data": (60, 60),     # 60 data calls per minute per IP
}

# Path prefix → group
_PATH_GROUPS: dict[str, str] = {
    "/api/news/summary": "ai",
    "/api/news/summarize-selection": "ai",
}


def _get_rate_group(path: str) -> str | None:
    for prefix, group in _PATH_GROUPS.items():
        if path.startswith(prefix):
            return group
    if path.startswith("/api/"):
        return "data"
    return None


def _client_ip(request: Request) -> str:
    """Best-effort client IP (respects X-Forwarded-For from trusted proxies)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Input sanitisation helpers (for prompt-injection mitigation)
# ---------------------------------------------------------------------------
# Patterns that look like prompt injection attempts.
_INJECTION_PATTERNS = re.compile(
    r"(?i)"
    r"(ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?))"
    r"|(you\s+are\s+now\s+(a|an|in)\s+)"
    r"|(system\s*prompt)"
    r"|(disregard\s+(all|the|your))"
    r"|(do\s+not\s+follow)"
    r"|(new\s+instructions?:)"
    r"|(developer\s+mode)"
    r"|(jailbreak)"
)


def sanitise_text(text: str, max_length: int = 200) -> str:
    """Sanitise a user-provided string before it enters an LLM prompt.

    - Strips control characters and excessive whitespace.
    - Truncates to *max_length* characters.
    - Does NOT reject; callers can additionally check ``has_injection_pattern``.
    """
    # Remove control characters (keep newlines and tabs).
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Collapse multiple newlines / whitespace runs.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned[:max_length].strip()


def has_injection_pattern(text: str) -> bool:
    """Return True if *text* contains a likely prompt-injection phrase."""
    return bool(_INJECTION_PATTERNS.search(text))


# ---------------------------------------------------------------------------
# Combined middleware
# ---------------------------------------------------------------------------
class SecurityMiddleware(BaseHTTPMiddleware):
    """Applies API-key check and rate limiting to every request."""

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        # Allow CORS preflight through unconditionally.
        if request.method == "OPTIONS":
            return await call_next(request)

        # Public paths skip auth.
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # --- API key check ---
        if not _check_api_key(request):
            logger.warning("Rejected request to %s — bad API key from %s", path, _client_ip(request))
            return JSONResponse({"detail": "Invalid or missing API key."}, status_code=403)

        # --- Rate limiting ---
        group = _get_rate_group(path)
        if group:
            window, limit = _RATE_LIMITS[group]
            ip = _client_ip(request)
            bucket_key = f"{group}:{ip}"
            bucket = _rate_buckets[group][bucket_key]
            if not bucket.allow(time.time(), window, limit):
                logger.warning("Rate-limited %s on %s (%s group)", ip, path, group)
                return JSONResponse(
                    {"detail": "Too many requests. Please try again later."},
                    status_code=429,
                    headers={"Retry-After": str(window)},
                )

        return await call_next(request)
