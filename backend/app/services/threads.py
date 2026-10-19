"""Story threads: the same developing story across outlets and places, assigned at ingestion.

Each cycle, every newly embedded article (and a backlog of the last 6 hours'
unassigned ones) joins the best-matching active thread, or starts one:

- **Vectors.** A story is its headline embedding's unit 512-d prefix
  (text-embedding-3-small is Matryoshka-trained). A thread's
  ``centroid_sum`` is the decayed sum of its distinct stories' vectors (one
  per ``story_key``: syndicated copies join but add nothing, so syndication
  can't overweight a story); ``thread_centroids`` holds its unit form under
  an HNSW inner-product index, for active threads only. A centroid row is
  written only when the centroid changes (a thread starts, a story joins, an
  inactive thread comes back): its 1 KB rows fill their pages, so every
  update is a new HNSW entry and a dead one.
- **Joining.** A story joins its best candidate at a cosine of JOIN_SIM, or
  of JOIN_SIM_WITH_ENTITY when it shares a specific person or organisation
  with the thread (one in more than GENERIC_ENTITY_SHARE of active threads,
  and in more than one, is generic and doesn't count). Titles shorter than
  MIN_TITLE_WORDS ("Police arrest man") neither join nor seed a thread.
- **Aggregates** (counts, places, entities, topic, lead) are recomputed once
  at the end from ``thread_members`` only, so ``first_seen`` moves forward
  when the retention purge removes a thread's oldest members; velocity is
  the distinct stories of the last 6 hours; a thread goes inactive (its
  centroid row deleted) after ACTIVE_HOURS without a story, or
  SINGLETON_HOURS for a one-story thread.

Nothing here reads the ``articles`` heap beyond a bounded set of ids by
primary key and the last 6 hours through ``idx_articles_published_at``, and
nothing writes to ``articles``.

``threads`` has fillfactor 80 (migration 013) for HOT updates, but an update
is HOT only when it changes no indexed column. Velocity, lead-title and
synopsis updates are. The aggregate step's are not: it changes
``aggregated_at``, ``n_stories`` and ``n_sources``, the predicates of migration
015's partial indexes. Nor are joins and copies (``last_seen``,
``aggregated_at``).

The thresholds are starting points, calibrated on live data after deploy:
production's embeddings can't be read locally.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.titles import display_title

logger = logging.getLogger("orbis.threads")

PREFIX_DIMS = 512  # text-embedding-3-small's Matryoshka prefix
ACTIVE_HOURS = 72  # a thread with 2+ stories stays joinable this long after its last story
SINGLETON_HOURS = 24  # a one-story thread stays joinable this long
JOIN_SIM = 0.80  # join on similarity alone
JOIN_SIM_WITH_ENTITY = 0.62  # join when sharing a specific person or org with the thread
GENERIC_ENTITY_SHARE = 0.01  # in more than this share of active threads: generic, not shared
MIN_TITLE_WORDS = 4  # shorter titles neither join nor seed a thread
DECAY = 0.97  # each join multiplies centroid_sum by this before adding
CANDIDATES = 15  # nearest active threads scored per story
TIME_BUDGET_S = 60  # stop starting new articles after this; the backlog takes the rest

BACKLOG_HOURS = 6  # also take unassigned embedded articles this recent
BACKLOG_LIMIT = 500
VELOCITY_HOURS = 6  # velocity: distinct stories in this window
MAX_PLACES = 30  # places kept per thread, in first-report order
TOP_ENTITIES = 8
ENTITIES_PER_TYPE = 8  # a member's entities: up to 8 persons, then up to 8 orgs
HNSW_EF_SEARCH = 100  # so dead index entries can't crowd live candidates out

# The same raw word count as Python's title_words: btrim drops spaces, \s+ splits.
_TITLE_WORDS_SQL = r"array_length(regexp_split_to_array(btrim(a.title), '\s+'), 1)"

# Not this cycle's own ids (they come anyway), and the oldest first: what a time
# budget or a big embedding cycle left over goes before it ages out of the window.
BACKLOG_SQL = f"""
    SELECT a.id
    FROM articles a
    WHERE a.published_at >= $1 AND a.embedding IS NOT NULL
      AND NOT (a.id = ANY($4::uuid[]))
      AND NOT EXISTS (SELECT 1 FROM thread_members m WHERE m.article_id = a.id)
      AND {_TITLE_WORDS_SQL} >= $2
    ORDER BY a.published_at
    LIMIT $3
