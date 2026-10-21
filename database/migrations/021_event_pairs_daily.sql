-- 021_event_pairs_daily.sql
-- GDELT Events (Phase 5, PR 19): daily country-pair rollups of the
-- machine-coded events in GDELT 2.0's 15-minute export files, and the log
-- of the files added. Ingestion (app/services/events.py) adds each file's
-- events into these rows; nothing is stored per event.
--
-- One row per (actor 1 country, actor 2 country, UTC day, QuadClass):
--   a_iso, b_iso   ISO 3166-1 alpha-2 of Actor1CountryCode and
--                  Actor2CountryCode (CAMEO codes mapped by
--                  app/services/cameo_countries.py). Never equal: domestic
--                  events are not stored.
--   day            the UTC day GDELT added the events (DATEADDED), not the
--                  day they happened (SQLDATE), so retention and windows
--                  follow reporting, as articles.published_at does.
--   quad_class     1 verbal cooperation, 2 material cooperation,
--                  3 verbal conflict, 4 material conflict.
--   n_events, mentions (NumMentions: each event's first 15 minutes only),
--   goldstein_sum, tone_sum: sums, so each file adds to them; reads divide
--   by n_events. No report count: distinct URLs per row can't be summed
--   across rows without counting one article several times.
--   sample_urls    up to 3 first-report URLs (http(s) only), first seen first.
--   outlets        up to 8 distinct outlet hosts, first seen first; reads
--                  count the distinct union across a pair's rows.
-- About 2K-5K rows a day, kept for retention_days (ingestion deletes older
-- days). fillfactor 70 leaves room on each page, so a cycle's additions,
-- which change no indexed column, are HOT updates.
--
-- event_files: one row per 15-minute export added, found missing, or found
-- unreadable (never retried), so a file is never added twice: rollups are
-- sums.
--
-- New tables only, and nothing references articles or any other table:
-- safe while the previous backend still serves.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS event_pairs_daily (
    a_iso         TEXT NOT NULL,
    b_iso         TEXT NOT NULL,
    day           DATE NOT NULL,
    quad_class    SMALLINT NOT NULL CHECK (quad_class BETWEEN 1 AND 4),
    n_events      INT NOT NULL,
    mentions      INT NOT NULL,
    goldstein_sum DOUBLE PRECISION NOT NULL,
    tone_sum      DOUBLE PRECISION NOT NULL,
    sample_urls   TEXT[] NOT NULL DEFAULT '{}',
    outlets       TEXT[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (a_iso, b_iso, day, quad_class),
    CHECK (a_iso <> b_iso),
    CHECK (char_length(a_iso) = 2 AND char_length(b_iso) = 2)
) WITH (fillfactor = 70);
-- The relations list and the retention purge read by day; the primary key
-- serves a pair's detail and the upsert.
CREATE INDEX IF NOT EXISTS idx_event_pairs_day ON event_pairs_daily (day);

CREATE TABLE IF NOT EXISTS event_files (
    slot         TIMESTAMPTZ PRIMARY KEY,   -- the file's 15-minute timestamp (UTC)
    status       TEXT NOT NULL CHECK (status IN ('ok', 'missing', 'unreadable')),
    n_rows       INT NOT NULL DEFAULT 0,    -- events in the file
    n_kept       INT NOT NULL DEFAULT 0,    -- events added to the rollups
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
