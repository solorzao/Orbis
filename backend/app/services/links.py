"""Co-coverage links: countries the window's stories cover together.

A story links its own country (``articles.country_code``, where it is
placed on the globe) with each other country it mentions
(``articles.mentioned_countries``). A pair's ``n`` is how many stories link
it, whichever side they come from.

A story is an article's ``story_key``, its title without the outlet's name
(``titles.story_key``): a wire story syndicated ten times is ten articles
but one story, and counts once in every number here. Its copies decide
its topic (any copy's), tone (their mean) and origin (their commonest).
Articles written before ingestion stored the key count by their exact
title (``titles.story_key_sql``).

Hubs (the US, Russia) are in most pairs, so links are ranked by lift by
default: ``n_ab * N / (n_a * n_b)``, how many times more often the two are
covered together than if each story's countries were independent. ``N`` is
the window's linking stories, ``n_a`` those touching country a.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Any, Literal

from app.middleware.security import has_injection_pattern, sanitise_text, strip_invisible
from app.services.ai_summary import SummaryUnavailable, _call_claude, _window_key
from app.services.cache import get_cached, set_cached
from app.services.country_centroids import centroid
from app.services.database import get_pool
from app.services.titles import dedup_key, story_key_sql

logger = logging.getLogger(__name__)

# The six topic pills' article tags (Climate is "environment"), in tie order.
TOPIC_TAGS = ("politics", "conflict", "technology", "environment", "economy", "health")

# Lift is noisy on few stories: a pair needs this many to rank by it.
MIN_LIFT_STORIES = 5

# An article's story, in queries that alias articles as a.
_STORY = story_key_sql("a")

# So that the US does not take every slot.
MAX_ARCS_PER_COUNTRY = 6

Rank = Literal["lift", "count"]


def _window(start: datetime, end: datetime, topic: str | None) -> tuple[list[str], list[Any]]:
    """The window and topic predicates on articles, as SQL conditions and their arguments."""
    conditions = ["published_at >= $1", "published_at <= $2"]
    args: list[Any] = [start, end]
    if topic is not None:
        args.append(topic)
        conditions.append(f"topic_tags && ARRAY[${len(args)}::text]")
    return conditions, args


def _linking_cte(conditions: list[str]) -> str:
    """The ``linking`` CTE: the window's articles that mention another country.

    ``others`` is the countries an article mentions besides its own, and
    ``story`` the story it is a copy of. Shared by the links and the detail
    queries, so a pair's n and lift agree in both.
    """
    return f"""linking AS (
            SELECT country_code, topic_tags, sentiment_score, others, story
            FROM (
                SELECT country_code, topic_tags, sentiment_score,
                       array_remove(mentioned_countries, country_code) AS others, {_STORY} AS story
                FROM articles a
                WHERE {" AND ".join(conditions)}
                  AND country_code <> '' AND cardinality(mentioned_countries) > 0
            ) w
            WHERE cardinality(others) > 0
        )"""


def links_query(start: datetime, end: datetime, topic: str | None) -> tuple[Any, ...]:
    """SQL and arguments for every country pair in the window, as ``pool.fetch`` takes them.

    Each row is a pair (``a`` < ``b``) with its stories ``n``, their mean
    ``tone``, most common origin ``from_iso``, stories per topic tag, and
    what lift needs: ``n_a``, ``n_b`` and the window's linking stories,
    ``total``. Every count is of stories, not articles.

    Articles first collapse to one row per pair and story (``stories``),
    which is then grouped by pair and, for ``n_a`` and ``n_b``, by country
    and story (``touched``: the countries a story touches are the ends of
    the pairs it links). That is two grouping passes over the window's pair
    rows, each grouped once (no ``count(DISTINCT ...)`` or ``mode()``, which
    would sort each pair's rows again); the planner picks how. At 7 days on
    the production server ``stories`` runs as a sort (spilled to disk, about
    10 MB) feeding a GroupAggregate, and ``touched``'s HashAggregate spills,
    at the default 4 MB work_mem. A story's tone is ``sum / count``, whose
    state is a number, where ``avg``'s is an array. A pair's origin is
    always one of its two ends, so the most common one is a count against
    half, for a story's copies and then for the pair's stories.
    """
    conditions, args = _window(start, end, topic)
    story_topics = ",\n".join(
        f"bool_or(l.topic_tags && '{{{tag}}}') AS {tag}" for tag in TOPIC_TAGS
    )
    topic_counts = ",\n".join(f"count(*) FILTER (WHERE {tag}) AS {tag}" for tag in TOPIC_TAGS)
    query = f"""
        WITH {_linking_cte(conditions)},
        stories AS (
            SELECT LEAST(l.country_code, m) AS a, GREATEST(l.country_code, m) AS b, l.story,
                   sum(l.sentiment_score) / count(l.sentiment_score) AS tone,
                   2 * count(*) FILTER (WHERE l.country_code < m) >= count(*) AS from_a,
                   {story_topics}
            FROM linking l, unnest(l.others) AS m
            GROUP BY 1, 2, 3
        ),
        touched AS (
            SELECT c, count(*) AS n
            FROM (
                SELECT c, s.story FROM stories s, unnest(ARRAY[s.a, s.b]) AS c
                GROUP BY 1, 2
            ) t
            GROUP BY c
        ),
        grouped AS (
            SELECT a, b, count(*) AS n, avg(tone) AS tone,
                   count(*) FILTER (WHERE from_a) AS from_a,
                   {topic_counts}
            FROM stories
            GROUP BY a, b
        )
        SELECT g.a, g.b, g.n, g.tone,
               CASE WHEN 2 * g.from_a >= g.n THEN g.a ELSE g.b END AS from_iso,
               {", ".join(f"g.{tag}" for tag in TOPIC_TAGS)},
               ta.n AS n_a, tb.n AS n_b,
               (SELECT count(*) FROM (SELECT story FROM stories GROUP BY story) s) AS total
        FROM grouped g
        JOIN touched ta ON ta.c = g.a
        JOIN touched tb ON tb.c = g.b
    """
    return query, *args


async def get_link_pairs(start: datetime, end: datetime, topic: str | None) -> list[dict]:
    """Every country pair the window's stories (of *topic*, if given) link."""
    pool = await get_pool()
    rows = await pool.fetch(*links_query(start, end, topic))
    return [dict(r) for r in rows]


def dominant_topic(row: dict) -> str:
    """The topic tag most of the row's stories carry (ties: TOPIC_TAGS order), or general."""
    best = max(TOPIC_TAGS, key=lambda tag: (row.get(tag) or 0, -TOPIC_TAGS.index(tag)))
    return best if row.get(best) else "general"


def lift(n: int, n_a: int, n_b: int, total: int) -> float:
    """How many times more often a and b are covered together than by chance."""
    return n * total / (n_a * n_b) if n_a and n_b else 0.0


def _country(iso: str) -> dict:
    point = centroid(iso)
    return {"iso": iso, "name": point.name, "lat": point.lat, "lng": point.lng}


def rank_links(rows: list[dict], rank: Rank, limit: int, topic: str | None = None) -> list[dict]:
    """The top *limit* pairs as links, at most MAX_ARCS_PER_COUNTRY per country.

    ``lift`` ranks pairs with MIN_LIFT_STORIES stories or more by lift, then
    stories; ``count`` ranks every pair by stories, then lift. Pairs with a
    country that has no label point are dropped first. *topic* is the
    window's topic filter: every link is then of that topic.
    """
    usable = [r for r in rows if centroid(r["a"]) and centroid(r["b"])]
    if dropped := len(rows) - len(usable):
        logger.debug("Links: dropped %d country pairs without a label point.", dropped)
    scored = [(lift(r["n"], r["n_a"], r["n_b"], r["total"]), r) for r in usable]
    if rank == "lift":
        scored = [(x, r) for x, r in scored if r["n"] >= MIN_LIFT_STORIES]
        scored.sort(key=lambda s: (-s[0], -s[1]["n"], s[1]["a"], s[1]["b"]))
    else:
        scored.sort(key=lambda s: (-s[1]["n"], -s[0], s[1]["a"], s[1]["b"]))

    arcs: Counter[str] = Counter()
    links = []
    for score, row in scored:
        if len(links) == limit:
            break
        if arcs[row["a"]] >= MAX_ARCS_PER_COUNTRY or arcs[row["b"]] >= MAX_ARCS_PER_COUNTRY:
            continue
        arcs.update((row["a"], row["b"]))
        links.append(
            {
                "a": _country(row["a"]),
                "b": _country(row["b"]),
                "n": row["n"],
                "lift": round(score, 2),
                "topic": topic or dominant_topic(row),
                "tone": round(row["tone"] or 0.0, 2),
                "from": row["from_iso"],
            }
        )
    return links


# ---------------------------------------------------------------------------
# One link: its stories, shared names and themes (/api/links/detail)
# ---------------------------------------------------------------------------

# Names in at least this many of the pair's stories count as shared.
MIN_SHARED_STORIES = 2
MAX_SHARED = 8
MAX_THEMES = 5
_MAX_NAME_CHARS = 80

# Fetched before cleaning drops some: names, themes, and stories (syndicated
# copies are dropped down to the 10 shown).
_NAME_FETCH_LIMIT = 16
_THEME_FETCH_LIMIT = 25
ARTICLE_FETCH_LIMIT = 30

# GDELT themes that say nothing about a link, so are not shown: who and what
# a story names in passing (functional actors such as officials, languages,
# ethnicities, religions, military ranks, animals, places); economic-policy-
# uncertainty and US-specific indicators; CrisisLex's crisis-message classes,
# which repeat the core themes (KILL, WOUND) in worse words; and the most
# generic core themes.
DROPPED_THEME_PREFIXES = (
    "TAX_FNCACT_",
    "TAX_WORLDLANGUAGES_",
    "TAX_ETHNICITY_",
    "TAX_RELIGION_",
    "TAX_MILITARY_TITLE_",
    "TAX_WORLDMAMMALS_",
    "TAX_WORLDBIRDS_",
    "TAX_WORLDFISH_",
    "TAX_WORLDREPTILES_",
    "TAX_WORLDARACHNIDS_",
    "TAX_WORLDINSECTS_",
    "SOC_POINTSOFINTEREST_",
    "USPEC_",
    "EPU_",
    "CRISISLEX_",
)
DROPPED_THEMES = frozenset({"GENERAL_GOVERNMENT", "LEADER", "MEDIA_MSM"})

# Families whose prefix goes: World Bank, UN Guiding Principles, social, taxonomy.
_THEME_PREFIXES = ("WB_", "UNGP_", "SOC_", "TAX_")
# The number World Bank themes put before the theme (WB_2432_).
_THEME_CODE = re.compile(r"^\d+_")
_THEME_CHARS = re.compile(r"[A-Za-z0-9_]+")

# The commonest themes, by code without the family prefix, as words.
_THEME_LABELS = {
    "ARMEDCONFLICT": "Armed conflict",
    "ARREST": "Arrests",
    "ELECTION": "Elections",
    "FRAGILITY_CONFLICT_AND_VIOLENCE": "Fragility, conflict and violence",
    "GENERALCRIME": "Crime",
    "GENERAL_HEALTH": "Health",
    "KILL": "Killings",
    "PROTEST": "Protests",
    "TERROR": "Terrorism",
    "WOUND": "Injuries",
}
# Themes shown as one label whatever follows the code's start.
_THEME_GROUPS = (
    ("MANMADE_DISASTER", "Man-made disaster"),
    ("NATURAL_DISASTER", "Natural disaster"),
)
# Families of names (taxonomy themes without the TAX_), shown as
# "Family: Name": "TERROR_GROUP_HAMAS" -> "Terror group: Hamas".
_NAMED_FAMILIES = (
    ("TERROR_GROUP_", "Terror group"),
    ("POLITICAL_PARTY_", "Political party"),
    ("AIDGROUPS_", "Aid group"),
)
# Lower case inside a name ("Save the Children"); acronyms kept in one.
_NAME_SMALL_WORDS = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"}
)
_NAME_ACRONYMS = frozenset({"EU", "UK", "UN", "US"})
# A one-word name this short is an acronym: ISIS, BJP, ANC, PKK.
_MAX_ACRONYM_CHARS = 4
# Families shown as "Family: theme".
_THEME_FAMILIES = (
    ("ECON_", "Economy"),
    ("ENV_", "Environment"),
    ("HEALTH_", "Health"),
    ("WEAPONS_", "Weapons"),
    ("DISEASE_", "Disease"),
)
# Words GDELT runs together.
_THEME_WORDS = {
    "ARMEDCONFLICT": "armed conflict",
    "CLIMATECHANGE": "climate change",
    "EARNINGSREPORT": "earnings report",
    "FOREIGNINVEST": "foreign investment",
    "FREESPEECH": "free speech",
    "FREETRADE": "free trade",
    "FUELPRICES": "fuel prices",
    "MASSMIGRATION": "mass migration",
    "NUCLEARPOWER": "nuclear power",
    "OILPRICE": "oil prices",
    "PRICECONTROL": "price controls",
    "STOCKMARKET": "stock market",
}


