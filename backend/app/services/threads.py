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
  and in more than one, is generic and doesn't count). A title is judged as
  it shows (``display_title``: "Police arrest man - BBC News" shows "Police
  arrest man"): shorter than MIN_TITLE_WORDS (MIN_NAMED_TITLE_WORDS when the
  article names a person or org: "Biden drops out"), a news digest or a bare
  section name ("National"), it neither joins nor seeds a thread.
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
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.thread_reads import LISTED_SQL
from app.services.titles import (
    DASH_CHARS,
    LEADING_TAGS_PATTERN,
    OUTLET_MAX_CHARS,
    OUTLET_SEP_PATTERN,
    display_title,
)

logger = logging.getLogger("orbis.threads")

PREFIX_DIMS = 512  # text-embedding-3-small's Matryoshka prefix
ACTIVE_HOURS = 72  # a thread with 2+ stories stays joinable this long after its last story
SINGLETON_HOURS = 24  # a one-story thread stays joinable this long
# Joining and merging, calibrated on production (2026-10-20). For each of the 444
# listed active threads (of 10,021 active), its nearest other active centroid:
#
#   similarity   >= 0.90  0.85-0.90  0.80-0.85  0.75-0.80  0.70-0.75  0.65-0.70  < 0.65
#   threads            0         24         54         50         47         58     211
#
# 0.85-0.90 were all one story split in two (the Alberta referendum, the Houthi
# strike on a Yemen camp, Brent near a 5-month high, Storm Austen, ...); 0.80-0.85
# mostly one story (Paris curfews, Dussehra greetings, the Google Cloud outage, ...).
#
# Recalibrated after the first merges (62 in the first cycle), from each listed
# thread's nearest unmerged neighbour at 0.74-0.86:
#
#   similarity  shared names  verdict
#   0.80-0.86   none          almost all one story: the Alberta referendum 0.855,
#                             Dussehra greetings 0.844, the DeepSeek ban 0.836,
#                             Ebola in Nigeria 0.831, a Colombia mine collapse
#                             0.812, the Google Cloud outage 0.801, ... (short
#                             headlines often name no one, so none shared doesn't
#                             mean two stories)
#               none          the two wrong pairs, both under 0.815: DC police
#                             assault vs National Guard shot (0.806); early voting
#                             record vs Harris County record (0.814, related but a
#                             different scope)
#   0.77-0.80   2 or more     one story or tightly related: the SCO trip 0.774 (5
#                             shared), Saudi FII postponed 0.799 (5), Tarique Rahman
#                             0.791, the Jio IPO 0.790, Tiger Shroff 0.786 (2 each)
#   0.683       2             apart, rightly: the RSS chief's Vijayadashami speech vs
#                             the Election Commission and the Opposition
#
# Hence MERGE_SIM 0.82, over both wrong pairs, and MERGE_SIM_WITH_ENTITY 0.77 with
# MERGE_SHARED_ENTITIES (2) specific names in both; one shared name needs MERGE_SIM.
#
# The risk, from a synthetic stress test (#100): different stories whose threads
# sit 0.82-0.84 apart would merge, and merging duplicates makes centroids purer,
# lifting such neighbours over the bar. At deploy, production had no wrong pair at
# 0.82 or above (16 nearest pairs at 0.80-0.85: the one wrong one was 0.806). A
# guard against threads naming disjoint people was rejected: top names differ
# even within one story (12 of the 13 pairs it would block were true duplicates).
# Watch for wrong merges in the audit log: one "Thread merge:" line per merge.
#
# Centroids of one story sit closer than its articles do. With headlines alike at
# rho, an article's cosine to a k-story centroid is k*rho / sqrt(k*(1 + (k-1)*rho)):
# at rho = 0.7, 0.70 for k = 1 and 0.78 for k = 3, under JOIN_SIM; but two such
# 3-story centroids are 0.88 apart. So a story's early articles can start a
# duplicate thread that only a centroid-level merge (MERGE_SIM) catches. JOIN_SIM
# stays: lowering it would join different stories as well as these.
JOIN_SIM = 0.80  # join on similarity alone
JOIN_SIM_WITH_ENTITY = 0.62  # join when sharing a specific person or org with the thread
MERGE_SIM = 0.82  # merge two active threads on centroid similarity alone
MERGE_SIM_WITH_ENTITY = 0.77  # ... or with MERGE_SHARED_ENTITIES specific names in both
MERGE_SHARED_ENTITIES = 2  # top entities (people, orgs) both threads name, not generic
MERGE_NEIGHBOURS = 3  # nearest active threads checked per candidate
MERGE_ROUNDS = 3  # a pass's rounds: each round's winners look for their nearest again
MAX_MERGES = 200  # a cycle's merges at most
MERGE_AUDIT_LINES = 50  # "Thread merge:" lines a pass logs; then a count of the rest
# A pass starts no new round, and no new merge but its first, after this: the
# first after a deploy may take 10-40 s, a minute under embedding I/O, and the
# step has no other time bound. The rest wait for the catch-up next cycle.
MERGE_TIME_BUDGET_S = 30
# A cycle's moved members at most (each a non-HOT update into five indexes, some
# 16 GIN entries): one merge always goes ahead, and the rest wait for the next.
MAX_MOVED_MEMBERS = 5000
CATCH_UP_LIMIT = 2000  # a process's first merge pass checks this many listed threads
GENERIC_ENTITY_SHARE = 0.01  # in more than this share of active threads: generic, not shared
MIN_TITLE_WORDS = 4  # titles shorter than this, as shown, neither join nor seed a thread,
# but for MIN_NAMED_TITLE_WORDS when the article names a person or org: "Biden drops
# out" is a story and "Police arrest man" isn't (both shown without the outlet's name).
MIN_NAMED_TITLE_WORDS = 3
DECAY = 0.97  # each join multiplies centroid_sum by this before adding
CANDIDATES = 15  # nearest active threads scored per story
# Placement stops starting new articles after this (counted from its start, not
# the cycle's: setup must never starve it), once MIN_PLACED, the oldest, are
# placed; the backlog takes the rest.
TIME_BUDGET_S = 60
MIN_PLACED = 100
# Articles a cycle takes at most (this cycle's and the backlog's, oldest first),
# so its setup scales and a backlog drains over a few cycles. About what
# placement does in TIME_BUDGET_S (999 took 41.9 s on production).
MAX_BATCH = 1200

