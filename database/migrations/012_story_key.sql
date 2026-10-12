-- 012_story_key.sql
-- A 64-bit hash of the article's story: its title without the outlet's name,
-- lowercased (app.services.titles.dedup_key), so every syndicated copy of a wire
-- story shares one key. Links, surges and "since your last visit" count stories
-- by grouping on it, instead of re-deriving the key from the title in SQL.
-- Written by ingestion from the next PR; rows written before then keep NULL
-- until they age out (7-day retention), and readers count a NULL-key row as its
-- own story.
SET lock_timeout = '5s';
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS story_key BIGINT;
