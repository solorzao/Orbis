-- 016_kg_entity_name_trgm.sql
-- A trigram index over people and organisations only. Search
-- (app/services/search.py) and dossier name resolution
-- (app/services/entities.py) match PERSON and ORG names by prefix ILIKE or
-- trigram similarity. idx_kg_nodes_name_trgm (migration 006) covers every
-- node, including one ARTICLE node per headline. So "trump" matched
-- thousands of headlines, and each one was a random heap read just to find
-- its type and drop it: 25-45 s cold on production. The queries name this
-- predicate literally (type IN ('PERSON', 'ORG')), so every plan can use
-- this index, which holds only the names they want.
--
-- kg_nodes is written every ingestion cycle. A plain CREATE INDEX would
-- block those writes for the whole build. CONCURRENTLY never blocks
-- ingestion writes or API reads, and psql runs each statement in autocommit
-- mode, as CONCURRENTLY requires. There's no lock_timeout (as in 008 and
-- 010): CONCURRENTLY takes only SHARE UPDATE EXCLUSIVE, and a timeout
-- mid-build would leave an INVALID index behind. Nothing here touches
-- articles.

-- A failed concurrent build leaves an INVALID index that IF NOT EXISTS would
-- keep, so drop it first. Keep a VALID one: a rerun must not take away the
-- index the new backend already relies on.
SELECT EXISTS (
    SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
    WHERE c.relname = 'idx_kg_nodes_entity_name_trgm' AND NOT i.indisvalid
) AS entity_name_trgm_invalid \gset
\if :entity_name_trgm_invalid
DROP INDEX CONCURRENTLY idx_kg_nodes_entity_name_trgm;
\endif

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_nodes_entity_name_trgm
    ON kg_nodes USING gin (name gin_trgm_ops) WHERE type IN ('PERSON', 'ORG');