BACKLOG_HOURS = 6  # also take unassigned embedded articles this recent
BACKLOG_LIMIT = 500
VELOCITY_HOURS = 6  # velocity: distinct stories in this window
MAX_PLACES = 30  # places kept per thread, in first-report order
TOP_ENTITIES = 8
ENTITIES_PER_TYPE = 8  # a member's entities: up to 8 persons, then up to 8 orgs
HNSW_EF_SEARCH = 100  # so dead index entries can't crowd live candidates out

# News digests: one page summarising many stories under a clock-stamped title
# ("AP News Summary at 6:14 a.m. EDT", "AP News in Brief at 12:04 a.m. EDT"). They
# embed alike, so they formed thread 129, "Developing news story with no
# identifiable details" (15 stories, 16 outlets). They neither join nor seed a
# thread. One pattern for Python (re, case-insensitive) and Postgres (~*): plain
# ERE, no \b (a backspace there), no quotes.
DIGEST_PATTERN = (
    r"^\s*(ap news (summary|in brief)|news (summary|in brief|digest|roundup)"
    r"|today in history|(morning|evening|daily|weekly) (briefing|digest|roundup)"
    r"|top (stories|headlines))([^a-z]|$)"
)
_DIGEST = re.compile(DIGEST_PATTERN, re.IGNORECASE)

