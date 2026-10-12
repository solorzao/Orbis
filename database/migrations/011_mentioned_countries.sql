-- 011_mentioned_countries.sql
-- ISO 3166-1 alpha-2 codes of the countries an article mentions (GDELT
-- country-level locations), filled by ingestion from PR 13b. Links between
-- places are computed from this column instead of joining the knowledge graph
-- (4.2 s cold at 24h on production, 2026-10-12).
SET lock_timeout = '5s';
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS mentioned_countries TEXT[] NOT NULL DEFAULT '{}';
