-- 008_halfvec_embedding_index.sql
-- Index embeddings at half precision: the HNSW index is half the size, which
-- matters with 2 GiB of RAM on the B1ms server. The column stays VECTOR(1536);
-- the similarity query casts to halfvec(1536) so it can use this index.
-- CONCURRENTLY never blocks ingestion writes or API reads while the index
-- builds; psql runs each statement in autocommit mode, as CONCURRENTLY requires.
--
-- No lock_timeout (unlike 007): CONCURRENTLY takes only SHARE UPDATE EXCLUSIVE,
-- which does not conflict with reads or writes, and a timeout mid-build would
-- leave an INVALID index behind.

-- A halfvec(1536) is about 3 KB per row; with the HNSW graph on top, today's
-- build needs about 50 MB. At 110K-220K rows a future rebuild outgrows 256 MB,
-- and pgvector then logs a NOTICE and finishes with a slower build rather than
-- failing. 256 MB for this one session is safe on 2 GiB of RAM.
SET maintenance_work_mem = '256MB';

-- A failed concurrent build leaves an INVALID index that IF NOT EXISTS would
-- keep, so drop it first. Keep a VALID one: a rerun after a failure past the
-- CREATE must not take away the index the new backend already relies on.
SELECT EXISTS (
    SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
    WHERE c.relname = 'idx_articles_embedding_half' AND NOT i.indisvalid
) AS half_index_invalid \gset
\if :half_index_invalid
DROP INDEX CONCURRENTLY idx_articles_embedding_half;
\endif

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_embedding_half
    ON articles USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops);
DROP INDEX CONCURRENTLY IF EXISTS idx_articles_embedding;
