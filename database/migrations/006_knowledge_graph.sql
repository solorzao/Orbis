-- 006_knowledge_graph.sql
-- Knowledge graph tables for the embedded agent + embedding HNSW index

-- Trigram extension for fuzzy entity name matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Graph nodes: entities, locations, topics, articles
CREATE TABLE IF NOT EXISTS kg_nodes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type        TEXT NOT NULL,   -- PERSON, ORG, LOCATION, TOPIC, ARTICLE
    name        TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (type, name)
);

CREATE INDEX idx_kg_nodes_type ON kg_nodes (type);
CREATE INDEX idx_kg_nodes_name_trgm ON kg_nodes USING gin (name gin_trgm_ops);

-- Graph edges: typed relationships between nodes
CREATE TABLE IF NOT EXISTS kg_edges (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_node_id  UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    target_node_id  UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    rel_type        TEXT NOT NULL,  -- MENTIONED_IN, LOCATED_AT, ABOUT_TOPIC, CO_MENTIONED
    weight          INT DEFAULT 1,
    article_id      UUID REFERENCES articles(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_kg_edges_source ON kg_edges (source_node_id);
CREATE INDEX idx_kg_edges_target ON kg_edges (target_node_id);
CREATE INDEX idx_kg_edges_rel ON kg_edges (rel_type);
CREATE INDEX idx_kg_edges_article ON kg_edges (article_id);

-- HNSW index for vector similarity search on article embeddings
CREATE INDEX IF NOT EXISTS idx_articles_embedding
    ON articles USING hnsw (embedding vector_cosine_ops);
