-- 019_thread_merges.sql
-- Thread merges (Phase 4 calibration). The merge pass merges a thread into its
-- nearest active neighbour when both tell one story; the merged thread keeps its
-- row, emptied, with merged_into naming the thread it joined, so an id held by a
-- share link or the UI still resolves: GET /api/threads/{id} follows merged_into
-- (by primary key, through any later merges) and answers with that thread.
--
-- One instant change: a nullable column without a default is catalog-only. No
-- index (building one would scan threads), so no foreign key either (unindexed,
-- it would scan threads for every thread the retention purge deletes): a
-- merged_into whose thread was purged reads as an unknown thread.
SET lock_timeout = '5s';

ALTER TABLE threads ADD COLUMN IF NOT EXISTS merged_into BIGINT;