def _pair_conditions(
    a: str, b: str, start: datetime, end: datetime, topic: str | None
) -> tuple[list[str], list[Any]]:
    """The window, topic and pair predicates: stories from either country naming the other."""
    conditions, args = _window(start, end, topic)
    args += [a, b]
    pa, pb = f"${len(args) - 1}", f"${len(args)}"
    conditions.append(
        f"((country_code = {pa} AND {pb} = ANY(mentioned_countries)) "
        f"OR (country_code = {pb} AND {pa} = ANY(mentioned_countries)))"
    )
    return conditions, args


def detail_stats_query(
    a: str, b: str, start: datetime, end: datetime, topic: str | None
) -> tuple[Any, ...]:
    """SQL and arguments for the pair's n, tone, topic counts and what lift needs.

    Stories, as the links query counts them: each story is one row, which
    links the pair, or touches a country, if any of its copies does. Its
    tone and topics are those of the copies that link the pair.
    """
    conditions, args = _window(start, end, topic)
    args += [a, b]
    pa, pb = f"${len(args) - 1}", f"${len(args)}"
    story_topics = ",\n".join(
        f"bool_or(linked AND topic_tags && '{{{tag}}}') AS {tag}" for tag in TOPIC_TAGS
    )
    topic_counts = ",\n".join(f"count(*) FILTER (WHERE {tag}) AS {tag}" for tag in TOPIC_TAGS)
    query = f"""
        WITH {_linking_cte(conditions)},
        stories AS (
            SELECT story,
                   bool_or(country_code = {pa} OR {pa} = ANY(others)) AS has_a,
                   bool_or(country_code = {pb} OR {pb} = ANY(others)) AS has_b,
                   bool_or(linked) AS linked,
                   sum(sentiment_score) FILTER (WHERE linked)
                   / count(sentiment_score) FILTER (WHERE linked) AS tone,
                   {story_topics}
            FROM (
                SELECT story, country_code, others, topic_tags, sentiment_score,
                       (country_code = {pa} AND {pb} = ANY(others))
                       OR (country_code = {pb} AND {pa} = ANY(others)) AS linked
                FROM linking
            ) marked
            GROUP BY story
        )
        SELECT count(*) AS total,
               count(*) FILTER (WHERE has_a) AS n_a,
               count(*) FILTER (WHERE has_b) AS n_b,
               count(*) FILTER (WHERE linked) AS n,
               avg(tone) AS tone,
               {topic_counts}
        FROM stories
    """
    return query, *args


