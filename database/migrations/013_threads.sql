-- 013_threads.sql
-- Story threads: the same developing story across outlets and places
-- (Phase 4, PR 15). Ingestion assigns each newly embedded article to the
-- best-matching active thread, or starts one (app/services/threads.py).
-- thread_members carries every field threads read (story, outlet, time,
-- place, entities, tone), so thread queries never scan the wide articles
-- heap and no articles row is rewritten. New tables only: safe while the
-- previous backend still serves.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS threads (
    id              BIGSERIAL PRIMARY KEY,
    -- Sum of members' unit 512-d embedding prefixes; compare with
    -- l2_normalize(centroid_sum). A sum, so joining is centroid_sum + v.
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
    lead_article_id UUID REFERENCES articles(id) ON DELETE SET NULL,
    title           TEXT,                        -- AI title (PR 15c); NULL until then
    synopsis        TEXT,
    summarized_at   TIMESTAMPTZ,
    summarized_n    INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_threads_last_seen ON threads (last_seen DESC);

CREATE TABLE IF NOT EXISTS thread_members (
    article_id   UUID PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    thread_id    BIGINT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    story_key    BIGINT,
    source_name  TEXT NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ NOT NULL,
    latitude     DOUBLE PRECISION NOT NULL,
    longitude    DOUBLE PRECISION NOT NULL,
    region       TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL DEFAULT '',
    topic        TEXT NOT NULL DEFAULT '',
    entities     TEXT[] NOT NULL DEFAULT '{}',   -- persons and orgs, capped at 10
    tone         REAL,
    similarity   REAL NOT NULL                   -- to the thread when joined
);
CREATE INDEX IF NOT EXISTS idx_thread_members_thread ON thread_members (thread_id, published_at);
CREATE INDEX IF NOT EXISTS idx_thread_members_story ON thread_members (story_key);
CREATE INDEX IF NOT EXISTS idx_thread_members_published ON thread_members (published_at);
