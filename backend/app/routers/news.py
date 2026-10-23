"""API routes for news data, clusters, summaries, and topics."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.middleware.security import has_injection_pattern, sanitise_text, strip_invisible
from app.models.news import (
    BreakingStory,
    ClusterSummaryResponse,
    Delta,
    GlobeDataPoint,
    HourlyDensity,
    HourlyVolume,
    NewsArticle,
    PlacePreview,
    PreviewEntity,
    SelectionSummaryRequest,
    SelectionSummaryResponse,
    TopicCount,
)
from app.routers.http_cache import edge_cached, retry_shortly
from app.services.ai_summary import (
    _window_key,
    cached_summary,
    summarise_cluster,
    summarise_selection,
)
from app.services.breaking import get_breaking
from app.services.cache import (
    WEEK_TTL,
    FlightCancelled,
    cached_model,
    cycle_ttl,
    get_cached,
    set_cached,
    single_flight,
    week_fresh,
)
from app.services.database import (
    get_articles_in_bounds,
    get_cell_entities,
    get_cell_spark,
    get_globe_points,
    get_globe_points_by_topic,
    get_hourly_density,
    get_hourly_volume,
    get_topic_counts,
)
from app.services.delta import get_delta
from app.services.grid import cell_index
from app.services.thread_reads import article_thread
from app.services.titles import dedup_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["news"])

# Frontend sends "Climate" but classifier uses "environment"
_TOPIC_ALIASES = {"climate": "environment"}

# The globe's topic pills (frontend Topic), lowercased; "All" is no filter.
_GLOBE_TOPICS = frozenset({"politics", "conflict", "technology", "climate", "economy", "health"})


def _deduplicate_articles(articles: list) -> list:
    """Remove syndicated duplicates, keeping the first (most recent) per title."""
    seen: set[str] = set()
    result = []
    for a in articles:
        key = dedup_key(a.title)
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def _resolve_topic(topic: str | None) -> str | None:
    if not topic:
        return None
    lower = topic.lower()
    return _TOPIC_ALIASES.get(lower, lower)


def _globe_topic_tag(topic: str | None) -> str | None:
    """The article tag for a globe topic pill (any case), or None for All or no topic.

    Anything else is a 422: an unknown topic would otherwise come back as an
    empty globe, or the whole one.
    """
    if not isinstance(topic, str) or not topic or topic.lower() == "all":
        return None
    if topic.lower() not in _GLOBE_TOPICS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown topic {topic!r}: one of All, Politics, Conflict, Technology, "
            "Climate, Economy or Health.",
        )
    return _resolve_topic(topic)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string to a timezone-aware datetime."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# How long an empty globe window stays cached: long enough to spare the
# database a request per visitor, short enough that new stories show soon.
_EMPTY_GLOBE_TTL = 60

# The longest live window: the timeline's 7-day preset.
_MAX_TIMESPAN_HOURS = 168


def _parse_timespan(timespan: str) -> int:
    """Convert a timespan string like '24h' or '168h' to hours, from 1 to 168."""
    s = timespan.strip().lower()
    if s.endswith("h"):
        try:
            return min(max(int(s[:-1]), 1), _MAX_TIMESPAN_HOURS)
        except ValueError:
            pass
    return 24


def _row_to_article(row: dict) -> NewsArticle:
    """Convert a database row dict to a NewsArticle model."""
    return NewsArticle(
        id=str(row.get("id", "")),
        title=row.get("title", ""),
        summary=row.get("summary"),
        source_url=row.get("source_url", ""),
        source_name=row.get("source_name", ""),
        source_language=row.get("source_language", "en"),
        published_at=row.get("published_at", datetime.now(timezone.utc)),
        ingested_at=row.get("ingested_at", datetime.now(timezone.utc)),
        latitude=row.get("latitude", 0.0),
        longitude=row.get("longitude", 0.0),
        country_code=row.get("country_code", ""),
        region=row.get("region", ""),
        topic_tags=row.get("topic_tags", []),
        sentiment_score=row.get("sentiment_score", 0.0),
        entities=(
            json.loads(row["entities"])
            if isinstance(row.get("entities"), str)
            else row.get("entities", {})
        ),
        image_url=row.get("image_url"),
        thread=article_thread(row),
    )


@router.get("/news", response_model=list[GlobeDataPoint], dependencies=[Depends(edge_cached)])
async def get_globe_data(
    timespan: str = Query("24h", description="Timespan, e.g. 24h, 48h"),
    limit: int = Query(500, ge=1, le=500, description="Max data points"),
    start_time: str | None = Query(None, description="ISO start time"),
    end_time: str | None = Query(None, description="ISO end time"),
    topic: str | None = Query(
        None,
        description="Topic pill: Politics, Conflict, Technology, Climate, Economy, Health or All",
    ),
) -> list[GlobeDataPoint]:
    """Return globe data points clustered from articles in the database.

    A topic keeps only its stories, before the busiest *limit* cells are
    picked: each cell's count, headline and colour are then the topic's.
    Each point also carries what the hover card shows first: its lead story,
    topic mix and tone (see get_globe_points).
    """
    return await cached_globe(
        _parse_timespan(timespan), start_time, end_time, limit, _globe_topic_tag(topic)
    )


async def cached_globe(
    hours: int, start_time: str | None, end_time: str | None, limit: int, tag: str | None
) -> list[GlobeDataPoint]:
    """/api/news' answer: cached, else computed and cached.

    The request and its cache warmers come here, or store what it would, so a
    warmed entry has the key and the bytes a request would have stored. An
    entry that no longer fits GlobeDataPoint is a miss.

    The 7-day window's answers are week-long entries (wk:*, refreshed hourly
    by warm_globe_week). A miss there is computed once for concurrent
    requests: for the frontend's limit, by the one pass that stores every
    topic's, so clicking through topics reads the week once.
    """
    cache_k = _globe_key(hours, start_time, end_time, limit, tag)
    cached = await get_cached(cache_k)
    if cached is not None:  # [] is a cached empty window
        points = cached_model(cache_k, cached, _globe_points)
        if points is not None:
            return points

    load = functools.partial(_load_globe, cache_k, hours, start_time, end_time, limit, tag)
    if not _is_week(hours, start_time, end_time):
        return await load()
    try:
        if limit == _FIRST_VISIT_GLOBE_LIMIT:
            return (await single_flight(_GLOBE_WEEK_FLIGHT, _refresh_globe_week))[tag]
        return await single_flight(cache_k, load)
    except FlightCancelled as stopped:  # at a cycle's boundary: a 503 to retry
        raise retry_shortly(stopped) from None


def _is_week(hours: int, start_time: str | None, end_time: str | None) -> bool:
    """Whether a globe request is the 7-day window's (live, 168 hours)."""
    return hours == _WEEK_HOURS and not start_time and not end_time