def detail_articles_query(
    a: str, b: str, start: datetime, end: datetime, topic: str | None, limit: int
) -> tuple[Any, ...]:
    """SQL and arguments for the pair's newest stories: the columns a NewsArticle reads."""
    conditions, args = _pair_conditions(a, b, start, end, topic)
    args.append(limit)
    query = f"""
        SELECT id, title, summary, source_url, source_name, source_language,
               published_at, ingested_at, latitude, longitude, country_code,
               region, topic_tags, sentiment_score, entities, image_url
        FROM articles
        WHERE {" AND ".join(conditions)}
        ORDER BY published_at DESC, id
        LIMIT ${len(args)}
    """
    return query, *args


def detail_headlines_query(
    a: str, b: str, start: datetime, end: datetime, topic: str | None, limit: int
) -> tuple[Any, ...]:
    """SQL and arguments for the titles of the pair's newest stories."""
    conditions, args = _pair_conditions(a, b, start, end, topic)
    args.append(limit)
    query = f"""
        SELECT title FROM articles
        WHERE {" AND ".join(conditions)}
        ORDER BY published_at DESC, id
        LIMIT ${len(args)}
    """
    return query, *args


def detail_names_query(
    a: str, b: str, start: datetime, end: datetime, topic: str | None, limit: int
) -> tuple[Any, ...]:
    """SQL and arguments for the people and organisations in several of the pair's stories."""
    conditions, args = _pair_conditions(a, b, start, end, topic)
    args.append(limit)
    query = f"""
        WITH linked AS (
            SELECT {_STORY} AS story, persons, orgs FROM articles a
            WHERE {" AND ".join(conditions)}
        )
        SELECT name, type, count(DISTINCT story) AS n
        FROM (
            SELECT story, unnest(persons) AS name, 'person' AS type FROM linked
            UNION ALL
            SELECT story, unnest(orgs) AS name, 'org' AS type FROM linked
        ) mentions
        GROUP BY name, type
        HAVING count(DISTINCT story) >= {MIN_SHARED_STORIES}
        ORDER BY n DESC, name
        LIMIT ${len(args)}
    """
    return query, *args


