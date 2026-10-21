"""Relations between countries from GDELT's reported events (Phase 5, PR 19c).

Reads only event_pairs_daily: the rollups ingestion keeps (app/services/events.py).
Relations are a 7-day lens: always the last 7 UTC days, whatever the timeline
shows. Events are machine-coded from news reports; nothing here calls them facts.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from app.services.country_centroids import centroid
from app.services.database import get_pool
from app.services.links import MAX_ARCS_PER_COUNTRY, _country
from app.services.titles import display_title
from app.services.urls import outlet, web_url

# A pair needs this much behind it to be drawn: one article can yield many
# events, and outlets (a distinct union across the pair's rows) beat them.
# Starting values (Phase 5 decision 8), recalibrated from production's spread
# by "Measure on prod" (19b+). The detail applies neither.
MIN_EVENTS = 5
MIN_OUTLETS = 2
MAX_SAMPLES = 10
LENS_DAYS = 7  # the lens: today and the 6 UTC days before

QUADS = {"all": [1, 2, 3, 4], "cooperation": [1, 2], "conflict": [3, 4]}
QUAD_NAMES = {
    1: "verbal_cooperation",
    2: "material_cooperation",
    3: "verbal_conflict",
    4: "material_conflict",
}

LIST_SQL = """
WITH r AS MATERIALIZED (
    SELECT least(a_iso, b_iso) AS a, greatest(a_iso, b_iso) AS b, a_iso, quad_class,
           n_events, mentions, goldstein_sum, tone_sum, outlets
    FROM event_pairs_daily
    WHERE day BETWEEN $1 AND $2 AND quad_class = ANY($3::smallint[])
),
p AS (
    SELECT a, b,
           sum(n_events)::int AS n,
           sum(mentions)::bigint AS mentions,
           sum(goldstein_sum) / sum(n_events) AS goldstein,
           sum(tone_sum) / sum(n_events) AS tone,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 1), 0)::int AS q1,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 2), 0)::int AS q2,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 3), 0)::int AS q3,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 4), 0)::int AS q4,
           coalesce(sum(n_events) FILTER (WHERE a_iso = a), 0)::int AS from_a
    FROM r
    GROUP BY a, b
    HAVING sum(n_events) >= $4
),
o AS (
    SELECT r.a, r.b, count(DISTINCT x)::int AS outlets
    FROM r JOIN p USING (a, b) CROSS JOIN LATERAL unnest(r.outlets) AS x
    GROUP BY r.a, r.b
)
SELECT p.*, o.outlets
FROM p JOIN o USING (a, b)
WHERE o.outlets >= $5
ORDER BY p.mentions DESC, p.n DESC, p.a, p.b
"""

# The ramp (plan review I4): the earliest rollup day in the lens, the same for
# every pair. The day index's first entry in the range.
SINCE_SQL = "SELECT min(day) FROM event_pairs_daily WHERE day BETWEEN $1 AND $2"

DETAIL_SQL = """
SELECT a_iso, b_iso, day, quad_class, n_events, mentions,
       goldstein_sum, tone_sum, sample_urls, outlets
FROM event_pairs_daily
WHERE ((a_iso = $1 AND b_iso = $2) OR (a_iso = $2 AND b_iso = $1))
  AND day BETWEEN $3 AND $4
"""

TITLES_SQL = "SELECT source_url, title FROM articles WHERE source_url = ANY($1::text[])"


def lens_days(now: datetime | None = None) -> tuple[date, date]:
    """The lens's first and last UTC days: the last LENS_DAYS, today included."""
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    return today - timedelta(days=LENS_DAYS - 1), today


def _quad(counts: dict[int, int]) -> dict[str, int]:
    """All four classes, by name, zeros included (the contract's rule 7)."""
    return {name: int(counts.get(q, 0)) for q, name in QUAD_NAMES.items()}


def _kind(cooperation: int, conflict: int, goldstein: float) -> str:
    if conflict != cooperation:
        return "conflict" if conflict > cooperation else "cooperation"
    return "conflict" if goldstein < 0 else "cooperation"


async def get_since(first: date, last: date) -> date | None:
    pool = await get_pool()
    return await pool.fetchval(SINCE_SQL, first, last)


