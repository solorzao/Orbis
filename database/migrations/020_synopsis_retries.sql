-- 020_synopsis_retries.sql
-- Synopsis retries back off (Phase 4 review). A thread whose synopsis fails (no
-- usable headline, or a reply validation rejects, such as one saying "linked
-- to") was left unwritten, so the next cycle picked it again: every cycle, one of
-- its six slots and a Claude call. Now each failure in a row is counted, and the
-- thread isn't eligible again until synopsis_retry_at (2 hours, doubling, at most
-- a day); a synopsis resets both.
--
-- One instant change: a constant default and a nullable column are catalog-only.
-- Neither is indexed, so the updates that write them stay HOT.
SET lock_timeout = '5s';

ALTER TABLE threads
    ADD COLUMN IF NOT EXISTS synopsis_failures INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS synopsis_retry_at TIMESTAMPTZ;
