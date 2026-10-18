"""Breaking stories: an event many outlets have just started covering, in one place.

Place surges counted a place's coverage; live, that flagged a hub's busy
afternoon (59 outlets at the White House, on everything) and one local
outlet's crawl batch, and missed the real events at busy places (the Paris
unrest: 23 outlets on one event, under a baseline of 19 outlets a block).
What told them apart was how many outlets were on one event. So:

- **Recent stories.** The last 2 hours' articles, one row per story
  (titles.story_key_sql), placed and compared by its newest embedded copy
  (a story none of whose copies is embedded yet is skipped), with the
  outlets (source_name) of every copy: twenty outlets running one AP
  headline word for word are twenty outlets. Embeddings are of the
  headline, so "alike" means headlines about one thing.
- **Candidate cells.** 1° cells (the globe's dots) with at least MIN_OUTLETS
  distinct outlets.
- **Events in a cell.** For each story s there, its neighbours are the cell's
  stories at least SAME_STORY_SIM alike (cosine, exact; s is its own),
  outlets(s) their copies' distinct outlets and stories(s) their number. A
  neighbourhood with at least MIN_OUTLETS outlets and MIN_STORIES stories is
  an event, unless a better one in the cell is alike to it (better: more
  outlets, then newer). One wire feature run everywhere (one story) is never
  an event.
- **Breaking.** Of a cell's three best events, the best whose coverage is
  mostly new: the outlets that covered it in the 22 hours before (alike to
  s, in the cell, not among those covering it now) are no more than the
  outlets now (MIN_NEW_SHARE of the total). So a hub's ongoing story (Kyiv,
  Gaza) doesn't hide a new event there.
- **One event, one place.** When two cells' events are alike (one event filed
  under "Paris" and under "France"), they are kept greedily in rank order:
  the one more outlets cover stays, and one alike only to an event already
  dropped stays too.

SAME_STORY_SIM is a starting point to tune against live output: what cosine
two headlines about one event have in text-embedding-3-small can't be
measured without the embeddings.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.middleware.security import sanitise_text, strip_invisible
from app.services.database import GLOBE_TOPIC_TAGS, dominant_topic, get_pool, globe_lead
from app.services.places import display_place
from app.services.titles import display_title, story_key_sql

RECENT = timedelta(hours=2)  # what "now" is
PRIOR = timedelta(hours=24)  # how far back "covered before" looks (the 22 hours before RECENT)

MIN_OUTLETS = 7  # distinct outlets on one event, now
MIN_STORIES = 3  # distinct stories (newsrooms' headlines) about it, now
SAME_STORY_SIM = 0.60  # cosine at which two headlines are about one event
MIN_NEW_SHARE = 0.5  # of the event's outlets (now and before), those now
EVENTS_PER_CELL = 3  # a cell's best distinct events given the prior check

_MAX_HEADLINE_CHARS = 200


def breaking_query(now: datetime) -> tuple[Any, ...]:
    """SQL and arguments for every place's breaking story as of *now*, as ``pool.fetch``
    takes them, ranked: most outlets, then the newest first seen, then cell.

    Vectors are read once each, normalised, into materialised CTEs: the
    candidate cells' recent stories (the neighbourhoods compare them
    pairwise, about the sum of n^2 pairs a cell) and the 22 hours before in
    the cells with an event. A 1536-d vector is stored out of line, so
    comparing the table's column would fetch it again for every pair. For
    unit vectors the cosine is the inner product (-(a <#> b)), exact; the
    half-precision HNSW index is for nearest-neighbour search, not a cell's
    pairs. Each row is one place's event: its cell, outlets, stories, first
    seen, six topics' neighbours, the other places' events alike to it
    (``alike``, for get_breaking's dedup), its own story (the headline, place
    and tags) and its lead (its newest neighbour with an https image, else
    the newest). Thresholds are literals; the windows are arguments.
    """
    sim = SAME_STORY_SIM
    topic_counts = ",\n".join(
        f"                   count(DISTINCT t.story) FILTER (WHERE t.topic_tags && '{{{t}}}')"
        f" AS {t}"
        for t in GLOBE_TOPIC_TAGS
    )
    tags = ", ".join(GLOBE_TOPIC_TAGS)

    def cols(alias: str) -> str:
        return ", ".join(f"{alias}.{t}" for t in GLOBE_TOPIC_TAGS)

    query = f"""
        WITH copies AS MATERIALIZED (
            SELECT a.id, {story_key_sql("a")} AS story,
                   FLOOR(a.latitude) AS lat_cell, FLOOR(a.longitude) AS lng_cell,
                   NULLIF(a.source_name, '') AS outlet, a.published_at,
                   a.embedding IS NOT NULL AS embedded
            FROM articles a
            WHERE a.published_at >= $1
        ),
        recent AS (
            SELECT r.id, r.story, r.lat_cell, r.lng_cell, r.published_at,
                   COALESCE(o.outlets, '{{}}') AS outlets, o.first_at
            FROM (
                SELECT DISTINCT ON (story) id, story, lat_cell, lng_cell, published_at
                FROM copies WHERE embedded ORDER BY story, published_at DESC, id
            ) r
            JOIN (
                SELECT story, array_agg(DISTINCT outlet) FILTER (WHERE outlet IS NOT NULL)
                       AS outlets, min(published_at) AS first_at
                FROM copies GROUP BY story
            ) o ON o.story = r.story
        ),
        candidates AS (
            SELECT r.lat_cell, r.lng_cell
            FROM recent r, unnest(r.outlets) AS o(outlet)
            GROUP BY 1, 2 HAVING count(DISTINCT o.outlet) >= {MIN_OUTLETS}
        ),
        stories AS MATERIALIZED (
            SELECT r.id, r.story, r.lat_cell, r.lng_cell, r.published_at, r.first_at,
                   r.outlets, l2_normalize(a.embedding) AS embedding, a.topic_tags, a.image_url
            FROM recent r
            JOIN candidates c ON c.lat_cell = r.lat_cell AND c.lng_cell = r.lng_cell
            JOIN articles a ON a.id = r.id
        ),
        neighbourhoods AS (
            SELECT s.id, s.lat_cell, s.lng_cell, s.published_at,
                   count(DISTINCT o.outlet) AS outlets,
                   count(DISTINCT t.story) AS stories,
                   min(t.first_at) AS first_seen,
                   array_agg(DISTINCT o.outlet) FILTER (WHERE o.outlet IS NOT NULL) AS outlet_list,
                   (array_agg(t.id ORDER BY (t.image_url LIKE 'https://%') DESC NULLS LAST,
                              t.published_at DESC, t.id))[1] AS lead_id,
{topic_counts}
            FROM stories s JOIN stories t
              ON t.lat_cell = s.lat_cell AND t.lng_cell = s.lng_cell
             AND -(s.embedding <#> t.embedding) >= {sim}
            LEFT JOIN LATERAL unnest(t.outlets) AS o(outlet) ON true
            GROUP BY s.id, s.lat_cell, s.lng_cell, s.published_at
        ),
        qualifying AS MATERIALIZED (
            SELECT n.id, n.lat_cell, n.lng_cell, n.published_at, n.outlets, n.stories,
                   n.first_seen, n.outlet_list, n.lead_id, {cols("n")}, s.embedding
            FROM neighbourhoods n JOIN stories s ON s.id = n.id
            WHERE n.outlets >= {MIN_OUTLETS} AND n.stories >= {MIN_STORIES}
        ),
        events AS (
            SELECT id, lat_cell, lng_cell, outlets, stories, first_seen, outlet_list, lead_id,
                   {tags}, embedding, place_rank
            FROM (
                SELECT q.id, q.lat_cell, q.lng_cell, q.outlets, q.stories, q.first_seen,
                       q.outlet_list, q.lead_id, {cols("q")}, q.embedding,
                       row_number() OVER (PARTITION BY q.lat_cell, q.lng_cell
                                          ORDER BY q.outlets DESC, q.published_at DESC, q.id)
                           AS place_rank
                FROM qualifying q
                WHERE NOT EXISTS (
                    SELECT 1 FROM qualifying b
                    WHERE b.lat_cell = q.lat_cell AND b.lng_cell = q.lng_cell
                      AND (b.outlets, b.published_at, q.id) > (q.outlets, q.published_at, b.id)
                      AND -(b.embedding <#> q.embedding) >= {sim}
                )
            ) distinct_in_cell
            WHERE place_rank <= {EVENTS_PER_CELL}
        ),
        prior_rows AS MATERIALIZED (
            SELECT FLOOR(p.latitude) AS lat_cell, FLOOR(p.longitude) AS lng_cell,
                   p.source_name, l2_normalize(p.embedding) AS embedding
            FROM articles p
            WHERE p.published_at >= $2 AND p.published_at < $1
              AND p.embedding IS NOT NULL AND p.source_name <> ''
              AND (FLOOR(p.latitude), FLOOR(p.longitude)) IN (SELECT lat_cell, lng_cell FROM events)
        ),
        prior AS (
            SELECT e.id, count(DISTINCT p.source_name) AS prior_outlets
            FROM events e
            JOIN prior_rows p ON p.lat_cell = e.lat_cell AND p.lng_cell = e.lng_cell
            WHERE NOT (p.source_name = ANY (e.outlet_list))
              AND -(e.embedding <#> p.embedding) >= {sim}
            GROUP BY e.id
        ),
        cell_breaking AS (
            SELECT DISTINCT ON (e.lat_cell, e.lng_cell)
                   e.id, e.lat_cell, e.lng_cell, e.outlets, e.stories, e.first_seen,
                   e.lead_id, {cols("e")}, e.embedding
            FROM events e LEFT JOIN prior pr ON pr.id = e.id
            WHERE e.outlets >= {MIN_NEW_SHARE} * (e.outlets + COALESCE(pr.prior_outlets, 0))
            ORDER BY e.lat_cell, e.lng_cell, e.place_rank
        ),
        alike AS (
            SELECT d.id,
                   ARRAY(
                       SELECT o.id FROM cell_breaking o
                       WHERE o.id <> d.id AND -(o.embedding <#> d.embedding) >= {sim}
                   ) AS alike
            FROM cell_breaking d
        )
        SELECT d.id, al.alike, d.lat_cell + 0.5 AS lat, d.lng_cell + 0.5 AS lng,
               d.outlets, d.stories, d.first_seen, {cols("d")},
               ev.title AS headline, ev.region, ev.country_code, ev.topic_tags AS event_tags,
               lead.title, lead.source_name, lead.published_at, lead.image_url, lead.topic_tags
        FROM cell_breaking d
        JOIN alike al ON al.id = d.id
        JOIN articles ev ON ev.id = d.id
        JOIN articles lead ON lead.id = d.lead_id
        ORDER BY d.outlets DESC, d.first_seen DESC, d.lat_cell, d.lng_cell
    """
    return query, now - RECENT, now - PRIOR


async def get_breaking(now: datetime) -> list[dict[str, Any]]:
    """Every breaking story as of *now*, most outlets first: BreakingStory dicts.

    One event filed under several places is kept once, greedily in rank
    order: a place's event stays unless one already kept is alike to it. The
    caller filters by topic and caps the list: an event is an event, so
    candidates are never filtered by topic.
    """
    pool = await get_pool()
    rows = await pool.fetch(*breaking_query(now))
    kept: list[Any] = []
    kept_ids: set[Any] = set()
    for row in rows:  # in rank order
        if kept_ids.isdisjoint(row["alike"] or ()):
            kept.append(row)
            kept_ids.add(row["id"])
    return [_story(row) for row in kept]


def clean_headline(title: str | None) -> str:
    """A headline to show: titles.display_title (typography folded, no tag in front or
    outlet's name behind, its case kept) as one line of at most 200 characters, with no
    hidden or control characters."""
    if not isinstance(title, str):
        return ""
    text = sanitise_text(strip_invisible(display_title(title)), max_length=_MAX_HEADLINE_CHARS)
    return " ".join(text.split())


def _story(row: Any) -> dict[str, Any]:
    mix = {t: row[t] for t in GLOBE_TOPIC_TAGS if row[t]}
    return {
        "headline": clean_headline(row["headline"]),
        "place": display_place(row["region"], row["country_code"]),
        "lat": row["lat"],
        "lng": row["lng"],
        "outlets": row["outlets"],
        "stories": row["stories"],
        "first_seen": row["first_seen"],
        "topic": dominant_topic(mix, row["event_tags"] or []),
        "lead": globe_lead(row),
    }
