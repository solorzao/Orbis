# Soft Orbit Redesign and Feature Foundations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the Orbis frontend in the Soft Orbit design language and add the "connections" features (hover previews, arcs, story threads, co-pilot, board), on top of data and API foundations that make those features accurate and cheap.

**Architecture:** Work lands as small PRs to `main`, each green in CI before hand-off. Phase 1 fixes data and API foundations in the FastAPI backend (no visual change). Phase 2 moves the Next.js frontend onto the Soft Orbit tokens and shell. Phases 3 to 5 add features, each backend endpoint paired with its Soft Orbit surface.

**Tech Stack:** FastAPI + asyncpg + PostgreSQL (PostGIS, pgvector, pg_trgm) on Azure; GDELT GKG ingestion every 15 minutes; Claude Haiku 5.5 (`claude-haiku-5-5`); OpenAI `text-embedding-3-small`; Upstash Redis; Next.js 16 + React 19 + Tailwind v4 + globe.gl on Vercel.

**Reference material (read before starting):**
- Feature report: `docs/redesign/features/feature-exploration.md` (data audit, feature specs F1 to F5, Q1 to Q4, D1 to D8, cost model).
- Chosen UI direction: `docs/redesign/ui/soft-orbit/` (`mockup.html`, `tokens.md`, `tokens.json`).
- Design system (published): https://claude.ai/artifact/MZ88T7Yogx1w4RsaiqgymQ (Orbis Soft Orbit: tokens, brand book, 10 component previews).
- Owner decisions (2026-10-10): Haiku 5.5 (done, PR #41); show publisher images, blur conflict images; add the GDELT Events feed; keep history short with a bias towards recent events (no long-term narratives); motto contrast fix (PR #42); half-precision embedding index and storing more GKG fields, including GDELT page titles (2026-10-11).

**Working rules for every PR:**
- Branch from `origin/main`; one PR per numbered item; run the checks below locally; open the PR; wait for every check to finish green before handing it over.
- Backend checks: `cd backend && python -m pytest tests -q && python -m ruff check app tests && python -m ruff format --check app tests`. (Three ruff errors in `tests/test_agent.py` and `tests/test_knowledge_graph.py` already exist on `main`; don't add new ones.)
- Frontend checks: `cd frontend && npm run lint && npm run format:check && npm run test && npm run build`. On Windows, `format:check` reports every file because of CRLF checkouts; check changed files with `npx prettier --check --end-of-line auto <files>`.
- Never deploy by hand: merging to `main` deploys (Vercel for the frontend, the `Deploy` workflow for the backend, function and migrations).
- New migrations must be safe to run while the old backend is still serving (the workflow runs migrations and the backend deploy in parallel).

---

## Roadmap

| PR | Phase | What | Depends on |
|---|---|---|---|
| 1 | 1 Foundations | Agent globe actions actually fly the globe | none |
| 2 | 1 | Embed every new article each cycle | none |
| 2b | 1 | Half-precision embedding index | 2 |
| 3 | 1 | Expose article images (https only) in the API | none |
| 4a | 1 | Migration: `articles.country_fips` column | none |
| 4b | 1 | Store ISO country codes; backfill old rows | 4a merged and deployed |
| 5 | 1 | Daily LLM spend cap | none |
| 6 | 1 | Fix summary grid mismatch and cluster time filtering | none |
| 7a | 1 | Migration: GKG field columns | 4b |
| 7b | 1 | Knowledge graph: co-mentions on demand | none |
| 7c | 1 | Store GKG fields and take titles from GDELT | 7a deployed, 7b |
| 8 | 2 UI foundation | Soft Orbit tokens and fonts in the frontend | none |
| 9 | 2 | Soft Orbit shell: sky, glass panels, layout, pills | 8 |
| 9b | 2 | Side panel (co-pilot and stories tabs), narrow-screen sheet | 9 |
| 10 | 2 | Timeline capsule and layer switcher | 9b |
| 11 | 2 | Co-pilot console restyle with action pills | 1, 9 |
| 12 | 3 Quick wins | City hover card (image, headline, topic mix, tone, sparkline) | 3, 9 |
| 13a | 3 | Migration: `articles.mentioned_countries` | none |
| 13b | 3 | Co-coverage links API (country pairs, lift, detail, explain) | 13a deployed |
| 13c | 3 | Links layer and link inspector | 13b, 9b |
| 14 | 3 | Surge alerts ticker and "since your last visit" strip | 9 |
| 15 | 4 Flagships | Story threads backend (embedding clusters, synopses) | 2, 5, 7c |
| 16 | 4 | Threads panel with spread replay and aurora arcs | 13, 15 |
| 17 | 4 | Entity tracker | 7c, 9 |
| 18 | 4 | Investigation board (split view, pins mirrored on the globe) | 12, 13 |
| 19 | 5 Events | GDELT Events ingestion: daily country-pair rollups | 4b |
| 20 | 5 | Relation arcs layer (cooperation and conflict) | 13, 19 |

Phase 1 is detailed below and done (through #58). Phase 2's bite-sized plan is `docs/plans/2026-10-11-soft-orbit-phase-2.md` (done through #64), and Phase 3's is `docs/plans/2026-10-12-soft-orbit-phase-3.md`. Phases 4 and 5 are scoped here and get their bite-sized plans when the phase before them is done, so they build on what actually shipped.

---

## Phase 1: Foundations (detailed)

### Task 1 (PR 1): Agent globe actions actually fly the globe

**Why:** The synthesis prompt asks the model for `{"lat", "lng", "label"}` (`backend/app/services/agent.py:207`), but the frontend only acts on `action.type === "flyTo"` (`frontend/src/app/page.tsx:80`). Nothing adds `type`, so no globe action has ever fired. Fix it at the source: the backend validates and normalises every action.

**Files:**
- Modify: `backend/app/services/agent.py` (add `_normalize_globe_actions`; use it where `globe_actions` is returned, around lines 640 to 650)
- Test: `backend/tests/test_agent.py`

**Step 1: Write the failing tests** (append to `backend/tests/test_agent.py`)

```python
from app.services.agent import _normalize_globe_actions


def test_normalize_globe_actions_adds_fly_to_type():
    raw = [{"lat": 6.45, "lng": 3.39, "label": "Lagos"}]
    assert _normalize_globe_actions(raw) == [
        {"type": "flyTo", "lat": 6.45, "lng": 3.39, "label": "Lagos"}
    ]


def test_normalize_globe_actions_drops_invalid_and_caps_at_three():
    raw = [
        {"lat": 95, "lng": 0},  # latitude out of range
        {"lat": "x", "lng": 1},  # not a number
        "Lagos",  # not an object
        {"lat": 1, "lng": 1},
        {"lat": 2, "lng": 2},
        {"lat": 3, "lng": 3},
        {"lat": 4, "lng": 4},
    ]
    result = _normalize_globe_actions(raw)
    assert [a["lat"] for a in result] == [1, 2, 3]
    assert all(a["type"] == "flyTo" and a["label"] == "" for a in result)


def test_normalize_globe_actions_handles_non_list():
    assert _normalize_globe_actions(None) == []
    assert _normalize_globe_actions({"lat": 1}) == []
```

Also change the existing `test_synthesize_answer_returns_structured_response` assertion to expect the normalised shape: `assert result["globe_actions"][0] == {"type": "flyTo", "lat": 38.0, "lng": 34.0, "label": "Turkey"}`.

**Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent.py -q`
Expected: FAIL with `ImportError: cannot import name '_normalize_globe_actions'`

**Step 3: Implement** (in `backend/app/services/agent.py`, above `synthesize_answer`)

```python
_MAX_GLOBE_ACTIONS = 3


def _normalize_globe_actions(raw: object) -> list[dict]:
    """Validate model-proposed globe actions and give them the frontend's shape.

    The model returns ``{"lat", "lng", "label"}``; the frontend acts on
    ``{"type": "flyTo", ...}``. Anything malformed or out of range is dropped.
    """
    if not isinstance(raw, list):
        return []
    actions: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        lat, lng = item.get("lat"), item.get("lng")
        if isinstance(lat, bool) or isinstance(lng, bool):
            continue
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        label = item.get("label")
        actions.append(
            {"type": "flyTo", "lat": lat, "lng": lng, "label": label if isinstance(label, str) else ""}
        )
        if len(actions) == _MAX_GLOBE_ACTIONS:
            break
    return actions
```

Then in `synthesize_answer`, replace `"globe_actions": parsed.get("globe_actions", []),` with `"globe_actions": _normalize_globe_actions(parsed.get("globe_actions")),`.

**Step 4: Run to verify they pass**

Run: `cd backend && python -m pytest tests -q`
Expected: all pass.

**Step 5: Commit**

```bash
git add backend/app/services/agent.py backend/tests/test_agent.py
git commit -m "fix(agent): normalise globe actions so the globe actually flies to them"
```

**Manual check after deploy:** ask the co-pilot "What's happening in Lagos?" on orbisapp.co; the globe should fly to Lagos when the answer completes.

---

### Task 2 (PR 2): Embed every new article each cycle

**Why:** `generate_embeddings` embeds at most `embedding_batch_size` (100) articles per 15-minute cycle against roughly 600 new ones, so most articles never get a vector. Story threads and related-story links need full coverage. Cost at full coverage is well under $2 a month.

**Files:**
- Modify: `backend/app/config.py` (add `embedding_max_per_cycle`)
- Modify: `backend/app/services/embeddings.py` (loop over batches)
- Test: `backend/tests/test_embeddings.py`

**Step 1: Write the failing test** (add to `TestGenerateEmbeddings`)

```python
    @pytest.mark.asyncio
    async def test_generate_embeddings_loops_until_backlog_is_empty(self):
        from app.services.embeddings import generate_embeddings

        batch = [{"id": uuid.uuid4(), "title": f"Headline {i}"} for i in range(2)]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(side_effect=[batch, batch, []])
        mock_pool.executemany = AsyncMock()
        emb = MagicMock()
        emb.embedding = _fake_embedding()
        response = MagicMock()
        response.data = [emb, emb]
        client = AsyncMock()
        client.embeddings.create = AsyncMock(return_value=response)

        with (
            patch("app.services.embeddings._get_openai_client", return_value=client),
            patch("app.services.embeddings.get_pool", new_callable=AsyncMock, return_value=mock_pool),
        ):
            count = await generate_embeddings()

        assert count == 4
        assert client.embeddings.create.await_count == 2
```

In the existing `test_generate_embeddings_calls_openai`, change `mock_pool.fetch = AsyncMock(return_value=db_rows)` to `AsyncMock(side_effect=[db_rows, []])` so the loop ends.

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_embeddings.py -q`
Expected: the new test FAILS (`count == 2`, one call).

**Step 3: Implement**

In `backend/app/config.py`, under `embedding_batch_size`:

```python
    embedding_max_per_cycle: int = field(
        default_factory=lambda: _env_int("EMBEDDING_MAX_PER_CYCLE", 2000)
    )
```

In `backend/app/services/embeddings.py`, replace the body of `generate_embeddings` after `client` is obtained:

```python
    total = 0
    try:
        pool = await get_pool()
        while total < settings.embedding_max_per_cycle:
            rows = await pool.fetch(
                "SELECT id, title FROM articles "
                "WHERE embedding IS NULL "
                "ORDER BY ingested_at DESC "
                "LIMIT $1",
                settings.embedding_batch_size,
            )
            if not rows:
                break
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=[r["title"] for r in rows],
            )
            updates: list[tuple[str, Any]] = [
                ("[" + ",".join(str(v) for v in emb.embedding) + "]", row["id"])
                for row, emb in zip(rows, response.data)
            ]
            await pool.executemany(
                "UPDATE articles SET embedding = $1::vector WHERE id = $2",
                updates,
            )
            total += len(updates)
        if total:
            logger.info("Generated embeddings for %d articles.", total)
        return total
    except Exception:
        logger.error("Embedding generation failed after %d articles.", total, exc_info=True)
        return total
```

**Step 4: Run to verify**

Run: `cd backend && python -m pytest tests -q`
Expected: all pass.

**Step 5: Commit**

```bash
git add backend/app/config.py backend/app/services/embeddings.py backend/tests/test_embeddings.py
git commit -m "feat(embeddings): embed the whole backlog each cycle, capped per cycle"
```

**Manual check after deploy:** in the logs, the first cycle after deploy shows "Generated embeddings for N articles." with N above 100.

---

### Task 2b (PR 2b): Half-precision embedding index (owner-approved 2026-10-11)

Shrink the HNSW index by half. The `embedding` column stays `VECTOR(1536)`, so there is no table rewrite and no re-embedding. Only the index and the similarity query use `halfvec`.

**Files:**
- Create: `database/migrations/008_halfvec_embedding_index.sql`
- Modify: `backend/app/services/retrieval.py` (`semantic_search`)
- Test: `backend/tests/test_retrieval.py`

**Migration:**
```sql
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
```

**Query:** in `semantic_search`, use `embedding::halfvec(1536) <=> $1::halfvec(1536)` for both the `distance` column and the `ORDER BY`. The expression must match the index expression exactly, or the planner falls back to a sequential scan.

**Tests:**
- The SQL sent by `semantic_search` orders by `embedding::halfvec(1536) <=> $1::halfvec(1536)`.
- A cross-file check: the migration's index expression `(embedding::halfvec(1536)) halfvec_cosine_ops` and the query's `embedding::halfvec(1536) <=>` use the same cast, so a later edit can't silently desync them.

**Deploy safety:** migrations and the backend deploy run in parallel. The old code's `embedding <=> $1::vector` and the new code before the index exists both still work, as a sequential scan over at most a few tens of thousands of rows.

**Verify after deploy:** `EXPLAIN` the new query on production and expect `Index Scan using idx_articles_embedding_half`. Compare `pg_relation_size` against the old 96 MB index.

---

### Task 3 (PR 3): Expose article images (https only)

**Why:** Ingestion stores GDELT's sharing image in `articles.image_url`, and `database.py` already selects it, but `NewsArticle` has no field for it, so the API drops it. Some URLs are `http://`, which browsers block on orbisapp.co: upgrade those to `https://` and let the frontend fall back to the topic glyph if an image fails to load.

**Files:**
- Modify: `backend/app/models/news.py` (`NewsArticle.image_url`)
- Modify: `backend/app/routers/news.py` (`_row_to_article`)
- Modify: `frontend/src/lib/api.ts` (`ApiNewsArticle.image_url`)
- Test: `backend/tests/test_news_router.py`

**Step 1: Write the failing tests** (append to `backend/tests/test_news_router.py`)

```python
from app.routers.news import _https_image, _row_to_article


def test_https_image_upgrades_http_and_rejects_other_schemes():
    assert _https_image("http://cdn.example.com/a.jpg") == "https://cdn.example.com/a.jpg"
    assert _https_image("https://cdn.example.com/a.jpg") == "https://cdn.example.com/a.jpg"
    assert _https_image("javascript:alert(1)") is None
    assert _https_image("") is None
    assert _https_image(None) is None


def test_row_to_article_includes_image_url():
    row = {
        "id": "1", "title": "t", "source_url": "https://s", "source_name": "s",
        "latitude": 1.0, "longitude": 2.0, "image_url": "http://cdn.example.com/a.jpg",
    }
    assert _row_to_article(row).image_url == "https://cdn.example.com/a.jpg"
```

**Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_news_router.py -q`
Expected: FAIL with `ImportError: cannot import name '_https_image'`

**Step 3: Implement**

`backend/app/models/news.py`, in `NewsArticle` after `entities`:

```python
    image_url: str | None = None
```

`backend/app/routers/news.py`, above `_row_to_article` (add `from urllib.parse import urlsplit` to the imports):

```python
def _https_image(url: str | None) -> str | None:
    """Return the image URL over https, or None if it isn't a web URL."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return parts._replace(scheme="https").geturl()
```

and in `_row_to_article` add `image_url=_https_image(row.get("image_url")),`.

`frontend/src/lib/api.ts`, in `ApiNewsArticle` after `entities`:

```ts
  image_url: string | null;
```

**Step 4: Run all checks** (backend and frontend)
Expected: all pass. `GET /api/news/cluster` responses now include `image_url`.

**Step 5: Commit**

```bash
git add backend/app/models/news.py backend/app/routers/news.py backend/tests/test_news_router.py frontend/src/lib/api.ts
git commit -m "feat(api): expose article images over https"
```

---

### Task 4a (PR 4a): Migration: `articles.country_fips`

**Why:** GKG location codes are FIPS 10-4, but every consumer (the agent's country filter, future dossiers) assumes ISO 3166-1 alpha-2, so "CN" returns Comoros, "ES" El Salvador. PR 4b converts to ISO. This PR only adds a column to keep the raw FIPS code, merged first so PR 4b's code never writes to a missing column.

**Files:**
- Create: `database/migrations/007_country_fips.sql`

**Step 1: Write the migration**

```sql
-- Raw GDELT FIPS 10-4 country code. articles.country_code becomes ISO 3166-1
-- alpha-2 (see backend/app/services/country_codes.py). NULL marks rows written
-- before the switch, which ingestion backfills.
ALTER TABLE articles ADD COLUMN IF NOT EXISTS country_fips TEXT;
```

**Step 2: Verify** it is idempotent: it uses `IF NOT EXISTS`, and the existing deploy loop records it in `schema_migrations`.

**Step 3: Commit, PR, merge, and confirm** the Deploy workflow's "Run Database Migrations" job applied `007_country_fips.sql` before starting PR 4b.

```bash
git add database/migrations/007_country_fips.sql
git commit -m "feat(db): add articles.country_fips for the FIPS to ISO switch"
```

---

### Task 4b (PR 4b): Store ISO country codes; backfill old rows

**Files:**
- Create: `scripts/gen_country_codes.py` (one-off generator, committed for provenance)
- Create: `backend/app/services/country_codes.py` (generated)
- Modify: `backend/app/services/gdelt.py:323,334` (map `parts[2]`)
- Modify: `backend/app/services/database.py` (write `country_fips` in the upsert, around lines 200 to 240)
- Modify: `backend/app/services/ingestion.py` (backfill rows with `country_fips IS NULL`; carry `country_fips` through at line 81)
- Test: `backend/tests/test_country_codes.py`, `backend/tests/test_gdelt.py`

**Step 1: Generate the mapping from GeoNames** (`countryInfo.txt` lists ISO and FIPS codes side by side)

`scripts/gen_country_codes.py`:

```python
"""Generate backend/app/services/country_codes.py from GeoNames countryInfo.txt.

Usage: python scripts/gen_country_codes.py
"""

import urllib.request

URL = "https://download.geonames.org/export/dump/countryInfo.txt"
OUT = "backend/app/services/country_codes.py"

text = urllib.request.urlopen(URL, timeout=30).read().decode("utf-8")
pairs = {}
for line in text.splitlines():
    if not line or line.startswith("#"):
        continue
    cols = line.split("\t")
    iso, fips = cols[0].strip(), cols[3].strip()
    if iso and fips:
        pairs[fips] = iso

body = "\n".join(f'    "{f}": "{i}",' for f, i in sorted(pairs.items()))
with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(
        '"""FIPS 10-4 (GDELT) to ISO 3166-1 alpha-2 country codes.\n\n'
        "Generated by scripts/gen_country_codes.py from GeoNames countryInfo.txt.\n"
        '"""\n\nfrom __future__ import annotations\n\n'
        f"FIPS_TO_ISO2: dict[str, str] = {{\n{body}\n}}\n\n\n"
        "def fips_to_iso2(fips: str | None) -> str:\n"
        '    """Return the ISO alpha-2 code for a GDELT FIPS code, or "" if unknown."""\n'
        '    return FIPS_TO_ISO2.get((fips or "").strip().upper(), "")\n'
    )
print(f"wrote {len(pairs)} codes to {OUT}")
```

Run: `python scripts/gen_country_codes.py`
Expected: `wrote 2xx codes to backend/app/services/country_codes.py`. Then `cd backend && python -m ruff format app/services/country_codes.py`.

**Step 2: Write the failing tests** (`backend/tests/test_country_codes.py`)

```python
from app.services.country_codes import fips_to_iso2


def test_known_fips_codes_map_to_iso():
    assert fips_to_iso2("CH") == "CN"  # China
    assert fips_to_iso2("SP") == "ES"  # Spain
    assert fips_to_iso2("UK") == "GB"  # United Kingdom
    assert fips_to_iso2("AS") == "AU"  # Australia
    assert fips_to_iso2("RS") == "RU"  # Russia
    assert fips_to_iso2("NI") == "NG"  # Nigeria


def test_unknown_or_empty_returns_empty_string():
    assert fips_to_iso2("ZZ") == ""
    assert fips_to_iso2("") == ""
    assert fips_to_iso2(None) == ""
```

Add to `backend/tests/test_gdelt.py` a test that a parsed GKG record with location country `UK` yields `country_code == "GB"` and `country_fips == "UK"` (use the existing `_make_gkg_record` helper with a V2Locations entry whose third `#` field is `UK`).

Run: `cd backend && python -m pytest tests/test_country_codes.py tests/test_gdelt.py -q`
Expected: the gdelt test FAILS (`country_code == "UK"`).

**Step 3: Implement**
- `gdelt.py` lines 323 and 334: store `"country_fips": parts[2]` and `"country_code": fips_to_iso2(parts[2])` (import from `app.services.country_codes`). Carry `country_fips` into the article dict built at line 376.
- `ingestion.py` line 81: add `"country_fips": a.get("country_fips"),`.
- `database.py` upsert: add `country_fips` to the column list, the `VALUES` placeholders, `ON CONFLICT ... DO UPDATE SET country_fips = EXCLUDED.country_fips`, and the argument tuple (`article.get("country_fips")`).
- `ingestion.py`, a backfill run at the start of each cycle (idempotent and cheap once done):

```python
async def _backfill_iso_country_codes(pool) -> int:
    """Convert rows written before the FIPS to ISO switch (country_fips IS NULL)."""
    fips_codes = await pool.fetch(
        "SELECT DISTINCT country_code FROM articles WHERE country_fips IS NULL"
    )
    updated = 0
    for row in fips_codes:
        fips = row["country_code"] or ""
        result = await pool.execute(
            "UPDATE articles SET country_fips = $1, country_code = $2 "
            "WHERE country_fips IS NULL AND country_code = $1",
            fips,
            fips_to_iso2(fips),
        )
        updated += int(result.split()[-1])
    if updated:
        logger.info("Backfilled ISO country codes for %d articles.", updated)
    return updated
```

Call it in `run_ingestion_cycle` before purging, wrapped in `try/except Exception: logger.warning(..., exc_info=True)` so a failure never blocks ingestion.

**Step 4: Run all backend checks**
Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/gen_country_codes.py backend/app/services/country_codes.py backend/app/services/gdelt.py backend/app/services/ingestion.py backend/app/services/database.py backend/tests/test_country_codes.py backend/tests/test_gdelt.py
git commit -m "fix(data): store ISO country codes (GDELT is FIPS) and backfill old rows"
```

**Manual check after deploy:** ask the co-pilot "What's happening in Spain?"; retrieved stories are Spanish, not Salvadoran.

---

### Task 5 (PR 5): Daily LLM spend cap

**Why:** Every AI endpoint is public. Rate limits are per IP, so many IPs can still run up the Anthropic bill. Add a global daily dollar cap; past it, AI endpoints return their existing "temporarily unavailable" fallbacks until midnight UTC.

**Files:**
- Create: `backend/app/services/llm_budget.py`
- Modify: `backend/app/config.py` (`llm_daily_budget_usd`)
- Modify: `backend/app/services/agent.py`, `backend/app/services/ai_summary.py` (check before each call, record after)
- Test: `backend/tests/test_llm_budget.py`

**Step 1: Write the failing tests** (`backend/tests/test_llm_budget.py`)

```python
from types import SimpleNamespace

import pytest

from app.services import llm_budget


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    async def none():
        return None

    monkeypatch.setattr(llm_budget, "get_redis", none)
    llm_budget._memory.clear()
    monkeypatch.setattr(llm_budget.settings, "llm_daily_budget_usd", 0.01)


def test_cost_uses_haiku_5_5_prices():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
    assert llm_budget.cost_usd(usage) == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_budget_blocks_after_cap():
    assert await llm_budget.has_budget()
    await llm_budget.record(SimpleNamespace(input_tokens=20_000, output_tokens=20_000))  # $0.012
    assert not await llm_budget.has_budget()
```

Run: `cd backend && python -m pytest tests/test_llm_budget.py -q`
Expected: FAIL with `ImportError`.

**Step 2: Implement** `backend/app/services/llm_budget.py`

```python
"""Global daily cap on Claude spend, shared across all AI endpoints.

Uses Redis when available (survives restarts), else an in-process counter;
the API runs as a single replica, so the in-process counter is exact.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.cache import get_redis

logger = logging.getLogger(__name__)

# Claude Haiku 5.5, prompts up to 100K tokens (USD per token)
_INPUT_PER_TOKEN = 0.10 / 1_000_000
_OUTPUT_PER_TOKEN = 0.50 / 1_000_000

_memory: dict[str, float] = {}


def cost_usd(usage: Any) -> float:
    return usage.input_tokens * _INPUT_PER_TOKEN + usage.output_tokens * _OUTPUT_PER_TOKEN


def _key() -> str:
    return "llm:spend:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _spent() -> float:
    r = await get_redis()
    if r is not None:
        try:
            value = await r.get(_key())
            return float(value or 0)
        except Exception:
            logger.warning("Budget read from Redis failed; using memory.", exc_info=True)
    return _memory.get(_key(), 0.0)


async def has_budget() -> bool:
    return await _spent() < settings.llm_daily_budget_usd


async def record(usage: Any) -> None:
    amount = cost_usd(usage)
    _memory[_key()] = _memory.get(_key(), 0.0) + amount
    r = await get_redis()
    if r is not None:
        try:
            await r.incrbyfloat(_key(), amount)
            await r.expire(_key(), 2 * 86400)
        except Exception:
            logger.warning("Budget write to Redis failed.", exc_info=True)
```

`backend/app/config.py`:

```python
    llm_daily_budget_usd: float = field(
        default_factory=lambda: float(_env("LLM_DAILY_BUDGET_USD", "1.0"))
    )
```

At each of the three Claude call sites (`plan_retrieval`, `synthesize_answer`, `ai_summary._call_claude`): before calling, `if not await llm_budget.has_budget(): raise LLMBudgetExceeded` (define `class LLMBudgetExceeded(RuntimeError)` in `llm_budget.py`); each call site's existing `except` path then returns its fallback. After a successful call, `await llm_budget.record(response.usage)`. Add one test per call site that sets the budget to 0 and asserts `messages.create` is not called and the fallback is returned.

**Step 3: Run all backend checks**
Expected: all pass.

**Step 4: Commit**

```bash
git add backend/app/services/llm_budget.py backend/app/config.py backend/app/services/agent.py backend/app/services/ai_summary.py backend/tests/test_llm_budget.py backend/tests/test_agent.py backend/tests/test_ai_summary.py
git commit -m "feat(ai): global daily Claude spend cap (default $1/day)"
```

$1 a day is about $30 a month, the ceiling of the spend caps set on the API key. Adjust with the `LLM_DAILY_BUDGET_USD` app setting.

---

### Task 6 (PR 6): Fix summary grid mismatch and cluster time filtering

Scope from the feature report (section on bugs):
- Cluster summaries use a 2-degree cache grid while globe dots use 1-degree cells, and the summary ignores the selected time window. Key the cache on the dot's 1-degree cell **and** the window, and filter the summary's articles by the window.
- `GET /api/news/cluster` takes the newest 50 articles first and filters by time afterwards, so busy cells come back empty for older windows and "Load more" stops at 50. Move the time filter into the SQL `WHERE` clause before `LIMIT`/`OFFSET`.
- Topic filters judge each cell by its newest story only. Filter on `topic_tags && $topics` in SQL, so a cell appears if any of its stories match.

Write a failing test for each in `backend/tests/test_news_router.py` (mock the pool and assert the SQL receives the window bounds and the topic filter), then fix. Bite-sized steps will be written when this PR starts, after re-reading `routers/news.py` and `services/database.py` at that commit.

### Production baseline (2026-10-11)

- `articles`: 12,627 rows after about 19 hours (about 660 an hour, so about 110K at 7-day retention), 209 MB in total. Every row is embedded; the float32 HNSW index is 96 MB. pgvector 0.8.2, `shared_buffers` 256 MB, `maintenance_work_mem` 97 MB.
- `kg_edges`: 150 MB with 725K edges, 568K of them `CO_MENTIONED`. That is already bigger than `articles`, and grows to about 1.3 GB at 7 days at today's volume.
- In a current GKG file (2026-10-11 14:00), all 448 city-level records carry `<PAGE_TITLE>`, which gives 357 distinct titles. Ingestion currently keeps about 160 a cycle (the rest fail title scraping). Taking titles from GDELT therefore roughly doubles article volume. Word-count filtering hardly helps: 96% of these pages have 100+ words.
- Averages per city-level record: 33 distinct themes, 4.2 persons, 3.0 orgs, 10.7 distinct names, 1.2 counts, 384 bytes of extras XML.

Because of the volume increase, the knowledge-graph change (7b) lands before the title change (7c).

### Task 7a (PR 7a): Migration: GKG field columns

**Files:**
- Create: `database/migrations/009_gkg_fields.sql`

```sql
-- 009_gkg_fields.sql
-- GKG fields kept on the article row (filled by the ingestion change that
-- follows this migration): GDELT themes, people, organisations, the most
-- frequent proper names, and typed counts (killed, arrested, protesting, ...).
-- Tone details go into the existing entities JSONB.
-- Constant defaults make this catalog-only, but fail fast rather than queue
-- API reads behind an ingestion transaction's lock.
SET lock_timeout = '5s';
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS themes  TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS persons TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS orgs    TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS names   TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS counts  JSONB  NOT NULL DEFAULT '[]';
```

No GIN indexes yet. The PRs that query these columns (15 threads, 17 entity tracker) add them, so ingestion doesn't pay index maintenance before anything reads them. `nearby_articles` and friends return `SETOF articles`, so new columns don't break them. Merge and deploy this before 7c.

### Task 7b (PR 7b): Knowledge graph: co-mentions on demand

`populate_graph` writes a `CO_MENTIONED` row for every pair of entities in every article. That is O(n²) awaited round trips (an UPDATE, then an INSERT), and those rows are 78% of `kg_edges`. Stop writing them, and compute co-mentions when the agent asks.

**Files:**
- Modify: `backend/app/services/knowledge_graph.py`: remove step 7 (the `combinations(...)` loop, plus `entity_node_ids` and the `itertools` import if unused).
- Modify: `backend/app/services/retrieval.py`: `graph_traverse` and `entity_lookup`.
- Test: `backend/tests/test_knowledge_graph.py`, `backend/tests/test_retrieval.py`.

**Behaviour:**
- Traversal ignores stored `CO_MENTIONED` edges (`AND e.rel_type <> 'CO_MENTIONED'` in both halves of the recursive CTE, and wherever `entity_lookup` reads edges). The existing rows age out within 7 days through `ON DELETE CASCADE` on `article_id`; no data migration is needed.
- When `rel_type` is None or `'CO_MENTIONED'`, add on-demand co-mentions: the entities that share an ARTICLE node with the start entity through `MENTIONED_IN` edges. Each one's `weight` is the number of distinct shared article nodes, top 20 by weight, returned as `rel_type='CO_MENTIONED'`, `depth=1`, with one representative `article_id` so the article fetch still works. With `rel_type='CO_MENTIONED'`, return only these.
  ```sql
  SELECT n.id, n.type, n.name, 'CO_MENTIONED' AS rel_type,
         count(DISTINCT e2.target_node_id)::int AS weight,
         (array_agg(e2.article_id ORDER BY e2.created_at DESC))[1] AS article_id,
         1 AS depth
  FROM kg_edges e1
  JOIN kg_edges e2 ON e2.target_node_id = e1.target_node_id
                  AND e2.rel_type = 'MENTIONED_IN'
                  AND e2.source_node_id <> $1
  JOIN kg_nodes n ON n.id = e2.source_node_id
  WHERE e1.source_node_id = $1 AND e1.rel_type = 'MENTIONED_IN'
  GROUP BY n.id, n.type, n.name
  ORDER BY weight DESC
  LIMIT 20
  ```
  (`MENTIONED_IN` edges point from the entity to the ARTICLE node. Check this against `populate_graph` before relying on it.)
- Agent tool descriptions in `agent.py` still name `CO_MENTIONED`, which is still a valid relationship. Change them only if a description says how it is stored.

**Tests:**
- `populate_graph` no longer sends any `CO_MENTIONED` SQL.
- `graph_traverse(rel_type='CO_MENTIONED')` runs the aggregation and not the CTE.
- The default traversal excludes stored `CO_MENTIONED` edges and merges the computed ones.

**Verify after deploy:** a co-pilot question such as "Who is connected to <a person in today's news>?" still lists related people and organisations. `kg_edges` stops growing by about 30K rows an hour.

### Task 7c (PR 7c): Store GKG fields and take titles from GDELT

Depends on 7a being deployed and 7b merged.

**Files:**
- Modify: `backend/app/services/gdelt.py` (`fetch_raw_gkg`), `backend/app/services/ingestion.py` (`_ingest_from_raw_gkg`), `backend/app/services/database.py` (`upsert_articles`).
- Test: `backend/tests/test_gdelt.py`, `backend/tests/test_ingestion.py`, `backend/tests/test_database.py`.

**Parse in `fetch_raw_gkg`** (0-based GKG 2.1 columns; add each to the comment block listing field indices):
- `page_title` from field 26 (`V2EXTRASXML`), `<PAGE_TITLE>…</PAGE_TITLE>`:
  - First strip HTML comments (`<!-- … -->`) and any tags, in a helper that `scrape_titles` uses too, so GDELT and scraped titles are cleaned alike before `_is_usable_title`. Production has 31 of 12,627 scraped titles like `…Lapses<!-- --> | ZeroHedge`. Test both paths with a title like that.
  - Apply `html.unescape`, collapse whitespace, and cap at 300 characters.
  - Return `''` when the tag is missing, the title is 5 characters or fewer, or `_is_usable_title` rejects it.
- `themes` from field 7 (`V1THEMES`): distinct, non-empty, first-seen order, capped at 64.
- `persons` (field 11) and `organizations` (field 13): already parsed; cap each at 30.
- `names` from field 23 (`V2.1ALLNAMES`, `Name,offset;…`): count repeats per name and keep the top 15 by count, ties broken by the earliest offset.
- `counts` from field 6 (`V2.1COUNTS`), falling back to field 5 (`V1COUNTS`):
  - Blocks look like `TYPE#N#OBJECT#LOCTYPE#LOCNAME#FIPS#ADM1#LAT#LNG#FEATUREID[#OFFSET]`.
  - Keep only the types `AFFECT, ARREST, KIDNAP, KILL, PROTEST, SEIZE, WOUND`. Others in the field are theme names such as `SOC_GENERALCRIME`.
  - Store `{"type", "n": int, "object", "country": fips_to_iso2(FIPS) or "", "place": LOCNAME}`.
  - Skip blocks whose N isn't an integer, drop exact duplicates, and cap at 10.
- `tone_detail` from field 15 (`V1.5TONE`): `{"tone", "pos", "neg", "polarity", "words": int}` from positions 0, 1, 2, 3 and 6. Omit it if the field is malformed. The existing `tone` float stays.

**Ingest:**
- The title is `page_title` when present. Call `scrape_titles` only for records without one.
- Log `"Titles: %d from GDELT, %d scraped, %d dropped."`, replacing the scrape-only log line or adding to it.
- Rows gain `themes`, `persons`, `orgs` (from `organizations`), `names`, `counts`, and `entities = {"tone": tone_detail}` (or `{}`).
- The knowledge graph still receives `persons`, `organizations` and `mentioned_locations` as today.

**Upsert:**
- Add `themes, persons, orgs, names, counts` as `$16`–`$20`, with `counts` sent as `json.dumps`, and update all five on conflict.
- The existing placeholder-count test must still pass.

**Check:** `ml_models` sends titles in parallel chunks. Confirm that about 400 titles a cycle stays inside its timeout.

**Verify after deploy:**
- Each cycle logs about 300+ upserts and the new title line.
- Spot-check a fresh row's `themes`, `persons`, `names`, `counts` and `entities`.
- After 24 hours, check the database's "CPU credits remaining" and `pg_total_relation_size('articles')`.

---

## Phase 2: Soft Orbit UI foundation (scoped)

- **PR 8 (tokens):**
  - Replace the token block in `frontend/src/app/globals.css` with the Soft Orbit night tokens. The source is `docs/redesign/ui/soft-orbit/tokens.json`, which is also published in the design system.
  - Map them into Tailwind v4 `@theme` names, and keep the current names as aliases until the components move over.
  - Keep `--text-motto` from PR #42.
  - The light theme is retired with the redesign (Soft Orbit is dark-only), so remove `ThemeToggle` here or in PR 9.
  - Check: `next build`, plus a visual check that today's UI still renders.
- **PR 9 (shell):**
  - `.so-sky` ground with starfield, `GlassPanel`, pill controls, floating layout (threads left, co-pilot right, search and topics top centre), orbital rings overlay, low-power mode, reduced motion.
  - The brand lockup is unchanged.
  - Port classes from `docs/redesign/ui/soft-orbit/mockup.html` and the design system's `components/bundle.css`.
- **PR 10 (timeline):** `TimelineCapsule` with a 7-day hourly volume area chart (from `/api/news/density`), presets 1h/6h/24h/7d, and replay; the layer switcher (Dots, Intensity, Mood, Links, Threads).
- **PR 11 (co-pilot):** the `CoPilot` console with context pills, citation pills, a quiet tool line and suggested-action pills. Actions come from the normalised `globe_actions` plus a fixed list (Open thread, Pin to board).

## Phase 3: Quick wins (scoped)

- **PR 12 (hover card):**
  - Add `top_headline`, `top_image_url`, topic mix and tone to the `/api/news` globe payload, so hovering never fetches.
  - Build the `HoverCard`: image, or the topic glyph when there's no image or it's a logo. Conflict images are blurred until clicked. Sentiment score is printed next to its colour.
- **PR 13 (arcs):**
  - Add `/api/links`: co-coverage pairs computed on demand over the selected window, from the article rows' `persons` and `orgs` arrays (filled by 7c) and the knowledge graph's `MENTIONED_IN` and `LOCATED_AT` edges, with story counts. (Stored `CO_MENTIONED` edges stop with 7b.) Cache it with `s-maxage`.
  - `ConnectionArc` layer, arc label pill, and a link inspector showing the shared entities and stories.
- **PR 14 (alerts):**
  - Surges: an hourly z-score per cell over the 7-day baseline, at no LLM cost.
  - "Since your last visit" strip, with the last-visit time kept in `localStorage`.

## Phase 4: Flagships (scoped)

- **PR 15 (threads backend):** cluster recent embeddings into story threads, incrementally each cycle. Generate one Haiku 5.5 synopsis per thread per day (about $2 a month), within the PR 5 budget.
- **PR 16 (threads UI):** threads panel, spread route, replay animating aurora arcs over time.
- **PR 17 (entity tracker):** follow a person, org or named event across the globe, with mention markers and a trend line.
- **PR 18 (investigation board):** split-view sheet with pins and four edge kinds; pins are mirrored on the globe. The optional AI memo stays within budget.

## Phase 5: GDELT Events (scoped)

- **PR 19:** ingest `export.CSV.zip` from the same `lastupdate.txt` each cycle. Keep only daily `event_pairs_daily(a_iso, b_iso, quad_class, day, n_events, mentions, avg_goldstein, avg_tone, sample_urls)` rollups (CAMEO actor codes mapped to ISO), with 7-day retention like everything else.
- **PR 20:** relation arcs in `arc-relation-cooperation` / `arc-relation-conflict`, always labelled, from `/api/relations`.

## Risks to watch

- **Database CPU credits** (burstable B1ms) once PRs 7c, 15 and 19 land. Set an Azure alert on "CPU credits remaining" before PR 15.
- **Hover-driven requests:** keep hover data in the main payload and add `s-maxage` to public GETs.
- **Mobile:** every hover interaction needs a tap equivalent. The bottom-sheet layout is in the Soft Orbit spec.