# A site section's name, all a headline shows once display_title takes the outlet's
# name off ("National - The Hindu" shows "National"): thread 9574, "National", grew
# from three ("National", "Health", "World"). These words only, in any number ("Top
# News Headlines Today"). Plain ERE, as DIGEST_PATTERN. English only: another
# language's section names pass (as its digests do).
_SECTION_WORDS = (
    "latest|top|breaking|local|world|national|international|regional|business|economy"
    "|markets|money|sport|sports|health|opinion|opinions|editorial|live|politics"
    "|entertainment|tech|technology|science|lifestyle|culture|weather|news|home"
    "|updates|update|stories|headlines|video|videos|today|and|&"
)
SECTION_PATTERN = rf"^\s*({_SECTION_WORDS})(\s+({_SECTION_WORDS}))*\s*$"
_SECTION = re.compile(SECTION_PATTERN, re.IGNORECASE)


# Python's \s (str.isspace; all in the BMP), which display_title collapses, spelled
# out as ARE escapes: Postgres' own \s follows the database's locale (U+2028 and
# U+1680 are spaces in some, not in others).
SPACE_CHARS = "".join(c for c in map(chr, range(0x10000)) if c.isspace())
_SPACES_SQL = "[" + "".join(f"\\u{ord(c):04x}" for c in SPACE_CHARS) + "]+"


def shown_title_sql(title: str) -> str:
    """FROM items giving ``st.shown``: ``display_title`` of *title* (a column of an
    earlier FROM item) in SQL, so the backlog judges a title as Python does
    (tests/test_threads_db.py compares them). The same steps but two: html.unescape
    (ingestion's titles are unescaped already, in gdelt._clean_title) and folding
    quotes, which adds or removes no word or separator. So ``st.shown`` keeps curly
    quotes: it is for judging a title, never for showing one.

    The outlet's name goes at the last separator ``finditer`` finds: the last of
    regexp_count's non-overlapping matches, so stacked ones ("Floods - | The Hindu")
    cut where Python cuts. The lateral subqueries are flattened into the scan."""
    dashes = "-" * len(DASH_CHARS)
    sep = OUTLET_SEP_PATTERN
    return f"""
    CROSS JOIN LATERAL (
        SELECT regexp_replace(
                   regexp_replace(translate(normalize({title}, NFKC), '{DASH_CHARS}', '{dashes}'),
                                  '{_SPACES_SQL}', ' ', 'g'),
                   '{LEADING_TAGS_PATTERN}', '', 'i') AS tagless
    ) tt
    CROSS JOIN LATERAL (SELECT regexp_count(tt.tagless, '{sep}') AS seps) ts
    CROSS JOIN LATERAL (
        SELECT btrim(CASE
                   WHEN ts.seps > 0
                        AND length(tt.tagless) + 1
                            - regexp_instr(tt.tagless, '{sep}', 1, ts.seps, 1)
                            < {OUTLET_MAX_CHARS}
                   THEN left(tt.tagless, regexp_instr(tt.tagless, '{sep}', 1, ts.seps) - 1)
                   ELSE tt.tagless
               END) AS shown
    ) st"""


def threadable_sql(shown: str, min_words: str, names: str) -> str:
    """``threadable`` as an SQL condition on a shown title (shown_title_sql's
    ``st.shown``): *min_words* is MIN_TITLE_WORDS, as a parameter, and *names* the
    article's persons and orgs as one text[] (NULL and empty names name no one).
    title_words' rule: \\s+ splits (shown is trimmed, its spaces collapsed)."""
    words = f"array_length(regexp_split_to_array({shown}, '\\s+'), 1)"
    named = f"coalesce(array_to_string({names}, ''), '') <> ''"
    return (
        f"({words} >= {min_words} OR ({words} >= {MIN_NAMED_TITLE_WORDS} AND {named}))"
        f" AND {shown} !~* '{DIGEST_PATTERN}'"
        f" AND {shown} !~* '{SECTION_PATTERN}'"
    )


