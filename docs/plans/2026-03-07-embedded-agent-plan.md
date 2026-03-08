# Embedded News Agent — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an AI agent embedded in a left-side chat panel that answers questions about recent news using semantic search, a PostgreSQL knowledge graph, and globe interaction.

**Architecture:** Two-step agent (Haiku plans retrieval, Sonnet synthesizes answer). Data pipeline extends existing ingestion to extract GKG entities, generate embeddings, and populate a graph. Frontend adds a left slide-out chat panel that streams responses and triggers globe actions.

**Tech Stack:** Python FastAPI, asyncpg, OpenAI embeddings, Anthropic Claude (Haiku + Sonnet), React/Next.js, Framer Motion, SSE streaming, globe.gl

**Design doc:** `docs/plans/2026-03-07-embedded-agent-design.md`

---

## Task 1: Database Migration — Knowledge Graph Tables & Embedding Index

**Files:**
- Create: `database/migrations/006_knowledge_graph.sql`

**Step 1: Write the migration**

```sql
-- 006_knowledge_graph.sql
-- Knowledge graph tables for the embedded agent

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
```

**Step 2: Apply migration to the database**

Run: `psql $DATABASE_URL -f database/migrations/006_knowledge_graph.sql`
Expected: Tables and indexes created without error.

**Step 3: Commit**

```bash
git add database/migrations/006_knowledge_graph.sql
git commit -m "feat(agent): add knowledge graph tables and embedding index"
```

---

## Task 2: Entity Extraction from GKG

Parse persons (field 5) and organizations (field 6) from the raw GKG TSV during ingestion.

**Files:**
- Modify: `backend/app/services/gdelt.py` (lines 271-338, inside `fetch_raw_gkg()`)
- Test: `backend/tests/test_gdelt.py`

**Step 1: Write the failing test**

Add to `backend/tests/test_gdelt.py`:

```python
@pytest.mark.asyncio
async def test_fetch_raw_gkg_extracts_persons_and_orgs(mock_gkg_response):
    """Entity fields (persons, orgs) should be parsed from GKG fields 5 and 6."""
    # Build a GKG line with persons in field 5 and orgs in field 6
    fields = [""] * 19
    fields[1] = "20260307120000"  # date
    fields[3] = "example.com"     # domain
    fields[4] = "https://example.com/article1"  # url
    fields[5] = "Joe Biden;Donald Trump"  # V1PERSONS
    fields[6] = "United Nations;NATO"     # V1ORGANIZATIONS
    fields[7] = "TAX_FNCACT_PRESIDENT"    # themes
    fields[9] = "4#London, United Kingdom#UK#UKH9#51.5074#-0.1278#-1234567"  # location
    fields[15] = "1.5,3.0,1.5,0,0"  # tone
    fields[18] = ""  # image

    gkg_line = "\t".join(fields)
    gkg_content = f"some_header_info\n{gkg_line}"

    with patch("app.services.gdelt._download_bytes", return_value=gkg_content.encode()):
        with patch("app.services.gdelt._fetch_latest_gkg_url", return_value="http://fake/gkg.zip"):
            articles = await fetch_raw_gkg()

    url = "https://example.com/article1"
    assert url in articles
    assert articles[url]["persons"] == ["Joe Biden", "Donald Trump"]
    assert articles[url]["organizations"] == ["United Nations", "NATO"]


@pytest.mark.asyncio
async def test_fetch_raw_gkg_handles_empty_entity_fields(mock_gkg_response):
    """Articles with empty person/org fields should get empty lists."""
    fields = [""] * 19
    fields[1] = "20260307120000"
    fields[3] = "example.com"
    fields[4] = "https://example.com/article2"
    fields[5] = ""  # no persons
    fields[6] = ""  # no orgs
    fields[7] = ""
    fields[9] = "4#Tokyo, Japan#JA#JA13#35.6762#139.6503#-1234567"
    fields[15] = "0.0"
    fields[18] = ""

    gkg_line = "\t".join(fields)
    gkg_content = f"header\n{gkg_line}"

    with patch("app.services.gdelt._download_bytes", return_value=gkg_content.encode()):
        with patch("app.services.gdelt._fetch_latest_gkg_url", return_value="http://fake/gkg.zip"):
            articles = await fetch_raw_gkg()

    url = "https://example.com/article2"
    assert url in articles
    assert articles[url]["persons"] == []
    assert articles[url]["organizations"] == []
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gdelt.py::test_fetch_raw_gkg_extracts_persons_and_orgs -v`
Expected: FAIL - `persons` key not in article dict.

**Step 3: Implement entity parsing in `gdelt.py`**

In `backend/app/services/gdelt.py`, inside `fetch_raw_gkg()`, after extracting `domain` (around line 315), add parsing of fields 5 and 6:

```python
        # Extract persons (field 5) and organizations (field 6)
        persons_raw = fields[5] if len(fields) > 5 else ""
        orgs_raw = fields[6] if len(fields) > 6 else ""
        persons = [p.strip().title() for p in persons_raw.split(";") if p.strip()] if persons_raw else []
        organizations = [o.strip().title() for o in orgs_raw.split(";") if o.strip()] if orgs_raw else []
```

Then add them to the article dict being built (around line 325):

```python
        articles[url] = {
            # ... existing fields ...
            "persons": persons,
            "organizations": organizations,
        }
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_gdelt.py -v`
Expected: All pass, including the two new tests.

**Step 5: Commit**

```bash
git add backend/app/services/gdelt.py backend/tests/test_gdelt.py
git commit -m "feat(agent): extract persons and organizations from GKG fields"
```

---

## Task 3: Knowledge Graph Service

Populate the knowledge graph from ingested articles and clean up orphaned nodes on purge.

**Files:**
- Create: `backend/app/services/knowledge_graph.py`
- Modify: `backend/app/services/ingestion.py`
- Test: `backend/tests/test_knowledge_graph.py`

**Step 1: Write failing tests**

Create `backend/tests/test_knowledge_graph.py`:

