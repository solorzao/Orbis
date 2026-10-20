"""Security middleware: API-key gate, per-IP rate limiting, input sanitisation."""

from __future__ import annotations

import hmac
import html
import logging
import re
import time
import unicodedata
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


def _has_valid_api_key(request: Request) -> bool:
    """True only if a key is configured and the request presents it."""
    expected = settings.api_key
    if not expected:
        return False
    provided = request.headers.get("X-API-Key", "")
    return hmac.compare_digest(provided.encode(), expected.encode())


def _check_api_key(request: Request) -> bool:
    """Return True if the request carries a valid API key (or none is configured)."""
    if not settings.api_key:
        # No key configured → open access (dev mode).
        return True
    return _has_valid_api_key(request)


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
    "ai": (60, 10),  # 10 AI summary calls per minute per IP
    "data": (60, 60),  # 60 data calls per minute per IP
    # A page asks once per visit; each since is its own cache entry, and a
    # miss can read a week of stories. Its own bucket, so it never spends AI calls.
    "delta": (60, 10),
}

# Path prefix → group
_PATH_GROUPS: dict[str, str] = {
    "/api/news/summary": "ai",
    "/api/news/summarize-selection": "ai",
    "/api/agent/ask": "ai",
    "/api/links/explain": "ai",
    "/api/board/analyze": "ai",
    "/api/news/delta": "delta",
}


def _get_rate_group(path: str) -> str | None:
    for prefix, group in _PATH_GROUPS.items():
        if path.startswith(prefix):
            return group
    if path.startswith("/api/"):
        return "data"
    return None


# Set by the frontend's server-side proxy to the visitor's IP. Only honoured
# on requests that passed the API-key check, since only the proxy holds the key.
_PROXY_CLIENT_IP_HEADER = "X-Orbis-Client-IP"


def _client_ip(request: Request, trusted: bool = False) -> str:
    """Best-effort client IP for rate limiting and logs.

    *trusted* means the request carried a valid API key, i.e. it came from our
    proxy, so its client-IP header is believed. Otherwise use the rightmost
    X-Forwarded-For entry: earlier entries are client-supplied and spoofable,
    while the Container Apps ingress appends the address it actually saw.
    """
    if trusted:
        proxied = request.headers.get(_PROXY_CLIENT_IP_HEADER, "").strip()
        if proxied:
            return proxied
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_ip(request: Request) -> str:
    """Client IP for rate limiting; trusts the proxy header only for a matched key."""
    return _client_ip(request, trusted=_has_valid_api_key(request))


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


# Characters that render as nothing: C1 controls, the Arabic letter mark,
# zero-width and bidi marks, word joiners and isolates, the BOM, and Unicode
# tags. They can reorder what a reader sees, or hide an injection phrase from
# the patterns above ("Ig<tag g>nore previous instructions").
_INVISIBLE = re.compile(
    r"[\x80-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\U000e0000-\U000e007f]"
)


def strip_invisible(text: str) -> str:
    """Remove the characters that render as nothing (see ``_INVISIBLE``)."""
    return _INVISIBLE.sub("", text)


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
    """Return True if *text* contains a likely prompt-injection phrase.

    Invisible characters can't hide one: the phrase is looked for with them
    removed ("Ig<tag>nore") and read as spaces ("Ignore<tag>previous"). Nor can
    lookalikes or entities: it is also looked for in an NFKC-normalised,
    HTML-unescaped copy ("ｉｇｎｏｒｅ", "&#105;gnore"). *text* itself is unchanged.
    """
    shown = unicodedata.normalize("NFKC", html.unescape(text))
    return any(
        _INJECTION_PATTERNS.search(variant)
        for form in ((text,) if shown == text else (text, shown))
        for variant in (form, _INVISIBLE.sub("", form), _INVISIBLE.sub(" ", form))
    )


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
            logger.warning(
                "Rejected request to %s — bad API key from %s",
                path,
                _client_ip(request),
            )
            return JSONResponse({"detail": "Invalid or missing API key."}, status_code=403)

        # --- Rate limiting ---
        group = _get_rate_group(path)
        if group:
            window, limit = _RATE_LIMITS[group]
            ip = _rate_limit_ip(request)
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
