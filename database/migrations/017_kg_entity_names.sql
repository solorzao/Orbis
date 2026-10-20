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
-- Filled here, so it is complete when the new backend first reads it: one
-- sequential pass over kg_nodes, which takes only ACCESS SHARE (ingestion
-- keeps writing), then a bulk build of the trigram index over the filled
-- table. Ingestion keeps it in sync from then on: knowledge_graph.upsert_node
-- adds a row for each person and organisation it writes or mentions again,
-- and the orphan purge deletes the rows of the nodes it deletes. Nodes the
-- previous backend writes while the deploy finishes are added by their next
-- mention, or by scripts/reconcile_entity_names.py.
--
-- New table only. No foreign key to kg_nodes, so it takes no lock that
-- conflicts with ingestion's writes; nothing here touches articles. Safe
-- while the previous backend still serves.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS kg_entity_names (
    node_id UUID PRIMARY KEY,   -- kg_nodes.id (no FK: see above)
    type    TEXT NOT NULL,      -- PERSON or ORG
    name    TEXT NOT NULL
);

INSERT INTO kg_entity_names (node_id, type, name)
SELECT id, type, name FROM kg_nodes WHERE type IN ('PERSON', 'ORG')
ON CONFLICT (node_id) DO NOTHING;

-- Built after the fill: one bulk GIN build rather than a row-by-row insert.
CREATE INDEX IF NOT EXISTS idx_kg_entity_names_trgm
    ON kg_entity_names USING gin (name gin_trgm_ops);
