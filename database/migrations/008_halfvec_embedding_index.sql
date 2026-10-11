-- 008_halfvec_embedding_index.sql
-- Index embeddings at half precision: the HNSW index is half the size, which
-- matters with 2 GiB of RAM on the B1ms server. The column stays VECTOR(1536);
-- the similarity query casts to halfvec(1536) so it can use this index.
-- CONCURRENTLY never blocks ingestion writes or API reads while the index
-- builds; psql runs each statement in autocommit mode, as CONCURRENTLY requires.

SET maintenance_work_mem = '256MB';
-- A failed concurrent build leaves an INVALID index that IF NOT EXISTS would keep.
DROP INDEX CONCURRENTLY IF EXISTS idx_articles_embedding_half;
CREATE INDEX CONCURRENTLY idx_articles_embedding_half
    ON articles USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops);
DROP INDEX CONCURRENTLY IF EXISTS idx_articles_embedding;