```python
"""Tests for the knowledge graph population service."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.knowledge_graph import populate_graph, purge_orphaned_nodes


def _make_article(
    title="Test Article",
    url="https://example.com/a",
    lat=51.5,
    lng=-0.12,
    region="London, United Kingdom",
    country_code="UK",
    topic_tags=None,
    persons=None,
    organizations=None,
):
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "source_url": url,
        "latitude": lat,
        "longitude": lng,
        "region": region,
        "country_code": country_code,
        "topic_tags": topic_tags or ["politics"],
        "persons": persons or [],
        "organizations": organizations or [],
        "published_at": datetime.now(timezone.utc),
    }


@pytest.mark.asyncio
async def test_populate_graph_creates_article_node():
    """An ARTICLE node should be upserted for each article."""
    mock_conn = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_conn.fetchval = AsyncMock(return_value=str(uuid.uuid4()))

    with patch("app.services.knowledge_graph.get_pool", return_value=mock_pool):
        article = _make_article()
        await populate_graph([article])

    calls = [str(c) for c in mock_conn.fetchval.call_args_list]
    assert any("ARTICLE" in c for c in calls)


@pytest.mark.asyncio
async def test_populate_graph_creates_entity_edges():
    """PERSON and ORG entities should get MENTIONED_IN edges to the article."""
    mock_conn = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_conn.fetchval = AsyncMock(side_effect=[str(uuid.uuid4()) for _ in range(20)])

    with patch("app.services.knowledge_graph.get_pool", return_value=mock_pool):
        article = _make_article(persons=["Joe Biden"], organizations=["NATO"])
        await populate_graph([article])

    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("MENTIONED_IN" in c for c in calls)


@pytest.mark.asyncio
async def test_populate_graph_creates_co_mentioned_edges():
    """Entities in the same article should get CO_MENTIONED edges."""
    mock_conn = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_conn.fetchval = AsyncMock(side_effect=[str(uuid.uuid4()) for _ in range(20)])

    with patch("app.services.knowledge_graph.get_pool", return_value=mock_pool):
        article = _make_article(persons=["Joe Biden", "Volodymyr Zelenskyy"])
        await populate_graph([article])

    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("CO_MENTIONED" in c for c in calls)


@pytest.mark.asyncio
async def test_purge_orphaned_nodes():
    """Nodes with no remaining edges should be deleted."""
    mock_pool = AsyncMock()
    mock_pool.execute = AsyncMock(return_value="DELETE 5")

    with patch("app.services.knowledge_graph.get_pool", return_value=mock_pool):
        await purge_orphaned_nodes()

    mock_pool.execute.assert_called_once()
    call_sql = str(mock_pool.execute.call_args)
    assert "kg_nodes" in call_sql
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_knowledge_graph.py -v`
Expected: FAIL - module not found.

**Step 3: Implement knowledge_graph.py**

Create `backend/app/services/knowledge_graph.py`:

```python
"""Knowledge graph population and query service.

Manages a PostgreSQL-based knowledge graph of entities, topics, locations,
and articles extracted from GDELT news data.
"""
from __future__ import annotations

import json
import logging
from itertools import combinations

from app.services.database import get_pool

logger = logging.getLogger("orbis.knowledge_graph")

_UPSERT_NODE = """
    INSERT INTO kg_nodes (type, name, metadata)
    VALUES ($1, $2, $3::jsonb)
    ON CONFLICT (type, name) DO UPDATE SET metadata = kg_nodes.metadata || $3::jsonb
    RETURNING id
"""

_UPSERT_EDGE = """
    INSERT INTO kg_edges (source_node_id, target_node_id, rel_type, weight, article_id)
    VALUES ($1, $2, $3, 1, $4)
    ON CONFLICT DO NOTHING
"""

_INCREMENT_EDGE = """
    UPDATE kg_edges SET weight = weight + 1
    WHERE source_node_id = $1 AND target_node_id = $2 AND rel_type = $3
"""


async def _upsert_node(conn, node_type: str, name: str, metadata: dict | None = None) -> str:
    """Upsert a graph node and return its ID."""
    meta = json.dumps(metadata or {})
    return await conn.fetchval(_UPSERT_NODE, node_type, name, meta)


async def populate_graph(articles: list[dict]) -> int:
    """Populate the knowledge graph from a batch of ingested articles.

    For each article, creates:
    - ARTICLE node
    - PERSON / ORG nodes for extracted entities
    - LOCATION node for the article's region
    - TOPIC nodes for each topic tag
    - MENTIONED_IN edges (entity -> article)
    - LOCATED_AT edge (article -> location)
    - ABOUT_TOPIC edges (article -> topic)
    - CO_MENTIONED edges between entity pairs in the same article

    Returns the number of edges created.
    """
    if not articles:
        return 0

    pool = await get_pool()
    edge_count = 0

    async with pool.acquire() as conn:
        for article in articles:
            article_id = article.get("id")
            if not article_id:
                continue

            # Upsert ARTICLE node
            article_node_id = await _upsert_node(conn, "ARTICLE", article["title"], {
                "url": article.get("source_url", ""),
                "lat": article.get("latitude"),
                "lng": article.get("longitude"),
                "published_at": str(article.get("published_at", "")),
            })

            entity_node_ids = []

            # Upsert PERSON nodes + MENTIONED_IN edges
            for person in article.get("persons", []):
                if not person:
                    continue
                node_id = await _upsert_node(conn, "PERSON", person)
                entity_node_ids.append(node_id)
                await conn.execute(_UPSERT_EDGE, node_id, article_node_id, "MENTIONED_IN", article_id)
                edge_count += 1

            # Upsert ORG nodes + MENTIONED_IN edges
            for org in article.get("organizations", []):
                if not org:
                    continue
                node_id = await _upsert_node(conn, "ORG", org)
                entity_node_ids.append(node_id)
                await conn.execute(_UPSERT_EDGE, node_id, article_node_id, "MENTIONED_IN", article_id)
                edge_count += 1

            # Upsert LOCATION node + LOCATED_AT edge
            region = article.get("region", "")
            if region:
                loc_node_id = await _upsert_node(conn, "LOCATION", region, {
                    "lat": article.get("latitude"),
                    "lng": article.get("longitude"),
                    "country_code": article.get("country_code", ""),
                })
                await conn.execute(_UPSERT_EDGE, article_node_id, loc_node_id, "LOCATED_AT", article_id)
                edge_count += 1

            # Upsert TOPIC nodes + ABOUT_TOPIC edges
            for topic in article.get("topic_tags", []):
                if not topic:
                    continue
                topic_node_id = await _upsert_node(conn, "TOPIC", topic)
                await conn.execute(_UPSERT_EDGE, article_node_id, topic_node_id, "ABOUT_TOPIC", article_id)
                edge_count += 1

            # CO_MENTIONED edges between all entity pairs
            for a_id, b_id in combinations(entity_node_ids, 2):
                await conn.execute(_UPSERT_EDGE, a_id, b_id, "CO_MENTIONED", article_id)
                await conn.execute(_INCREMENT_EDGE, a_id, b_id, "CO_MENTIONED")
                edge_count += 1

    logger.info("Knowledge graph: created %d edges from %d articles.", edge_count, len(articles))
    return edge_count


async def purge_orphaned_nodes() -> int:
    """Delete graph nodes that have no remaining edges."""
    pool = await get_pool()
    status = await pool.execute(
        """
        DELETE FROM kg_nodes
        WHERE id NOT IN (SELECT source_node_id FROM kg_edges)
          AND id NOT IN (SELECT target_node_id FROM kg_edges)
        """
    )
    count = int(status.split()[-1])
    if count:
        logger.info("Purged %d orphaned graph nodes.", count)
    return count
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_knowledge_graph.py -v`
Expected: All 4 tests pass.

