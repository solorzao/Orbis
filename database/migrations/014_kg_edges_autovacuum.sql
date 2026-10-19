-- 014_kg_edges_autovacuum.sql
-- Vacuum kg_edges after 1% new rows, not the default 20%, so its newest
-- pages become all-visible within hours. Search counts each candidate's
-- recent mentions newest first on idx_kg_edges_source_recent (migration
-- 010): an index-only scan, except that every entry on a page written since
-- the last vacuum costs a heap fetch, a random read on the P4 disk.
-- kg_edges only grows by insert (the purge deletes in bulk), so the
-- insert-driven threshold is the one that matters.
--
-- ALTER TABLE ... SET (autovacuum_*) takes SHARE UPDATE EXCLUSIVE, which
-- doesn't conflict with reads or writes, and changes no data: safe while the
-- previous backend still serves. The lock_timeout makes it fail fast rather
-- than queue behind a running vacuum; rerun the Deploy workflow if it does.
SET lock_timeout = '5s';

ALTER TABLE kg_edges SET (autovacuum_vacuum_insert_scale_factor = 0.01);
