-- 010_kg_edge_recency_indexes.sql
-- Index each knowledge-graph edge endpoint together with the edge's age.
-- Retrieval (backend/app/services/retrieval.py) reads a node's edges one
-- direction at a time, newest first, and stops after a fixed number:
--     WHERE source_node_id = $1 ... ORDER BY created_at DESC LIMIT n
--     WHERE target_node_id = $1 ... ORDER BY created_at DESC LIMIT n
-- That is every graph_traverse hop, both entity_lookup edge queries and the
-- co-mention window. With these indexes each read is a range scan that stops
-- after n rows, however many edges a hot entity or topic has; without them the
-- planner reads all of the node's edges and sorts them.
--
-- They also answer every plain equality lookup on source_node_id or
-- target_node_id (co-mention joins, the ON DELETE CASCADE checks when kg_nodes
-- rows go), so the single-column indexes from 006 become redundant and are
-- dropped, with idx_kg_edges_rel: rel_type has four values, nothing filters on
-- it selectively, and each of these indexes costs every ingestion insert.
--
-- CONCURRENTLY never blocks ingestion writes or API reads while an index
-- builds; psql runs each statement in autocommit mode, as CONCURRENTLY requires.
-- No lock_timeout (as in 008): CONCURRENTLY takes only SHARE UPDATE EXCLUSIVE,
-- which does not conflict with reads or writes, and a timeout mid-build would
-- leave an INVALID index behind.

-- A failed concurrent build leaves an INVALID index that IF NOT EXISTS would
-- keep, so drop it first. Keep a VALID one: a rerun after a failure past the
-- CREATE must not take away the index the new backend already relies on.
SELECT EXISTS (
    SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
    WHERE c.relname = 'idx_kg_edges_source_recent' AND NOT i.indisvalid
) AS source_recent_invalid \gset
\if :source_recent_invalid
DROP INDEX CONCURRENTLY idx_kg_edges_source_recent;
\endif

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_edges_source_recent
    ON kg_edges (source_node_id, created_at DESC);

SELECT EXISTS (
    SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
    WHERE c.relname = 'idx_kg_edges_target_recent' AND NOT i.indisvalid
) AS target_recent_invalid \gset
\if :target_recent_invalid
DROP INDEX CONCURRENTLY idx_kg_edges_target_recent;
\endif

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_edges_target_recent
    ON kg_edges (target_node_id, created_at DESC);

-- Reached only once both indexes above are valid: ON_ERROR_STOP ends the file
-- at a failed CREATE, which leaves the old indexes in place.
DROP INDEX CONCURRENTLY IF EXISTS idx_kg_edges_source;
DROP INDEX CONCURRENTLY IF EXISTS idx_kg_edges_target;
DROP INDEX CONCURRENTLY IF EXISTS idx_kg_edges_rel;