**Step 5: Wire into ingestion pipeline**

In `backend/app/services/ingestion.py`, add the import:

```python
from app.services.knowledge_graph import populate_graph, purge_orphaned_nodes
```

In `_ingest_from_raw_gkg()`, after `count = await upsert_articles(rows)` (line 90), add:

```python
    # Populate knowledge graph from ingested articles
    pool = await get_pool()
    upserted = await pool.fetch(
        "SELECT id, title, source_url, latitude, longitude, region, country_code, topic_tags "
        "FROM articles WHERE source_url = ANY($1)",
        [r["source_url"] for r in rows],
    )

    # Merge entity data from rows into the DB records
    url_to_entities = {r["source_url"]: r for r in rows}
    graph_articles = []
    for row in upserted:
        src = url_to_entities.get(row["source_url"], {})
        graph_articles.append({
            "id": str(row["id"]),
            "title": row["title"],
            "source_url": row["source_url"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "region": row["region"],
            "country_code": row["country_code"],
            "topic_tags": row["topic_tags"],
            "persons": src.get("persons", []),
            "organizations": src.get("organizations", []),
            "published_at": src.get("published_at"),
        })

    await populate_graph(graph_articles)
```

In `_purge_old_articles()`, after the DELETE, add orphan cleanup:

```python
    await purge_orphaned_nodes()
```

Also pass `persons` and `organizations` through in the rows dict (around line 67-84 in `_ingest_from_raw_gkg`):

```python
        rows.append(
            {
                # ... existing fields ...
                "persons": a.get("persons", []),
                "organizations": a.get("organizations", []),
            }
        )
```

Note: `persons` and `organizations` are not DB columns. They are carried through in the dict for knowledge graph population only.

**Step 6: Run all tests**

Run: `cd backend && python -m pytest -v`
Expected: All pass.

**Step 7: Commit**

```bash
git add backend/app/services/knowledge_graph.py backend/app/services/ingestion.py backend/tests/test_knowledge_graph.py
git commit -m "feat(agent): knowledge graph population and orphan cleanup"
```

---

## Task 4: Embedding Service

Generate OpenAI embeddings for article titles during ingestion.

**Files:**
- Create: `backend/app/services/embeddings.py`
- Modify: `backend/app/services/ingestion.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_embeddings.py`

**Step 1: Add config for embedding model**

In `backend/app/config.py`, add to the Settings class in the AI section:

```python
    # --- AI ---
    # ... existing fields ...
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = 100
```

**Step 2: Write failing tests**

Create `backend/tests/test_embeddings.py`:

```python
"""Tests for the embedding generation service."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embeddings import generate_embeddings


@pytest.mark.asyncio
async def test_generate_embeddings_calls_openai():
    """Should call OpenAI API with article titles and update the DB."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": "uuid-1", "title": "Breaking news about climate"},
        {"id": "uuid-2", "title": "Tech stocks surge"},
    ])
    mock_pool.executemany = AsyncMock()

    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1] * 1536

    mock_response = MagicMock()
    mock_response.data = [mock_embedding, mock_embedding]

    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with patch("app.services.embeddings.get_pool", return_value=mock_pool):
        with patch("app.services.embeddings._get_openai_client", return_value=mock_client):
            count = await generate_embeddings()

    assert count == 2
    mock_client.embeddings.create.assert_called_once()


@pytest.mark.asyncio
async def test_generate_embeddings_skips_when_no_api_key():
    """Should return 0 if OpenAI API key is not configured."""
    with patch("app.services.embeddings._get_openai_client", return_value=None):
        count = await generate_embeddings()
    assert count == 0
```

**Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: FAIL - module not found.

**Step 4: Implement embeddings.py**

Create `backend/app/services/embeddings.py`:

```python
"""OpenAI embedding generation for article titles.

Batches articles that are missing embeddings and updates the
embedding column in PostgreSQL (VECTOR(1536)).
"""
from __future__ import annotations

import logging

from app.config import settings
from app.services.database import get_pool

logger = logging.getLogger("orbis.embeddings")


def _get_openai_client():
    """Return an async OpenAI client, or None if not configured."""
    if not settings.openai_api_key:
        return None
    try:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=settings.openai_api_key)
    except ImportError:
        logger.warning("openai package not installed.")
        return None


async def generate_embeddings() -> int:
    """Generate embeddings for articles that don't have one yet.

    Fetches articles with NULL embedding, batches titles to the
    OpenAI API, and updates the embedding column.

    Returns the number of articles embedded.
    """
    client = _get_openai_client()
    if client is None:
        return 0

    pool = await get_pool()

    # Fetch articles missing embeddings
    rows = await pool.fetch(
        "SELECT id, title FROM articles WHERE embedding IS NULL "
        "ORDER BY ingested_at DESC LIMIT $1",
        settings.embedding_batch_size,
    )

    if not rows:
        return 0

    titles = [row["title"] for row in rows]
    ids = [row["id"] for row in rows]

    try:
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=titles,
        )
    except Exception:
        logger.error("OpenAI embedding call failed.", exc_info=True)
        return 0

    # Build (embedding_vector, article_id) pairs for batch update
    updates = []
    for i, item in enumerate(response.data):
        vec_str = "[" + ",".join(str(v) for v in item.embedding) + "]"
        updates.append((vec_str, ids[i]))

    await pool.executemany(
        "UPDATE articles SET embedding = $1::vector WHERE id = $2",
        updates,
    )

    logger.info("Generated embeddings for %d articles.", len(updates))
    return len(updates)
```

**Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: Both tests pass.

**Step 6: Wire into ingestion pipeline**

In `backend/app/services/ingestion.py`, add import:

```python
from app.services.embeddings import generate_embeddings
```

In `run_ingestion_cycle()`, after `await _purge_old_articles()`, add:

```python
        await generate_embeddings()
```

**Step 7: Run all tests**

Run: `cd backend && python -m pytest -v`
Expected: All pass.

**Step 8: Commit**

```bash
git add backend/app/services/embeddings.py backend/app/config.py backend/app/services/ingestion.py backend/tests/test_embeddings.py
git commit -m "feat(agent): OpenAI embedding generation during ingestion"
```

---

## Task 5: Retrieval Functions

The tools the agent's Haiku planner can invoke: semantic search, graph traversal, keyword search, trending topics, entity lookup.

**Files:**
- Create: `backend/app/services/retrieval.py`
- Test: `backend/tests/test_retrieval.py`

**Step 1: Write failing tests**

Create `backend/tests/test_retrieval.py`:

```python
"""Tests for agent retrieval functions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval import (
    semantic_search,
    graph_traverse,
    keyword_search,
    trending_topics,
    entity_lookup,
)


@pytest.mark.asyncio
async def test_semantic_search_queries_by_embedding():
    """Should embed the query and search articles by vector similarity."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": "uuid-1", "title": "Climate summit", "source_url": "https://x.com/1",
         "latitude": 48.8, "longitude": 2.35, "source_name": "Reuters",
         "published_at": "2026-03-07T12:00:00Z", "sentiment_score": 0.2},
    ])

    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1] * 1536
    mock_response = MagicMock()
    mock_response.data = [mock_embedding]
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with patch("app.services.retrieval.get_pool", return_value=mock_pool):
        with patch("app.services.retrieval._get_openai_client", return_value=mock_client):
            results = await semantic_search("climate change", limit=5)

    assert len(results) == 1
    assert results[0]["title"] == "Climate summit"


@pytest.mark.asyncio
async def test_graph_traverse_returns_connected_nodes():
    """Should find nodes connected to the given entity."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": "n1", "type": "ARTICLE", "name": "Biden meets Zelenskyy",
         "rel_type": "MENTIONED_IN", "depth": 1, "metadata": "{}"},
    ])

    with patch("app.services.retrieval.get_pool", return_value=mock_pool):
        results = await graph_traverse("Joe Biden", depth=2)

    assert len(results) == 1
    assert results[0]["name"] == "Biden meets Zelenskyy"


@pytest.mark.asyncio
async def test_keyword_search_filters_articles():
    """Should return articles matching keyword and filters."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": "uuid-1", "title": "US election updates", "source_url": "https://x.com/2",
         "latitude": 38.9, "longitude": -77.0, "source_name": "AP",
         "published_at": "2026-03-07T10:00:00Z", "sentiment_score": -0.1},
    ])

    with patch("app.services.retrieval.get_pool", return_value=mock_pool):
        results = await keyword_search(terms="election", topic="politics", limit=10)

    assert len(results) == 1


@pytest.mark.asyncio
async def test_trending_topics_returns_counts():
    """Should return topic counts sorted by frequency."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {"topic": "conflict", "count": 42},
        {"topic": "politics", "count": 38},
    ])

    with patch("app.services.retrieval.get_pool", return_value=mock_pool):
        results = await trending_topics()

    assert results[0]["topic"] == "conflict"
    assert results[0]["count"] == 42


@pytest.mark.asyncio
async def test_entity_lookup_finds_node_and_connections():
    """Should fuzzy-match an entity and return direct connections."""
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(side_effect=[
        [{"id": "n1", "type": "PERSON", "name": "Joe Biden", "metadata": "{}"}],
        [{"id": "n2", "type": "ARTICLE", "name": "Biden speech", "rel_type": "MENTIONED_IN", "metadata": "{}"}],
    ])

    with patch("app.services.retrieval.get_pool", return_value=mock_pool):
        result = await entity_lookup("Biden")

    assert result["node"]["name"] == "Joe Biden"
    assert len(result["connections"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_retrieval.py -v`
Expected: FAIL - module not found.

**Step 3: Implement retrieval.py**

Create `backend/app/services/retrieval.py`:

