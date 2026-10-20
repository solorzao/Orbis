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
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from app.middleware.security import strip_invisible
from app.services.country_centroids import centroid
from app.services.database import _cell_box, get_pool
from app.services.entities import newest_per_story, resolve_entity, top_places
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
ENTITY_SAMPLE_SQL = """
    SELECT c.name, s.*
    FROM unnest($1::text[]) AS c(name)
    CROSS JOIN LATERAL (
        SELECT article_id, story_key, published_at, latitude, longitude, region, country_code,
               tone
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


# ---------------------------------------------------------------------------
# Edges between pins (/api/board/links)
# ---------------------------------------------------------------------------

# Edge kinds, in the order a pair of pins lists them.
EDGE_KINDS = ("same_thread", "shared_entity", "same_place", "co_covered")
# Shared names an edge's label lists, at most.
LABEL_NAMES = 3

# Article pins' thread and names, by the members' primary key.
MEMBERS_SQL = """
    SELECT article_id, thread_id, entities
    FROM thread_members
    WHERE article_id = ANY($1::uuid[])
"""

# Which pinned threads have a member naming a pinned entity: one probe per
# (name, thread), each stopping at its first match, through the member
# indexes (the thread's members, or the name's through the entity index). A
# LATERAL with LIMIT 1, not EXISTS: the planner may flatten EXISTS into a
# semi-join that hashes a scan of every member.
MENTIONS_SQL = """
    SELECT e.name, t.id AS thread_id
    FROM unnest($1::text[]) AS e(name) CROSS JOIN unnest($2::bigint[]) AS t(id)
    CROSS JOIN LATERAL (
        SELECT 1 FROM thread_members m
        WHERE m.thread_id = t.id AND m.entities @> ARRAY[e.name]::text[]
        LIMIT 1
    ) hit
