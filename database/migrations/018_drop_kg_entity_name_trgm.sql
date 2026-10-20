-- 018_drop_kg_entity_name_trgm.sql
-- Drop 016's partial trigram index of people and organisations in kg_nodes.
-- Search and dossier name resolution read kg_entity_names (017) instead, so
-- nothing uses it, and it cost a GIN write for every new person or org.
-- The full idx_kg_nodes_name_trgm (006) stays: retrieval's fuzzy entity
-- lookup searches every node type with it.
--
-- CONCURRENTLY: a plain DROP INDEX takes ACCESS EXCLUSIVE on kg_nodes, which
-- ingestion writes every cycle. psql runs it in autocommit mode, as
-- CONCURRENTLY requires. No lock_timeout (as in 008, 010 and 016): a timeout
-- mid-drop could leave the index INVALID; IF EXISTS makes a rerun safe.

DROP INDEX CONCURRENTLY IF EXISTS idx_kg_nodes_entity_name_trgm;