```python
"""Retrieval functions for the news agent.

These are the tools available to the Haiku planner:
- semantic_search: vector similarity on article embeddings
- graph_traverse: recursive CTE on knowledge graph
- keyword_search: SQL filters on articles
- trending_topics: aggregate topic_tag counts
- entity_lookup: fuzzy-match entity + direct connections
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.database import get_pool

logger = logging.getLogger("orbis.retrieval")


def _get_openai_client():
    """Return an async OpenAI client, or None if not configured."""
    if not settings.openai_api_key:
        return None
    try:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=settings.openai_api_key)
    except ImportError:
        return None


async def semantic_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Embed the query and find similar articles by vector cosine distance."""
    client = _get_openai_client()
    if client is None:
        return []

    try:
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=[query],
        )
        query_vec = response.data[0].embedding
    except Exception:
        logger.error("Failed to embed query.", exc_info=True)
        return []

    vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, title, source_url, source_name, latitude, longitude,
               published_at, sentiment_score,
               embedding <=> $1::vector AS distance
        FROM articles
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        vec_str, limit,
    )

    return [dict(r) for r in rows]


async def graph_traverse(
    entity_name: str,
    rel_type: str | None = None,
    depth: int = 2,
) -> list[dict[str, Any]]:
    """Traverse the knowledge graph from an entity node using recursive CTE.

    Finds all nodes reachable within `depth` hops, optionally filtered by
    relationship type.
    """
    pool = await get_pool()
    depth = min(depth, 3)  # Cap at 3 hops

    # First find the starting node by fuzzy match
    start_nodes = await pool.fetch(
        "SELECT id, type, name FROM kg_nodes "
        "WHERE name ILIKE '%' || $1 || '%' LIMIT 1",
        entity_name,
    )
    if not start_nodes:
        return []

    start_id = start_nodes[0]["id"]

    rel_filter = "AND e.rel_type = $3" if rel_type else ""
    params: list = [start_id, depth]
    if rel_type:
        params.append(rel_type)

    rows = await pool.fetch(
        f"""
        WITH RECURSIVE graph AS (
            SELECT n.id, n.type, n.name, n.metadata, CAST(NULL AS TEXT) AS rel_type, 0 AS depth
            FROM kg_nodes n WHERE n.id = $1

            UNION ALL

            SELECT n.id, n.type, n.name, n.metadata, e.rel_type, g.depth + 1
            FROM graph g
            JOIN kg_edges e ON e.source_node_id = g.id OR e.target_node_id = g.id
            JOIN kg_nodes n ON n.id = CASE
                WHEN e.source_node_id = g.id THEN e.target_node_id
                ELSE e.source_node_id
            END
            WHERE g.depth < $2 {rel_filter}
        )
        SELECT DISTINCT id, type, name, rel_type, depth, metadata::text
        FROM graph
        WHERE depth > 0
        ORDER BY depth, type
        LIMIT 50
        """,
        *params,
    )

    return [dict(r) for r in rows]


async def keyword_search(
    terms: str | None = None,
    topic: str | None = None,
    country: str | None = None,
    time_range: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search articles using SQL filters on title, topic, country, and time."""
    pool = await get_pool()

    conditions = []
    params: list = []
    idx = 1

    if terms:
        conditions.append(f"title ILIKE '%' || ${idx} || '%'")
        params.append(terms)
        idx += 1

    if topic:
        conditions.append(f"${idx} = ANY(topic_tags)")
        params.append(topic)
        idx += 1

    if country:
        conditions.append(f"country_code = ${idx}")
        params.append(country)
        idx += 1

    if time_range:
        conditions.append(f"published_at > NOW() - ${idx}::interval")
        params.append(time_range)
        idx += 1

    where = " AND ".join(conditions) if conditions else "TRUE"
    params.append(limit)

    rows = await pool.fetch(
        f"""
        SELECT id, title, source_url, source_name, latitude, longitude,
               published_at, sentiment_score
        FROM articles
        WHERE {where}
        ORDER BY published_at DESC
        LIMIT ${idx}
        """,
        *params,
    )

    return [dict(r) for r in rows]


async def trending_topics(hours: int = 24) -> list[dict[str, Any]]:
    """Return topic counts over the recent time window."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT UNNEST(topic_tags) AS topic, COUNT(*) AS count
        FROM articles
        WHERE published_at > NOW() - make_interval(hours => $1)
        GROUP BY topic
        ORDER BY count DESC
        LIMIT 20
        """,
        hours,
    )
    return [dict(r) for r in rows]


async def entity_lookup(name: str) -> dict[str, Any]:
    """Fuzzy-match an entity by name and return its direct connections."""
    pool = await get_pool()

    # Find best matching node using trigram similarity
    nodes = await pool.fetch(
        """
        SELECT id, type, name, metadata::text
        FROM kg_nodes
        WHERE name ILIKE '%' || $1 || '%'
        ORDER BY similarity(name, $1) DESC
        LIMIT 1
        """,
        name,
    )

    if not nodes:
        return {"node": None, "connections": []}

    node = dict(nodes[0])

    # Get direct connections
    connections = await pool.fetch(
        """
        SELECT n.id, n.type, n.name, e.rel_type, n.metadata::text
        FROM kg_edges e
        JOIN kg_nodes n ON n.id = CASE
            WHEN e.source_node_id = $1 THEN e.target_node_id
            ELSE e.source_node_id
        END
        WHERE e.source_node_id = $1 OR e.target_node_id = $1
        ORDER BY e.weight DESC
        LIMIT 20
        """,
        node["id"],
    )

    return {"node": node, "connections": [dict(r) for r in connections]}
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_retrieval.py -v`
Expected: All 5 tests pass.

**Step 5: Commit**

```bash
git add backend/app/services/retrieval.py backend/tests/test_retrieval.py
git commit -m "feat(agent): retrieval functions for semantic, graph, and keyword search"
```

---

## Task 6: Agent Pipeline + SSE Endpoint

**Files:**
- Create: `backend/app/services/agent.py`
- Create: `backend/app/routers/agent.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_agent.py`

**Step 1: Add Sonnet config**

In `backend/app/config.py`, add to Settings:

```python
    sonnet_model_id: str = field(
        default_factory=lambda: _env("SONNET_MODEL_ID", "claude-sonnet-4-5-20241022")
    )
    agent_max_retrieval_results: int = 20
    agent_conversation_ttl: int = 3600  # 1 hour
```

**Step 2: Write failing tests**

Create `backend/tests/test_agent.py`:

```python
"""Tests for the agent pipeline."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent import plan_retrieval, synthesize_answer, RETRIEVAL_TOOLS


@pytest.mark.asyncio
async def test_plan_retrieval_returns_tool_calls():
    """Haiku should return a list of retrieval tool calls."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(
        type="text",
        text=json.dumps({
            "tools": [
                {"name": "keyword_search", "args": {"terms": "earthquake", "limit": 10}},
                {"name": "trending_topics", "args": {}},
            ]
        }),
    )]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        tools = await plan_retrieval("What earthquakes happened this week?", [])

    assert len(tools) == 2
    assert tools[0]["name"] == "keyword_search"


@pytest.mark.asyncio
async def test_synthesize_answer_returns_structured_response():
    """Sonnet should return answer + citations + globe_actions."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(
        type="text",
        text=json.dumps({
            "answer": "A 6.2 earthquake struck Turkey.",
            "citations": [
                {"title": "Earthquake hits Turkey", "url": "https://x.com/1",
                 "source_name": "Reuters", "lat": 39.9, "lng": 32.8}
            ],
            "globe_actions": [
                {"type": "flyTo", "lat": 39.9, "lng": 32.8, "zoom": 4.0}
            ],
        }),
    )]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    context = [{"title": "Earthquake hits Turkey", "source_url": "https://x.com/1",
                "latitude": 39.9, "longitude": 32.8, "source_name": "Reuters"}]

    with patch("app.services.agent._get_anthropic_client", return_value=mock_client):
        result = await synthesize_answer("What earthquakes?", context, [])

    assert "earthquake" in result["answer"].lower()
    assert len(result["citations"]) == 1
    assert result["globe_actions"][0]["type"] == "flyTo"


def test_retrieval_tools_schema():
    """Tool schema should list all available retrieval functions."""
    tool_names = [t["name"] for t in RETRIEVAL_TOOLS]
    assert "semantic_search" in tool_names
    assert "graph_traverse" in tool_names
    assert "keyword_search" in tool_names
    assert "trending_topics" in tool_names
    assert "entity_lookup" in tool_names
```

**Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent.py -v`
Expected: FAIL - module not found.

**Step 4: Implement agent.py**

Create `backend/app/services/agent.py`:

```python
"""Two-step agent pipeline: Haiku planner + Sonnet synthesizer.

Step 1 (Haiku): Receives user question, returns a plan of retrieval
tool calls to run.

Step 2 (Sonnet): Receives question + retrieved context, returns a
structured answer with citations and globe actions.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import anthropic

from app.config import settings
from app.services.retrieval import (
    semantic_search,
    graph_traverse,
    keyword_search,
    trending_topics,
    entity_lookup,
)

logger = logging.getLogger("orbis.agent")

RETRIEVAL_TOOLS = [
    {
        "name": "semantic_search",
        "description": "Search articles by meaning/concept using vector similarity. Best for open-ended questions.",
        "parameters": {"query": "str - the search query", "limit": "int - max results (default 10)"},
    },
    {
        "name": "graph_traverse",
        "description": "Traverse the knowledge graph from an entity to find connected people, orgs, articles, locations, and topics.",
        "parameters": {"entity_name": "str", "rel_type": "str|null - MENTIONED_IN, LOCATED_AT, ABOUT_TOPIC, CO_MENTIONED", "depth": "int - max hops 1-3"},
    },
    {
        "name": "keyword_search",
        "description": "Search articles by keyword, topic, country, or time range.",
        "parameters": {"terms": "str|null", "topic": "str|null", "country": "str|null - 2-letter code", "time_range": "str|null - e.g. '24 hours', '3 days'", "limit": "int"},
    },
    {
        "name": "trending_topics",
        "description": "Get the most common news topics in the last N hours.",
        "parameters": {"hours": "int - default 24"},
    },
    {
        "name": "entity_lookup",
        "description": "Find an entity (person, org, location) by name and show its knowledge graph connections.",
        "parameters": {"name": "str - entity name or partial match"},
    },
]

_TOOL_DISPATCH = {
    "semantic_search": semantic_search,
    "graph_traverse": graph_traverse,
    "keyword_search": keyword_search,
    "trending_topics": trending_topics,
    "entity_lookup": entity_lookup,
}

_PLANNER_SYSTEM = """You are a retrieval planner for a news agent. Given the user's question and conversation history, decide which retrieval tools to call to gather relevant information.

Available tools:
{tools}

Return a JSON object with a "tools" array. Each element has "name" (tool name) and "args" (dict of arguments).
Choose 1-3 tools. Prefer combining semantic_search with graph_traverse for entity-related questions.
For trending/overview questions, use trending_topics.
For specific locations or topics, use keyword_search.

Return ONLY valid JSON, no explanation."""

_SYNTHESIZER_SYSTEM = """You are the Orbis news agent. You answer questions about recent world news using the retrieved context below.

Rules:
- Ground every claim in the retrieved articles. Do not fabricate information.
- Use [N] citation markers (1-indexed) referencing the citations array.
- Keep answers concise (2-4 paragraphs max).
- When mentioning locations, include them in globe_actions so the user's 3D globe can visualize them.
- For comparative questions, structure the answer with clear sections.

Return a JSON object with:
- "answer": markdown string with [N] citation markers
- "citations": array of {{title, url, source_name, lat, lng}} for each referenced article
- "globe_actions": array of {{type: "flyTo"|"highlight", lat, lng, zoom?}} for relevant locations