# Not this cycle's own ids (they come anyway), and the oldest first: what a time
# budget or a big embedding cycle left over goes before it ages out of the window.
# Titles are judged as shown, as threadable() judges them: one Python drops but this
# keeps would come back every cycle and crowd the 500 out.
BACKLOG_SQL = f"""
    SELECT a.id
    FROM articles a
    {shown_title_sql("a.title")}
    WHERE a.published_at >= $1 AND a.embedding IS NOT NULL
      AND NOT (a.id = ANY($4::uuid[]))
      AND NOT EXISTS (SELECT 1 FROM thread_members m WHERE m.article_id = a.id)
      AND {threadable_sql("st.shown", "$2", "a.persons || a.orgs")}
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
    LIMIT $2
"""

GENERIC_SQL = """
    SELECT e
    FROM threads t JOIN thread_centroids c ON c.thread_id = t.id, unnest(t.top_entities) AS e
    GROUP BY e
    HAVING count(*) > GREATEST(1, $1::float8 * (SELECT count(*) FROM thread_centroids))
"""

# Each query vector is parsed from text once, in the materialized CTE: cast
# inside the LATERAL, it was parsed again for every (article, centroid) pair a
# seq scan visits, 2M parses a cycle, and scoring took 4 minutes on production
# (2026-10-19). SCORE_SETTINGS make the HNSW index the plan: a seq scan computes
# every pair, which grows with the active threads (tens of thousands a day).
SCORE_SQL = f"""
    WITH q AS MATERIALIZED (
        SELECT a.ord, a.t::halfvec({PREFIX_DIMS}) AS v
        FROM unnest($1::int[], $2::text[]) AS a(ord, t)
    )
    SELECT q.ord, c.thread_id, c.sim
    FROM q
    CROSS JOIN LATERAL (
        SELECT thread_id, -(centroid <#> q.v) AS sim
        FROM thread_centroids
        ORDER BY centroid <#> q.v
        LIMIT $3
    ) c
"""

# Inside SCORE_SQL's transaction, the only place it runs. ef_search: so dead
# index entries can't crowd live candidates out of the top CANDIDATES.
# enable_seqscan: the planner prefers a seq scan and top-N sort to HNSW for a
# few thousand rows, computing every pair (900 x 1100 took 79 s on a CI runner
# with the old query, 0.5 s with this one). plan_cache_mode: asyncpg prepares
# the query, and a cached generic plan keeps the settings it was planned under
# (a generic plan with LIMIT $3 chose the seq scan at 5000 rows: over 150 s).
SCORE_SETTINGS = (
    f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}",
    "SET LOCAL enable_seqscan = off",
    "SET LOCAL plan_cache_mode = force_custom_plan",
)

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

# The merge pass: each candidate's nearest other active threads, on the HNSW
# index (under SCORE_SETTINGS: centroids are halfvecs already, nothing to parse).
NEIGHBOURS_SQL = """
    SELECT t.thread_id AS id, n.thread_id AS other, n.sim
    FROM thread_centroids t
    CROSS JOIN LATERAL (
        SELECT c.thread_id, -(c.centroid <#> t.centroid) AS sim
        FROM thread_centroids c
        WHERE c.thread_id <> t.thread_id
        ORDER BY c.centroid <#> t.centroid
        LIMIT $2
    ) n
    WHERE t.thread_id = ANY($1::bigint[])
"""

MERGE_INFO_SQL = """
    SELECT id, n_stories, n_articles, top_entities FROM threads WHERE id = ANY($1::bigint[])
"""

# A process's first pass also checks every listed active thread (idx_threads_listed),
# so duplicates from before merges existed are caught once.
CATCH_UP_SQL = f"""
    SELECT t.id
    FROM threads t
    WHERE t.last_seen >= $1 AND {LISTED_SQL}
      AND EXISTS (SELECT 1 FROM thread_centroids c WHERE c.thread_id = t.id)
    ORDER BY t.last_seen DESC
    LIMIT $2
"""

