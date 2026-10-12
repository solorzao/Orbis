-- 012_story_key.sql
-- A 64-bit hash of the article's story: its title without the outlet's name,
-- lowercased (ingestion's _dedup_key), so every syndicated copy of a wire story
-- shares one key. Links, surges and "since your last visit" count stories by
-- grouping on it, instead of re-deriving the key from the title in SQL.
-- Written by ingestion from the next PR, which also fills recent rows; NULL
-- means not keyed yet.
SET lock_timeout = '5s';
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS story_key BIGINT;