def detail_themes_query(
    a: str, b: str, start: datetime, end: datetime, topic: str | None, limit: int
) -> tuple[Any, ...]:
    """SQL and arguments for the GDELT themes of the pair's stories, in most stories first.

    Themes display_theme drops are not fetched, so the *limit* goes to ones
    that show.
    """
    conditions, args = _pair_conditions(a, b, start, end, topic)
    args += [list(DROPPED_THEME_PREFIXES), sorted(DROPPED_THEMES)]
    prefixes, dropped = f"${len(args) - 1}", f"${len(args)}"
    args.append(limit)
    query = f"""
        SELECT theme, count(DISTINCT story) AS n
        FROM (
            SELECT {_STORY} AS story, themes FROM articles a
            WHERE {" AND ".join(conditions)}
        ) linked, unnest(themes) AS theme
        WHERE NOT theme ^@ ANY ({prefixes}::text[])
          AND theme <> ALL ({dropped}::text[])
        GROUP BY theme
        ORDER BY n DESC, theme
        LIMIT ${len(args)}
    """
    return query, *args


def _theme_words(code: str) -> str:
    """A theme code's words, lower case: "STOCKMARKET_CRASH" -> "stock market crash"."""
    return " ".join(_THEME_WORDS.get(word, word.lower()) for word in code.split("_") if word)