def _globe_key(
    hours: int, start_time: str | None, end_time: str | None, limit: int, tag: str | None
) -> str:
    """cached_globe's key for a request: the 7-day window's under wk:, which no
    cycle invalidates (see cache.WEEK_TTL), the others under db:."""
    # v2: points carry the hover card's lead, topic mix and tone.
    prefix = "wk" if _is_week(hours, start_time, end_time) else "db"
    return f"{prefix}:globe:v2:{start_time or hours}:{end_time or ''}:{limit}:{tag or ''}"


def _globe_points(cached: list) -> list[GlobeDataPoint]:
    return [GlobeDataPoint.model_validate(p) for p in cached]


async def _load_globe(
    cache_k: str,
    hours: int,
    start_time: str | None,
    end_time: str | None,
    limit: int,
    tag: str | None,
) -> list[GlobeDataPoint]:
    """Compute one globe (one topic's) and cache it under *cache_k*."""
    rows = await get_globe_points(
        timespan_hours=hours,
        cell_size=1.0,
        limit=limit,
        start_time=_parse_iso(start_time),
        end_time=_parse_iso(end_time),
        topic=tag,
    )
    return await _cache_globe(cache_k, rows, week=_is_week(hours, start_time, end_time))


async def _cache_globe(cache_k: str, rows: list[dict], *, week: bool) -> list[GlobeDataPoint]:
    """Cache a globe's points: a week's for WEEK_TTL, others until the next cycle
    ends. An empty globe only briefly, so new stories show soon; but an empty
    week other than All's (the warm's gate, which must not read as fresh) for
    WEEK_TTL, or each request for it would read the week again."""
    points = [GlobeDataPoint(**r) for r in rows]
    if points:
        ttl = WEEK_TTL if week else cycle_ttl(settings.db_cache_ttl)
    elif week and cache_k != _GLOBE_WEEK_GATE:
        ttl = WEEK_TTL
    else:
        ttl = _EMPTY_GLOBE_TTL
    await set_cached(cache_k, [p.model_dump(mode="json") for p in points], ttl)
    return points


