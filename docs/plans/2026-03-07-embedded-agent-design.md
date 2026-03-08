# Embedded News Agent — Design

**Date:** 2026-03-07
**Status:** Approved

## Overview

An AI agent embedded in the Orbis UI that answers questions about recent news (7-day window) using semantic search, a knowledge graph, and globe interaction. Users chat with the agent in a left-side panel while browsing news on the right.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| UI placement | Left slide-out panel | Right side already has news panel + minimized tabs; left is underutilized |
| Query types | Factual, analytical/comparative, globe interaction | Full capability from day one |
| Knowledge graph | Full graph (entities, topics, articles, locations) in PostgreSQL | 7-day window keeps dataset small; no new infra needed |
| Graph storage | PostgreSQL tables (nodes + edges) with recursive CTEs | Avoids new services; bounded dataset makes this performant |
| AI models | Haiku for retrieval planning, Sonnet for synthesis | Cost/quality tradeoff — cheap planning, smart answers |
| Entity extraction | Parse from GDELT GKG fields during ingestion | Free, fast, no API calls; quality sufficient for co-occurrence graph |
| Embeddings | OpenAI text-embedding-3-small on article titles during ingestion | Existing pgvector column ready; batch embedding is cheap |

## Architecture

### 1. Data Pipeline Additions

#### Embeddings

- After upserting articles, batch titles with `embedding IS NULL` and call OpenAI `text-embedding-3-small`
- Batch size: ~100 titles per API call
- Update the existing `embedding VECTOR(1536)` column on the articles table
- Add HNSW index: `CREATE INDEX idx_articles_embedding ON articles USING hnsw (embedding vector_cosine_ops)`
- If OpenAI is unavailable, skip — articles land without embeddings, backfill next cycle

#### Entity Extraction

- Parse GKG field 5 (V1PERSONS — semicolon-delimited person names)
- Parse GKG field 6 (V1ORGANIZATIONS — semicolon-delimited org names)
- Existing field 7 (V1THEMES) already parsed for topic classification
- Pass extracted `persons` and `organizations` lists through to the article dict
- Basic normalization: title-case names, strip whitespace, deduplicate within article

#### Knowledge Graph Tables

```sql
-- New migration: 004_knowledge_graph.sql

CREATE TABLE kg_nodes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        TEXT NOT NULL,  -- PERSON, ORG, LOCATION, TOPIC, ARTICLE
    name        TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (type, name)
);

CREATE INDEX idx_kg_nodes_type ON kg_nodes (type);
CREATE INDEX idx_kg_nodes_name ON kg_nodes USING gin (name gin_trgm_ops);

CREATE TABLE kg_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
```

Note: `pg_trgm` extension needed for fuzzy name matching on kg_nodes.

#### Graph Population (during ingestion)

For each ingested article:
1. Upsert ARTICLE node (name = title, metadata = {url, published_at, lat, lng})
2. Upsert PERSON nodes for each extracted person
3. Upsert ORG nodes for each extracted organization
4. Upsert LOCATION node (name = region, metadata = {lat, lng, country_code})
5. Upsert TOPIC nodes for each topic_tag
6. Create edges: MENTIONED_IN (person/org → article), LOCATED_AT (article → location), ABOUT_TOPIC (article → topic)
7. Create CO_MENTIONED edges between all entity pairs within the same article (weight increments on duplicates)

#### Retention Cleanup

- `kg_edges` has `ON DELETE CASCADE` from `article_id` FK — when articles are purged, their edges are automatically deleted
- Orphaned `kg_nodes` (nodes with no remaining edges) cleaned up periodically:
  ```sql
  DELETE FROM kg_nodes WHERE id NOT IN (
      SELECT source_node_id FROM kg_edges
      UNION
      SELECT target_node_id FROM kg_edges
  )
  ```

### 2. Agent Backend — Query Pipeline

#### Two-Step Architecture

**Step 1 — Retrieval Planning (Haiku):**

User question arrives at `POST /api/agent/ask`. Haiku receives the question plus conversation history and a tool schema. It returns a plan: a list of 1-3 tool calls to execute in parallel.