"""

_TOPICAL = frozenset({"article", "thread"})  # pins with a thread and names
_LOCATED = frozenset({"article", "place"})  # pins in one cell
_COUNTRIED = frozenset({"article", "place", "link"})  # pins with countries


@dataclass(frozen=True)
class Facts:
    """What a pin's edges are made of.

    ``thread``: an article's thread, or a thread pin's own id; ``entities``: an
    article's names (its member row), or a thread's top names; ``cell``: an
    article's or a place's 1° cell; ``countries``: an article's or a place's
    country, or a link's two; ``name``: an entity pin's stored name.
    """

    thread: int | None = None
    entities: tuple[str, ...] = ()
    cell: tuple[int, int] | None = None
    countries: frozenset[str] = frozenset()
    name: str | None = None


def _edge(a: BoardItem, b: BoardItem, kind: str, label: str) -> dict:
    return {"a": a.id, "b": b.id, "kind": kind, "label": label}


def _shared(names: list[str]) -> str:
    return "shared: " + ", ".join(names[:LABEL_NAMES])


def _names_it(entity: Facts, other: BoardItem, facts: Facts, mentions: set) -> bool:
    """Whether an article (its names) or a thread (a member's) names the entity."""
    if entity.name is None:
        return False
    if other.kind == "article":
        return entity.name in facts.entities
    return (entity.name, facts.thread) in mentions


def _pair_edges(
    a: BoardItem,
    b: BoardItem,
    fa: Facts,
    fb: Facts,
    mentions: set[tuple[str, int]],
    listed: set[frozenset[str]] | None,
) -> list[dict]:
    edges = []
    if a.kind in _TOPICAL and b.kind in _TOPICAL:
        if fa.thread is not None and fa.thread == fb.thread:
            edges.append(_edge(a, b, "same_thread", "same thread"))
        theirs = set(fb.entities)
        shared = [name for name in fa.entities if name in theirs]
        if shared:
            edges.append(_edge(a, b, "shared_entity", _shared(shared)))
    elif a.kind == "entity" and b.kind in _TOPICAL and _names_it(fa, b, fb, mentions):
        edges.append(_edge(a, b, "shared_entity", _shared([fa.name])))
    elif b.kind == "entity" and a.kind in _TOPICAL and _names_it(fb, a, fa, mentions):
        edges.append(_edge(a, b, "shared_entity", _shared([fb.name])))
    if a.kind in _LOCATED and b.kind in _LOCATED and fa.cell is not None and fa.cell == fb.cell:
        edges.append(_edge(a, b, "same_place", "same place"))
    if listed is not None and a.kind in _COUNTRIED and b.kind in _COUNTRIED:
        pairs = sorted(
            {
                (min(x, y), max(x, y))
                for x in fa.countries
                for y in fb.countries
                if x != y and frozenset((x, y)) in listed
            }
        )
        if pairs:
            edges.append(_edge(a, b, "co_covered", "covered together: " + link_title(*pairs[0])))
    return edges


def connect(
    items: list[BoardItem],
    facts: dict[str, Facts],
    mentions: set[tuple[str, int]],
    listed: set[frozenset[str]] | None,
) -> list[dict]:
    """The edges between every two pins, each from the earlier pin, by pins then kind.

    - ``same_thread``: two articles in one thread, or an article and its thread;
    - ``shared_entity``: articles and threads sharing names (up to 3 in the
      label, in the earlier pin's order), or an entity pin and an article or
      thread naming it (*mentions*: the (name, thread) pairs a member names);
    - ``same_place``: places and articles in one 1° cell;
    - ``co_covered``: places, articles and links whose countries make a pair
      in *listed* (the 7-day /api/links list); none when *listed* is None.
    """
    edges = []
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            fa, fb = facts.get(a.id, Facts()), facts.get(b.id, Facts())
            edges += _pair_edges(a, b, fa, fb, mentions, listed)
    return edges


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return math.floor(lat), math.floor(lng)


def _countries(code: str | None) -> frozenset[str]:
    return frozenset({code}) if code else frozenset()


async def _members(pool, items: list[BoardItem]) -> dict[str, Any]:
    ids = [item.key for item in items if item.kind == "article"]
    if not ids:
        return {}
    return {str(row["article_id"]): row for row in await pool.fetch(MEMBERS_SQL, ids)}


async def _mentions(pool, names: list[str], threads: list[int]) -> set[tuple[str, int]]:
    if not names or not threads:
        return set()
    rows = await pool.fetch(MENTIONS_SQL, names, threads)
    return {(row["name"], row["thread_id"]) for row in rows}


def _article_facts(article: Any | None, member: Any | None) -> Facts:
    return Facts(
        thread=member["thread_id"] if member else None,
        entities=tuple(member["entities"] or ()) if member else (),
        cell=_cell(article["latitude"], article["longitude"]) if article else None,
        countries=_countries(article["country_code"]) if article else frozenset(),
    )


async def board_edges(
    items: list[BoardItem], listed: set[frozenset[str]] | None, now: datetime
) -> list[dict]:
    """The edges between *items* (see ``connect``), from bounded reads: articles,
    members and threads by primary key, entity names as the dossier resolves
    them, the (name, thread) probes, and, only when *listed* is given, each
    place's newest story for its country."""
    pool = await get_pool()
    articles = await _articles(pool, items)
    members = await _members(pool, items)
    threads = await _threads(pool, items)
    names = await _entity_names(items, now)
    places = await _places(pool, items, now) if listed is not None else {}
    mentions = await _mentions(pool, sorted(set(names.values())), sorted(threads))

    facts: dict[str, Facts] = {}
    for item in items:
        if item.kind == "article":
            facts[item.id] = _article_facts(articles.get(item.key), members.get(item.key))
        elif item.kind == "thread" and item.key in threads:
            top = tuple(threads[item.key]["top_entities"] or ())
            facts[item.id] = Facts(thread=item.key, entities=top)
        elif item.kind == "place":
            place = places.get(item.key)
            countries = _countries(place["country_code"]) if place else frozenset()
            facts[item.id] = Facts(cell=item.key, countries=countries)
        elif item.kind == "link":
            facts[item.id] = Facts(countries=frozenset(item.key))
        elif item.kind == "entity":
            facts[item.id] = Facts(name=names.get(item.key))
    return connect(items, facts, mentions, listed)