# The frontend's first visit: DEFAULT_WINDOW (24 hours), GLOBE_LIMIT, all topics.
_FIRST_VISIT_GLOBE_HOURS = 24
_FIRST_VISIT_GLOBE_LIMIT = 500


async def warm_globe() -> None:
    """Cache the globe the first visit asks for (app.warm, after each ingestion cycle)."""
    await cached_globe(_FIRST_VISIT_GLOBE_HOURS, None, None, _FIRST_VISIT_GLOBE_LIMIT, None)


# The timeline's 7-day preset (frontend LiveHours).
_WEEK_HOURS = 168

# The one pass that refreshes the 7-day globe's seven entries (single_flight).
_GLOBE_WEEK_FLIGHT = "wk:globe:v2:168::500:*"

# All's 7-day entry: its age gates warm_globe_week (cache.week_fresh).
_GLOBE_WEEK_GATE = _globe_key(_WEEK_HOURS, None, None, _FIRST_VISIT_GLOBE_LIMIT, None)


async def warm_globe_week() -> None:
    """Refresh the 7-day globe for All and each topic pill about hourly (app.warm).

    Nothing while it is fresh (cache.week_fresh: under 55 minutes old), so most
    cycles skip it: each refresh reads the week's stories (25 s on production).
    Joins a refresh that a request's miss has started; the warm's timeout, or a
    stop (stop_background_tasks), cancels it.
    """
    if await week_fresh(_GLOBE_WEEK_GATE):
        return
    await single_flight(_GLOBE_WEEK_FLIGHT, _refresh_globe_week, cancel_with_caller=True)


async def _refresh_globe_week() -> dict[str | None, list[GlobeDataPoint]]:
    """Compute the 7-day globe for All and each topic from one pass over the week
    (get_globe_points_by_topic), and cache each for WEEK_TTL under the key, and as
    the bytes, its request would cache. Each was its own query, 20-73 s cold on
    production, and a topic click kept the last topic's dots up meanwhile.

    All's entry is written last: it gates the warm, so a refresh cancelled
    partway never leaves it fresh over stale topics."""
    globes = await get_globe_points_by_topic(
        timespan_hours=_WEEK_HOURS, cell_size=1.0, limit=_FIRST_VISIT_GLOBE_LIMIT
    )
    points: dict[str | None, list[GlobeDataPoint]] = {}
    for tag in sorted(globes, key=lambda t: t is None):  # the topics, then All
        key = _globe_key(_WEEK_HOURS, None, None, _FIRST_VISIT_GLOBE_LIMIT, tag)
        points[tag] = await _cache_globe(key, globes[tag], week=True)
    return points


# Grid cell size must match get_globe_points() call in get_globe_data().
_CELL_SIZE = 1.0

# Newest articles fetched per cell: the most "Load more" can page through.
_CELL_FETCH_LIMIT = 300

# Articles fetched for a cell summary: it summarises the first 10 (and
# summarise_cluster reads at most 30); the rest is headroom for the syndicated
# copies _deduplicate_articles drops.
_SUMMARY_FETCH_LIMIT = 30


