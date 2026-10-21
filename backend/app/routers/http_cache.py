"""HTTP cache headers for the API's public reads."""

from __future__ import annotations

from fastapi import HTTPException, Response

# Vercel's edge serves a public read for a minute, then for up to five more
# while it refetches in the background. Every visitor gets the same answer for
# the same URL (nothing in these reads depends on who asks), so a busy minute
# reaches the API once per URL instead of once per visitor.
EDGE_CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=300"


def edge_cached(response: Response) -> None:
    """Route dependency: let the CDN in front of the API cache a successful answer.

    Only the answer the route returns carries the header. An error (an
    HTTPException, a validation 422, the rate limiter's 429) is a new response
    without it, so it is never cached.
    """
    response.headers["Cache-Control"] = EDGE_CACHE_CONTROL


# Seconds a client waits before asking again after a 503: a week read stopped at
# a cycle's boundary is soon recomputed, or warmed.
RETRY_AFTER_SECONDS = 15


def retry_shortly(reason: Exception) -> HTTPException:
    """A 503 to raise for a computation stopped under a request (cache.FlightCancelled):
    the client retries after Retry-After. An HTTPException, so no traceback is
    logged and the edge never keeps it."""
    return HTTPException(
        status_code=503,
        detail=f"{reason}; retry shortly.",
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )
