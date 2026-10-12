"""HTTP cache headers for the API's public reads."""

from __future__ import annotations

from fastapi import Response

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
