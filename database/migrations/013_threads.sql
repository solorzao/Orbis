-- 013_threads.sql
-- Story threads: the same developing story across outlets and places
-- (Phase 4, PR 15). Ingestion assigns each newly embedded story to the
-- best-matching active thread, or starts one (app/services/threads.py).
--
-- Nothing here references articles. A REFERENCES articles constraint would
-- lock articles while this runs and fire a trigger for every article the
-- purge deletes; instead ingestion purges thread_members by published_at,
-- and a lead_article_id that no longer resolves is skipped when read.
-- thread_members carries every field thread and entity reads need (story,
-- outlet, time, place, entities, tone, image), so they never touch the wide
-- articles heap and no articles row is rewritten. New tables only: safe
-- while the previous backend still serves.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS threads (
    id              BIGSERIAL PRIMARY KEY,
    -- Decayed sum of the unit 512-d embedding prefixes of the thread's
    -- distinct stories (one vector per story_key). thread_centroids holds
    -- its normalised form for comparison.
    centroid_sum    VECTOR(512) NOT NULL,
    first_seen      TIMESTAMPTZ NOT NULL,
    last_seen       TIMESTAMPTZ NOT NULL,
    n_articles      INT NOT NULL DEFAULT 0,
    n_stories       INT NOT NULL DEFAULT 0,
    n_sources       INT NOT NULL DEFAULT 0,
    velocity        INT NOT NULL DEFAULT 0,      -- distinct stories in the last 6 h
    countries       TEXT[] NOT NULL DEFAULT '{}',
    places          JSONB NOT NULL DEFAULT '[]', -- first report per 1° cell, in order
    top_entities    TEXT[] NOT NULL DEFAULT '{}',
    topic           TEXT NOT NULL DEFAULT '',
    lead_article_id UUID,                        -- no FK: see above
    lead_title      TEXT NOT NULL DEFAULT '',
    title           TEXT,                        -- AI title (PR 15c); NULL until then
    synopsis        TEXT,
    summarized_at   TIMESTAMPTZ,
    summarized_n    INT NOT NULL DEFAULT 0,
    aggregated_at   TIMESTAMPTZ,                 -- aggregates last recomputed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
) WITH (fillfactor = 80);                        -- room for HOT updates (velocity, counts)
CREATE INDEX IF NOT EXISTS idx_threads_last_seen ON threads (last_seen DESC);

-- The comparison index: one narrow row per *active* thread, with its unit
-- centroid inline (1 KB halfvec, STORAGE PLAIN) under an HNSW inner-product
-- index. Rows are deleted when a thread goes inactive, so the index only
-- ever holds the threads a new story can join.
CREATE TABLE IF NOT EXISTS thread_centroids (
    thread_id BIGINT PRIMARY KEY REFERENCES threads(id) ON DELETE CASCADE,
    last_seen TIMESTAMPTZ NOT NULL,
    n_stories INT NOT NULL DEFAULT 1,
    centroid  HALFVEC(512) NOT NULL
);
ALTER TABLE thread_centroids ALTER COLUMN centroid SET STORAGE PLAIN;
CREATE INDEX IF NOT EXISTS idx_thread_centroids_hnsw
    ON thread_centroids USING hnsw (centroid halfvec_ip_ops);

CREATE TABLE IF NOT EXISTS thread_members (
    article_id      UUID PRIMARY KEY,            -- no FK: see above
    thread_id       BIGINT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    story_key       BIGINT,
    source_name     TEXT NOT NULL DEFAULT '',
    published_at    TIMESTAMPTZ NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    region          TEXT NOT NULL DEFAULT '',
    country_code    TEXT NOT NULL DEFAULT '',
    topic           TEXT NOT NULL DEFAULT '',
    entities        TEXT[] NOT NULL DEFAULT '{}', -- persons and orgs, capped at 10
    tone            REAL,
    has_https_image BOOLEAN NOT NULL DEFAULT false,
    similarity      REAL NOT NULL                -- to the thread when joined
);
CREATE INDEX IF NOT EXISTS idx_thread_members_thread ON thread_members (thread_id, published_at);
CREATE INDEX IF NOT EXISTS idx_thread_members_story ON thread_members (story_key);
CREATE INDEX IF NOT EXISTS idx_thread_members_published ON thread_members (published_at);
CREATE INDEX IF NOT EXISTS idx_thread_members_entities ON thread_members USING gin (entities);
