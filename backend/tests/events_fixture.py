"""About a week of production's event rollups, for plan tests.

ROWS_PER_DAY comes from 19b's repro (rows a day): update it from the repro's
report and from production's measure. Rows are as wide as ingestion writes
them: three sample URLs and four outlets each.

They're laid out as production's are. Ingestion adds a row when a cycle first
sees its (pair, day, class), and a pair's classes and directions turn up at
different times of day, so:
- rows are written day by day, and within a day class by class (ORDER BY d
  DESC, q, k), so one pair's rows sit on a different page for each day and
  class, not its whole week packed onto a few pages;
- BUSY_PAIR, written every day in every class, is written both ways round, its
  reverse rows mid-day (k), apart from its own, as the busiest pairs' are.
So the detail's page bound sees production's worst layout: 7 days x 4 classes
x 2 directions, each row on a page of its own.
"""

from __future__ import annotations

from datetime import date

from app.services.country_centroids import COUNTRY_CENTROIDS

# 19b's repro (2026-10-21, 96 files): 2,616 rows after a day, rounded up.
ROWS_PER_DAY = 3000
ISO = sorted(COUNTRY_CENTROIDS)[:150]
# The pair g = 1 writes (FILL_SQL's a and b), in code order.
BUSY_PAIR = (ISO[1], ISO[2])

FILL_SQL = """
WITH r AS (
    SELECT d, g, q,
           ($3::text[])[1 + g % 150] AS a,
           ($3::text[])[1 + (g % 150 + 1 + (g / 150) % 149) % 150] AS b,
           g AS k
    FROM generate_series(0, $2::int - 1) d, generate_series(1, $4::int) g,
         generate_series(1, 4) q
)
INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events, mentions,
                               goldstein_sum, tone_sum, sample_urls, outlets)
SELECT a, b, $1::date - d, q,
       1 + g % 40, 10 + g % 400, -1.5 * (1 + g % 40), -2.0 * (1 + g % 40),
       ARRAY['https://zzevents' || g % 97 || '.test/2026/10/21/a-story-slug-of-usual-length-'
             || g || '-' || q,
             'https://zzevents' || g % 89 || '.test/2026/10/21/another-story-slug-'
             || g || '-' || q,
             'https://zzevents' || g % 83 || '.test/2026/10/21/a-third-story-slug-'
             || g || '-' || q],
       ARRAY['zzevents' || g % 97 || '.test', 'zzevents' || g % 89 || '.test',
             'zzevents' || g % 83 || '.test', 'zzevents' || g % 79 || '.test']
FROM (
    SELECT * FROM r
    UNION ALL
    -- BUSY_PAIR the other way round, written mid-day, apart from its own rows.
    SELECT d, g, q, b, a, g + $4::int / 2 FROM r WHERE g = 1
) x
ORDER BY d DESC, q, k
"""


async def fill_week(conn, today: date, days: int = 8, per_day: int = ROWS_PER_DAY) -> None:
    """*days* UTC days of rollups ending *today*, then ANALYZE, as autovacuum leaves them."""
    await conn.execute(FILL_SQL, today, days, ISO, per_day // 4)
    await conn.execute("ANALYZE event_pairs_daily")
