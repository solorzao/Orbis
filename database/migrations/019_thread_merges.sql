-- 019_thread_merges.sql
-- Thread merges (Phase 4 calibration). The merge pass merges a thread into its
-- nearest active neighbour when both tell one story; the merged thread keeps its
-- row, emptied, with merged_into pointing at the thread it joined, so an id held
-- by a share link or the UI still resolves (GET /api/threads/{id} answers with
-- that thread). Threads merged into it earlier are repointed, so one hop always
-- reaches the winner. ON DELETE SET NULL: retention may delete either first.
--
-- Also deletes the threads built from news digests ("AP News Summary at 6:14
-- a.m. EDT", thread 129), which ingestion no longer threads: their lead headline
-- matches app.services.threads.DIGEST_PATTERN. Their members go with them (the
-- articles stay).
--
-- threads only (never articles); a nullable column without a default is
-- catalog-only, and threads is small.
SET lock_timeout = '5s';

ALTER TABLE threads
    ADD COLUMN IF NOT EXISTS merged_into BIGINT REFERENCES threads(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_threads_merged_into
    ON threads (merged_into) WHERE merged_into IS NOT NULL;

DELETE FROM threads WHERE lead_title ~* '^\s*(ap news (summary|in brief)|news (summary|in brief|digest|roundup)|today in history|(morning|evening|daily|weekly) (briefing|digest|roundup)|top (stories|headlines))([^a-z]|$)';
