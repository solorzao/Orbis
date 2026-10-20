"""The investigation board: what its pins are now, how they connect, and an AI memo.

The board itself lives in the visitor's browser; the server only reads. A pin
is an item id, also used in share links:

- ``article:{uuid}``: one article (lowercase, as the API gives ids);
- ``place:{lat}:{lng}``: a 1° cell, by its floor values (the globe's grid);
- ``link:{AA}-{BB}``: two countries covered together, in code order as
  /api/links gives them;
- ``thread:{id}``: a story thread;
- ``entity:{person|org}:{name}``: a person or organisation, its name trimmed
  and single-spaced (as /api/entities normalises one).

Ids are parsed strictly before any SQL: anything else is malformed. Every
read is bounded: primary keys for articles, threads and members, the cell's
geography box for a place, the entity index for names.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from app.middleware.security import strip_invisible
from app.services.country_centroids import centroid
from app.services.database import _cell_box, get_pool
from app.services.entities import STORY_SQL, newest_per_story, resolve_entity, top_places
from app.services.places import display_place
from app.services.titles import display_title

# Pins a board holds, and so the most a request names.
MAX_ITEMS = 20
# An entity name's characters, at most (as /api/entities takes one).
MAX_NAME = 200

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_DEGREE = r"0|-?[1-9][0-9]{0,2}"
_ITEM = re.compile(
    rf"article:(?P<article>{_UUID})"
    rf"|place:(?P<lat>{_DEGREE}):(?P<lng>{_DEGREE})"
    r"|link:(?P<a>[A-Z]{2})-(?P<b>[A-Z]{2})"
    r"|thread:(?P<thread>[1-9][0-9]{0,18})"
    r"|entity:(?P<etype>person|org):(?P<name>.+)",
    re.DOTALL,
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_BIGINT = 2**63 - 1


class BoardItem(NamedTuple):
    """A parsed pin: its id as given, its kind, and its key.

    The key is the article's uuid (text), the cell's (lat, lng) floors, the
    link's (a, b) codes, the thread's id, or the entity's (type, name).
    """

    id: str
    kind: str
    key: Any


def parse_item(raw: str) -> BoardItem:
    """*raw* as a board item, or ValueError when it is not exactly one of the formats."""
    match = _ITEM.fullmatch(raw)
    if match is None:
        raise ValueError("malformed board item id")
    if match["article"]:
        return BoardItem(raw, "article", match["article"])
    if match["lat"] is not None:
        lat, lng = int(match["lat"]), int(match["lng"])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("cell out of range")
        return BoardItem(raw, "place", (lat, lng))
    if match["a"]:
        a, b = match["a"], match["b"]
        if not (a < b and centroid(a) and centroid(b)):
            raise ValueError("a link is two countries with label points, in code order")
        return BoardItem(raw, "link", (a, b))
    if match["thread"]:
        thread_id = int(match["thread"])
        if thread_id > _MAX_BIGINT:
            raise ValueError("thread id out of range")
        return BoardItem(raw, "thread", thread_id)
    name = match["name"]
    canonical = " ".join(strip_invisible(name).split())
    if len(name) > MAX_NAME or name != canonical or _CONTROL.search(name):
        raise ValueError("an entity name is 1-200 characters, trimmed and single-spaced")
    return BoardItem(raw, "entity", (match["etype"], name))


def parse_items(raws: list[str]) -> list[BoardItem]:
    """The items in order, or ValueError naming the first malformed one by its index
    (never its text: it is what a visitor sent), or saying they repeat."""
    items = []
    for index, raw in enumerate(raws):
        try:
            items.append(parse_item(raw))
        except ValueError:
            raise ValueError(f"items[{index}] is not a board item id.") from None
    if len({item.id for item in items}) != len(items):
        raise ValueError("items must be distinct.")
    return items


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

# Article pins by primary key: at most MAX_ITEMS rows.
ARTICLES_SQL = """
    SELECT id, title, source_url, published_at, latitude, longitude, region, country_code
    FROM articles
    WHERE id = ANY($1::uuid[])
"""

# Thread pins by primary key.
THREADS_SQL = """
    SELECT id, title, lead_title, places, last_seen, top_entities
    FROM threads
    WHERE id = ANY($1::bigint[])
"""

# A cell's newest story in a window: what the cell is called now. Every story
# of the cell in the window is read first (MATERIALIZED, through the
# geography box of idx_articles_location), then the newest is taken, so the
# LIMIT can't turn the plan into a backward walk of the time index, which
# would read every article of the window for a quiet cell.
_CELL_CONDITIONS, _ = _cell_box(0, 0, 1, 1)
PLACE_SQL = f"""
    WITH cell AS MATERIALIZED (
        SELECT id, published_at, latitude, longitude, region, country_code
        FROM articles
        WHERE {" AND ".join(_CELL_CONDITIONS)} AND published_at >= $9
    )
    SELECT * FROM cell ORDER BY published_at DESC, id LIMIT 1
"""
# The windows a place is looked up in, in turn: the last few hours first, so a
# busy cell reads only those; a cell quiet that long has few stories this week.
PLACE_WINDOWS = (timedelta(hours=6), timedelta(days=7))

# Members naming an entity this week, read for its top place: at most this
# many per name (a sample of whichever members the index scan meets first, as
# search counts names), so a heavy name costs no more.
ENTITY_SAMPLE = 100
ENTITY_WINDOW = timedelta(days=7)
ENTITY_SAMPLE_SQL = f"""
    SELECT c.name, s.*
    FROM unnest($1::text[]) AS c(name)
    CROSS JOIN LATERAL (
        SELECT article_id, story_key, published_at, latitude, longitude, region, country_code,
               tone, {STORY_SQL} AS story
        FROM thread_members
        WHERE entities @> ARRAY[c.name]::text[] AND published_at >= $2
        LIMIT $3
    ) s
