"""Pydantic models for news articles, clusters, and globe data points."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, BeforeValidator, Field

_MAX_IMAGE_URL_LENGTH = 2048
_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f]")
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal")


def _is_local_host(host: str) -> bool:
    """True for IP literals and names that only resolve on a local network."""
    host = host.rstrip(".")
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES) or "." not in host


def https_image_url(url: str | None) -> str | None:
    """Return a third-party image URL as a public https URL, or None.

    Image URLs come from GDELT, so anything that isn't a plain public
    http(s) URL is dropped instead of being allowed to fail the request.
    """
    if not isinstance(url, str) or not url:
        return None
    url = url.strip()
    if len(url) > _MAX_IMAGE_URL_LENGTH or _UNSAFE_URL_CHARS.search(url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError for a non-numeric or out-of-range port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if _is_local_host(parts.hostname):
        return None
    netloc = parts.netloc
    if parts.scheme == "http" and port == 80:
        netloc = netloc.rsplit(":", 1)[0]
    return parts._replace(scheme="https", netloc=netloc).geturl()


# An image URL that is either a public https URL or None, whatever the input.
HttpsImageUrl = Annotated[str | None, BeforeValidator(https_image_url)]


class NewsArticle(BaseModel):
    """A single geolocated news article."""

    id: str
    title: str
    summary: str | None = None
    source_url: str
    source_name: str
    source_language: str = "en"
    published_at: datetime
    ingested_at: datetime
    latitude: float
    longitude: float
    country_code: str = ""
    region: str = ""
    topic_tags: list[str] = Field(default_factory=list)
    sentiment_score: float = 0.0
    entities: dict = Field(default_factory=dict)
    image_url: HttpsImageUrl = None


class NewsCluster(BaseModel):
    """A spatial cluster of related articles."""

    center_lat: float
    center_lng: float
    articles: list[NewsArticle]
    topic: str
    avg_sentiment: float


class GlobeDataPoint(BaseModel):
    """Lightweight point for rendering on the 3-D globe."""

    lat: float
    lng: float
    weight: float
    article_count: int
    top_headline: str
    topic: str
    location_name: str = ""


class ClusterSummaryResponse(BaseModel):
    """Response payload for the /api/news/summary endpoint."""

    lat: float
    lng: float
    article_count: int
    summary: str


class TopicCount(BaseModel):
    """A topic with its article count."""

    topic: str
    count: int


class HourlyDensity(BaseModel):
    """Article count for a single hour bucket."""

    hour: int
    count: int


class SelectionSummaryRequest(BaseModel):
    """Request body for summarizing a user-selected set of articles."""

    headlines: list[str] = Field(..., min_length=1, max_length=10)
    location_name: str | None = Field(None, max_length=100)


class SelectionSummaryResponse(BaseModel):
    """Response payload for the selection summary endpoint."""

    summary: str
    article_count: int
