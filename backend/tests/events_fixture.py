"""About a week of production's event rollups, for plan tests.

ROWS_PER_DAY comes from 19b's repro (rows a day): update it from the repro's
report and from production's measure. Rows are as wide as ingestion writes
them: three sample URLs and four outlets each. They're written day by day
(ORDER BY d, g, q), as ingestion writes them, so one pair's rows sit on a
different page each day: the detail's page bound sees production's layout,
not a pair's whole week packed onto one page.
"""

from __future__ import annotations

from datetime import date

from app.services.country_centroids import COUNTRY_CENTROIDS

# 19b's repro (2026-10-21, 96 files): 2,616 rows after a day, rounded up.
ROWS_PER_DAY = 3000
ISO = sorted(COUNTRY_CENTROIDS)[:150]

FILL_SQL = """
INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events, mentions,
                               goldstein_sum, tone_sum, sample_urls, outlets)
SELECT ($3::text[])[1 + g % 150],
       ($3::text[])[1 + (g % 150 + 1 + (g / 150) % 149) % 150],
       $1::date - d, q,
       1 + g % 40, 10 + g % 400, -1.5 * (1 + g % 40), -2.0 * (1 + g % 40),
       ARRAY['https://zzevents' || g % 97 || '.test/2026/10/21/a-story-slug-of-usual-length-'
             || g || '-' || q,
             'https://zzevents' || g % 89 || '.test/2026/10/21/another-story-slug-'
             || g || '-' || q,
             'https://zzevents' || g % 83 || '.test/2026/10/21/a-third-story-slug-'
             || g || '-' || q],
       ARRAY['zzevents' || g % 97 || '.test', 'zzevents' || g % 89 || '.test',
             'zzevents' || g % 83 || '.test', 'zzevents' || g % 79 || '.test']
FROM generate_series(0, $2::int - 1) d, generate_series(1, $4::int) g, generate_series(1, 4) q
ORDER BY d DESC, g, q
"""


async def fill_week(conn, today: date, days: int = 8, per_day: int = ROWS_PER_DAY) -> None:
    """*days* UTC days of rollups ending *today*, then ANALYZE, as autovacuum leaves them."""
    await conn.execute(FILL_SQL, today, days, ISO, per_day // 4)
    await conn.execute("ANALYZE event_pairs_daily")