# One merge, loser ($2) into winner ($1), in one transaction: the members move;
# the winner's sum adds the loser's (each a decayed sum of its stories' vectors)
# and it is aggregated again; the loser keeps its row, emptied and pointing at the
# winner (so its id still resolves; reads follow merged_into through later merges,
# so threads merged into the loser before need no update, and nothing looks
# merged_into up, which has no index); its centroid row goes, and the winner's is
# rewritten once.
MERGE_MEMBERS_SQL = "UPDATE thread_members SET thread_id = $1 WHERE thread_id = $2"
MERGE_WINNER_SQL = """
    UPDATE threads w
    SET centroid_sum = w.centroid_sum + l.centroid_sum,
        first_seen = LEAST(w.first_seen, l.first_seen),
        last_seen = GREATEST(w.last_seen, l.last_seen),
        aggregated_at = NULL
    FROM threads l
    WHERE w.id = $1 AND l.id = $2
"""
MERGE_LOSER_SQL = """
    UPDATE threads
    SET merged_into = $1, n_articles = 0, n_stories = 0, n_sources = 0, velocity = 0,
        aggregated_at = $3
    WHERE id = $2
"""
DROP_CENTROID_SQL = "DELETE FROM thread_centroids WHERE thread_id = $1"

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


def is_digest(title: str | None) -> bool:
    """Whether *title* is a news digest's (DIGEST_PATTERN), not one story's."""
    return bool(_DIGEST.match(title or ""))


def is_section_label(title: str | None) -> bool:
    """Whether *title* is only a site section's name (SECTION_PATTERN), not a story."""
    return bool(_SECTION.match(title or ""))


def threadable(
    title: str | None, persons: Sequence[str] | None = (), orgs: Sequence[str] | None = ()
) -> bool:
    """Whether an article may join or seed a thread, judged on the title as shown
    (display_title: "National - The Hindu" shows "National"): MIN_TITLE_WORDS, or
    MIN_NAMED_TITLE_WORDS when it names a person or org, and never a digest or a bare
    section name. The backlog's SQL rule (threadable_sql)."""
    shown = display_title(title or "")
    words = title_words(shown)
    named = any(name for name in (*(persons or ()), *(orgs or ())))
    return (
        (words >= MIN_TITLE_WORDS or (words >= MIN_NAMED_TITLE_WORDS and named))
        and not is_digest(shown)
        and not is_section_label(shown)
    )


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
    deferred: int = 0  # left to the backlog: past MAX_BATCH, or by the time budget
    aggregated: int = 0  # threads the aggregate step recomputed
    merged: int = 0  # threads merged into another
    active: int = 0
    seconds: float = 0.0
    # Each phase's seconds: the backlog and the load; generic entities, scoring,
    # candidates' entities and copies' threads; placement; aggregates, velocity
    # and deactivation.
    load_seconds: float = 0.0
    score_seconds: float = 0.0
    place_seconds: float = 0.0
    finish_seconds: float = 0.0
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


@dataclass
class ThreadInfo:
    """What deciding a merge needs of a thread."""

    n_stories: int
    entities: set[str]
    n_articles: int = 0  # its members, the rows a merge moves


def plan_merges(
    pairs: list[tuple[int, int, float]],
    infos: dict[int, ThreadInfo],
    generic: set[str],
    limit: int | None = None,
) -> list[tuple[int, int]]:
    """The merges to make, in order, as (loser, winner): at most *limit* (MAX_MERGES).

    A pair (a, b, similarity) of active threads merges at MERGE_SIM, or at
    MERGE_SIM_WITH_ENTITY when both name MERGE_SHARED_ENTITIES specific (not
    generic) people or orgs among their top entities. Most similar first; a merged
    group is one thread from then on, with the stories of all its members. The
    smaller merges into the larger (by stories, the older on a tie).
    """
    return [(loser, winner) for loser, winner, _, _ in _planned(pairs, infos, generic, limit)]