Return ONLY valid JSON."""


def _get_anthropic_client():
    """Return an async Anthropic client."""
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def plan_retrieval(
    question: str,
    conversation_history: list[dict],
) -> list[dict[str, Any]]:
    """Use Haiku to plan which retrieval tools to call."""
    client = _get_anthropic_client()

    tools_desc = json.dumps(RETRIEVAL_TOOLS, indent=2)
    system = _PLANNER_SYSTEM.format(tools=tools_desc)

    messages = list(conversation_history) + [{"role": "user", "content": question}]

    response = await client.messages.create(
        model=settings.haiku_model_id,
        max_tokens=512,
        system=system,
        messages=messages,
    )

    text = response.content[0].text if response.content else "{}"
    try:
        plan = json.loads(text)
        return plan.get("tools", [])
    except json.JSONDecodeError:
        logger.error("Haiku returned invalid JSON: %s", text)
        return [{"name": "keyword_search", "args": {"terms": question, "limit": 10}}]


async def execute_retrieval(tool_calls: list[dict]) -> list[dict[str, Any]]:
    """Run the planned retrieval tool calls in parallel."""

    async def _run_tool(call: dict) -> dict:
        name = call.get("name", "")
        args = call.get("args", {})
        func = _TOOL_DISPATCH.get(name)
        if func is None:
            return {"tool": name, "error": "unknown tool"}
        try:
            result = await func(**args)
            return {"tool": name, "result": result}
        except Exception as e:
            logger.error("Retrieval tool %s failed: %s", name, e)
            return {"tool": name, "error": str(e)}

    results = await asyncio.gather(*[_run_tool(c) for c in tool_calls])
    return list(results)


def _build_context(retrieval_results: list[dict], max_articles: int = 20) -> list[dict]:
    """Flatten retrieval results into a deduplicated article list for the synthesizer."""
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for result in retrieval_results:
        items = result.get("result", [])
        if isinstance(items, dict):
            items = items.get("connections", [])
        if not isinstance(items, list):
            continue
        for item in items:
            url = item.get("source_url") or item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                articles.append(item)
            if len(articles) >= max_articles:
                break

    return articles


async def synthesize_answer(
    question: str,
    context: list[dict],
    conversation_history: list[dict],
) -> dict[str, Any]:
    """Use Sonnet to synthesize an answer from retrieved context."""
    client = _get_anthropic_client()

    context_lines = []
    for i, article in enumerate(context, 1):
        title = article.get("title") or article.get("name", "Unknown")
        source = article.get("source_name", "")
        url = article.get("source_url") or article.get("url", "")
        lat = article.get("latitude") or article.get("lat", "")
        lng = article.get("longitude") or article.get("lng", "")
        context_lines.append(f"[{i}] {title} -- {source} ({lat}, {lng}) {url}")

    context_text = "\n".join(context_lines) if context_lines else "No articles found."

    messages = list(conversation_history) + [
        {"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {question}"}
    ]

    response = await client.messages.create(
        model=settings.sonnet_model_id,
        max_tokens=1024,
        system=_SYNTHESIZER_SYSTEM,
        messages=messages,
    )

    text = response.content[0].text if response.content else "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Sonnet returned invalid JSON: %s", text)
        return {"answer": text, "citations": [], "globe_actions": []}


async def ask(question: str, conversation_history: list[dict]) -> dict[str, Any]:
    """Full agent pipeline: plan -> retrieve -> synthesize."""
    tool_calls = await plan_retrieval(question, conversation_history)
    logger.info("Agent plan: %s", [t.get("name") for t in tool_calls])

    retrieval_results = await execute_retrieval(tool_calls)
    context = _build_context(retrieval_results, settings.agent_max_retrieval_results)
    result = await synthesize_answer(question, context, conversation_history)
    result["tools_used"] = [t.get("name") for t in tool_calls]

    return result
```

**Step 5: Run agent tests**

Run: `cd backend && python -m pytest tests/test_agent.py -v`
Expected: All 3 tests pass.

**Step 6: Create SSE endpoint**

Create `backend/app/routers/agent.py`:

```python
"""Agent chat endpoint with SSE streaming."""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.services.agent import plan_retrieval, execute_retrieval, _build_context, synthesize_answer
from app.services.cache import get_redis

logger = logging.getLogger("orbis.agent.router")

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None


async def _get_conversation(conversation_id: str) -> list[dict]:
    """Load conversation history from Redis."""
    r = await get_redis()
    if not r:
        return []
    raw = await r.get(f"agent:conv:{conversation_id}")
    if not raw:
        return []
    return json.loads(raw)


async def _save_conversation(conversation_id: str, history: list[dict]) -> None:
    """Save conversation history to Redis (last 5 exchanges = 10 messages)."""
    r = await get_redis()
    if not r:
        return
    trimmed = history[-10:]
    await r.set(
        f"agent:conv:{conversation_id}",
        json.dumps(trimmed),
        ex=settings.agent_conversation_ttl,
    )


@router.post("/ask")
async def ask_agent(req: AskRequest):
    """Agent endpoint that returns the full response (non-streaming)."""
    from app.services.agent import ask

    conversation_id = req.conversation_id or str(uuid.uuid4())
    history = await _get_conversation(conversation_id)

    result = await ask(req.question, history)

    history.append({"role": "user", "content": req.question})
    history.append({"role": "assistant", "content": result.get("answer", "")})
    await _save_conversation(conversation_id, history)

    return {"conversation_id": conversation_id, **result}


@router.post("/ask/stream")
async def ask_agent_stream(req: AskRequest):
    """SSE streaming agent endpoint.

    Events:
    - planning: {tools: [...]}
    - retrieving: {tool: "name"}
    - token: {text: "..."}
    - done: {citations: [...], globe_actions: [...]}
    """
    conversation_id = req.conversation_id or str(uuid.uuid4())

    async def event_generator():
        history = await _get_conversation(conversation_id)

        # Step 1: Plan
        tool_calls = await plan_retrieval(req.question, history)
        yield {
            "event": "planning",
            "data": json.dumps({"tools": [t.get("name") for t in tool_calls]}),
        }

        # Step 2: Retrieve
        for call in tool_calls:
            yield {
                "event": "retrieving",
                "data": json.dumps({"tool": call.get("name", "")}),
            }

        retrieval_results = await execute_retrieval(tool_calls)
        context = _build_context(retrieval_results, settings.agent_max_retrieval_results)

        # Step 3: Synthesize
        result = await synthesize_answer(req.question, context, history)

        # Stream the answer text in chunks
        answer = result.get("answer", "")
        chunk_size = 20
        for i in range(0, len(answer), chunk_size):
            yield {
                "event": "token",
                "data": json.dumps({"text": answer[i:i + chunk_size]}),
            }

        # Final event with structured data
        yield {
            "event": "done",
            "data": json.dumps({
                "conversation_id": conversation_id,
                "citations": result.get("citations", []),
                "globe_actions": result.get("globe_actions", []),
                "tools_used": [t.get("name") for t in tool_calls],
            }),
        }

        # Save conversation
        history.append({"role": "user", "content": req.question})
        history.append({"role": "assistant", "content": answer})
        await _save_conversation(conversation_id, history)

    return EventSourceResponse(event_generator())
```

**Step 7: Install sse-starlette dependency**

Run: `cd backend && pip install sse-starlette`

Add `sse-starlette>=1.6.0` to `backend/requirements.txt`.

**Step 8: Register router in main.py**

In `backend/app/main.py`, add import:

```python
from app.routers.agent import router as agent_router
```

After `app.include_router(news_router)`, add:

```python
app.include_router(agent_router)
```

**Step 9: Run all tests**

Run: `cd backend && python -m pytest -v`
Expected: All pass.

**Step 10: Commit**

```bash
git add backend/app/services/agent.py backend/app/routers/agent.py backend/app/config.py backend/app/main.py backend/tests/test_agent.py backend/requirements.txt
git commit -m "feat(agent): two-step agent pipeline with SSE streaming endpoint"
```

---

## Task 7: Frontend Chat Panel

**Files:**
- Create: `frontend/src/components/AgentPanel.tsx`
- Create: `frontend/src/components/AgentMessage.tsx`
- Create: `frontend/src/hooks/useAgent.ts`
- Modify: `frontend/src/app/page.tsx`

**Step 1: Create the useAgent hook**

Create `frontend/src/hooks/useAgent.ts`. This manages SSE connection, message state, and conversation ID.

Key exports:
- `useAgent({ onGlobeAction })` hook
- Types: `Citation`, `GlobeAction`, `AgentMessage`
- Returns: `{ messages, isLoading, activeTools, ask, stop, clear }`

The hook should:
- POST to `/api/agent/ask/stream` with fetch + ReadableStream
- Parse SSE events: `planning`, `retrieving`, `token`, `done`
- Accumulate token text into the current assistant message
- On `done`, attach citations and globe_actions, call onGlobeAction callback
- Support abort via AbortController
- Generate `conversation_id` via `crypto.randomUUID()` on first use

**Step 2: Create AgentMessage component**

Create `frontend/src/components/AgentMessage.tsx`. Renders a single chat message.

- User messages: right-aligned, blue tinted background
- Assistant messages: left-aligned, card surface background with subtle border
- Renders `message.content` as whitespace-preserving text
- If `message.citations` exist, renders clickable citation chips below the text
  - Each chip shows `[N] Title -- Source`
  - Clicking calls `onCitationClick(citation)`
- If `message.status === "streaming"`, shows a blinking cursor
- Uses Framer Motion fade-in animation matching existing pattern: `ease: [0.23, 1, 0.32, 1]`

**Step 3: Create AgentPanel component**

Create `frontend/src/components/AgentPanel.tsx`. The left slide-out chat panel.

Layout:
- `fixed left-0 top-0 z-50 h-full max-w-md` with `border-r`
- Slides from left: `initial={{ x: "-100%" }}` / `animate={{ x: 0 }}`
- Spring transition matching NewsPanel: `damping: 28, stiffness: 300`
- Frosted glass: `bg-[var(--surface-panel)] backdrop-blur-xl`

Sections (top to bottom):
1. **Header**: blue pulse dot + "Orbis Agent" + clear button + close button
2. **Messages area**: scrollable, auto-scroll on new messages. Empty state shows welcome text.
3. **Active tools indicator**: animated pills showing which retrieval tools are running
4. **Input form**: text input + Ask/Stop button. Submit on Enter.

**Step 4: Wire into page.tsx**

In `frontend/src/app/page.tsx`:

Add imports for `AgentPanel`, `useAgent`, `GlobeAction`, `Citation`.

Add state: `const [agentOpen, setAgentOpen] = useState(false)`

Add hook: `const { messages, isLoading, activeTools, ask, stop, clear } = useAgent({ onGlobeAction: handleGlobeAction })`

Add `handleGlobeAction` callback (integration point for Task 8).

Add `handleCitationClick` that calls `handleGlobeAction` with flyTo.

Add JSX:
- Toggle button: `fixed bottom-3 left-3 z-40` sparkle icon button
- `<AnimatePresence>` wrapping `<AgentPanel>` when `agentOpen` is true

**Step 5: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds without type errors.

**Step 6: Commit**

```bash
git add frontend/src/components/AgentPanel.tsx frontend/src/components/AgentMessage.tsx frontend/src/hooks/useAgent.ts frontend/src/app/page.tsx
git commit -m "feat(agent): frontend chat panel with SSE streaming and globe actions"
```

---

## Task 8: Globe Action Integration

Wire the agent's globe_actions to the actual globe.gl camera.

**Files:**
- Modify: `frontend/src/components/Globe.tsx`
- Modify: `frontend/src/app/page.tsx`

**Step 1: Expose globe camera controls**

In `frontend/src/components/Globe.tsx`, add an `onReady` prop that passes camera control functions back to the parent:

```typescript
interface GlobeProps {
  // ... existing props ...
  onReady?: (controls: { flyTo: (lat: number, lng: number, altitude: number) => void }) => void;
}
```

After the globe instance is initialized, call `onReady` with a `flyTo` function that wraps `globeRef.current.pointOfView({ lat, lng, altitude }, 1500)`.

**Step 2: Connect in page.tsx**

Add a ref: `const globeControlsRef = useRef<...>(null)`

Update `handleGlobeAction`:
```typescript
const handleGlobeAction = useCallback((action: GlobeAction) => {
  if (!globeControlsRef.current) return;
  const altitude = action.zoom ? 300 / action.zoom : 2.0;
  globeControlsRef.current.flyTo(action.lat, action.lng, altitude);
}, []);
```

Pass `onReady` to Globe component to capture the ref.

**Step 3: Run build**

Run: `cd frontend && npm run build`
Expected: Builds successfully.

**Step 4: Commit**

```bash
git add frontend/src/components/Globe.tsx frontend/src/app/page.tsx
git commit -m "feat(agent): wire globe flyTo actions from agent responses"
```

---

## Summary

| Task | Description | New Files | Modified Files |
|------|-------------|-----------|----------------|
| 1 | DB migration: KG tables + embedding index | `006_knowledge_graph.sql` | -- |
| 2 | Entity extraction from GKG | -- | `gdelt.py`, `test_gdelt.py` |
| 3 | Knowledge graph service | `knowledge_graph.py`, `test_knowledge_graph.py` | `ingestion.py` |
| 4 | Embedding service | `embeddings.py`, `test_embeddings.py` | `ingestion.py`, `config.py` |
| 5 | Retrieval functions | `retrieval.py`, `test_retrieval.py` | -- |
| 6 | Agent pipeline + SSE endpoint | `agent.py`, `agent router`, `test_agent.py` | `config.py`, `main.py`, `requirements.txt` |
| 7 | Frontend chat panel | `AgentPanel.tsx`, `AgentMessage.tsx`, `useAgent.ts` | `page.tsx` |
| 8 | Globe action integration | -- | `Globe.tsx`, `page.tsx` |
