# Soft Orbit Phase 3 (Quick Wins) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (or superpowers:executing-plans) to implement this plan task-by-task.

**Goal:** Add the three "quick win" surfaces on top of the live Soft Orbit UI:
- the city hover card;
- co-coverage arcs with a link inspector;
- surge alerts with a "since your last visit" strip.

None of them generates AI text on hover, and each lands in a slot Phase 2 reserved.

**Architecture:**
- Each feature is a backend read path (SQL measured on production, cached in Redis, plus `s-maxage` at Vercel's edge) paired with a Soft Orbit surface.
- Data that hovering needs rides in the main `/api/news` payload. Anything per place is fetched on dwell and cached.
- Links need one new article column (`mentioned_countries`), so that PR is preceded by its own migration PR, as in Phase 1.

**Tech Stack:**
- Backend: FastAPI and asyncpg on Azure PostgreSQL 16 B1ms (PostGIS, pgvector); Upstash Redis.
- Frontend: Next.js 16, React 19, Tailwind v4, globe.gl/three-globe 2.45 (pinned).
- Tests: Vitest with Testing Library, and Playwright.

**Parent plan:** `docs/plans/2026-10-10-soft-orbit-redesign.md`. Phase 3 is PRs 12–14; PR 13 is split into 13a, 13b and 13c here.

**Design sources (read before starting):**
- `docs/redesign/features/feature-exploration.md`: Q1 hover recon card, Q2 connection arcs, Q3 "since your last visit", Q4 surge pings.
- `docs/redesign/ui/soft-orbit/tokens.md`: the Hover card, Connection arc and Mobile adaptation sections, and the do and don't list.
- `docs/redesign/ui/soft-orbit/mockup.html`:
  - CSS: `.recon` and `.rc` (lines 375–402), `.insp`/`.ro`/`.art` (357–372), `.since` (289–293), `.surges` (420–424), `.arc-pill` and `.tag` (213–217).
  - JS: `thumb`/`renderRecon` (1070–1111), `inspectHTML` (link branch, 1136–1170), the reticle and leader (1356–1382), the arc pill (1394–1403), `renderSurges`/`renderTop` (1194–1225).

---

## Production measurements (2026-10-12, read-only)

| Query | Result |
|---|---|
| Current `/api/news` cell query | 0.16 s at 24h, 0.13 s at 7 days |
| Hover-card payload, naive form (correlated topic-mix subquery, `DISTINCT ON` lead over the whole window, `mode()` place) | **11.0 s** at 24h, 15.4 s at 7 days. Don't ship this shape. |
| Hover-card payload, one-pass form (per-cell `count(*) FILTER (...)` for the six topics, `avg(sentiment_score)`, `max(published_at)`, top 500 cells, then a `LATERAL` lookup of the newest story by `published_at = newest` inside the cell's lat/lng box) | **0.16 s** at 24h, 0.24 s at 7 days |
| Lead images | 499 of the top 500 cells have an `https` lead image |
| Links through the knowledge graph (articles → `MENTIONED_IN` → LOCATION nodes, country pairs) | 4.2 s cold at 24h, 2.0 s warm at 7 days, across 66,843 location-mention edges |
| Links, top pairs | US–Iran 492, US–Russia 391, RU–Ukraine 343, SA–Yemen 340: hub-dominated, hence lift ranking |
| Surges (distinct titles in the last 2h vs the 7-day baseline, per 1° cell) | 0.31 s. Top ratios included 21 vs 1 and 15 vs 25, so it needs minimum counts and a domain-diversity guard. |
| `persons` filled in the last 24h | 72% of articles (7c is working) |

Region names are noisy, e.g. `South Island, New Zealand (General), New Zealand`.

## Working rules (every PR)

These are the same as Phase 2, plus:
- **One branch per PR from `origin/main`. No stacked PRs:** #57 merged into its base branch instead of `main`.
- **Checks:**
  - Backend: `cd backend && python -m pytest tests -q && python -m ruff check app && python -m ruff format --check app`.
  - Frontend: `cd frontend && npm run lint && npm run test && npm run build`, then `npx prettier --check --end-of-line auto <changed files>`, then `CI=1 npx playwright test` (port 3000 must be free).
- **CI runners report 4 CPU cores, which puts the app in low-power mode** (`useMotionPrefs`): no glass blur, no Intensity. An e2e test that needs a full-power feature must set `localStorage["orbis-low-power"] = "0"` via `page.addInitScript`.
- **New SQL runs against the local Postgres 16 + PostGIS + pgvector container** (`orbis-pg-test`, `postgresql://postgres:test@localhost:55432/postgres`, migrations 001–010 applied; run 011 for 13a) with marker rows that are deleted afterwards. The controller also times it read-only on production before the PR goes to the owner, against the targets in each task.
- **Migrations** follow the 008 and 009 patterns: `SET lock_timeout = '5s'` for column adds, the rerun guard for concurrent indexes, and a static guard test like `backend/tests/test_migrations.py`.
- **Visual check** of a production build at 1440, 1280, 1024 and 390 wide (Playwright with `mockAllApiRoutes`); the 1440 screenshot goes in the PR.
- **Every new chrome region** joins `e2e/layout.spec.ts` (12px gaps, the viewport edge, the timeline centred).
- **Hand-off:** hand a PR to the owner only after every CI check is green.

---

## PR 12: City hover card

Branch: `claude/p3-hover`.

### Task 12.1: Hover data in the globe payload (backend)

**Files:**
- Modify: `backend/app/services/database.py` (`get_globe_points`, `_globe_points_query`), `backend/app/models/news.py` (`GlobeDataPoint`), `backend/app/routers/news.py`.
- Test: `backend/tests/test_database.py`, `backend/tests/test_news_router.py`, `backend/tests/test_models.py`.

**New fields on `GlobeDataPoint`** (keep every existing field):

```python
class GlobeLead(BaseModel):
    title: str
    source_name: str
    published_at: datetime
    image_url: HttpsImageUrl = None        # https only (PR 3's validator); None otherwise
    topic: str                             # the lead story's first tag

class GlobeDataPoint(BaseModel):
    ...
    lead: GlobeLead | None = None
    topic_mix: dict[str, int] = {}         # six UI topics' tags -> stories in the cell (a story can count twice)
    tone: float = 0.0                      # mean sentiment_score of the cell's stories, -1..1
```

**SQL:** use the measured one-pass shape:

```sql
WITH cells AS (
  SELECT FLOOR(latitude / $c) * $c + $c / 2 AS lat,
         FLOOR(longitude / $c) * $c + $c / 2 AS lng,
         count(*) AS article_count,
         avg(sentiment_score) AS tone,
         count(*) FILTER (WHERE topic_tags && '{politics}')    AS politics,
         count(*) FILTER (WHERE topic_tags && '{conflict}')    AS conflict,
         count(*) FILTER (WHERE topic_tags && '{technology}')  AS technology,
         count(*) FILTER (WHERE topic_tags && '{environment}') AS environment,
         count(*) FILTER (WHERE topic_tags && '{economy}')     AS economy,
         count(*) FILTER (WHERE topic_tags && '{health}')      AS health,
         max(published_at) AS newest
  FROM articles
  WHERE <window> [AND topic_tags && ARRAY[$t::text]]
  GROUP BY 1, 2
  ORDER BY article_count DESC, 1, 2
  LIMIT $limit
)
SELECT cells.*, lead.*
FROM cells
CROSS JOIN LATERAL (
  SELECT title, source_name, published_at, image_url, region, topic_tags
  FROM articles a
  WHERE a.latitude  >= cells.lat - $c / 2 AND a.latitude  < cells.lat + $c / 2
    AND a.longitude >= cells.lng - $c / 2 AND a.longitude < cells.lng + $c / 2
    AND <window, same predicate> [AND topic filter]
  ORDER BY (a.image_url LIKE 'https://%') DESC NULLS LAST, a.published_at DESC
  LIMIT 1
) lead
```

Notes:
- **Lead story:** the lateral prefers the newest story that has an `https` image, so the headline and the image always belong to the same story. If that ordering costs more than 0.5 s at 7 days on production, use `published_at = cells.newest` as measured, and say so.
- **`NULLS LAST`:** a NULL `image_url`'s `LIKE` is NULL, and `DESC` sorts NULLs first, so without it a story with no image outranks the https one. The shipped query looks the lead up by `published_at = COALESCE(newest_with_image, newest)` (a whole GDELT batch shares one time) and, when the cell has an https image, keeps only https stories at that time.
- **Ties:** `ORDER BY article_count DESC, 1, 2` breaks ties by the cell, so the top 500 are the same cells every time.
- **Parameters:** keep them positional and build the predicates in Python, the way the existing function does.

**Dot colour:** with no topic filter, `topic` becomes the cell's **most common** of the six topics (ties go to the lead's first tag; `general` when the cell has none). This replaces "the newest story's first tag", so a dot's colour stops flickering with each new story. With a filter, it stays the filter's tag.

**Place name:** add `display_place(region)` in a new `backend/app/services/places.py`, used for `location_name`. It removes GDELT's `(General)` fragments and a repeated trailing country:
- `South Island, New Zealand (General), New Zealand` → `South Island, New Zealand`
- `Washington, District Of Columbia, United States` → unchanged
- `''` → `''`

Test it table-driven with at least 8 real-looking cases.

**Steps:**
1. Write the failing tests:
   - The model accepts and serialises `lead`, `topic_mix` and `tone`. An `http://` image becomes `None`.
   - The query's parameter numbering and placeholder count are right with and without a topic and a range.
   - The `LATERAL` and the six `FILTER` counts are present.
   - `topic` is the dominant topic without a filter and the tag with one.
   - `display_place` cases.
2. Run them and see them fail.
3. Implement.
4. Run the SQL against the local Postgres, with a cell holding 3 politics and 2 conflict stories, one with an https image: check the counts, mix, tone, lead and colour. Report the timing.
5. Commit: `feat(api): hover data in the globe payload`.

**Target:** under 0.5 s at 7 days on production. The controller measures this before hand-off.

### Task 12.2: Place preview endpoint (backend)

**Endpoint:** `GET /api/news/preview?lat=&lng=&timespan=|start_time=&end_time=&topic=` returns:

```json
{ "spark": [24 ints], "entities": [{"name": "…", "type": "person|org", "n": 7}], "brief": "…" | null }
```

- **`spark`:** stories per hour in the cell over the 24 hours ending at the window's end (`now` when live), oldest first. Use `generate_series` with zero fill and UTC, as in `get_hourly_volume`.
- **`entities`:** the top 3 names across the cell's stories in the window, by count, from `unnest(persons)` and `unnest(orgs)`. A name needs at least 2 stories. Run each through `strip_invisible` and `sanitise_text` (they come from GDELT and are shown as text).
- **`brief`:** read-only. Look up the cell's cached summary under the exact key `summarise_cluster` would write: `summary:v3:{cell}:{window}[:{topic}]`, built with the same `cell_index` and `_window_key` helpers, so expose a `summary_cache_key(lat, lng, cell_size, start, end, topic)` from `ai_summary` and use it in both places. **Never call Claude here.** `null` if nothing is cached.
- **Validation and caching:** validate as `/api/news/cluster` does: lat/lng ranges, the 1° cell, the topic via `_globe_topic_tag`, and the window via the TimeWindow rules. Cache in Redis for 300 s, keyed on cell, window (floored to the hour) and topic. The endpoint is in the `data` rate-limit group.

**Tests:**
- Spark length, order and zero fill.
- Entity threshold and cleaning.
- The brief is read through the same key as the writer (prove it by writing with `summarise_cluster`'s key builder and reading in preview).
- No Anthropic client is ever constructed (patch it to raise).
- Validation errors give 422.
- Run the SQL on the local Postgres.

Commit: `feat(api): place preview for the hover card`.

### Task 12.3: Edge caching for public GETs

`/api/news`, `/api/news/volume`, `/api/news/preview` and `/api/topics` set `Cache-Control: public, s-maxage=60, stale-while-revalidate=300`. Leave the cluster articles and the summary as they are.
- A shared FastAPI dependency or helper sets the header, with tests.
- The Next proxy already passes `cache-control` through (`frontend/src/lib/backendProxy.ts:12`). Add a unit test there that it survives.
- After deploy, the controller checks `x-vercel-cache: HIT` on a repeated request.

Commit: `perf(api): let Vercel's edge cache public reads for a minute`.

### Task 12.4: HoverCard UI

**Files:**
- Create: `frontend/src/components/HoverCard.tsx` with a test, `frontend/src/components/GlobeHud.tsx` (reticle and leader SVG) with a test, `frontend/src/hooks/useHoverPreview.ts` with a test, and `frontend/src/lib/imageSafety.ts` with a test.
- Modify: `frontend/src/components/Globe.tsx`, `frontend/src/lib/api.ts`, `frontend/src/types/news.ts`, `frontend/src/lib/clustering.ts` (`apiPointsToGlobePoints` maps `lead`, `topicMix`, `tone`), `frontend/src/app/page.tsx`, and `frontend/src/app/soft-orbit.css` (port `.recon` and `.rc`, `.thumb`, `.mix`, `.mixl`, `.tone`, `.kv`, `.brief`, `.foot`).

**Behaviour:**
1. **Showing the card:**
   - **Hover:** globe.gl's `onPointHover` gives the hovered point. After 150 ms over the same dot, show the card from payload data only.
   - **Dwell:** after 400 ms, fetch the preview (`useHoverPreview`: one request per cell, window and topic; cached in memory for the session; abort when the hover moves on). Show the sparkline, entity pills and AI brief when it arrives, with a skeleton until then.
2. **Placement:** port the mockup's placement (lines 1366–1373):
   - beside the dot, preferring the side away from the globe's centre;
   - never over the side panel (use its bounding box when it's open);
   - never over the top bar or the bottom row;
   - clamped 16px inside the viewport.

   `GlobeHud` draws the reticle and a curved leader to the card from `globe.getScreenCoords` on a `requestAnimationFrame` loop that runs only while the card is shown. Remove `.pointLabel(pointTooltipHtml)` and `pointTooltipHtml`, which this card replaces.
3. **Content:**
   - **Header:** a thumbnail (40% column), the place (`display_place`) with its ISO code small beside it, "N stories, last 24 h" (or the window's label), and the sparkline.
   - **Body:** the lead headline (2-line clamp), source and age, a topic-mix bar with the top 2 labels and percentages, the tone bar with its marker, and the `.sent` dot with the signed score.
   - **Extras:** up to 3 entity pills (inert in this PR; PR 17 makes them track), and the AI brief on a scrim with the `AI` badge, only when `brief` isn't null.
   - **Footer:** "Click to open".
4. **Image safety** (`imageSafety.ts`, the PR 3 follow-up):
   - `<img referrerPolicy="no-referrer" loading="lazy" decoding="async" alt="">`, https only.
   - Show the topic glyph instead when `onError` fires, the URL looks like a logo (`/logo|favicon|placeholder|default[-_]?image/i`), or after load `naturalWidth < 160` or the aspect ratio is outside 0.5–3.
   - When the lead's topic is `conflict`, blur the image with a "Conflict image hidden · Show" veil button. Show reveals it for the rest of the session (kept in memory, not stored).
5. **Interaction:**
   - The card stays while the pointer is on it, so the veil button can be clicked.
   - Clicking the dot opens the panel as today.
   - Escape hides the card.
6. **Touch devices** (`(hover: none)`):
   - The first tap on a dot shows the card docked above the bottom sheet, full width minus 24px, with an "Open stories" pill. A second tap on the same dot, or the pill, opens the panel. A tap elsewhere hides the card.
   - Mouse behaviour is unchanged, so the e2e `clickPlace` still opens the panel directly.
7. **Motion:** the card fades in over `--dur-base`. Reduced motion makes it appear instantly; the reticle animation stops.
8. **Accessibility:**
   - The card is `aria-live="polite"` with a short label (place, stories, lead headline).
   - The dots themselves aren't reachable by keyboard: they live in WebGL. That stays a known gap (Phase 4 adds a keyboard places list); keyboard users reach the same data through the Stories panel and the co-pilot.

**Tests:**
- Unit:
  - `imageSafety` decisions (logo URL, tiny image, odd aspect ratio, http, conflict blur).
  - `useHoverPreview`: dwell timing with fake timers, the cache, aborting on hover change.
  - HoverCard rendering with and without a preview or a brief.
  - The placement function: pure, tested against the side panel and viewport edges.
- e2e (mock `/api/news/preview*` in `e2e/fixtures.ts`):
  - Hovering a real dot (reuse `clickPlace`'s projection, but `hover`) shows the card, with the headline and "stories".
  - The sparkline appears after the dwell.
  - A conflict lead shows the veil, and Show reveals the image.
  - Escape hides the card.
  - At 390, a tap shows the docked card, and Open stories opens the panel.
- Layout: add `hover-card` to `layout.spec.ts`'s checks against the side panel, top bar and bottom row at 1440 and 1280.

Commit: `feat(ui): city hover card`.

### Task 12.5: PR 12

1. Run every check and do the visual check.
2. The controller runs the query timing on production, read-only.
3. Open the PR `feat: city hover card (PR 12)`. Note the new dot-colour rule in its description: a cell's dominant topic, not its newest story's.

---

## PR 13a: Migration: `articles.mentioned_countries`

Branch: `claude/p3-links-column`. This merges and deploys before 13b, because the column must exist before code writes it.

**Files:**
- Create: `database/migrations/011_mentioned_countries.sql`.
- Modify: `backend/tests/test_migrations.py`, `database/README.md`.

```sql
-- 011_mentioned_countries.sql
-- ISO 3166-1 alpha-2 codes of the countries an article mentions (GDELT
-- country-level locations), filled by ingestion from PR 13b. Links between
-- places are computed from this column instead of joining the knowledge graph
-- (4.2 s cold at 24h on production, 2026-10-12).
SET lock_timeout = '5s';
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS mentioned_countries TEXT[] NOT NULL DEFAULT '{}';
```

- **Guard test:** extend the 009 guard in `test_migrations.py` to 011: lock timeout, constant `NOT NULL DEFAULT`, no table rewrite.
- **Local check:** apply 011 on the local Postgres and run it again (idempotent).

Commit and PR: `feat(db): add mentioned_countries to articles (PR 13a)`. The PR description repeats the 7a note about re-running the workflow if the lock timeout trips.

---

## PR 13b: Links backend

Branch: `claude/p3-links-api`, from `main` after 13a is deployed.

### Task 13b.1: Ingestion writes `mentioned_countries`

**Files:** `backend/app/services/gdelt.py`, `backend/app/services/ingestion.py`, `backend/app/services/database.py` (`upsert_articles`: add `$21`; update it on conflict), and their tests.

- The parser already builds `mentioned_locations` from V1LOCATIONS type-1 (country) blocks, with `country_code` mapped to ISO. `mentioned_countries` keeps those distinct, non-empty ISO codes in first-seen order, capped at 20. Keep the article's own country too; the links query drops self-pairs.
- Tests: parsing (including a record that mentions the same country twice and one with unknown codes) and the upsert argument count.

Commit: `feat(ingest): store the countries each article mentions`.

### Task 13b.2: Backfill the last 7 days from the knowledge graph

`backend/scripts/backfill_mentioned_countries.py`:
- **Source:** for articles where `mentioned_countries = '{}'`, take the ISO codes of LOCATION nodes linked by `MENTIONED_IN` edges for that `article_id` (`kg_nodes.metadata->>'country_code'`).
- **Batching:** 5,000 articles per batch, newest first, one transaction per batch.
- **Dry run:** prints counts by default and needs `--yes` to write.
- **Idempotent:** only empty arrays are touched.
- Test its selection SQL against the local Postgres (KG rows with marker names).
- **Don't run it on production;** the controller runs it after 13b deploys.

Commit: `feat(scripts): backfill mentioned countries from the knowledge graph`.

### Task 13b.3: Country centroids

- `scripts/gen_country_centroids.py` generates `backend/app/services/country_centroids.py` from the Natural Earth file shipped in three-globe: `frontend/node_modules/three-globe/example/country-polygons/ne_110m_admin_0_countries.geojson`. It is pinned at 2.45.0 by the frontend's npm override.
- For each country it records `ISO_A2 → (name, lat, lng)` from `LABEL_Y`/`LABEL_X`.
- Natural Earth uses `-99` for `ISO_A2` on some countries (France, Norway, Kosovo in some versions): fall back to `ISO_A2_EH`, and validate that FR, NO, US, CN, RU, BR, ZA and AU are present.
- Write a header with the source and SHA-256, like `country_codes.py`.
- Tests:
  - Anchor coordinates are within 3° of known label points.
  - Every code `fips_to_iso2` can return that appears in the last 7 days of data has a centroid. Approximate this with the generated table covering at least 170 codes; list any gaps.

Commit: `feat(api): country label points for link arcs`.

### Task 13b.4: `/api/links`

**Endpoint:** `GET /api/links?timespan=|start_time=&end_time=&topic=&rank=lift|count&limit=40` (`limit` 1–60; `rank` defaults to `lift`) returns:

```json
[{ "a": {"iso": "US", "name": "United States", "lat": 39.8, "lng": -98.6},
   "b": {"iso": "IR", "name": "Iran", "lat": 32.0, "lng": 53.7},
   "n": 492, "lift": 1.8, "topic": "politics", "tone": -0.31, "from": "US" }]
```

**SQL:**

```sql
WITH w AS (
  SELECT id, country_code, mentioned_countries, topic_tags, sentiment_score
  FROM articles WHERE <window> [AND topic_tags && ARRAY[$t::text]]
    AND country_code <> '' AND cardinality(mentioned_countries) > 0),
pairs AS (
  SELECT LEAST(w.country_code, m) AS a, GREATEST(w.country_code, m) AS b,
         w.country_code AS origin, w.id, w.topic_tags, w.sentiment_score
  FROM w, unnest(w.mentioned_countries) AS m
  WHERE m <> w.country_code)
SELECT a, b, count(DISTINCT id) AS n, avg(sentiment_score) AS tone,
       mode() WITHIN GROUP (ORDER BY origin) AS from_iso,
       <six FILTER counts as in 12.1, for the dominant topic>
FROM pairs GROUP BY a, b
```

Then in Python:
- **Lift:** `lift = n_ab * N / (n_a * n_b)`, where:
  - `N` is the number of linking articles in the window;
  - `n_a` and `n_b` are the linking articles touching each country (a second small aggregate, or computed from `pairs`).
- **Ranking:** with `rank=lift`, only pairs with `n ≥ 5` qualify, sorted by lift, then n. With `rank=count`, sort by n. Cap 6 arcs per country so the US doesn't take every slot.
- **Coordinates:** join the centroids table. Drop pairs whose code has no centroid, and log their count once per request at debug level.

**Caching:** Redis for 600 s, keyed on window (floored to the hour, or `live:{hours}`), topic, rank and limit. Edge caching via 12.3's helper.

**Target:** under 0.5 s at 7 days on production, measured after the 13b.2 backfill.

**Tests:**
- Self-pairs dropped; unordered pairs merged.
- `from` is the dominant origin.
- Lift arithmetic on a small fixture.
- The `n ≥ 5` threshold and the per-country cap.
- Topic filter and validation (422s).
- Run the SQL on the local Postgres: three articles US→IR, one IR→US and one FR→FR give a single US–IR pair with n = 4, from US, and no FR pair.

Commit: `feat(api): co-coverage links between countries`.

### Task 13b.5: `/api/links/detail` and `/api/links/explain`

**Detail:** `GET /api/links/detail?a=US&b=IR&<window>&topic=` returns:

```json
{ "a": {...}, "b": {...}, "n": …, "lift": …, "topic_mix": {...}, "tone": …,
  "shared": [{"name": "…", "type": "person|org", "n": …}],   // in ≥ 2 linking stories, top 8, cleaned
  "themes": ["…"],                                           // top 5 GDELT themes, prefix-stripped
  "articles": [NewsArticle, …] }                             // 10 newest linking stories, explicit column list
```

**Explain:** `POST /api/links/explain {a, b, start_time?, end_time?, topic?}` returns `{"text": "…"}`.
- **Input:** 2–3 sentences from Claude Haiku 5.5 over up to 15 linking headlines (cleaned and injection-filtered like `ai_summary`) and the two country names from the centroid table. The client never supplies names.
- **Prompt:** says "covered together" and never implies cause and effect.
- **Cache:** per pair, window floored to the hour, and topic, for 3 hours. Never cache failures (follow `SummaryUnavailable`).
- **Budget and limits:** the full budget share (cached and shared, like cluster summaries); the `ai` rate-limit group.

**Tests:**
- Codes are validated against the centroid table (anything else gives 422).
- Detail: thresholds, cleaning, article columns without the embedding.
- Explain: the prompt contains no client text, the cache key, failures aren't cached, and an over-budget request gets the paused message.

Commit: `feat(api): link detail and explanation`.

### Task 13b.6: PR 13b

1. Run every check.
2. The controller runs the backfill on production after deploy (dry run first), then times `/api/links` read-only.
3. Open the PR `feat(api): co-coverage links (PR 13b)`.

---

## PR 13c: Links layer and link inspector

Branch: `claude/p3-links-ui`, from `main` after 13b merges.

### Task 13c.1: Links overlay and arcs

**Files:** `frontend/src/components/LayerSwitcher.tsx`, `frontend/src/components/Globe.tsx`, `frontend/src/hooks/useLinks.ts` (+ test), `frontend/src/lib/api.ts`, `frontend/src/app/page.tsx`, `frontend/src/app/soft-orbit.css`, `frontend/src/types/news.ts`.

**Layer switcher:**
- Base layers (Dots, Intensity) stay exclusive.
- After the mockup's `.sep`, a **Links** toggle (`aria-pressed`) overlays arcs on either base layer.
- While Links is on, a small `.seg` beside it switches **Surprising** (lift) and **Most covered** (count).

**Arcs:**
- Data: `useLinks(timeWindow, topic, rank)` follows the `useGlobePoints` pattern (abort, ignore late answers), and fetches only while Links is on.
- Drawing: `arcsData` with stroke `0.16 + n / maxN * 0.5`.
  - Colour: `--arc-coverage`, except the inspected link, which uses `--arc-highlight`.
  - Dashes flow from `from` to the other end over `--dur-arc-flow`, but only with full motion and not in low-power mode.
- Hover: a floating `.arc-pill` near the arc's midpoint says "41 stories link United States and Iran, mostly politics".
- Click: opens the link inspector (13c.2).

**Tests:**
- Unit: arc stroke and colour, and the dash decision against motion preferences.
- e2e (mock `/api/links*`):
  - Turning on Links fetches `rank=lift`, and the switch refetches `rank=count`.
  - The globe has arc objects: expose a `data-arcs` count like `data-dots`.
  - Clicking an arc is hard to do reliably in WebGL, so the inspector is opened through the same handler from a test-only `data-` hook on the switcher, or through the co-pilot action in 13c.3. Document the choice.

Commit: `feat(ui): links layer with co-coverage arcs`.

### Task 13c.2: Link inspector in the side panel

- **Tab:** rename the second tab from **Stories** to **Inspect**. It shows the current inspection, `{ kind: "place", panelId } | { kind: "link", a, b, query }`.
- **Recent pills:** the recent row (RecentPlaces) holds both places and links (`US ↔ IR`), up to `MAX_PANELS`.
- **Test ids:** keep `side-tab-stories` as an alias test id on the tab, or update every spec. Prefer updating the specs and renaming the test id to `side-tab-inspect`.

**Inspector content** (mockup `inspectHTML`, link branch):
- The heading, `United States and Iran`.
- The caption "Named in the same stories. Covered together does not mean cause and effect."
- `.readouts`: Stories, Lift (`1.8×`), Topic (coloured), Tone (`.sent`).
- "Shared in coverage" entity pills (inert until PR 17) and theme pills (dashed).
- "Linking stories" as `.art` rows: source, place, age, `.sent`. Each opens its URL (http(s) only, through `isWebUrl`).
- An **Explain this link** aurora button: the AI text appears with the `AI` badge, the button disables while loading, and the paused or failed messages show as text.

The link's query (window and topic) is frozen at open time, like a panel query.

**Tests:**
- Unit: the inspector rendering and the explain flow (loading, success, paused).
- e2e: open a link and see the readouts, shared pills and stories, then Explain.
- `layout.spec`: unchanged boxes.

Commit: `feat(ui): link inspector`.

### Task 13c.3: Co-pilot and hover card hooks

- **Hover card:** the footer shows "N linked countries" for the hovered place's country (from the loaded links), only while Links is on.
- **Co-pilot:** it gets a "Show links" action pill when Links is off and its answer has 2 or more globe actions in different countries. The pill turns on the Links layer.

Tests for both. Commit: `feat(ui): link hints in the hover card and co-pilot`.

### Task 13c.4: PR 13c

1. Run every check and do the visual check, with Links on at 1440.
2. Open the PR `feat(ui): links layer and link inspector (PR 13c)`.

---

## PR 14: Surge alerts and "since your last visit"

Branch: `claude/p3-surges`.

### Task 14.1: Surges (backend)

**Endpoint:** `GET /api/news/surges?topic=` returns `[{lat, lng, place, recent, baseline, ratio, topic, lead: GlobeLead}]`, at most 8.
- **Counting:** per 1° cell:
  - `recent` = distinct normalised titles in the last 2 hours;
  - `baseline` = distinct normalised titles over the previous 7 days ÷ 83 (the number of 2-hour blocks).

  Normalise titles with the same rule as `ingestion._dedup_key`, moved to a shared helper and expressed in SQL as `lower(regexp_replace(title, '\s+[|:–—-]\s+[^|:–—-]{0,40}$', ''))`. A test proves the SQL and the Python agree on 10 titles.
- **Ratio and thresholds:**
  - `ratio = recent / max(baseline, 0.5)`;
  - a surge needs `recent ≥ 8`, `ratio ≥ 3`, and at least 3 distinct `source_name` values among the recent stories (one wire story syndicated 40 times isn't a surge).
- **Order and display:** sorted by ratio, then recent. Show `20×+` above 20 (the frontend formats it; the API returns the number).
- **Outage guard:** if no stories at all arrived in the last 2 hours, return `[]`.
- **Caching:** Redis for 300 s (data changes every 15 min) and the edge-cache helper. Target: under 0.5 s on production (0.31 s measured for the draft query).
- **Tests:**
  - Thresholds: the syndication guard, the outage guard, a cold start where the baseline is 0, and the topic filter.
  - Run the SQL on the local Postgres with marker rows for a surging cell (10 distinct titles from 4 sources in the last 2 hours, 2 in the week before) and a syndicated cell (12 copies of one title from 1 source).

Commit: `feat(api): surge detection per place`.

### Task 14.2: "Since your last visit" (backend)

**Endpoint:** `GET /api/news/delta?since=ISO` returns `{"new_stories": int, "new_places": int, "surging": int, "top": [{lat, lng, place, new, lead: GlobeLead}]}`.
- **`since`:** clamped to the last 7 days; in the future or invalid gives 422.
- **`top`:** the 5 cells with the most new distinct stories since then.
- **`surging`:** the count from 14.1's query.
- **Caching:** Redis keyed on `since` floored to 15 minutes, for 300 s.

Tests for clamping, counting and validation, plus a local SQL run. Commit: `feat(api): what changed since a visit`.

### Task 14.3: Surge ticker and surge rings

**Files:** `frontend/src/components/SurgeTicker.tsx` (+ test), `frontend/src/hooks/useSurges.ts` (+ test), `frontend/src/components/BottomBar.tsx` (third track), `frontend/src/components/Globe.tsx` (rings), `frontend/src/app/soft-orbit.css` (port `.surges`).

**Ticker:**
- **Layout:** the bottom row's third track is a `.pillbar.surges` reading `Surges · Kinshasa 2.6× · lead headline · 1 of 4`, with previous and next icon buttons. It sits right-aligned in the right track. At ≥ 1180 that track is clear of the side panel vertically, as the bottom row is now.
- **Rotation:** every 6 s. It pauses while hovered or focused, and doesn't auto-rotate with reduced motion.
- **Click:** an item flies the globe there (`flyTo`) and opens Inspect for that cell (`pointAt`, then `handlePointClick`).
- **Empty:** the ticker is hidden when there are no surges.
- **Narrow screens:** below 1180 it is hidden. The co-pilot gains a "What's surging?" quick prompt when there are surges, so the information is still reachable.

**Rings:** `ringsData` becomes the surging cells only, coloured `--signal-warning`, pulsing (motion-gated as now). Today every dot pulses; the mockup pulses alerts only.

**Polling:** surges are fetched every 5 minutes (aborted on unmount), refetched on a topic change, and only for live windows. During a replay or a dragged range the ticker hides.

**Tests:**
- Unit: rotation timing with fake timers, pausing, reduced motion, formatting `20×+`.
- e2e: with mocked surges the ticker shows, next and previous work, and a click opens Inspect for that place. `layout.spec` adds `surge-ticker` at the wide sizes, checked for overlap and spacing.

Commit: `feat(ui): surge ticker and rings`.

### Task 14.4: "Since your last visit" strip and last-visit marker

**Files:** `frontend/src/components/SinceStrip.tsx` (+ test), `frontend/src/hooks/useLastVisit.ts` (+ test), `frontend/src/components/TimelineCapsule.tsx`, `frontend/src/lib/volumeChart.ts`, `frontend/src/app/page.tsx`, `frontend/src/app/soft-orbit.css` (port `.since`).

**Last visit** (`useLastVisit`):
- At mount it reads `localStorage["orbis-last-visit"]` (an ISO string) into memory.
- It writes `now` on `visibilitychange` to hidden and on `pagehide`, and once 60 s after mount, so a visit that crashes still counts.
- Storage access is wrapped in try/catch.
- The strip only shows when the previous visit was at least 1 hour and at most 7 days ago. Missing or unreadable storage counts as a first visit and shows nothing.

**Strip:**
- **Text:** a `.pillbar.since` under the brand at ≥ 1180 (top 80, left 24) reading "Welcome back. 14 h since your visit: 1,286 new stories, 4 surging places."
- **Buttons:**
  - **Show** sets the time window to the range `[lastVisit, now]`.
  - **Top 5** expands a small list of the top cells (place, new count, lead headline). Clicking one flies there and opens it.
  - **Dismiss** (×) hides the strip for the session.
- **Narrow screens:** below 1180 the strip appears inside the bottom sheet's Co-pilot tab as a callout card, since there's no room under the brand.

**Timeline:** draws the mockup's dashed lavender last-visit line with its "Your last visit" title (`volumeChart` gains a helper that gives its x position), whenever the last visit falls inside the 7 days.

**Tests:**
- Unit: storage edge cases (missing, garbage, blocked), the 1 h and 7 d bounds, Show setting the range, dismiss.
- e2e: seed a last visit 14 h ago through `addInitScript`; the strip shows with mocked delta numbers, Show changes the timeline label to the range, and the marker exists. `layout.spec` adds `since-strip` at the wide sizes, against the brand, topics and side panel.

Commit: `feat(ui): since your last visit`.

### Task 14.5: PR 14

1. Run every check and do the visual check (seed a last visit; mock surges).
2. The controller times the surges and delta SQL on production.
3. Open the PR `feat: surge alerts and since your last visit (PR 14)`.

---

## After Phase 3

- **Phase 4** (PRs 15–18: threads, threads panel, entity tracker, investigation board) gets its bite-sized plan from what shipped here.
- **Pills that become live in Phase 4:** the hover card's entity pills and the link inspector's shared-entity pills become tracking actions in PR 17.
- **Keyboard access to places** (a listbox of visible places that drives the same hover card) is a Phase 4 accessibility item.