def _name_words(code: str) -> str:
    """A name's code in title case: "SAVE_THE_CHILDREN" -> "Save the Children".

    A one-word name of up to four letters is an acronym (ISIS, BJP), as are
    EU, UK, UN and US anywhere; small words after the first are lower case.
    """
    words = [word for word in code.split("_") if word]
    if len(words) == 1 and len(words[0]) <= _MAX_ACRONYM_CHARS:
        return words[0]
    shown = []
    for i, word in enumerate(words):
        if word in _NAME_ACRONYMS:
            shown.append(word)
        elif i and word.lower() in _NAME_SMALL_WORDS:
            shown.append(word.lower())
        else:
            shown.append(word.capitalize())
    return " ".join(shown)


def display_theme(theme: str) -> str:
    """A GDELT theme as a label: "ECON_STOCKMARKET" -> "Economy: stock market".

    Themes that say nothing about a link (DROPPED_THEME_PREFIXES,
    DROPPED_THEMES) show as nothing, as does anything but a plain theme
    code. Otherwise the family prefix, a World Bank number and trailing
    digits go; then the theme reads as a known label, a group's or a
    family's, or its own words in sentence case.
    """
    if not isinstance(theme, str) or not _THEME_CHARS.fullmatch(theme):
        return ""
    code = theme.upper()
    if code in DROPPED_THEMES or code.startswith(DROPPED_THEME_PREFIXES):
        return ""
    for prefix in _THEME_PREFIXES:
        if code.startswith(prefix):
            code = code[len(prefix) :]
            break
    code = _THEME_CODE.sub("", code).rstrip("0123456789_")
    if code in _THEME_LABELS:
        return _THEME_LABELS[code]
    for start, label in _THEME_GROUPS:
        if code.startswith(start):
            return label
    for prefix, family in _NAMED_FAMILIES:
        if code.startswith(prefix):
            name = _name_words(code[len(prefix) :])
            return f"{family}: {name}" if name else family
    for prefix, family in _THEME_FAMILIES:
        if code.startswith(prefix):
            words = _theme_words(code[len(prefix) :])
            return f"{family}: {words}" if words else family
    words = _theme_words(code)
    return words[:1].upper() + words[1:]