async def _fetch_cell_articles(
    lat: float,
    lng: float,
    topic: str | None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    sentiment: str | None = None,
    search: str | None = None,
    limit: int = _CELL_FETCH_LIMIT,
) -> list[NewsArticle]:
    """Fetch articles within the grid cell containing (lat, lng).

    The topic filter runs in SQL (any of the article's tags), before the
    limit; a topic the cell has no articles for gives an empty list. Then
    applies optional filters for sentiment band and title search.
    """
    # The dots' grid cell, as in the summary cache key.
    min_lat = cell_index(lat, _CELL_SIZE) * _CELL_SIZE
    min_lng = cell_index(lng, _CELL_SIZE) * _CELL_SIZE
    resolved = _resolve_topic(topic)
    rows = await get_articles_in_bounds(
        min_lat,
        min_lng,
        min_lat + _CELL_SIZE,
        min_lng + _CELL_SIZE,
        limit=limit,
        start_time=start_time,
        end_time=end_time,
        topics=[resolved] if resolved else None,
    )
    articles = _deduplicate_articles([_row_to_article(r) for r in rows])

    if sentiment:
        s = sentiment.lower()
        if s == "positive":
            articles = [a for a in articles if a.sentiment_score >= 0.5]
        elif s == "neutral":
            articles = [a for a in articles if 0 <= a.sentiment_score < 0.5]
        elif s == "negative":
            articles = [a for a in articles if a.sentiment_score < 0]

    if search:
        q = search.lower()
        articles = [a for a in articles if q in a.title.lower()]

    return articles


@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(0.75, description="Deprecated — ignored, uses grid cell"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name"),
    offset: int = Query(0, ge=0, description="Number of articles to skip"),
    limit: int = Query(10, ge=1, le=50, description="Max articles to return"),
    start_time: str | None = Query(None, description="ISO start time"),
    end_time: str | None = Query(None, description="ISO end time"),
    sentiment: str | None = Query(None, description="Sentiment band: positive, neutral, negative"),
    search: str | None = Query(None, description="Title text search"),
) -> list[NewsArticle]:
    """Return full articles in the grid cell around (lat, lng)."""
    start_dt = _parse_iso(start_time)
    end_dt = _parse_iso(end_time)
    articles = await _fetch_cell_articles(
        lat,
        lng,
        topic,
        start_time=start_dt,
        end_time=end_dt,
        sentiment=sentiment,
        search=search,
    )
    return articles[offset : offset + limit]


