"""Pydantic models for news articles, clusters, and globe data points."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, BeforeValidator, Field

_MAX_IMAGE_URL_LENGTH = 2048
_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# A plain ASCII hostname; anything else (%, \, brackets) is left over from parsing.
_ASCII_HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.?")
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal")
# The URL Standard's "ends in a number" check: browsers parse such hosts as IPv4.
_NUMERIC_LABEL = re.compile(r"[0-9]+|0x[0-9a-f]*", re.IGNORECASE)


def _is_local_host(host: str) -> bool:
    """True for IP literals (including shorthand IPv4), local-network names,
    and hosts that don't canonicalise to a plain ASCII hostname."""
    try:
        # Maps U+3002/U+FF0E and fullwidth chars; punycodes IDNs.
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return True
    if not _ASCII_HOST.fullmatch(host):
        return True
    host = host.rstrip(".")
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]):
        return True
    return host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES) or "." not in host


def https_image_url(url: str | None) -> str | None:
    """Return a third-party image URL as a public https URL, or None.

    Image URLs come from GDELT, so anything that isn't a plain public
    http(s) URL is dropped instead of being allowed to fail the request.
    """
    if not isinstance(url, str) or not url:
        return None
    url = url.strip().replace(" ", "%20")
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


def https_only_image_url(url: str | None) -> str | None:
    """Like ``https_image_url``, but an http URL is None rather than upgraded.

    For the hover card, which shows an image unprompted: an upgraded http URL
    often fails, and the globe query already prefers stories with https images.
    """
    if not isinstance(url, str) or not url.strip().lower().startswith("https://"):
        return None
    return https_image_url(url)


# A public https image URL as stored, or None (never an upgraded http one).
HttpsOnlyImageUrl = Annotated[str | None, BeforeValidator(https_only_image_url)]


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
    country_code: str = Field("", description="ISO 3166-1 alpha-2; '' if unknown")
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


class GlobeLead(BaseModel):
    """A cell's lead story for the hover card: its newest, preferring one with an image."""

    title: str
    source_name: str
    published_at: datetime
    image_url: HttpsOnlyImageUrl = None
    topic: str  # the story's first tag, "general" when it has none
    # Conflict among any of its tags: the card veils its image until asked.
    sensitive: bool = False


class GlobeDataPoint(BaseModel):
    """Lightweight point for rendering on the 3-D globe, with its hover card's data."""

    lat: float
    lng: float
    weight: float
    article_count: int
    top_headline: str
    # Sets the dot colour: the topic filter's tag when the globe is filtered,
    # otherwise the cell's most common of the six topics ("general" if none).
    topic: str
    location_name: str = ""  # display_place of the lead's region
    country_code: str = ""  # the lead's ISO 3166-1 alpha-2, '' if unknown
    lead: GlobeLead | None = None
    # The six topics' tags -> the cell's stories with that tag (a story with
    # two counts twice); topics without stories are left out.
    topic_mix: dict[str, int] = Field(default_factory=dict)
    tone: float = 0.0  # mean sentiment_score of the cell's stories, -1..1


class Surge(BaseModel):
    """A place whose coverage is surging (/api/news/surges): see services/surges.py."""

    lat: float  # the 1° cell's centre, as its globe dot has it
    lng: float
    place: str  # display_place of the lead's region
    recent: int  # distinct stories in the last 2 hours
    baseline: float  # distinct stories per 2 hours over the 166 hours before
    ratio: float  # recent / max(baseline, 0.5); the frontend shows "20×+" above 20
    topic: str  # the topic filter's tag, else the most common of the six ("general" if none)
    lead: GlobeLead  # the newest recent story, preferring an https image


class DeltaPlace(BaseModel):
    """One of the places with the most new stories since a visit."""

    lat: float  # the 1° cell's centre, as its globe dot has it
    lng: float
    place: str  # display_place of the lead's region
    new: int  # distinct stories since the visit
    lead: GlobeLead  # the newest of them, preferring an https image


class Delta(BaseModel):
    """What changed since a visit (/api/news/delta)."""

    new_stories: int  # distinct stories since the visit
    new_places: int  # 1° cells with any of them
    surging: int  # places surging now, as /api/news/surges lists them (at most 8)
    top: list[DeltaPlace]  # up to 5, most new stories first


class PreviewEntity(BaseModel):
    """A name a place's stories mention: a person or an organisation."""

    name: str
    type: Literal["person", "org"]
    n: int  # stories naming it


class PlacePreview(BaseModel):
    """What the hover card adds after a dwell (/api/news/preview)."""

    spark: list[int]  # stories per UTC hour, the 24 hours up to the window's end, oldest first
    entities: list[PreviewEntity]  # up to 3, most stories first
    brief: str | None = None  # the cell's cached AI summary, if a click has made one


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


class HourlyVolume(BaseModel):
    """Stories published in one UTC hour (``hour`` is the hour's start)."""

    hour: datetime
    count: int


class SelectionSummaryRequest(BaseModel):
    """Request body for summarizing a user-selected set of articles."""

    headlines: list[str] = Field(..., min_length=1, max_length=10)
    location_name: str | None = Field(None, max_length=100)


class SelectionSummaryResponse(BaseModel):
    """Response payload for the selection summary endpoint."""

    summary: str
    article_count: int