def _planned(
    pairs: list[tuple[int, int, float]],
    infos: dict[int, ThreadInfo],
    generic: set[str],
    limit: int | None = None,
) -> list[tuple[int, int, float, int]]:
    """plan_merges' merges, each with the similarity and the number of specific
    shared names of the pair that made it (for the audit log)."""
    limit = MAX_MERGES if limit is None else limit
    parent: dict[int, int] = {}
    size = {thread_id: info.n_stories for thread_id, info in infos.items()}

    def root(thread_id: int) -> int:
        while parent.get(thread_id, thread_id) != thread_id:
            thread_id = parent[thread_id]
        return thread_id

    def shared(a: int, b: int) -> int:
        return len((infos[a].entities - generic) & (infos[b].entities - generic))

    def qualifies(a: int, b: int, sim: float) -> bool:
        if sim >= MERGE_SIM:
            return True
        return sim >= MERGE_SIM_WITH_ENTITY and shared(a, b) >= MERGE_SHARED_ENTITIES

    merges: list[tuple[int, int, float, int]] = []
    for a, b, sim in sorted(pairs, key=lambda p: (-p[2], p[0], p[1])):
        if len(merges) >= limit:
            break
        if a not in infos or b not in infos or not qualifies(a, b, sim):
            continue
        ra, rb = root(a), root(b)
        if ra == rb:
            continue
        winner, loser = sorted((ra, rb), key=lambda t: (-size.get(t, 0), t))
        parent[loser] = winner
        size[winner] = size.get(winner, 0) + size.get(loser, 0)
        merges.append((loser, winner, sim, shared(a, b)))
    return merges


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
        articles = []
        if ids:
            rows = await conn.fetch(LOAD_SQL, ids, MAX_BATCH)
            if len(rows) == MAX_BATCH:  # the newest past the batch wait for the backlog
                stats.deferred += len(ids) - MAX_BATCH
            articles = [
                _Article.from_row(r)
                for r in rows
                if threadable(r["title"], r["persons"], r["orgs"])
            ]
        stats.load_seconds = time.monotonic() - began
        if articles:
            await _assign(conn, articles, stats)
        await _finish(conn, stats, now)
    stats.seconds = time.monotonic() - began
    logger.info(
        "Threads: %d assigned (%d joined, %d started, %d copies) in %.1f s"
        " (load %.1f, score %.1f, place %.1f, finish %.1f s);"
        " %d aggregated, %d merged, %d active.",
        stats.assigned,
        stats.joined,
        stats.started,
        stats.copies,
        stats.seconds,
        stats.load_seconds,
        stats.score_seconds,
        stats.place_seconds,
        stats.finish_seconds,
        stats.aggregated,
        stats.merged,
        stats.active,
    )
    if stats.deferred or stats.failed:
        logger.warning(
            "Threads: %d left to the backlog (the batch or the time budget), %d failed.",
            stats.deferred,
            stats.failed,
        )
    return stats


async def _assign(conn: Any, articles: list[_Article], stats: ThreadStats) -> None:
    began = time.monotonic()
    generic = {r["e"] for r in await conn.fetch(GENERIC_SQL, GENERIC_ENTITY_SHARE)}
    async with conn.transaction():
        for setting in SCORE_SETTINGS:
            await conn.execute(setting)
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
    placing = time.monotonic()
    stats.score_seconds = placing - began

    # Oldest first (LOAD_SQL's order); the budget counts placement only, and the
    # oldest MIN_PLACED are always placed, so the backlog always drains.
    for ord_, article in enumerate(articles):
        if ord_ >= MIN_PLACED and time.monotonic() - placing > TIME_BUDGET_S:
            stats.deferred += len(articles) - ord_
            break
        try:
            await _place(conn, cycle, ord_, article, stats)
        except Exception:
            stats.failed += 1
            logger.warning("Thread assignment failed for article %s.", article.id, exc_info=True)
    stats.place_seconds = time.monotonic() - placing


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


