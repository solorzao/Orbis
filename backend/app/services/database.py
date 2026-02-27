"""Supabase database client for the Orbis backend.

Provides helpers for querying articles with spatial, temporal, and
topic-based filters.  All public functions are importable via:

    from app.services.database import *
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client, create_client

from app.config import settings

__all__ = [
    "get_supabase",
    "get_articles",
    "get_nearby_articles",
    "get_articles_in_bounds",
    "upsert_articles",
    "get_topic_counts",
]

# ---------------------------------------------------------------------------
# Supabase client singleton
# ---------------------------------------------------------------------------

_client: Client | None = None


def get_supabase() -> Client:
    """Return a cached Supabase client (service-role for backend writes)."""
    global _client
    if _client is None:
        url = settings.supabase_url
        key = settings.supabase_service_role_key or settings.supabase_anon_key
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) "
                "must be set in environment variables."
            )
        _client = create_client(url, key)
    return _client


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_articles(
    *,
    topic: str | None = None,
    timespan_hours: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch articles with optional topic and timespan filters.

    Parameters
    ----------
    topic:
        If provided, only return articles whose ``topic_tags`` contain this
        value.
    timespan_hours:
        If provided, only return articles published within the last N hours.
    limit:
        Maximum number of rows to return (default 100).
    """
    sb = get_supabase()
    query = sb.table("articles").select("*")

    if topic:
        query = query.contains("topic_tags", [topic])

    if timespan_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
        query = query.gte("published_at", cutoff.isoformat())

    query = query.order("published_at", desc=True).limit(limit)
    response = query.execute()
    return response.data


def get_nearby_articles(
    lat: float,
    lng: float,
    radius_km: float = 100,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find articles within *radius_km* of a geographic point.

    Delegates to the ``nearby_articles`` Postgres function which uses
    PostGIS ``ST_DWithin``.
    """
    sb = get_supabase()
    response = sb.rpc(
        "nearby_articles",
        {
            "lat": lat,
            "lng": lng,
            "radius_km": radius_km,
            "limit_count": limit,
        },
    ).execute()
    return response.data


def get_articles_in_bounds(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return articles inside a lat/lng bounding box (for globe viewport).

    Delegates to the ``articles_in_bounds`` Postgres function.
    """
    sb = get_supabase()
    response = sb.rpc(
        "articles_in_bounds",
        {
            "min_lat": min_lat,
            "min_lng": min_lng,
            "max_lat": max_lat,
            "max_lng": max_lng,
            "limit_count": limit,
        },
    ).execute()
    return response.data


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def upsert_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bulk upsert articles, deduplicating on ``source_url``.

    Each dict in *articles* should contain at minimum the required columns
    (``title``, ``source_url``, ``source_name``, ``published_at``,
    ``latitude``, ``longitude``).  The ``location`` geography column is
    expected to be set by the caller or a database trigger; if you prefer
    to compute it in Python, include a WKT/GeoJSON string.

    Returns the upserted rows.
    """
    sb = get_supabase()
    response = (
        sb.table("articles")
        .upsert(articles, on_conflict="source_url")
        .execute()
    )
    return response.data


# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------


def get_topic_counts() -> dict[str, int]:
    """Return a mapping of topic tag to article count.

    Delegates to the ``topic_counts`` Postgres function.
    """
    sb = get_supabase()
    response = sb.rpc("topic_counts").execute()
    return {row["topic"]: row["count"] for row in response.data}
