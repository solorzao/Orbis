-- 017_kg_entity_names.sql
-- A narrow copy of the knowledge graph's people and organisations, for name
-- search (app/services/search.py) and dossier name resolution
-- (app/services/entities.py).
--
-- In kg_nodes, PERSON and ORG rows sit thinly among one ARTICLE row per
-- headline (about 1 in 3 rows), so every name a trigram match rechecks is a
-- random read of its own kg_nodes page. A short query whose opening letters
-- are common ("sunak", "hamas": every name with a word starting "Su" or "Ha")
-- rechecked thousands of names on thousands of pages, 8-19 s cold on
-- production even with 016's partial index. Here the same names fill a few
-- MB that stay cached.
--
-- Ingestion keeps it in sync: knowledge_graph.upsert_node adds a row for each
-- person and organisation it writes or mentions again, and the orphan purge
-- deletes the rows of the nodes it deletes. scripts/backfill_entity_names.py
-- adds the ones stored before this migration (run it once after deploy).
--
-- New table only. No foreign key to kg_nodes, so creating it takes no lock on
-- kg_nodes, which ingestion writes every cycle; nothing here touches articles.
-- Safe while the previous backend still serves.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS kg_entity_names (
    node_id UUID PRIMARY KEY,   -- kg_nodes.id (no FK: see above)
    type    TEXT NOT NULL,      -- PERSON or ORG
    name    TEXT NOT NULL
);

-- Built on the empty table, so a plain CREATE INDEX is instant.
CREATE INDEX IF NOT EXISTS idx_kg_entity_names_trgm
    ON kg_entity_names USING gin (name gin_trgm_ops);