# The order merge steps run in, one transaction per merge.
MERGE_STEPS = (
    MERGE_MEMBERS_SQL,
    MERGE_WINNER_SQL,
    MERGE_LOSER_SQL,
    DROP_CENTROID_SQL,
    JOIN_CENTROID_SQL,
)

# Whether the catch-up is done: this process's first merge pass, and any pass
# after one that stopped short (MAX_MERGES or MAX_MOVED_MEMBERS) or failed.
_caught_up = False


async def _aggregate(conn: Any, thread_ids: list[int], now: datetime) -> list[int]:
    """Recompute *thread_ids*' aggregates (and any left unaggregated), and their lead
    titles; the ids recomputed."""
    updated = [r["id"] for r in await conn.fetch(AGGREGATE_SQL, thread_ids, now)]
    if updated:
        rows = await conn.fetch(LEAD_TITLES_SQL, updated)
        titles = [(r["id"], display_title(r["title"] or "")) for r in rows]
        if titles:
            await conn.executemany(LEAD_TITLE_SQL, titles)
    return updated


async def _merge_pass(conn: Any, stats: ThreadStats, now: datetime) -> set[int]:
    """Merge the threads this cycle touched (and every listed active one until the
    catch-up is done) into their nearest active neighbour where plan_merges says
    so. Pairs are scored before a round's merges, so each round's winners, their
    centroids moved, look for their nearest again in the next (548 joined 448, and
    514 was over the bar only from the merged 448): MERGE_ROUNDS at most. Winners
    are aggregated after each round; the ids aggregated."""
    global _caught_up
    candidates = set(stats.touched)
    if not _caught_up:
        rows = await conn.fetch(CATCH_UP_SQL, now - timedelta(hours=ACTIVE_HOURS), CATCH_UP_LIMIT)
        candidates |= {r["id"] for r in rows}
    budget = _MergeBudget(MAX_MERGES, MAX_MOVED_MEMBERS, began=time.monotonic())
    aggregated: set[int] = set()
    complete = False
    for round_no in range(1, MERGE_ROUNDS + 1):
        if round_no > 1 and budget.out_of_time():
            logger.info(
                "Threads: merge time budget of %d s reached before round %d; the rest wait.",
                MERGE_TIME_BUDGET_S,
                round_no,
            )
            break
        winners: set[int] = set()
        done = await _merge(conn, stats, candidates, winners, budget, now, round_no)
        if winners:
            aggregated |= set(await _aggregate(conn, sorted(winners), now))
        if not done:
            break
        if not winners:
            complete = True
            break
        candidates = winners
    if budget.made > budget.logged:
        logger.info("Thread merge: %d more not listed.", budget.made - budget.logged)
    # Done only after a pass that completed: one that failed, stopped short or ran
    # out of rounds catches up next cycle.
    _caught_up = complete
    return aggregated


@dataclass
class _MergeBudget:
    merges: int  # merges left this pass
    members: int  # moved members left this pass (one merge always goes ahead)
    used: bool = False  # whether a merge has been made
    made: int = 0  # merges made this pass
    logged: int = 0  # of them, "Thread merge:" lines logged (MERGE_AUDIT_LINES)
    began: float = 0.0  # time.monotonic() at the pass's start
    generic: set[str] | None = None  # generic names, read once a pass when needed

    def out_of_time(self) -> bool:
        return time.monotonic() - self.began > MERGE_TIME_BUDGET_S