def top_themes(rows: list[dict]) -> list[str]:
    """The first MAX_THEMES themes as shown, without the ones that read the same."""
    themes: list[str] = []
    seen: set[str] = set()
    for row in rows:
        shown = display_theme(row.get("theme"))
        if shown and shown.casefold() not in seen:
            seen.add(shown.casefold())
            themes.append(shown)
            if len(themes) == MAX_THEMES:
                break
    return themes


def clean_entities(rows: list[dict]) -> list[dict]:
    """The shared names as text to show: GDELT's raw names, cleaned.

    Hidden and control characters go, then whitespace collapses to one line
    of at most 80 characters. A name left empty, one that looks like a
    prompt injection, and a repeat of an earlier name are dropped.
    """
    seen: set[str] = set()
    entities: list[dict] = []
    for row in rows:
        raw = row.get("name")
        if not isinstance(raw, str) or has_injection_pattern(raw):
            continue
        name = " ".join(sanitise_text(strip_invisible(raw), max_length=_MAX_NAME_CHARS).split())
        if not name or has_injection_pattern(name) or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        entities.append({"name": name, "type": row["type"], "n": row["n"]})
        if len(entities) == MAX_SHARED:
            break
    return entities


async def get_link_detail(
    a: str, b: str, start: datetime, end: datetime, topic: str | None
) -> dict:
    """Everything the link inspector shows for the pair a, b in the window.

    ``articles`` are raw rows, newest first (up to ARTICLE_FETCH_LIMIT, with
    syndicated copies still in); the rest is ready to show.
    """
    pool = await get_pool()
    stats, names, themes, articles = await asyncio.gather(
        pool.fetchrow(*detail_stats_query(a, b, start, end, topic)),
        pool.fetch(*detail_names_query(a, b, start, end, topic, _NAME_FETCH_LIMIT)),
        pool.fetch(*detail_themes_query(a, b, start, end, topic, _THEME_FETCH_LIMIT)),
        pool.fetch(*detail_articles_query(a, b, start, end, topic, ARTICLE_FETCH_LIMIT)),
    )
    return {
        "a": _country(a),
        "b": _country(b),
        "n": stats["n"],
        "lift": round(lift(stats["n"], stats["n_a"], stats["n_b"], stats["total"]), 2),
        "topic_mix": {tag: stats[tag] for tag in TOPIC_TAGS},
        "tone": round(stats["tone"] or 0.0, 2),
        "shared": clean_entities([dict(r) for r in names]),
        "themes": top_themes([dict(r) for r in themes]),
        "articles": [dict(r) for r in articles],
    }