"""

# The unit 512-d prefix; asyncpg has no halfvec codec, so vectors travel as text.
_UNIT_PREFIX_SQL = f"l2_normalize(subvector(a.embedding, 1, {PREFIX_DIMS}))::halfvec({PREFIX_DIMS})"

LOAD_SQL = f"""
    SELECT a.id, {_UNIT_PREFIX_SQL}::text AS v,
           a.persons, a.orgs, a.title, a.story_key, a.source_name, a.published_at,
           a.latitude, a.longitude, COALESCE(a.region, '') AS region,
           COALESCE(a.country_code, '') AS country_code,
           COALESCE(a.topic_tags[1], '') AS topic, a.sentiment_score,
           COALESCE(a.image_url LIKE 'https://%', false) AS has_https_image
    FROM articles a
    WHERE a.id = ANY($1::uuid[]) AND a.embedding IS NOT NULL
    ORDER BY a.published_at, a.id
"""

GENERIC_SQL = """
    SELECT e
    FROM threads t JOIN thread_centroids c ON c.thread_id = t.id, unnest(t.top_entities) AS e
    GROUP BY e
    HAVING count(*) > GREATEST(1, $1::float8 * (SELECT count(*) FROM thread_centroids))
"""

SCORE_SQL = f"""
    SELECT a.ord, c.thread_id, c.sim
    FROM unnest($1::int[], $2::text[]) AS a(ord, t)
    CROSS JOIN LATERAL (
        SELECT thread_id, -(centroid <#> a.t::halfvec({PREFIX_DIMS})) AS sim
        FROM thread_centroids
        ORDER BY centroid <#> a.t::halfvec({PREFIX_DIMS})
        LIMIT $3
    ) c
"""

CANDIDATE_ENTITIES_SQL = "SELECT id, top_entities FROM threads WHERE id = ANY($1::bigint[])"

STORY_THREADS_SQL = """
    SELECT DISTINCT ON (story_key) story_key, thread_id
    FROM thread_members
    WHERE story_key = ANY($1::bigint[])
    ORDER BY story_key, published_at DESC, article_id
"""

# Threads whose centroid changed this cycle (started, or joined), by id: their
# batch scores, if any, are against the centroid before.
RESCORE_SQL = f"""
    SELECT thread_id, -(centroid <#> $1::halfvec({PREFIX_DIMS})) AS sim
    FROM thread_centroids
    WHERE thread_id = ANY($2::bigint[])
"""

MEMBER_SQL = """
    INSERT INTO thread_members (
        article_id, thread_id, story_key, source_name, published_at, latitude, longitude,
        region, country_code, topic, entities, tone, has_https_image, similarity
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
    ON CONFLICT (article_id) DO NOTHING
    RETURNING article_id
"""

SUM_SQL = "SELECT centroid_sum::text FROM threads WHERE id = $1 FOR UPDATE"

# A member added clears aggregated_at, marking the thread for the aggregate step
# even if this cycle fails before it (idx_threads_unaggregated finds it next
# cycle; comparing last_seen with aggregated_at would miss it, since a story's
# published_at is usually older than the last aggregation).
JOIN_THREAD_SQL = """
    UPDATE threads
    SET centroid_sum = $2::vector, last_seen = GREATEST(last_seen, $3), aggregated_at = NULL
    WHERE id = $1
"""

COPY_THREAD_SQL = """
    UPDATE threads SET last_seen = GREATEST(last_seen, $2), aggregated_at = NULL WHERE id = $1
"""

# A centroid row is written only when the centroid changes: its 1 KB PLAIN rows
# fill their pages, so no update is HOT and each leaves a dead HNSW entry. Its
# last_seen and n_stories are informational, set when the row is written;
# deactivation reads threads. A join rewrites the row once; a copy writes it
# only to bring an inactive thread back (DO NOTHING when it is there).
_CENTROID_FROM_THREAD = f"""
    INSERT INTO thread_centroids (thread_id, last_seen, n_stories, centroid)
    SELECT id, last_seen, GREATEST(n_stories, 1),
           l2_normalize(centroid_sum)::halfvec({PREFIX_DIMS})
    FROM threads WHERE id = $1
"""
JOIN_CENTROID_SQL = (
    _CENTROID_FROM_THREAD
    + "    ON CONFLICT (thread_id) DO UPDATE"
    + " SET last_seen = EXCLUDED.last_seen, centroid = EXCLUDED.centroid\n"
)
REACTIVATE_SQL = _CENTROID_FROM_THREAD + "    ON CONFLICT (thread_id) DO NOTHING\n"

NEW_THREAD_SQL = """
    INSERT INTO threads (centroid_sum, first_seen, last_seen, lead_article_id, lead_title)
    VALUES ($1::vector, $2, $2, $3, $4)
    RETURNING id
"""

NEW_CENTROID_SQL = f"""
    INSERT INTO thread_centroids (thread_id, last_seen, n_stories, centroid)
    VALUES ($1, $2, 1, l2_normalize($3::vector)::halfvec({PREFIX_DIMS}))
"""

# Recomputed from thread_members only, for the threads touched this cycle and
# any a join or copy left unaggregated (aggregated_at NULL: a failed cycle's;
# idx_threads_unaggregated). A story is its story_key; a NULL key, its own
# article. first_seen is the oldest member kept, so it moves forward when the
# retention purge removes old members. Not a HOT update: aggregated_at,
# n_stories and n_sources are migration 015's partial-index predicates.
AGGREGATE_SQL = f"""
    WITH targets AS (
        SELECT id FROM threads
        WHERE id = ANY($1::bigint[]) OR aggregated_at IS NULL
    ),
    m AS MATERIALIZED (
        SELECT tm.thread_id, tm.article_id, tm.source_name, tm.published_at, tm.latitude,
               tm.longitude, tm.region, tm.country_code, tm.topic, tm.entities,
               tm.has_https_image,
               COALESCE(tm.story_key::text, 'a:' || tm.article_id::text) AS story
        FROM thread_members tm JOIN targets ON targets.id = tm.thread_id
    ),
    counts AS (
        SELECT thread_id, count(*) AS n_articles, count(DISTINCT story) AS n_stories,
               count(DISTINCT NULLIF(source_name, '')) AS n_sources,
               COALESCE(array_agg(DISTINCT country_code ORDER BY country_code)
                        FILTER (WHERE country_code <> ''), '{{}}') AS countries,
               min(published_at) AS first_seen, max(published_at) AS last_seen
        FROM m GROUP BY thread_id
    ),
    cells AS (
        SELECT thread_id, floor(latitude) AS lat_cell, floor(longitude) AS lng_cell,
               count(DISTINCT story) AS n, min(published_at) AS first_seen
        FROM m GROUP BY 1, 2, 3
    ),
    firsts AS (
        SELECT DISTINCT ON (thread_id, floor(latitude), floor(longitude))
               thread_id, floor(latitude) AS lat_cell, floor(longitude) AS lng_cell,
               latitude, longitude, region, country_code
        FROM m
        ORDER BY thread_id, floor(latitude), floor(longitude), published_at, article_id
    ),
    ranked_cells AS (
        SELECT c.thread_id, c.first_seen, c.n, f.latitude, f.longitude, f.region,
               f.country_code,
               row_number() OVER (PARTITION BY c.thread_id
                                  ORDER BY c.first_seen, c.lat_cell, c.lng_cell) AS rn
        FROM cells c
        JOIN firsts f
          ON f.thread_id = c.thread_id AND f.lat_cell = c.lat_cell AND f.lng_cell = c.lng_cell
    ),
    places AS (
        SELECT thread_id,
               jsonb_agg(jsonb_build_object('lat', latitude, 'lng', longitude,
                                            'region', region, 'country_code', country_code,
                                            'first_seen', first_seen, 'n', n)
                         ORDER BY rn) AS places
        FROM ranked_cells WHERE rn <= {MAX_PLACES}
        GROUP BY thread_id
    ),
    entity_counts AS (
        SELECT thread_id, e, count(DISTINCT story) AS n
        FROM m, unnest(entities) AS e
        GROUP BY 1, 2
    ),
    top_entities AS (
        SELECT thread_id, array_agg(e ORDER BY n DESC, e) AS top_entities
        FROM (
            SELECT thread_id, e, n,
                   row_number() OVER (PARTITION BY thread_id ORDER BY n DESC, e) AS rn
            FROM entity_counts
        ) ranked
        WHERE rn <= {TOP_ENTITIES}
        GROUP BY thread_id
    ),
    topics AS (
        SELECT DISTINCT ON (thread_id) thread_id, topic
        FROM (
            SELECT thread_id, topic, count(DISTINCT story) AS n
            FROM m WHERE topic <> '' GROUP BY 1, 2
        ) counted
        ORDER BY thread_id, n DESC, topic
    ),
    leads AS (
        SELECT DISTINCT ON (thread_id) thread_id, article_id
        FROM m
        ORDER BY thread_id, has_https_image DESC, published_at DESC, article_id
    )
    UPDATE threads t SET
        n_articles = c.n_articles,
        n_stories = c.n_stories,
        n_sources = c.n_sources,
        countries = c.countries,
        first_seen = c.first_seen,
        last_seen = c.last_seen,
        places = COALESCE(p.places, '[]'::jsonb),
        top_entities = COALESCE(e.top_entities, '{{}}'),
        topic = COALESCE(tp.topic, ''),
        lead_article_id = l.article_id,
        aggregated_at = $2
    FROM counts c
    JOIN leads l ON l.thread_id = c.thread_id
    LEFT JOIN places p ON p.thread_id = c.thread_id
    LEFT JOIN top_entities e ON e.thread_id = c.thread_id
    LEFT JOIN topics tp ON tp.thread_id = c.thread_id
    WHERE t.id = c.thread_id
    RETURNING t.id
"""

# The lead's title, from its article by primary key: one read per touched thread.
LEAD_TITLES_SQL = """
    SELECT t.id, a.title
    FROM threads t JOIN articles a ON a.id = t.lead_article_id
    WHERE t.id = ANY($1::bigint[])
"""

# HOT-eligible (lead_title is in no index), and only when the title changes.
LEAD_TITLE_SQL = "UPDATE threads SET lead_title = $2 WHERE id = $1 AND lead_title <> $2"

# Distinct stories in the last 6 hours; only threads whose value changes are
# written, and stale non-zero values (last seen within ACTIVE_HOURS) reset to 0.
# HOT-eligible: velocity is in no index.
VELOCITY_SQL = """
    WITH recent AS (
        SELECT thread_id,
               count(DISTINCT story_key) + count(*) FILTER (WHERE story_key IS NULL) AS velocity
        FROM thread_members
        WHERE published_at >= $1
        GROUP BY thread_id
    ),
    ids AS (
        SELECT thread_id FROM recent
        UNION
        SELECT id FROM threads WHERE last_seen >= $2 AND velocity <> 0
    )
    UPDATE threads t SET velocity = COALESCE(r.velocity, 0)
    FROM ids LEFT JOIN recent r ON r.thread_id = ids.thread_id
    WHERE t.id = ids.thread_id AND t.velocity IS DISTINCT FROM COALESCE(r.velocity, 0)
"""

# Through threads, whose last_seen and n_stories the cycle keeps current.
DEACTIVATE_SQL = """
    DELETE FROM thread_centroids c USING threads t
    WHERE c.thread_id = t.id AND (t.last_seen < $1 OR (t.n_stories <= 1 AND t.last_seen < $2))
"""

ACTIVE_SQL = "SELECT count(*) FROM thread_centroids"

PURGE_MEMBERS_SQL = """
    DELETE FROM thread_members WHERE published_at < $1::timestamptz - make_interval(days => $2)
"""

PURGE_THREADS_SQL = """
    DELETE FROM threads WHERE last_seen < $1::timestamptz - make_interval(days => $2)
"""

_WORDS = re.compile(r"\s+")


def title_words(title: str | None) -> int:
    """A title's raw word count, the backlog's SQL rule exactly: spaces trimmed from the
    ends, then split on whitespace (so a leading tab counts an empty first word, as it
    does in SQL; ``str.split`` would not, and the title would come back every cycle)."""
    return len(_WORDS.split((title or "").strip(" ")))


def story_entities(persons: list[str] | None, orgs: list[str] | None) -> list[str]:
    """A member's entities: up to 8 persons, then up to 8 orgs (per-type caps, so a
    person-heavy article keeps its orgs), each once."""
    picked = list(persons or [])[:ENTITIES_PER_TYPE] + list(orgs or [])[:ENTITIES_PER_TYPE]
    return list(dict.fromkeys(name for name in picked if name))


def choose(
    scores: dict[int, float],
    entities: list[str] | set[str],
    thread_entities: dict[int, set[str]],
    generic: set[str],
) -> tuple[int, float] | None:
    """The best candidate thread a story may join, with its similarity, or None.

    A candidate qualifies at JOIN_SIM, or at JOIN_SIM_WITH_ENTITY when the story and
    the thread share a specific (not generic) person or org. The best is the most
    similar, the lower id on a tie.
    """
    specific = set(entities) - generic
    best: tuple[int, float] | None = None
    for thread_id, sim in scores.items():
        shared = bool(specific & (thread_entities.get(thread_id, set()) - generic))
        if sim >= JOIN_SIM or (shared and sim >= JOIN_SIM_WITH_ENTITY):
            if best is None or (sim, -thread_id) > (best[1], -best[0]):
                best = (thread_id, sim)
    return best


def parse_vector(text: str) -> list[float]:
    """A pgvector text value ('[0.1,0.2]') as floats."""
    return [float(x) for x in text.strip("[]").split(",")]


def format_vector(values: list[float]) -> str:
    return "[" + ",".join("%.8g" % v for v in values) + "]"


def decayed_sum(current: list[float], vector: list[float]) -> list[float]:
    """``current * DECAY + vector``: pgvector has no scalar multiply, so in Python."""
    return [DECAY * c + v for c, v in zip(current, vector)]


@dataclass
class _Article:
    id: Any
    v: str  # the unit 512-d prefix, as pgvector text
    title: str
    story_key: int | None
    entities: list[str]
    source_name: str
    published_at: datetime
    latitude: float
    longitude: float
    region: str
    country_code: str
    topic: str
    tone: float | None
    has_https_image: bool

    @classmethod
    def from_row(cls, row: Any) -> _Article:
        return cls(
            id=row["id"],
            v=row["v"],
            title=row["title"] or "",
            story_key=row["story_key"],
            entities=story_entities(row["persons"], row["orgs"]),
            source_name=row["source_name"] or "",
            published_at=row["published_at"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            region=row["region"] or "",
            country_code=row["country_code"] or "",
            topic=row["topic"] or "",
            tone=row["sentiment_score"],
            has_https_image=bool(row["has_https_image"]),
        )

    def member_args(self, thread_id: int, similarity: float) -> tuple:
        return (
            self.id,
            thread_id,
            self.story_key,
            self.source_name,
            self.published_at,
            self.latitude,
            self.longitude,
            self.region,
            self.country_code,
            self.topic,
            self.entities,
            self.tone,
            self.has_https_image,
            similarity,
        )


@dataclass
class ThreadStats:
    assigned: int = 0
    joined: int = 0
    started: int = 0
    copies: int = 0
    failed: int = 0
    deferred: int = 0  # left to the backlog by the time budget
    active: int = 0
    seconds: float = 0.0
    finish_seconds: float = 0.0  # aggregates, velocity and deactivation
    touched: set[int] = field(default_factory=set)


class _NewThread:
    """A thread started this cycle, before the aggregate step: its entities counted
    per story, so it matches on its top TOP_ENTITIES as an existing thread does on
    its top_entities."""

    def __init__(self) -> None:
        self._stories: dict[str, set[Any]] = defaultdict(set)

    def add(self, article: _Article) -> None:
        story = article.story_key if article.story_key is not None else ("a", article.id)
        for name in article.entities:
            self._stories[name].add(story)

    def top_entities(self) -> set[str]:
        ranked = sorted(self._stories.items(), key=lambda item: (-len(item[1]), item[0]))
        return {name for name, _ in ranked[:TOP_ENTITIES]}


@dataclass
class _Cycle:
    """What one cycle's placements share."""

    candidates: dict[int, dict[int, float]]  # article ordinal -> thread -> batch score
    thread_entities: dict[int, set[str]]  # candidate threads' top_entities
    story_threads: dict[int, int]  # story_key -> its thread
    generic: set[str]
    started: dict[int, _NewThread] = field(default_factory=dict)
    changed: set[int] = field(default_factory=set)  # centroids rewritten this cycle


class _AlreadyAssigned(Exception):
    """The article became a member meanwhile: roll the new thread back."""


@asynccontextmanager
async def _connection(db: Any) -> AsyncIterator[Any]:
    """A connection from a pool, or the connection itself (tests pass one)."""
    if hasattr(db, "acquire"):
        async with db.acquire() as conn:
            yield conn
    else:
        yield db


async def assign_threads(
    db: Any, article_ids: list[Any], now: datetime | None = None
) -> ThreadStats:
    """Assign this cycle's embedded articles, and the last 6 hours' backlog, to threads.

    Then recompute the touched threads' aggregates, update velocities and deactivate
    stale threads. *db* is a pool (or a connection); *now* is for tests.
    """
    now = now or datetime.now(timezone.utc)
    began = time.monotonic()
    stats = ThreadStats()
    async with _connection(db) as conn:
        backlog = await conn.fetch(
            BACKLOG_SQL,
            now - timedelta(hours=BACKLOG_HOURS),
            MIN_TITLE_WORDS,
            BACKLOG_LIMIT,
            list(article_ids),
        )
        ids = list(dict.fromkeys([*article_ids, *(r["id"] for r in backlog)]))
        if ids:
            rows = await conn.fetch(LOAD_SQL, ids)
            articles = [
                _Article.from_row(r) for r in rows if title_words(r["title"]) >= MIN_TITLE_WORDS
            ]
            if articles:
                await _assign(conn, articles, stats, began)
        await _finish(conn, stats, now)
    stats.seconds = time.monotonic() - began
    logger.info(
        "Threads: %d assigned (%d joined, %d started, %d copies) in %.1f s; %d active.",
        stats.assigned,
        stats.joined,
        stats.started,
        stats.copies,
        stats.seconds,
        stats.active,
    )
    if stats.deferred or stats.failed:
        logger.warning(
            "Threads: %d left to the backlog by the time budget, %d failed.",
            stats.deferred,
            stats.failed,
        )
    return stats


async def _assign(conn: Any, articles: list[_Article], stats: ThreadStats, began: float) -> None:
    generic = {r["e"] for r in await conn.fetch(GENERIC_SQL, GENERIC_ENTITY_SHARE)}
    async with conn.transaction():
        await conn.execute(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}")
        scored = await conn.fetch(
            SCORE_SQL, list(range(len(articles))), [a.v for a in articles], CANDIDATES
        )
    candidates: dict[int, dict[int, float]] = defaultdict(dict)
    for r in scored:
        candidates[r["ord"]][r["thread_id"]] = r["sim"]
    thread_ids = sorted({t for scores in candidates.values() for t in scores})
    thread_entities: dict[int, set[str]] = {}
    if thread_ids:
        for r in await conn.fetch(CANDIDATE_ENTITIES_SQL, thread_ids):
            thread_entities[r["id"]] = set(r["top_entities"] or ())
    keys = sorted({a.story_key for a in articles if a.story_key is not None})
    story_threads: dict[int, int] = {}
    if keys:
        for r in await conn.fetch(STORY_THREADS_SQL, keys):
            story_threads[r["story_key"]] = r["thread_id"]
    cycle = _Cycle(candidates, thread_entities, story_threads, generic)

    for ord_, article in enumerate(articles):
        if time.monotonic() - began > TIME_BUDGET_S:
            stats.deferred = len(articles) - ord_
            break
        try:
            await _place(conn, cycle, ord_, article, stats)
        except Exception:
            stats.failed += 1
            logger.warning("Thread assignment failed for article %s.", article.id, exc_info=True)


async def _place(
    conn: Any, cycle: _Cycle, ord_: int, article: _Article, stats: ThreadStats
) -> None:
    """Join a copy's thread, else the best candidate, else start a thread."""
    copy_of = cycle.story_threads.get(article.story_key) if article.story_key is not None else None
    if copy_of is not None:
        if await _join(conn, article, copy_of, 1.0, copy=True):
            stats.copies += 1
            if copy_of in cycle.started:
                cycle.started[copy_of].add(article)
            _assigned(stats, cycle, article, copy_of)
        return

    scores = dict(cycle.candidates.get(ord_, {}))
    rescore = sorted(set(cycle.started) | (scores.keys() & cycle.changed))
    if rescore:
        for r in await conn.fetch(RESCORE_SQL, article.v, rescore):
            scores[r["thread_id"]] = r["sim"]
    entities = {
        t: (
            cycle.started[t].top_entities()
            if t in cycle.started
            else cycle.thread_entities.get(t, set())
        )
        for t in scores
    }
    choice = choose(scores, article.entities, entities, cycle.generic)
    if choice is not None:
        thread_id, sim = choice
        if await _join(conn, article, thread_id, sim, copy=False):
            stats.joined += 1
            cycle.changed.add(thread_id)
            if thread_id in cycle.started:
                cycle.started[thread_id].add(article)
            _assigned(stats, cycle, article, thread_id)
        return

    thread_id = await _start(conn, article)
    if thread_id is not None:
        stats.started += 1
        cycle.started[thread_id] = _NewThread()
        cycle.started[thread_id].add(article)
        _assigned(stats, cycle, article, thread_id)


def _assigned(stats: ThreadStats, cycle: _Cycle, article: _Article, thread_id: int) -> None:
    stats.assigned += 1
    stats.touched.add(thread_id)
    if article.story_key is not None:
        cycle.story_threads[article.story_key] = thread_id


async def _join(conn: Any, article: _Article, thread_id: int, sim: float, *, copy: bool) -> bool:
    """Make *article* a member of *thread_id*; False when it already was one."""
    async with conn.transaction():
        if await conn.fetchval(MEMBER_SQL, *article.member_args(thread_id, sim)) is None:
            return False
        if copy:  # a story counts once in the centroid: its row is left alone
            await conn.execute(COPY_THREAD_SQL, thread_id, article.published_at)
            await conn.execute(REACTIVATE_SQL, thread_id)  # only if the thread is inactive
        else:
            current = parse_vector(await conn.fetchval(SUM_SQL, thread_id))
            new_sum = decayed_sum(current, parse_vector(article.v))
            await conn.execute(
                JOIN_THREAD_SQL, thread_id, format_vector(new_sum), article.published_at
            )
            await conn.execute(JOIN_CENTROID_SQL, thread_id)
    return True


async def _start(conn: Any, article: _Article) -> int | None:
    """Start a thread seeded by *article*; None when it was already a member."""
    try:
        async with conn.transaction():
            thread_id = await conn.fetchval(
                NEW_THREAD_SQL,
                article.v,
                article.published_at,
                article.id,
                display_title(article.title),
            )
            await conn.execute(NEW_CENTROID_SQL, thread_id, article.published_at, article.v)
            if await conn.fetchval(MEMBER_SQL, *article.member_args(thread_id, 1.0)) is None:
                raise _AlreadyAssigned
    except _AlreadyAssigned:
        return None
    return thread_id


async def _finish(conn: Any, stats: ThreadStats, now: datetime) -> None:
    """Aggregates, lead titles, velocity and deactivation: every cycle, articles or not."""
    began = time.monotonic()
    active_since = now - timedelta(hours=ACTIVE_HOURS)
    updated = [r["id"] for r in await conn.fetch(AGGREGATE_SQL, sorted(stats.touched), now)]
    if updated:
        rows = await conn.fetch(LEAD_TITLES_SQL, updated)
        titles = [(r["id"], display_title(r["title"] or "")) for r in rows]
        if titles:
            await conn.executemany(LEAD_TITLE_SQL, titles)
    await conn.execute(VELOCITY_SQL, now - timedelta(hours=VELOCITY_HOURS), active_since)
    await conn.execute(DEACTIVATE_SQL, active_since, now - timedelta(hours=SINGLETON_HOURS))
    stats.active = await conn.fetchval(ACTIVE_SQL)
    stats.finish_seconds = time.monotonic() - began
    logger.info(
        "Threads: aggregates, velocity and deactivation in %.1f s (%d threads aggregated).",
        stats.finish_seconds,
        len(updated),
    )


async def purge_threads(db: Any, retention_days: int, now: datetime | None = None) -> None:
    """Delete members published, and threads last seen, before the retention window.

    With no foreign key to articles, this is the only path that removes members;
    a deleted thread takes its centroid row with it. *now* is for tests.
    """
    now = now or datetime.now(timezone.utc)
    async with _connection(db) as conn:
        await conn.execute(PURGE_MEMBERS_SQL, now, retention_days)
        await conn.execute(PURGE_THREADS_SQL, now, retention_days)
