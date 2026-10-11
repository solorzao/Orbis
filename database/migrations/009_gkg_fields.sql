-- 009_gkg_fields.sql
-- GKG fields kept on the article row (filled by the ingestion change that
-- follows this migration): GDELT themes, people, organisations, the most
-- frequent proper names, and typed counts (killed, arrested, protesting, ...).
-- Tone details go into the existing entities JSONB.
-- Constant defaults make this catalog-only, but fail fast rather than queue
-- API reads behind an ingestion transaction's lock.
SET lock_timeout = '5s';
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS themes  TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS persons TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS orgs    TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS names   TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS counts  JSONB  NOT NULL DEFAULT '[]';