# ---------------------------------------------------------------------------
# A link in words (/api/links/explain)
# ---------------------------------------------------------------------------

# Shared by everyone who opens the pair, so cached like cluster summaries.
EXPLAIN_TTL = 3 * 3600
_EXPLAIN_HEADLINES = 15
# Fetched before syndicated copies and injection attempts are dropped.
_HEADLINE_FETCH_LIMIT = 45
# Shown, not cached, when no headline is left to explain the link with.
NOT_ENOUGH_COVERAGE = "Not enough coverage in this window to explain the link."

_EXPLAIN_SYSTEM_PROMPT = (
    "You are a concise news analyst. You will receive two countries and the "
    "headlines of news stories that covered them together. Write a 2-3 sentence "
    "objective, third-person summary of what that coverage is about: the events, "
    "people and themes the stories share. Describe the two countries as covered "
    "together in the news. Never state or imply cause and effect between the "
    "countries or their events: no 'because', 'led to', 'in response to' or "
    "'as a result'. Do not address the reader. Do not reference news sources, "
    "media outlets, or where the information comes from. Output ONLY plain "
    "sentences — no markdown, no headings, no bold, no bullet points, no labels. "
    "Never explain your reasoning."
)


async def get_link_headlines(
    a: str, b: str, start: datetime, end: datetime, topic: str | None, limit: int
) -> list[str]:
    """Titles of the pair's newest stories."""
    pool = await get_pool()
    rows = await pool.fetch(*detail_headlines_query(a, b, start, end, topic, limit))
    return [r["title"] for r in rows]


def _prompt_headlines(titles: list[str]) -> list[str]:
    """Up to 15 headlines fit for a prompt: one clean line each, no injections, no copies."""
    lines: list[str] = []
    seen: set[str] = set()
    for title in titles:
        if not isinstance(title, str):
            continue
        clean = " ".join(sanitise_text(strip_invisible(title), max_length=200).split())
        key = dedup_key(clean)
        # Checked once cleaned: sanitise_text deletes control characters, which
        # would otherwise hide an injection phrase from the check ("Ig\x01nore").
        if not clean or has_injection_pattern(clean) or key in seen:
            continue
        seen.add(key)
        lines.append(clean)
        if len(lines) == _EXPLAIN_HEADLINES:
            break
    return lines


async def explain_link(a: str, b: str, start: datetime, end: datetime, topic: str | None) -> str:
    """2-3 sentences from Claude on what the stories linking a and b are about.

    Every prompt input is derived here: the countries' names come from the
    label-point table and the headlines from the database, so a client
    cannot steer an answer that is cached and shown to everyone. Cached per
    pair (either order), window floored to the hour, and topic, for 3 hours.
    A failure's message, or NOT_ENOUGH_COVERAGE when no usable headline is
    left, is returned but never cached.
    """
    a, b = sorted((a, b))
    topic_suffix = f":{topic}" if topic else ""
    cache_key = f"links:explain:v1:{a}:{b}:{_window_key(start, end)}{topic_suffix}"
    cached = await get_cached(cache_key)
    if cached is not None:
        return str(cached)

    lines = _prompt_headlines(
        await get_link_headlines(a, b, start, end, topic, _HEADLINE_FETCH_LIMIT)
    )
    if not lines:
        return NOT_ENOUGH_COVERAGE
    user_msg = (
        f"Countries: {centroid(a).name} and {centroid(b).name}\n\n"
        "Headlines of stories that covered both:\n" + "\n".join(f"- {line}" for line in lines)
    )
    try:
        text = await _call_claude(user_msg, system=_EXPLAIN_SYSTEM_PROMPT)
    except SummaryUnavailable as exc:
        return str(exc)

    await set_cached(cache_key, text, EXPLAIN_TTL)
    return text