@router.get("/news/summary", response_model=ClusterSummaryResponse)
async def get_cluster_summary(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(0.75, description="Deprecated — ignored, uses grid cell"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(
        None,
        description="Ignored: the place name is resolved server-side from the cell's articles",
    ),
    start_time: str | None = Query(None, description="ISO start time"),
    end_time: str | None = Query(None, description="ISO end time"),
) -> ClusterSummaryResponse:
    """Return an AI-generated summary for the cluster at a location."""
    resolved = _resolve_topic(topic)
    start_dt = _parse_iso(start_time)
    end_dt = _parse_iso(end_time)
    articles = await _fetch_cell_articles(
        lat, lng, resolved, start_time=start_dt, end_time=end_dt, limit=_SUMMARY_FETCH_LIMIT
    )
    nearby = articles[:10]

    summary_text = await summarise_cluster(
        nearby,
        lat,
        lng,
        topic=resolved,
        cell_size=_CELL_SIZE,
        start_time=start_dt,
        end_time=end_dt,
    )
    return ClusterSummaryResponse(
        lat=lat,
        lng=lng,
        article_count=len(nearby),
        summary=summary_text,
    )


# How long a place's preview stays cached: new stories, and a summary a click
# has just made, show within five minutes.
_PREVIEW_TTL = 300

# The timeline's live presets (frontend LiveHours); any other timespan is a 422.
_LIVE_HOURS = frozenset({1, 6, 24, 168})

# The longest range: the timeline's 7 days straddle 8 UTC days.
_MAX_RANGE = timedelta(days=8)

# Names fetched before cleaning, and the ones the card shows.
_ENTITY_FETCH_LIMIT = 10
_MAX_ENTITIES = 3
_MAX_ENTITY_CHARS = 80


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _preview_window(
    timespan: str, start_time: str | None, end_time: str | None
) -> tuple[datetime, datetime]:
    """The window's bounds, as the frontend's TimeWindow allows them, or a 422.

    A range needs both bounds, as ISO 8601 times, in order and at most 8 days
    apart. Otherwise the window is live: one of the timeline's presets, the
    last that many hours up to now.
    """
    if start_time is not None or end_time is not None:
        start, end = _parse_iso(start_time), _parse_iso(end_time)
        if start is None or end is None:
            raise HTTPException(
                status_code=422,
                detail="A range needs start_time and end_time, both ISO 8601 times.",
            )
        if start >= end:
            raise HTTPException(status_code=422, detail="start_time must be before end_time.")
        if end - start > _MAX_RANGE:
            raise HTTPException(status_code=422, detail="A range spans at most 8 days.")
        return start, end
    match = re.fullmatch(r"(\d{1,3})h", timespan.strip().lower())
    hours = int(match.group(1)) if match else 0
    if hours not in _LIVE_HOURS:
        raise HTTPException(status_code=422, detail="timespan must be 1h, 6h, 24h or 168h.")
    now = _now()
    return now - timedelta(hours=hours), now


def _clean_entities(rows: list[dict]) -> list[PreviewEntity]:
    """The top names as text to show, from GDELT's raw ones.

    Hidden characters and control characters go, then whitespace collapses to
    one line of at most 80 characters. A name left empty, one that looks like
    a prompt injection (PR 17 sends tracked names to the co-pilot), and a
    repeat of an earlier name are dropped.
    """
    seen: set[str] = set()
    entities: list[PreviewEntity] = []
    for row in rows:
        raw = row.get("name")
        if not isinstance(raw, str):
            continue
        name = " ".join(sanitise_text(strip_invisible(raw), max_length=_MAX_ENTITY_CHARS).split())
        if not name or has_injection_pattern(name) or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        entities.append(PreviewEntity(name=name, type=row["type"], n=row["n"]))
        if len(entities) == _MAX_ENTITIES:
            break
    return entities


@router.get("/news/preview", response_model=PlacePreview, dependencies=[Depends(edge_cached)])
async def get_place_preview(
    lat: float = Query(..., ge=-90, le=90, description="Latitude of the dot"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude of the dot"),
    timespan: str = Query("24h", description="A live window: 1h, 6h, 24h or 168h"),
    start_time: str | None = Query(None, description="A range's ISO start, with end_time"),
    end_time: str | None = Query(None, description="A range's ISO end, with start_time"),
    topic: str | None = Query(
        None,
        description="Topic pill: Politics, Conflict, Technology, Climate, Economy, Health or All",
    ),
) -> PlacePreview:
    """What the hover card adds once the pointer dwells on a dot.

    For the dot's 1° cell, its window and topic: stories per hour over the 24
    hours up to the window's end, the names its stories mention most, and
    the AI brief a click on the dot has cached for the same window and topic.
    Never calls Claude: no cached summary is a null brief.
    """
    tag = _globe_topic_tag(topic)
    start, end = _preview_window(timespan, start_time, end_time)
    cell_lat = cell_index(lat, _CELL_SIZE)
    cell_lng = cell_index(lng, _CELL_SIZE)

    # The window floored to the hour, as the summary's key has it.
    topic_suffix = f":{tag}" if tag else ""
    cache_k = f"preview:v1:{cell_lat}:{cell_lng}:{_window_key(start, end)}{topic_suffix}"
    cached = await get_cached(cache_k)
    preview = None if cached is None else cached_model(cache_k, cached, PlacePreview.model_validate)
    if preview is not None:
        return preview

    min_lat = cell_lat * _CELL_SIZE
    min_lng = cell_lng * _CELL_SIZE
    box = (min_lat, min_lng, min_lat + _CELL_SIZE, min_lng + _CELL_SIZE)
    spark, names, brief = await asyncio.gather(
        get_cell_spark(*box, end_time=end, topic=tag),
        get_cell_entities(
            *box, start_time=start, end_time=end, topic=tag, limit=_ENTITY_FETCH_LIMIT
        ),
        cached_summary(lat, lng, _CELL_SIZE, start, end, tag),
    )
    preview = PlacePreview(spark=spark, entities=_clean_entities(names), brief=brief)
    await set_cached(cache_k, preview.model_dump(), _PREVIEW_TTL)
    return preview


# How long breaking stories stay cached: at least until the next cycle ends
# (cycle_ttl). Each ingestion invalidates them once its new rows are embedded,
# and app.warm refills them. None breaking is an answer too.
_BREAKING_TTL = 300
_BREAKING_KEY = "db:breaking:v1"

# The last list the query answered, outside the db:* each cycle invalidates
# (as the week reads keep theirs under wk:*), written with _BREAKING_KEY by
# every query that lands, the warm's too. A miss serves it at once while one
# query refills both in the background: that query takes 11-14 s on
# production, near its 15 s limit, and a visitor between a cycle's
# invalidation and the warm's refill waited on it, or got a 500 when it timed
# out (110 in the four days to 2026-10-23). It lives an hour, four cycles:
# breaking counts the last 2 hours' coverage, so a list an hour old (plus the
# edge's minutes) still names events that broke within the last three: a
# ticker a little behind, rather than one failing. Older, it is gone, and a
# miss waits for the query again.
_BREAKING_LAST_KEY = "last:breaking:v1"
_BREAKING_LAST_TTL = 60 * 60

# The most a request lists: the ticker's.
_MAX_BREAKING = 8

# The breaking query running for each cache key: misses that arrive while it
# runs (visitors as the entry expires, or a delta) wait for it, or take the
# last good list, rather than run their own.
_breaking_in_flight: dict[str, asyncio.Task[list[BreakingStory]]] = {}

# Seconds the shared query may take. The pool sets no command timeout, so
# without this a hung query (a half-open connection) would hold every later
# breaking miss and delta in the process.
_BREAKING_QUERY_TIMEOUT = 15


async def _cached_breaking() -> list[BreakingStory]:
    """Every breaking story, for every topic, uncapped, from Redis when there.

    One list serves every topic: an event's topic is its stories', so the
    filter and the cap apply to it per request. On a miss, one query runs at
    a time, and the last good list (_BREAKING_LAST_KEY) is served while it
    does. With none, every concurrent caller waits for the query and gets its
    answer, or its error (nothing is cached then): a TimeoutError after 15 s.
    A caller that is cancelled leaves the query running for the others.
    """
    stories = await _breaking_entry(_BREAKING_KEY)
    if stories is not None:
        return stories
    task = _breaking_query()
    stories = await _breaking_entry(_BREAKING_LAST_KEY)
    if stories is not None:
        return stories  # the query runs on, and lands in both keys
    return await asyncio.shield(task)


async def _breaking_entry(cache_k: str) -> list[BreakingStory] | None:
    """The breaking list cached under *cache_k*, or None: missing, or no longer fitting."""
    cached = await get_cached(cache_k)
    if cached is None:  # [] is a cached answer too
        return None
    return cached_model(cache_k, cached, lambda c: [BreakingStory.model_validate(s) for s in c])


def _breaking_query() -> asyncio.Task[list[BreakingStory]]:
    """The breaking query running, or a new one: one at a time."""
    task = _breaking_in_flight.get(_BREAKING_KEY)
    if task is None:
        task = asyncio.create_task(_load_breaking(_BREAKING_KEY))
        _breaking_in_flight[_BREAKING_KEY] = task
        task.add_done_callback(functools.partial(_landed, _BREAKING_KEY))
    return task


async def _load_breaking(cache_k: str) -> list[BreakingStory]:
    timer = asyncio.timeout(_BREAKING_QUERY_TIMEOUT)
    try:
        async with timer:
            rows = await get_breaking(_now())
    except TimeoutError as exc:
        if timer.expired():
            raise TimeoutError(
                f"The breaking query took over {_BREAKING_QUERY_TIMEOUT} s"
            ) from None
        # One of its own (a connection's), not this limit: said as such.
        raise TimeoutError(
            f"The breaking query timed out before its {_BREAKING_QUERY_TIMEOUT} s limit"
        ) from exc
    stories = [BreakingStory(**s) for s in rows]
    dumped = [s.model_dump(mode="json") for s in stories]
    await set_cached(cache_k, dumped, cycle_ttl(_BREAKING_TTL))
    await set_cached(_BREAKING_LAST_KEY, dumped, _BREAKING_LAST_TTL)
    return stories


def _landed(cache_k: str, task: asyncio.Task) -> None:
    """Forget a finished breaking query, so the next miss runs a new one. One that
    failed is logged in a line: served the last good list, no caller hears of it."""
    if _breaking_in_flight.get(cache_k) is task:
        del _breaking_in_flight[cache_k]
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.warning(
            "Breaking query failed (%s: %s); the next miss retries.", type(exc).__name__, exc
        )


async def _breaking_for_request() -> list[BreakingStory]:
    """_cached_breaking for a request: a query that timed out with no last good list
    to serve is a 503 to retry (retry_shortly), not a 500."""
    try:
        return await _cached_breaking()
    except TimeoutError as timed_out:
        raise retry_shortly(timed_out) from None


async def warm_breaking() -> None:
    """Cache every breaking story, the list each topic's request filters (app.warm, after
    each ingestion cycle): the ticker's and the delta's first request then hit it.

    Joins a query a miss has started, and waits for it: the last good list a
    miss is served never stands in for the refill."""
    if await _breaking_entry(_BREAKING_KEY) is None:
        await asyncio.shield(_breaking_query())


@router.get(
    "/news/breaking", response_model=list[BreakingStory], dependencies=[Depends(edge_cached)]
)
async def get_news_breaking(
    topic: str | None = Query(
        None,
        description="Topic pill: Politics, Conflict, Technology, Climate, Economy, Health or All",
    ),
) -> list[BreakingStory]:
    """Events many outlets have just started covering, most outlets first: at most 8.

    An event is a story and its alike stories (by headline embedding) in one
    1° cell. It is breaking when, in the last 2 hours, at least 7 outlets
    cover it (counting every copy's outlet, so wire copies count) across at
    least 3 distinct stories (so one syndicated feature can't qualify), and
    they are at least as many as covered it in the 22 hours before. Each
    place lists its best breaking event, and an event filed under two
    places is listed once. A topic keeps the events whose stories are
    mostly of it.

    On a cache miss, the last good list, up to an hour old, while the query
    reruns; with none, a query that times out is a 503 with Retry-After.
    """
    tag = _globe_topic_tag(topic)
    stories = await _breaking_for_request()
    if tag is not None:
        stories = [s for s in stories if s.topic == tag]
    return stories[:_MAX_BREAKING]


# How long a delta stays cached.
_DELTA_TTL = 300

# The furthest back a delta reaches: as far as articles are kept.
_MAX_DELTA = timedelta(days=settings.retention_days)

# The visits that share a delta: its start is floored in UTC, coarser the
# older it is. Up to a day back, to the quarter hour; up to 3 days, to the
# hour; beyond, to 6 hours. A week of visits shares about 160 entries rather
# than 672 quarter hours.
_DELTA_FLOORS = (
    (timedelta(hours=24), timedelta(minutes=15)),
    (timedelta(hours=72), timedelta(hours=1)),
    (_MAX_DELTA, timedelta(hours=6)),
)

# A visit this far after now is a fast client clock, and counts as now.
_DELTA_CLOCK_SKEW = timedelta(minutes=15)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _delta_start(since: str, now: datetime) -> datetime:
    """The start a delta counts from: *since* in UTC, between the retention's
    start and *now*, floored as _DELTA_FLOORS says. Invalid, or more than 15
    minutes after *now*, is a 422."""
    start = _parse_iso(since)
    if start is None:
        raise HTTPException(status_code=422, detail="since must be an ISO 8601 time.")
    if start > now + _DELTA_CLOCK_SKEW:
        raise HTTPException(status_code=422, detail="since is in the future.")
    start = min(max(start, now - _MAX_DELTA), now).astimezone(timezone.utc)
    step = next(step for oldest, step in _DELTA_FLOORS if now - start <= oldest)
    return start - (start - _EPOCH) % step


@router.get("/news/delta", response_model=Delta, dependencies=[Depends(edge_cached)])
async def get_news_delta(
    since: str = Query(..., description="The last visit, an ISO 8601 time"),
) -> Delta:
    """What changed since a visit, for the "since your last visit" strip.

    The distinct stories since then, the places (1° cells) they're in, the
    stories breaking now (as /api/news/breaking lists them, every topic), and
    the 5 places with the most new stories, each with its lead. *since* is
    clamped to the last 7 days and floored: to the quarter hour within a day,
    the hour within 3 days, else 6 hours. Up to 15 minutes ahead counts as now.
    """
    start = _delta_start(since, _now())
    # v2: surging became breaking.
    cache_k = f"db:delta:v2:{start:%Y%m%d%H%M}"
    cached = await get_cached(cache_k)
    delta = None if cached is None else cached_model(cache_k, cached, Delta.model_validate)
    if delta is not None:
        return delta

    # A breaking query that times out with no last good list is a 503, as the ticker's.
    changes, stories = await asyncio.gather(get_delta(start), _breaking_for_request())
    delta = Delta(**changes, breaking=len(stories[:_MAX_BREAKING]))
    await set_cached(cache_k, delta.model_dump(mode="json"), _DELTA_TTL)
    return delta


@router.get("/news/density", response_model=list[HourlyDensity])
async def get_article_density(
    offset_days: int = Query(0, ge=0, le=6, description="Day offset (0=today, 1=yesterday, …6)"),
) -> list[HourlyDensity]:
    """Return article counts per hour for the time slider sparkline."""
    cache_k = f"db:density:{offset_days}"
    cached = await get_cached(cache_k)
    if cached:
        density = cached_model(
            cache_k, cached, lambda c: [HourlyDensity.model_validate(d) for d in c]
        )
        if density is not None:
            return density

    data = await get_hourly_density(offset_days=offset_days)
    result = [HourlyDensity(hour=h, count=data.get(h, 0)) for h in range(24)]

    if result:
        await set_cached(cache_k, [d.model_dump() for d in result], settings.db_cache_ttl)
    return result


@router.get("/news/volume", response_model=list[HourlyVolume], dependencies=[Depends(edge_cached)])
async def get_story_volume(
    days: int = Query(7, ge=1, le=7, description="Days back from now (1-7)"),
) -> list[HourlyVolume]:
    """Return stories per UTC hour for the timeline: every hour, zeros included."""
    return await cached_volume(days)


async def cached_volume(days: int) -> list[HourlyVolume]:
    """/api/news/volume's answer: cached, else computed and cached (as cached_globe)."""
    cache_k = f"db:volume:{days}"
    cached = await get_cached(cache_k)
    if cached:
        volume = cached_model(
            cache_k, cached, lambda c: [HourlyVolume.model_validate(v) for v in c]
        )
        if volume is not None:
            return volume

    result = [HourlyVolume(**r) for r in await get_hourly_volume(days)]
    if result:
        await set_cached(
            cache_k, [v.model_dump(mode="json") for v in result], cycle_ttl(settings.db_cache_ttl)
        )
    return result


# The timeline's sparkline: the frontend's CHART_DAYS.
_FIRST_VISIT_VOLUME_DAYS = 7


async def warm_volume() -> None:
    """Cache the timeline the first visit asks for (app.warm, after each ingestion cycle)."""
    await cached_volume(_FIRST_VISIT_VOLUME_DAYS)


@router.get("/topics", response_model=list[TopicCount], dependencies=[Depends(edge_cached)])
async def get_topics() -> list[TopicCount]:
    """Return available topic categories with article counts from the database."""
    cache_k = "db:topics"
    cached = await get_cached(cache_k)
    if cached:
        topics = cached_model(cache_k, cached, lambda c: [TopicCount.model_validate(t) for t in c])
        if topics is not None:
            return topics

    counts = await get_topic_counts()
    result = [TopicCount(topic=t, count=c) for t, c in counts.items()]
    result.sort(key=lambda t: t.count, reverse=True)

    if result:
        await set_cached(cache_k, [t.model_dump() for t in result], settings.db_cache_ttl)

    return result


@router.post("/news/summarize-selection", response_model=SelectionSummaryResponse)
async def summarize_selection(body: SelectionSummaryRequest) -> SelectionSummaryResponse:
    """Generate an AI summary for a user-selected set of article headlines."""
    summary_text = await summarise_selection(
        body.headlines,
        location_name=body.location_name,
    )
    return SelectionSummaryResponse(
        summary=summary_text,
        article_count=len(body.headlines),
    )
