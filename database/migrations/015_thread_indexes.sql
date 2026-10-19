-- 015_thread_indexes.sql
-- Partial indexes on threads (Phase 4, PR 15b review).
--
-- Plain CREATE INDEX (not CONCURRENTLY) is fine here: threads is a new, small
-- table (one narrow row per story thread, purged with the retention window)
-- that only ingestion writes, so the build takes moments and blocks no reader.
-- Nothing here touches articles.
SET lock_timeout = '5s';

-- The aggregate step's repair pick-up: threads a join or copy marked
-- (aggregated_at = NULL) that no aggregate has covered since, e.g. after a
-- failed cycle.
CREATE INDEX IF NOT EXISTS idx_threads_unaggregated
    ON threads (id) WHERE aggregated_at IS NULL;

-- Listed threads (3+ stories from 3+ outlets; app.services.thread_reads), so
-- the 168h and topic lists don't read every single-story thread in the window.
CREATE INDEX IF NOT EXISTS idx_threads_listed
    ON threads (last_seen DESC) WHERE n_stories >= 3 AND n_sources >= 3;
