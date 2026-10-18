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
- **The event of a cell.** For each story s there, its neighbours are the
  cell's stories at least SAME_STORY_SIM alike (cosine, exact; s is its own),
  outlets(s) their copies' distinct outlets and stories(s) their number. The
  cell's event is the s with the most outlets among those with at least
  MIN_OUTLETS outlets and MIN_STORIES stories, the newest on a tie: one wire
  feature run everywhere (one story) is never an event, nor hides the cell's.
- **Breaking.** The coverage is mostly new: the outlets that covered it in
  the 22 hours before (alike to s, in the cell, not among those covering it
  now) are no more than the outlets now (MIN_NEW_SHARE of the total).
- **One event, one place.** When two cells' events are alike (one event filed
  under "Paris" and under "France"), the one more outlets cover is kept.

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
from app.services.titles import story_key_sql

RECENT = timedelta(hours=2)  # what "now" is
PRIOR = timedelta(hours=24)  # how far back "covered before" looks (the 22 hours before RECENT)

MIN_OUTLETS = 7  # distinct outlets on one event, now
MIN_STORIES = 3  # distinct stories (newsrooms' headlines) about it, now
SAME_STORY_SIM = 0.60  # cosine at which two headlines are about one event
MIN_NEW_SHARE = 0.5  # of the event's outlets (now and before), those now

_MAX_HEADLINE_CHARS = 200


def breaking_query(now: datetime) -> tuple[Any, ...]:
    """SQL and arguments for every breaking story as of *now*, as ``pool.fetch`` takes them.

    Embeddings are read only for the candidate cells' recent stories (once,
    materialised: the neighbourhoods compare them pairwise, about the sum of
    n^2 pairs a cell), and for the 22 hours before in the cells with an event.
    Distances are exact (vector <=>); the half-precision HNSW index is for
    nearest-neighbour search, not a cell's all pairs. Each row is one event:
    its cell, outlets, stories, first seen, six topics' neighbours, its own
    story (the headline, place and tags) and its lead (its newest neighbour
    with an https image, else the newest). Thresholds are literals; the
    windows are arguments.
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
                   r.outlets, a.embedding, a.topic_tags, a.image_url
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
             AND 1 - (s.embedding <=> t.embedding) >= {sim}
            LEFT JOIN LATERAL unnest(t.outlets) AS o(outlet) ON true
            GROUP BY s.id, s.lat_cell, s.lng_cell, s.published_at
        ),
        events AS (
            SELECT best.id, best.lat_cell, best.lng_cell, best.outlets, best.stories,
                   best.first_seen, best.outlet_list, best.lead_id, {cols("best")},
                   s.embedding
            FROM (
                SELECT DISTINCT ON (lat_cell, lng_cell)
                       id, lat_cell, lng_cell, published_at, outlets, stories, first_seen,
                       outlet_list, lead_id, {tags}
                FROM neighbourhoods
                WHERE outlets >= {MIN_OUTLETS} AND stories >= {MIN_STORIES}
                ORDER BY lat_cell, lng_cell, outlets DESC, published_at DESC, id
            ) best
            JOIN stories s ON s.id = best.id
        ),
        prior AS (
            SELECT e.id, count(DISTINCT p.source_name) AS prior_outlets
            FROM events e
            JOIN articles p
              ON FLOOR(p.latitude) = e.lat_cell AND FLOOR(p.longitude) = e.lng_cell
            WHERE p.published_at >= $2 AND p.published_at < $1
              AND p.embedding IS NOT NULL AND p.source_name <> ''
              AND NOT (p.source_name = ANY (e.outlet_list))
              AND 1 - (e.embedding <=> p.embedding) >= {sim}
            GROUP BY e.id
        ),
        breaking AS (
            SELECT e.id, e.lat_cell, e.lng_cell, e.outlets, e.stories, e.first_seen,
                   e.lead_id, {cols("e")}, e.embedding
            FROM events e LEFT JOIN prior pr ON pr.id = e.id
            WHERE e.outlets >= {MIN_NEW_SHARE} * (e.outlets + COALESCE(pr.prior_outlets, 0))
        ),
        distinct_events AS (
            SELECT b.id, b.lat_cell, b.lng_cell, b.outlets, b.stories, b.first_seen,
                   b.lead_id, {cols("b")}
            FROM breaking b
            WHERE NOT EXISTS (
                SELECT 1 FROM breaking o
                WHERE (o.outlets, o.first_seen, -o.lat_cell, -o.lng_cell)
                      > (b.outlets, b.first_seen, -b.lat_cell, -b.lng_cell)
                  AND 1 - (o.embedding <=> b.embedding) >= {sim}
            )
        )
        SELECT d.lat_cell + 0.5 AS lat, d.lng_cell + 0.5 AS lng,
               d.outlets, d.stories, d.first_seen, {cols("d")},
               ev.title AS headline, ev.region, ev.country_code, ev.topic_tags AS event_tags,
               lead.title, lead.source_name, lead.published_at, lead.image_url, lead.topic_tags
        FROM distinct_events d
        JOIN articles ev ON ev.id = d.id
        JOIN articles lead ON lead.id = d.lead_id
        ORDER BY d.outlets DESC, d.first_seen DESC, d.lat_cell, d.lng_cell
    """
    return query, now - RECENT, now - PRIOR


async def get_breaking(now: datetime) -> list[dict[str, Any]]:
    """Every breaking story as of *now*, most outlets first: BreakingStory dicts.

    The caller filters by topic and caps the list: an event is an event, so
    candidates are never filtered by topic.
    """
    pool = await get_pool()
    rows = await pool.fetch(*breaking_query(now))
    return [_story(row) for row in rows]


def clean_headline(title: str | None) -> str:
    """A headline as one line to show: no hidden or control characters, at most 200."""
    if not isinstance(title, str):
        return ""
    return " ".join(sanitise_text(strip_invisible(title), max_length=_MAX_HEADLINE_CHARS).split())


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