async def get_relation_pairs(first: date, last: date, kind: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(LIST_SQL, first, last, QUADS[kind], MIN_EVENTS, MIN_OUTLETS)
    return [dict(r) for r in rows]


def rank_relations(rows: list[dict], kind: str, limit: int) -> list[dict]:
    """The pairs to draw, in order: label points known, at most MAX_ARCS_PER_COUNTRY
    each. Under a class filter, *kind* names the filter (the rows hold its events only)."""
    ranked: list[dict] = []
    per_country: Counter = Counter()
    for row in rows:
        a, b = row["a"], row["b"]
        if centroid(a) is None or centroid(b) is None:  # links._country raises on these
            continue
        if per_country[a] >= MAX_ARCS_PER_COUNTRY or per_country[b] >= MAX_ARCS_PER_COUNTRY:
            continue
        per_country.update((a, b))
        ranked.append(
            {
                "a": _country(a),
                "b": _country(b),
                "n": row["n"],
                "outlets": row["outlets"],
                "mentions": row["mentions"],
                "quad": _quad({1: row["q1"], 2: row["q2"], 3: row["q3"], 4: row["q4"]}),
                "kind": kind
                if kind != "all"
                else _kind(row["q1"] + row["q2"], row["q3"] + row["q4"], row["goldstein"]),
                "goldstein": round(row["goldstein"], 2),
                "tone": round(row["tone"], 2),
                "from": a if 2 * row["from_a"] >= row["n"] else b,  # a tie goes to a
            }
        )
        if len(ranked) == limit:
            break
    return ranked


def _samples(rows: list[dict]) -> list[dict]:
    """Up to MAX_SAMPLES distinct http(s) report URLs, newest day first."""
    picked: list[dict] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda r: (-r["day"].toordinal(), r["quad_class"], r["a_iso"])):
        for url in row["sample_urls"]:
            if url in seen or web_url(url) is None:
                continue
            seen.add(url)
            picked.append(
                {
                    "url": url,
                    "outlet": outlet(url),
                    "title": None,
                    "day": row["day"],
                    "quad_class": row["quad_class"],
                    "from": row["a_iso"],
                }
            )
            if len(picked) == MAX_SAMPLES:
                return picked
    return picked


def summarise_detail(
    a: str,
    b: str,
    first: date,
    last: date,
    since: date | None,
    rows: list[dict],
    titles: dict[str, str],
) -> dict | None:
    """One pair's numbers over every class, both directions (a→b first: *a* < *b*),
    each of the lens's days and sample reports; None without rows. No thresholds."""
    if not rows:
        return None
    quad: Counter = Counter()
    directions = {(a, b): Counter(), (b, a): Counter()}
    daily = {first + timedelta(days=i): [0, 0] for i in range((last - first).days + 1)}
    n = mentions = 0
    goldstein = tone = 0.0
    outlets: dict[str, None] = {}
    for row in rows:
        q, k = row["quad_class"], row["n_events"]
        quad[q] += k
        directions[(row["a_iso"], row["b_iso"])][q] += k
        daily.setdefault(row["day"], [0, 0])[0 if q <= 2 else 1] += k
        n += k
        mentions += row["mentions"]
        goldstein += row["goldstein_sum"]
        tone += row["tone_sum"]
        outlets.update(dict.fromkeys(row["outlets"]))
    samples = _samples(rows)
    for sample in samples:
        title = titles.get(sample["url"])
        sample["title"] = display_title(title) if title else None
    by_a = sum(directions[(a, b)].values())
    return {
        "first_day": first,
        "last_day": last,
        "since": since,
        "a": _country(a),
        "b": _country(b),
        "n": n,
        "outlets": len(outlets),
        "mentions": mentions,
        "quad": _quad(quad),
        "kind": _kind(quad[1] + quad[2], quad[3] + quad[4], goldstein / n),
        "goldstein": round(goldstein / n, 2),
        "tone": round(tone / n, 2),
        "from": a if 2 * by_a >= n else b,  # a tie goes to a
        "directions": [
            {"from": x, "to": y, "n": sum(c.values()), "quad": _quad(c)}
            for (x, y), c in directions.items()
            if c
        ],
        "daily": [
            {"day": d, "cooperation": v[0], "conflict": v[1]}
            for d, v in sorted(daily.items())
            if first <= d <= last
        ],
        "samples": samples,
    }


async def get_relation_detail(a: str, b: str, first: date, last: date) -> dict | None:
    """The pair's detail, *a* < *b* (the router sorts them), or None when it has no events."""
    pool = await get_pool()
    rows = [dict(r) for r in await pool.fetch(DETAIL_SQL, a, b, first, last)]
    if not rows:
        return None
    urls = [s["url"] for s in _samples(rows)]
    titles = (
        {r["source_url"]: r["title"] for r in await pool.fetch(TITLES_SQL, urls)} if urls else {}
    )
    since = await pool.fetchval(SINCE_SQL, first, last)
    return summarise_detail(a, b, first, last, since, rows, titles)