async def _merge(
    conn: Any,
    stats: ThreadStats,
    candidates: set[int],
    winners: set[int],
    budget: _MergeBudget,
    now: datetime,
    round_no: int = 1,
) -> bool:
    """Merge *candidates* where plan_merges says so, adding the winners to
    *winners*; whether every planned merge was made (none failed or was left for
    lack of budget)."""
    if not candidates:
        return True
    async with conn.transaction():
        for setting in SCORE_SETTINGS:
            await conn.execute(setting)
        rows = await conn.fetch(NEIGHBOURS_SQL, sorted(candidates), MERGE_NEIGHBOURS)
    pairs = [(r["id"], r["other"], r["sim"]) for r in rows if r["sim"] >= MERGE_SIM_WITH_ENTITY]
    if not pairs:
        return True
    ids = sorted({a for a, _, _ in pairs} | {b for _, b, _ in pairs})
    infos = {
        r["id"]: ThreadInfo(r["n_stories"], set(r["top_entities"] or ()), r["n_articles"])
        for r in await conn.fetch(MERGE_INFO_SQL, ids)
    }
    if budget.generic is None:
        budget.generic = {r["e"] for r in await conn.fetch(GENERIC_SQL, GENERIC_ENTITY_SHARE)}
    plan = _planned(pairs, infos, budget.generic, budget.merges)
    members = {thread_id: info.n_articles for thread_id, info in infos.items()}
    complete = len(plan) < budget.merges
    for loser, winner, sim, shared in plan:
        if budget.used and members.get(loser, 0) > budget.members:
            logger.info(
                "Threads: merge budget of %d moved members reached; the rest wait.",
                MAX_MOVED_MEMBERS,
            )
            return False
        if budget.used and budget.out_of_time():  # the first merge always goes ahead
            logger.info(
                "Threads: merge time budget of %d s reached in round %d; the rest wait.",
                MERGE_TIME_BUDGET_S,
                round_no,
            )
            return False
        try:
            async with conn.transaction():
                await conn.execute(MERGE_MEMBERS_SQL, winner, loser)
                await conn.execute(MERGE_WINNER_SQL, winner, loser)
                await conn.execute(MERGE_LOSER_SQL, winner, loser, now)
                await conn.execute(DROP_CENTROID_SQL, loser)
                await conn.execute(JOIN_CENTROID_SQL, winner)
        except Exception:
            logger.warning("Merging thread %s into %s failed.", loser, winner, exc_info=True)
            complete = False  # the catch-up tries again next cycle
            continue
        budget.used = True
        budget.made += 1
        if budget.logged < MERGE_AUDIT_LINES:  # ids only, to audit merges later
            logger.info(
                "Thread merge: %s -> %s sim=%.3f shared=%d round=%d",
                loser,
                winner,
                sim,
                shared,
                round_no,
            )
            budget.logged += 1
        budget.merges -= 1
        budget.members -= members.get(loser, 0)
        members[winner] = members.get(winner, 0) + members.get(loser, 0)
        stats.merged += 1
        winners.add(winner)
    return complete


async def _finish(conn: Any, stats: ThreadStats, now: datetime) -> None:
    """Aggregates, merges, lead titles, velocity and deactivation: every cycle,
    articles or not."""
    began = time.monotonic()
    active_since = now - timedelta(hours=ACTIVE_HOURS)
    # Merges decide on fresh counts and entities, then the winners are aggregated
    # again with their new members.
    updated = set(await _aggregate(conn, sorted(stats.touched), now))
    try:
        updated |= await _merge_pass(conn, stats, now)
    except Exception:  # merges wait for the next cycle; velocity and deactivation don't
        logger.warning("Thread merge pass failed; continuing.", exc_info=True)
    stats.aggregated = len(updated)
    await conn.execute(VELOCITY_SQL, now - timedelta(hours=VELOCITY_HOURS), active_since)
    await conn.execute(DEACTIVATE_SQL, active_since, now - timedelta(hours=SINGLETON_HOURS))
    stats.active = await conn.fetchval(ACTIVE_SQL)
    stats.finish_seconds = time.monotonic() - began


async def purge_threads(db: Any, retention_days: int, now: datetime | None = None) -> None:
    """Delete members published, and threads last seen, before the retention window.

    With no foreign key to articles, this is the only path that removes members;
    a deleted thread takes its centroid row with it. *now* is for tests.
    """
    now = now or datetime.now(timezone.utc)
    async with _connection(db) as conn:
        await conn.execute(PURGE_MEMBERS_SQL, now, retention_days)
        await conn.execute(PURGE_THREADS_SQL, now, retention_days)