"""

_MAX_URL = 2048
_URL_UNSAFE = re.compile(r"[\x00-\x20\x7f]")


def web_url(url: object) -> str | None:
    """*url* when it is an absolute http(s) link with a host, else None."""
    if not isinstance(url, str) or len(url) > _MAX_URL or _URL_UNSAFE.search(url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc or not parts.hostname:
        return None
    return url


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def snapshot(
    title: str,
    place: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    time: datetime | None = None,
    url: str | None = None,
) -> dict:
    return {"title": title, "place": place, "lat": lat, "lng": lng, "time": time, "url": url}


def _place_name(region: str | None, country_code: str | None) -> str | None:
    """A story's place as the globe names it, else its country's name, else None."""
    name = display_place(region, country_code)
    if name:
        return name
    country = centroid(country_code)
    return country.name if country else None


def link_title(a: str, b: str) -> str:
    return f"{centroid(a).name} and {centroid(b).name}"


async def _articles(pool, items: list[BoardItem]) -> dict[str, Any]:
    ids = [item.key for item in items if item.kind == "article"]
    if not ids:
        return {}
    return {str(row["id"]): row for row in await pool.fetch(ARTICLES_SQL, ids)}


async def _threads(pool, items: list[BoardItem]) -> dict[int, Any]:
    ids = [item.key for item in items if item.kind == "thread"]
    if not ids:
        return {}
    return {row["id"]: row for row in await pool.fetch(THREADS_SQL, ids)}


async def _place(pool, cell: tuple[int, int], now: datetime) -> Any | None:
    """The cell's newest story in the first window that has one, or None."""
    lat, lng = cell
    _, box = _cell_box(lat, lng, lat + 1, lng + 1)
    for window in PLACE_WINDOWS:
        rows = await pool.fetch(PLACE_SQL, *box, now - window)
        if rows:
            return rows[0]
    return None


async def _places(pool, items: list[BoardItem], now: datetime) -> dict[tuple[int, int], Any]:
    return {item.key: await _place(pool, item.key, now) for item in items if item.kind == "place"}


async def _entity_names(items: list[BoardItem], now: datetime) -> dict[tuple[str, str], str]:
    """Each entity pin's stored name (the graph's spelling, as the dossier resolves
    it), for the pins whose name and type the graph knows."""
    names = {}
    for item in items:
        if item.kind == "entity":
            entity_type, name = item.key
            stored = await resolve_entity(entity_type, name, now)
            if stored is not None:
                names[item.key] = stored
    return names


async def _entity_places(pool, names: list[str], now: datetime) -> dict[str, dict]:
    """Each name's 1° cell with the most stories among a sample of its members
    this week (entities.top_places), or nothing for a name with none."""
    if not names:
        return {}
    rows = await pool.fetch(ENTITY_SAMPLE_SQL, names, now - ENTITY_WINDOW, ENTITY_SAMPLE)
    members: dict[str, list[dict]] = {}
    for row in rows:
        members.setdefault(row["name"], []).append(dict(row))
    return {
        name: top_places(newest_per_story(found))[0] for name, found in members.items() if found
    }


async def resolve_items(items: list[BoardItem], now: datetime) -> list[dict | None]:
    """Each item's snapshot from server data, in order: None for an unknown or
    expired one (an article or thread purged, a cell with no story this week, a
    name the graph doesn't know)."""
    pool = await get_pool()
    articles = await _articles(pool, items)
    threads = await _threads(pool, items)
    places = await _places(pool, items, now)
    names = await _entity_names(items, now)
    entity_places = await _entity_places(pool, sorted(set(names.values())), now)

    def one(item: BoardItem) -> dict | None:
        if item.kind == "link":
            return snapshot(link_title(*item.key))
        if item.kind == "entity":
            stored = names.get(item.key)
            return None if stored is None else _entity_snapshot(stored, entity_places.get(stored))
        if item.kind == "article":
            row = articles.get(item.key)
            return None if row is None else _article_snapshot(row)
        if item.kind == "thread":
            row = threads.get(item.key)
            return None if row is None else _thread_snapshot(row)
        row = places.get(item.key)
        return None if row is None else _place_snapshot(item.key, row)

    return [one(item) for item in items]


def _article_snapshot(row: Any) -> dict:
    return snapshot(
        display_title(row["title"] or ""),
        _place_name(row["region"], row["country_code"]),
        row["latitude"],
        row["longitude"],
        row["published_at"],
        web_url(row["source_url"]),
    )


def _thread_snapshot(row: Any) -> dict:
    title = row["title"] or row["lead_title"] or ""
    places = _json(row["places"]) or []
    if not places:
        return snapshot(title, time=row["last_seen"])
    first = places[0]  # the first report's place
    return snapshot(
        title,
        _place_name(first.get("region"), first.get("country_code")),
        first["lat"],
        first["lng"],
        row["last_seen"],
    )


def _place_snapshot(cell: tuple[int, int], row: Any) -> dict | None:
    name = _place_name(row["region"], row["country_code"])
    if name is None:
        return None
    lat, lng = cell
    # The cell's centre, where the globe draws its dot.
    return snapshot(name, name, lat + 0.5, lng + 0.5, row["published_at"])


def _entity_snapshot(name: str, place: dict | None) -> dict:
    if place is None:
        return snapshot(name)
    return snapshot(name, place["place"] or None, place["lat"], place["lng"])