Available retrieval tools:
- `semantic_search(query, limit)` — embed the query with OpenAI, then `ORDER BY embedding <=> $1 LIMIT $2` on articles
- `graph_traverse(entity_name, rel_type, depth)` — find connected nodes via recursive CTE on kg_edges (max 3 hops)
- `keyword_search(terms, topic, country, time_range)` — SQL filters on articles (title ILIKE, topic_tags, country_code, published_at)
- `trending_topics()` — aggregate topic_tags counts over recent window
- `entity_lookup(name)` — fuzzy-match a kg_node and return its direct connections

**Step 2 — Synthesis (Sonnet):**

Retrieval results assembled into a context block. Sonnet receives:
- Original user question
- Retrieved context (articles, graph paths, aggregations) truncated to token budget
- Conversation history (last 5 exchanges)
- System prompt: cite sources, suggest globe locations, stay grounded in retrieved data

Sonnet returns structured JSON:
```json
{
    "answer": "Markdown text with [1] citation references...",
    "citations": [
        {"title": "...", "url": "...", "source_name": "...", "lat": 51.5, "lng": -0.12}
    ],
    "globe_actions": [
        {"type": "flyTo", "lat": 51.5, "lng": -0.12, "zoom": 3.5},
        {"type": "highlight", "lat": 48.8, "lng": 2.35}
    ]
}
```

#### API Endpoint

`POST /api/agent/ask`
- Request: `{ "question": "...", "conversation_id": "..." }`
- Response: SSE stream
  - Text tokens stream as `event: token` / `data: {"text": "..."}`
  - Final structured data as `event: done` / `data: {"citations": [...], "globe_actions": [...]}`

#### Conversation Memory

- Last 5 exchanges per `conversation_id` stored in Redis (TTL 1 hour)
- Passed to Haiku for context on follow-up questions
- `conversation_id` generated client-side on first message

#### New Config

```python
# config.py additions
sonnet_model_id: str = "claude-sonnet-4-5-20241022"
agent_max_retrieval_results: int = 20
agent_conversation_ttl: int = 3600  # 1 hour
```

### 3. Frontend — Chat Panel

#### Layout

- Left slide-out panel, mirrors the news panel pattern
- Toggle button: bottom-left area (sparkle/brain icon), or in the branding area
- Width: `max-w-md` (384px) on desktop, full-width sheet on mobile
- Branding shifts down when panel is open
- Z-index: z-50 (same as news panel)
- Animation: slides in from left (`x: "-100%" → 0`), spring animation matching news panel

#### Chat UI

- Message list (scrollable, auto-scroll to bottom on new messages)
- User messages: right-aligned bubbles
- Agent messages: left-aligned, render markdown
- Citation chips inline: `[1] Title — Source` — clickable to fly globe
- "Thinking" state: shows retrieval tool names as animated pills (e.g., "Searching articles...", "Traversing graph...")
- Input: text field + send button at bottom, submit on Enter

#### Globe Integration

- When agent returns `globe_actions`, execute them:
  - `flyTo` — animate globe camera to lat/lng with zoom
  - `highlight` — pulse/glow data points at specified coordinates
- Clicking a citation in chat flies globe to that article's location
- If multiple locations referenced, highlight all with connecting arcs

#### State

- Messages in React state (not persisted across page refreshes)
- `conversation_id` generated via `crypto.randomUUID()` on first message
- Panel open/closed state in same store as other panels

## New Files

### Backend
- `database/migrations/004_knowledge_graph.sql` — kg_nodes + kg_edges tables
- `backend/app/services/embeddings.py` — OpenAI batch embedding
- `backend/app/services/knowledge_graph.py` — graph population + query functions
- `backend/app/services/agent.py` — two-step agent pipeline (plan + synthesize)
- `backend/app/routers/agent.py` — SSE endpoint

### Frontend
- `frontend/src/components/AgentPanel.tsx` — chat panel UI
- `frontend/src/components/AgentMessage.tsx` — message rendering with citations
- `frontend/src/hooks/useAgent.ts` — SSE connection + state management

## Implementation Order

1. **Database migration** — kg tables + embedding index + pg_trgm extension
2. **Entity extraction** — parse GKG persons/orgs in gdelt.py
3. **Knowledge graph service** — populate graph during ingestion, cleanup on purge
4. **Embedding service** — batch embed titles during ingestion
5. **Retrieval functions** — semantic_search, graph_traverse, keyword_search, etc.
6. **Agent pipeline** — Haiku planner + Sonnet synthesizer + SSE endpoint
7. **Frontend chat panel** — UI, SSE streaming, globe actions
8. **Integration** — wire globe actions, citation clicks, thinking states
