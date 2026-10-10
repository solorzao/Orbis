# Orbis feature exploration: from news globe to analysis cockpit

**Date:** 2026-10-10
**Branch:** `claude/ui-revamp-exploration`
**Status:** Proposal only. No app code, infra, or live services were touched.
**Companion:** UI direction mockups are expected in `docs/redesign/ui/`. That folder did not exist when this was written. Section 6 lists what the UI should make room for.

The owner wants Orbis to feel like "a sci-fi cockpit that lets you analyze and make connections between events happening around the world (maybe image or summary previews when hovering over a certain city)". This document checks what the data and code can support today. It then proposes features with their cost, effort and risk, and orders them into a roadmap.

**Method.** I read the backend (`backend/app`), the ingestion and knowledge-graph code, the migrations, the frontend, the infra (Terraform), the docs in `docs/plans/` and `docs/project/`, and the GDELT GKG 2.1 and Event 2.0 codebooks in `docs/gdelt/`. I also checked GDELT's blog for fields added after the codebook was written, and Anthropic's pricing page.

**What I could not verify.** I did not query the production database or call the live API. Article volumes, image coverage and knowledge-graph size are therefore inferred from code. Appendix A has read-only SQL to measure them.

---

## 1. Summary

### Top recommendations

1. **Do a small foundation pass first (Phase 0).** Most cockpit features need data that ingestion already downloads and then throws away. The pass covers:
   - storing GKG themes, people, orgs, all locations, counts and quotes;
   - exposing `image_url`;
   - mapping country codes to ISO;
   - embedding every article, not just a slice;
   - hourly rollups kept beyond the 7-day article window;
   - fixing four bugs that would undermine the new features.
2. **Quick wins that deliver the vision early:**
   - a **hover recon card** with the lead image, headline, topic mix, tone and a sparkline;
   - **connection arcs v0**, links between places that appear in the same coverage, built from the existing knowledge graph;
   - a **"since your last visit"** delta view;
   - **surge pings**.
   None of these needs new LLM spend.
3. **Flagship cockpit features:**
   - **Story threads with cross-region arcs and replay.** This is the "connections" engine.
   - **Entity radar.** Track a person, org or named event across the globe.
   - **Co-pilot.** The existing agent becomes aware of what is on screen and can drive the globe.
   - **Investigation board.** Pin items and get auto-drawn links between them.
   - **Region dossier and hotspot monitor.**
4. **Consider moving from Claude Haiku 4.5 to Haiku 5.5 for all LLM calls.** Tokens are about 10x cheaper ($0.10/$0.50 vs $1/$5 per million). On Haiku 4.5, the full feature set adds about **$34/month** of LLM spend (about $19 if non-interactive work uses the Batch API), mostly thread summaries. On Haiku 5.5 it adds about **$5/month**. The switch needs small code changes; see D7.
5. **Add a global daily LLM budget guard before shipping any new AI surface.** Every endpoint is public and unauthenticated, and rate limits today are only per-IP and in-memory.

### Key data findings

| Question | Answer |
|---|---|
| Is `image_url` filled? | **Yes, partly. It is stored but never shown.** Ingestion saves GKG `V2.1SHARINGIMAGE` when present (`gdelt.py:367,382`). The API model `NewsArticle` has no `image_url`, and `_row_to_article` drops it (`routers/news.py:94`). The frontend never sees it. Coverage is unknown. Some images will be outlet logos, and `http://` URLs are accepted, which browsers block as mixed content. |
| Is `entities` filled? | **No. It is always `{}`** (`ingestion.py:85`). People and orgs are parsed from GKG but only written to the knowledge graph. `summary` is always NULL (`ingestion.py:74`). `source_language` is hard-coded to `"en"`. |
| Is the knowledge graph populated? | **Yes, by code path, every 15-minute cycle**: `populate_graph()` in `ingestion.py`, and migration 006 is applied by `deploy.yml`. It holds PERSON, ORG, LOCATION (the article's city plus country-level mentions), TOPIC and ARTICLE nodes. Row counts are unverified. |
| Is the knowledge graph exposed? | **Only to the agent**, through the `graph_traverse` and `entity_lookup` tools. There is no REST endpoint and no UI. |
| Embeddings | Title-only, and **capped at 100 per cycle** (`config.py:51`), newest first. Code comments suggest about 600 candidate articles per cycle before title scraping. Probably well under half of articles get embedded, and ones that miss their cycle are effectively never embedded. That makes semantic search and any "related stories" feature patchy. |
| Unused GKG data | A lot. Themes are parsed and then discarded (`gdelt.py:366`). Only the first tone value is kept. Additional city locations are dropped. Counts (killed, wounded, arrested, protesters) are not parsed, nor are quotations, named events and laws, amounts, related images, video embeds, or GDELT's own **page title**, authors, outbound links and precise publish time. Section 2.3 lists them all. |

### Surprises

- **GDELT already provides article titles.** Since September 2019, GKG's extras field carries `<PAGE_TITLE>`. Ingestion instead scrapes `<title>` from about 600 publisher pages every 15 minutes, 30 at a time, from a 0.25 vCPU container, and drops any article whose scrape fails. Parsing `PAGE_TITLE` (with scraping as a fallback) would save CPU and bandwidth and should keep more articles.
- **Country codes are FIPS 10-4, not ISO.** GKG location codes are FIPS (`gdelt.py:376`). The agent's `keyword_search` tool advertises a "Two-letter country code" (`agent.py:76`), and an LLM will pass ISO codes. In FIPS, "CN" is Comoros (China is "CH"), "RS" is Russia (ISO RS is Serbia), "ES" is El Salvador (Spain is "SP") and "IS" is Israel (ISO IS is Iceland). Country-filtered agent answers are silently wrong today, and any country-level feature would inherit the error.
- **The agent's globe actions never fire.** The synthesis prompt asks for `{"lat","lng","label"}` (`agent.py:206`). The frontend only acts when `action.type === "flyTo"` (`page.tsx:80`). Unless the model adds a `type` field on its own, the camera never moves. Only clicking a citation moves it.
- **Cluster summaries can belong to a neighbouring cell.** Globe cells are 1 degree (`news.py:152`), but the summary cache key snaps to a 2-degree grid (`ai_summary.py:50-53`). Up to four adjacent cells therefore share one cached summary. The summary endpoint also ignores the time window, so browsing "3 days ago" shows a summary of today's articles.
- **Old windows in busy cells come back empty.** `_fetch_cell_articles` asks SQL for the newest 50 articles in the cell and only then filters by time in Python (`news.py:174`, `database.py:171`). For a busy cell such as New York, a window several days back often returns nothing. "Load more" also caps at 50 even when the dot says "100 stories".
- **Topic filtering only considers the newest story in each cell.** Each cell's topic is that of its most recent article (`database.py:300`), so the "Conflict" filter hides cells whose latest story is about something else.
- **Synthesis uses Haiku, not Sonnet.** The agent docstring says Sonnet does synthesis, but both steps call Haiku. The unused default `sonnet_model_id` is `claude-sonnet-4-5-20241022`, which is not a real model ID.
- **The installed `globe.gl` (2.45) already supports every primitive the cockpit needs:** arcs with animated dashes, heatmaps, polygons, HTML-element markers, labels, paths and particles, plus `onPointHover` and `getScreenCoords` for anchored hover cards. No new 3D library is needed.

---

## 2. Data audit

### 2.1 What an article row holds today

| Column | Source | Populated? | In API response? | Notes |
|---|---|---|---|---|
| `title` | Scraped page `<title>` | Yes | Yes | Articles whose scrape fails are dropped. GKG `PAGE_TITLE` could replace this. |
| `summary` | none | **Never** (always NULL) | Yes (always null) | Available for per-article AI blurbs, but the LLM cost would be high. |
| `source_url`, `source_name` | GKG docid, domain | Yes | Yes | |
| `source_language` | hard-coded `"en"` | Constant | Yes | Only the English GKG feed is read. |
| `published_at` | GKG `V2.1DATE` | Yes | Yes | This is GDELT's 15-minute batch time, not the true publish time. `PAGE_PRECISEPUBTIMESTAMP` gives the real time for about a third of articles. |
| `latitude`/`longitude`/`location`/`region` | First city-level entry in `V1LOCATIONS` | Yes | Yes | V1 is a deduplicated list with no position info, so "first" is not "most important". `V2ENHANCEDLOCATIONS` has character offsets and repeats, which would allow ranking by mentions. |
| `country_code` | GKG location CountryCode | Yes | Yes | **FIPS 10-4, not ISO.** |
| `topic_tags` | Azure ML function (NYT RoBERTa plus keywords) | Yes | Yes | Tags: politics, economy, technology, health, sports, conflict, environment, general. The frontend has no Sports or General topic, so those show as "All". |
| `sentiment_score` | Azure ML (DistilBERT, title only) | Yes | Yes | GDELT tone is only used if ML classification is disabled. |
| `entities` | none | **Never** (`{}`) | Yes (empty) | People and orgs go only to the knowledge graph. |
| `embedding` | OpenAI `text-embedding-3-small`, title only | **Partial** (100 per cycle) | No | 1536-dim with an HNSW index. On a B1ms server (2 GiB RAM), the index will outgrow memory as coverage rises; see D4. |
| `image_url` | GKG `V2.1SHARINGIMAGE` | **Partial** | **No** | Some are publisher logos. Plain `http` URLs are accepted. |

### 2.2 Knowledge graph (`kg_nodes` / `kg_edges`)

- **Populated every cycle** by `knowledge_graph.populate_graph()` and pruned when articles age out: edges cascade on article delete, then orphaned nodes are purged.
- **Nodes:** ARTICLE (keyed by title, so syndicated copies collapse into one node), PERSON, ORG, LOCATION (both the article's city and country-level mentions, with lat/lng metadata) and TOPIC.
- **Edges:** MENTIONED_IN (entity to article), LOCATED_AT (article to city), ABOUT_TOPIC, and CO_MENTIONED (between every pair of entities in an article; weight increases on repeats).
- **Exposure:** agent tools only.
- **Issues that matter for new features:**
  - **Expensive writes.** CO_MENTIONED is O(n²) per article, and every write is its own awaited statement (an UPDATE, then an INSERT if no row changed). That means thousands to tens of thousands of round trips per cycle on a burstable DB.
  - **Fragile weights.** A CO_MENTIONED edge stores the `article_id` of the first article that created it, with `ON DELETE CASCADE`. When that article is purged, the whole accumulated co-mention history disappears with it.
  - **Duplicate pairs.** Pairs are stored in insertion order, so (A,B) and (B,A) can both exist.
  - **Noisy names.** GDELT's own codebook recommends discarding names that appear only once or twice. No threshold is applied.
  - **Recommendation:** for location and trend features, put people, orgs and names on the article row as GIN-indexed arrays and compute co-mentions on demand. Keep the graph for agent traversal, or slim it down; see D2.

### 2.3 What GKG 2.1 provides that we drop

Field numbers are 0-based tab columns in the GKG 2.1 file that ingestion already downloads every 15 minutes.

| # | Field | Content | Today | What it unlocks |
|---|---|---|---|---|
| 5/6 | `V1COUNTS` / `V2.1COUNTS` | Typed counts with an object and location, such as `KILL#47#jihadists#...`. Types are mostly AFFECT, ARREST, KIDNAP, KILL, PROTEST, SEIZE, WOUND. | Not parsed | Hotspot monitor, incident tallies in the dossier |
| 7 | `V1THEMES` | 300+ GDELT themes (for example PROTEST, TERROR, ELECTION, ECON_INFLATION, NATURAL_DISASTER_FLOOD) plus World Bank and CrisisLex taxonomies | **Parsed, then discarded** (`gdelt.py:366`) | Thread matching, precise filters, dossier "what it's about", watchlists by theme |
| 8 | `V2ENHANCEDTHEMES` | Themes with character offsets | Not parsed | Linking a theme to the nearest location or person |
| 9 | `V1LOCATIONS` | All locations (FIPS country, ADM1, lat/lng) | First city only, plus countries into the graph | Multi-place arcs (city to city) |
| 10 | `V2ENHANCEDLOCATIONS` | Locations with offsets and repeats, plus ADM2 | Not parsed | Choosing the primary location by mention count or dateline |
| 11/13 | `V1PERSONS` / `V1ORGANIZATIONS` | Names | Knowledge graph only | Entity radar, chips, watchlists |
| 15 | `V1.5TONE` | tone, positive, negative, polarity, activity, self-reference, word count | First value only, used only as a fallback | "Charged" coverage (high polarity), filtering out short or empty pages by word count |
| 16 | `V2.1ENHANCEDDATES` | Dates mentioned in the article | Not parsed | Look-ahead calendar of upcoming elections and summits (stretch) |
| 17 | `V2GCAM` | 2,300+ emotion and content dimensions | Not parsed | Emotion layers such as anxiety or anger (stretch; the field is large) |
| 18 | `V2.1SHARINGIMAGE` | og:image or twitter:image URL | Stored, not exposed | Hover card, panels |
| 19 | `V2.1RELATEDIMAGES` | In-article images GDELT judged relevant (alpha quality) | Not parsed | Image strip in dossier and thread panels |
| 20/21 | `V2.1SOCIALIMAGEEMBEDS` / `SOCIALVIDEOEMBEDS` | Embedded social images and YouTube/Vimeo videos | Not parsed | "Media" tab in the thread panel |
| 22 | `V2.1QUOTATIONS` | Quotes with the introducing verb ("said", "denied") | Not parsed | "Voices": quote cards and the entity dossier |
| 23 | `V2.1ALLNAMES` | All proper names, including named events, laws and movements (for example "Paris Agreement", "COP30") | Not parsed | Strong thread keys; trackable "named events" in the entity radar |
| 24 | `V2.1AMOUNTS` | Numeric amounts with objects ("2000000 displaced civilians", "$1.25 billion") | Not parsed | Key figures in the dossier and threads |
| 25 | `V2.1TRANSLATIONINFO` | Source language (translingual feed only) | n/a | Multilingual perspective lens |
| 26 | `V2EXTRASXML` | `<PAGE_TITLE>` (since 2019-09-22), `<PAGE_AUTHORS>`, `<PAGE_LINKS>`, `<PAGE_PRECISEPUBTIMESTAMP>`, `<PAGE_ALTURL_AMP>` | Not parsed | **Titles without scraping**, author bylines, article-to-article citation links, accurate timelines |

The 2016 GDELT blog post gives rough coverage for the extras fields: links about 55%, authors about 53%, precise timestamp about 33%, AMP URL about 36%. Titles are HTML-entity encoded and sometimes include the site name, so the existing `_is_usable_title` and outlet-suffix stripping should still run on them.

### 2.4 GDELT feeds not used

- **Events 2.0 export**, the `export.CSV.zip` line in the same `lastupdate.txt`. These are machine-coded "Actor1 did X to Actor2" events with:
  - actor and action geolocation;
  - `QuadClass` (verbal or material cooperation, verbal or material conflict);
  - `GoldsteinScale` from -10 to +10;
  - `NumMentions`, `NumSources`, `NumArticles` and `AvgTone`;
  - `SOURCEURL`, which can be joined to our articles.

  This is a structured source for **country-to-country relation arcs** and conflict intensity, with no LLM and no clustering needed.
- **Mentions table** (`mentions.CSV.zip`). Maps each event to every article mentioning it, with a confidence score. It is a ready-made "these articles cover the same event" signal, but it is large.
- **Translingual feed** (`lastupdate-translation.txt`, also every 15 minutes). GKG for machine-translated non-English coverage in about 65 languages. Enables "how is this story covered elsewhere", but it at least doubles ingestion volume and cost.
- **GDELT DOC 2.0 API**, free. Timelines and tone charts for a query over about 3 months. It could give the entity radar history beyond our 7-day window, but it is rate-limited, sometimes slow, and the GEO API was already abandoned once (`docs/plans/2026-02-28-gdelt-data-pipeline.md`). Optional and cached.

### 2.5 Data-quality issues and bugs to fix before building on them

| # | Issue | Where | Why it matters for new features |
|---|---|---|---|
| B1 | Globe actions schema mismatch (`label` with no `type`) | `agent.py:206`, `page.tsx:80` | The co-pilot cannot drive the globe |
| B2 | Summary cache key uses a 2-degree grid; globe cells are 1 degree | `ai_summary.py:50-53` vs `news.py:152` | Hover cards and panels can show a neighbouring cell's summary |
| B3 | Summary ignores the time window | `routers/news.py` `get_cluster_summary` | Time travel and the delta view show the wrong summary |
| B4 | `LIMIT 50` applied before the time filter | `news.py:174`, `database.py:171` | Old windows in busy cells come back empty; "Load more" caps at 50 |
| B5 | FIPS codes used as if they were ISO | `gdelt.py:376`, `agent.py:76` | Any country feature or agent country filter is wrong |
| B6 | Embedding cap of 100 per cycle | `config.py:51`, `embeddings.py` | Threads, related stories and scoped search miss most articles |
| B7 | Cell topic is that of the newest article only | `database.py:300` | Topic filter and topic colours mislead |
| B8 | `http://` image URLs accepted | `gdelt.py:382` | Mixed-content blocking on an HTTPS site |
| B9 | Responses read with `response.content[0].text` | `agent.py:436,621`, `ai_summary.py:136` | Breaks on Haiku 5.5, where a thinking block can come first (D7) |
| B10 | Agent "streaming" sends the finished answer in 20-character chunks | `routers/agent.py` | Time to first token equals the full generation time; the co-pilot will feel slow |
| B11 | Knowledge-graph CO_MENTIONED weight loss and duplicate pairs | `knowledge_graph.py:200-225` | Entity "connections" are unreliable |

### 2.6 Capacity and cost baseline

- **Compute.** One Container App at 0.25 vCPU and 0.5 GiB, min = max = 1 replica. It serves the API *and* runs ingestion: GKG download and parse, about 600 title scrapes, ML function calls, upserts, knowledge-graph writes and embeddings. Any heavier ingestion competes with request latency.
- **Database.** Azure PostgreSQL Flexible B1ms (burstable, 1 vCore, 2 GiB RAM, 32 GiB storage) with PostGIS, pgvector and pg_trgm. Burstable CPU credits are the constraint to watch. Storage has a lot of headroom.
- **ML.** Azure Functions Flex Consumption, called with each cycle's titles. Cost scales with article count.
- **Frontend.** Vercel. Every browser API call goes through the Next.js catch-all proxy, which is a function invocation. Hover-triggered fetches would multiply invocations, so preview data should ride in the main globe payload, and public GET responses could carry `s-maxage` (the proxy already passes `cache-control` through).
- **Current LLM use** (all Haiku 4.5):
  - Cluster summary: about 1k input and about 120 output tokens, roughly $0.0016 per call, cached 6 hours.
  - Agent question: a planning call plus a synthesis call, about 6.5k input and 750 output tokens, roughly **$0.01 per question**.
  - Rate limits: 10 AI calls and 60 data calls per minute per IP, in memory.
- **Pricing used in this document** (Anthropic pricing page, retrieved 2026-10-10; prices per million tokens, input / output):

| Model | Standard | Batch API (50% off) | Cache hit |
|---|---|---|---|
| Claude Haiku 4.5 (current) | $1 / $5 | $0.50 / $2.50 | $0.10 |
| Claude Haiku 5.5 (prompts up to 100k tokens) | $0.10 / $0.50 | $0.05 / $0.25 | $0.01 |
| Claude Sonnet 5.5 | $2 / $10 | $1 / $5 | $0.10 |

- **Embeddings.** OpenAI `text-embedding-3-small` at about $0.02 per million tokens (verify current price). Embedding every title plus a few names costs well under $1–2/month.

---

## 3. Phase 0: foundation work

These items are mostly invisible, but most features below depend on them.

### D1. Expose what we already store (S)
- Add `image_url` to `NewsArticle` and to the cell payload: the lead image is the newest article in the cell that has an HTTPS, non-logo image.
- **Logo filter heuristic:** treat an `image_url` as a logo if it appears on 3 or more articles from the same domain in 24 hours.
- Upgrade `http://` URLs to `https://` or drop them.
- Add per-cell `avg_sentiment` and a topic histogram (`topic_mix`) to `/api/news`. This also fixes B7.
- **Cost:** none. **Risk:** hotlinking publisher images exposes visitors' IPs to publisher CDNs. Use `referrerpolicy="no-referrer"` and lazy loading. Do not route arbitrary third-party images through Next/Image, which would act as an open proxy and incur image-optimization costs.

### D2. Persist the GKG fields we already download (M)
- **Migration sketch:**
  ```sql
  ALTER TABLE articles
    ADD COLUMN country_iso TEXT,
    ADD COLUMN themes  TEXT[] DEFAULT '{}',
    ADD COLUMN persons TEXT[] DEFAULT '{}',
    ADD COLUMN orgs    TEXT[] DEFAULT '{}',
    ADD COLUMN names   TEXT[] DEFAULT '{}',   -- V2.1ALLNAMES, top ~15
    ADD COLUMN thread_id UUID;
  CREATE INDEX ON articles USING GIN (persons);
  CREATE INDEX ON articles USING GIN (orgs);
  CREATE INDEX ON articles USING GIN (names);
  CREATE INDEX ON articles USING GIN (themes);
  -- reuse the empty `entities` JSONB for the rest:
  -- {locations:[{name,cc,lat,lng,type,mentions,first_offset}], counts:[{type,n,object,cc,lat,lng}],
  --  quotes:[{verb,text}] (<=3), amounts:[...] (<=5), tone:{tone,pos,neg,polarity,words},
  --  media:{related:[...<=3], video:[...<=2]}, authors, links_n, pub_ts_precise}
  ```
- Parse `V2EXTRASXML` for `PAGE_TITLE`, and scrape only when it is missing. Re-run the existing title filters on it.
- Choose the primary location from `V2ENHANCEDLOCATIONS`: the city mentioned most often, ties broken by earliest offset.
- Map themes to about 40 display themes (strip the `WB_`, `TAX_FNCACT_` and `CRISISLEX_` prefixes and keep raw values for matching).
- Make knowledge-graph writes set-based (`INSERT ... SELECT FROM unnest(...)`). Either drop per-pair CO_MENTIONED rows in favour of on-the-fly co-mention queries over the arrays, or store canonical (min, max) pairs without `article_id`.
- **Cost:** storage roughly 1–2 KB per article, comfortably within 32 GiB. **Risk:** more articles survive once titles come from GDELT. That means more ML function calls, rows and embeddings, so consider a minimum word count from the tone field.

### D3. Country codes (S)
- Add a static FIPS-to-ISO table (about 250 rows) and a `country_iso` column, backfilled once.
- Change the agent tool to accept ISO and translate. Expose ISO and display names in the API.

### D4. Embed every article (S)
- Raise the cap to 500–1,000 per cycle; one OpenAI request takes up to 2,048 inputs.
- Embed `title + top names/persons/orgs` rather than the bare title.
- **Shrink the vectors:** `text-embedding-3-small` supports a `dimensions` parameter. 512 dimensions, or pgvector `halfvec`, cuts index RAM 3–6x, which matters on a 2 GiB B1ms. The 7-day window re-embeds everything naturally after the column change.
- **Cost:** well under $1–2/month.

### D5. Rollups that outlive the 7-day article window (S/M)
- **Tables:**
  - `cell_hourly(cell_lat, cell_lng, hour, n, n_sources, sent_sum, topics jsonb)`
  - `country_daily(iso, day, n, sent_sum, topics, counts jsonb, top_themes)`
  - `entity_daily(type, name, day, n, countries text[])`
- Update them incrementally at the end of each cycle from that cycle's rows. Keep 30–90 days.
- These feed baselines for surge detection, trend sparklines, mood-over-time layers, the "since last visit" view and long-range dossiers.
- **Cost:** tens to hundreds of MB.

### D6. Fix B1–B11 (S)
B1–B4 and B7–B9 should be fixed before shipping any feature in this document. B10 and B11 can be fixed together with the co-pilot (F3) and the entity radar (F2).

### D7. LLM guardrails and model choice (S)
- **Global daily token budget.** A Redis counter by date, checked before every LLM call. When it runs out, fall back to cached or no-AI responses with an explicit "AI paused" state in the UI. Keep the Anthropic console spend limit as a backstop.
- **Move non-interactive generation to the Message Batches API** (50% off). This covers thread synopses, digests and dossier pre-generation.
- **Optional: move to Claude Haiku 5.5.** About 10x cheaper per token. Required changes:
  - read text blocks by `type`, because thinking blocks can come first (B9);
  - raise `max_tokens` (256 is too tight once thinking counts against it);
  - set `output_config.effort` to `"low"` for summaries;
  - check summary quality on a sample.

  The newer tokenizer produces about 30% more tokens for the same text, and the price difference still dominates. Haiku 5.5 also has safety classifiers that can decline a request with no server-side fallback, so handle `stop_reason == "refusal"`. Conflict news makes refusals worth testing for.

### D8 (optional). Move ingestion off the request path (M)
If Phase 0 and thread clustering make the cycle heavy, run ingestion as a scheduled Azure Container Apps Job, or raise the API container to 0.5 vCPU. On Consumption this is likely a few dollars a month; confirm with the Azure pricing calculator.

---

## 4. Feature proposals

Effort scale: **S** is about 1–3 focused days, **M** about 1–2 weeks, **L** more than 2 weeks, all for a single developer. LLM cost is per month, assuming about 1,000 sessions and 300 co-pilot questions a month. Section 7 has the full table.

### A. Quick wins

#### Q1. Hover recon card ("city preview")

**User sees and does.**
- **Desktop:** hovering a dot for about 150 ms opens a HUD card next to it. The card shows:
  - place name and country;
  - "37 stories, last 24h";
  - lead-story image (falling back to a topic glyph);
  - lead headline (2 lines), source and age;
  - topic-mix bar;
  - tone meter;
  - 24-hour sparkline;
  - up to 3 entity chips;
  - the cached AI brief, if one exists, labelled as AI.

  Clicking opens the full panel.
- **Mobile:** a tap shows the card; "Open" on the card opens the panel.

**Data and backend.**
- **Phase A (S).** Extend `get_globe_points()` so each cell includes `lead {title, source, published_at, image_url}`, `topic_mix`, `avg_sentiment` and `place` (the most common region name in the cell, not the newest). That is about 400 bytes per cell, roughly 60 KB gzipped for 500 cells.
- **Phase B (M).** Add `GET /api/news/preview?lat&lng&start&end` → `{spark:[24 ints], top_entities:[{name,type,n}], brief:string|null}`. Call it on hover-dwell of 400 ms or more, cache it client-side per cell, and keep it in Redis for 5 minutes. **Never generate an LLM summary on hover**; only read the existing summary cache (after fixing B2 and B3).

**Frontend surface.** A floating HUD card anchored to the dot via `globe.getScreenCoords()` on `onPointHover`. Use a React overlay rather than the `pointLabel` HTML string so it can animate and contain images. Keyboard focus should be able to move between dots and show the same card.

**Effort.** Phase A S; Phase B M (needs D2 for entities and D5 for the sparkline).

**Cost.** No LLM by default. Optional pre-generation of briefs for the top 10 cells every 3 hours: about $3.8/month on Haiku 4.5 (about $1.9 with batching), about $0.5 on Haiku 5.5.

**Risks.**
- Image hotlinking: privacy, broken links, logos.
- **Graphic war imagery on hover.** Blur images for conflict-tagged articles until clicked, or offer a setting.
- Hover-rate fetches going through Vercel and the 60/min data limit, mitigated by Phase A carrying most data in the main payload.

#### Q2. Connection arcs v0: place-to-place co-coverage

**User sees and does.**
- A "Links" layer draws animated arcs between places that appear in the same stories, for example an article located in Washington that mentions Ukraine.
- Arc thickness is the number of linking articles, colour is the dominant topic, and the dashes flow from the reporting place to the mentioned place.
- Hovering an arc shows "41 stories link Washington and Ukraine, mostly politics".
- Clicking an arc opens a **link inspector**: the linking articles, shared entities, and an "Explain this link" button that runs an AI explanation on demand.
- A "Surprising links" toggle ranks by lift rather than raw count, which hides the obvious hubs.

**Data and backend.**
- **v0 works on today's data.** Join articles (primary city and country) to knowledge-graph MENTIONED_IN edges from country-level LOCATION nodes, which carry lat/lng. Keep pairs where the two country codes differ, and aggregate by country pair within the time window.
- After D2, use the article `locations` JSON for city-to-city links.
- **Endpoints:**
  - `GET /api/links?start&end&topic&rank=count|lift&limit=40` → `[{a:{name,lat,lng,iso}, b:{...}, n, lift, topic, avg_sentiment, lead_title}]`, cached in Redis for 5–10 minutes.
  - `GET /api/links/detail?a=US&b=UP&start&end` → articles and shared entities.
  - `POST /api/links/explain` → AI explanation in 2–3 sentences, cached per pair and window for 3 hours, in the `ai` rate-limit group.
- Needs a composite index on `kg_edges(rel_type, article_id)` or a rollup table if the joins are slow.

**Frontend surface.** Globe `arcsData` (animated dash), arc hover label, link inspector panel, a layer toggle, and a count/lift switch.

**Effort.** S/M.

**Cost.** No LLM to draw arcs. Explanations about $0.9/month on Haiku 4.5, about $0.13 on Haiku 5.5.

**Risks.**
- Anglophone feed bias (most articles mention the US or UK), so cap arcs per origin and default to lift ranking.
- Co-coverage is not causation; the UI copy should say "covered together".
- Visual clutter; cap at about 40 arcs.

#### Q3. "Since your last visit"

**User sees and does.**
- A returning visitor gets a strip reading "SINCE YOUR LAST VISIT: 14h". It shows the number of new stories and surging places, and lists 5 top developments; clicking one flies the globe there.
- Cells with new activity glow in a "delta" colour.
- "Replay what I missed" animates the time slider from the last visit to now.

**Data and backend.**
- `GET /api/news/delta?since=ISO` (capped at 7 days) → `{new_articles, cells:[{lat,lng,new,baseline_rate,ratio,lead}], top:[...]}`, built from `cell_hourly` (D5) and articles.
- Optional `GET /api/digest/latest`: a global "what changed" paragraph generated at most once an hour, lazily, and shared by every visitor (never per user).

**Frontend surface.** The last-visit timestamp lives in `localStorage` (no accounts). Needs a HUD strip, a delta overlay style on cells, and a replay control.

**Effort.** S (no digest) / M (with digest and replay).

**Cost.** Digest at most 720 calls/month: about $4 on Haiku 4.5, about $0.5 on Haiku 5.5.

**Risks.** Few. Treat a cleared `localStorage` as a first visit.

#### Q4. Surge pings

**User sees and does.**
- When a place's coverage spikes, its dot emits a "surge" ring burst.
- An alert ticker shows items like "SURGE: Port-au-Prince, 6x normal, protests". Clicking an item flies there.

**Data and backend.**
- At the end of each cycle, compare the last 1–2 hours per cell and per country against the trailing same-hour baseline from D5.
- Count **distinct normalised titles and domains**, so one wire story syndicated 40 times does not trigger a surge.
- Write results to `alerts(id, kind, place, ratio, started_at, lead_article_id, themes)`. `GET /api/alerts?since` returns them.
- Cold start: use the 7-day article window until the rollups have history.

**Frontend surface.** Ring bursts (globe `ringsData`, already used), an alert ticker in the HUD, and an alerts drawer.

**Effort.** S/M.

**Cost.** None. Optional one-line AI captions for about 50 alerts/day: about $1.7/month on Haiku 4.5, about $0.2 on Haiku 5.5.

**Risks.** False positives from syndication and from GDELT feed hiccups; thresholds need tuning.

#### Q5. Globe layers: intensity and mood

**User sees and does.**
- A layer switcher: Dots (current), **Intensity** (heatmap of volume), **Mood** (hexes coloured by average headline tone on a diverging scale) and **Topics**.
- Works with the time slider. With D5 it can scrub 30 days instead of 7.

**Data and backend.** `/api/news` gains `avg_sentiment` (from D1). For history beyond 7 days, add a `cell_hourly` endpoint.

**Frontend surface.** Layer switcher in the HUD; globe `heatmapsData` and `hexBinPointsData` (already used).

**Effort.** S. **Cost.** None.

**Risk.** Sentiment comes from headlines only and is noisy. Label it "headline tone", not "mood of a nation".

#### Q6. Shareable view links (S)

**User sees and does.** A URL that captures the camera, time window, layer and selected cell, thread, entity or link. Good for portfolio demos and social posts.

**Data and backend.** None.

**Risk.** Links to articles older than 7 days must degrade gracefully.

### B. Flagship cockpit features

#### F1. Story threads and cross-region arcs (the connections engine)

**User sees and does.**
- Articles are grouped into **threads**: the same developing story across outlets and places.
- **"Active threads" rail:** threads sorted by velocity, each with a size badge and the countries it touches.
- **Thread panel:**
  - AI title and a 2–3 sentence synopsis;
  - status (emerging, developing, fading);
  - first seen, plus article, outlet and country counts;
  - a mini map of member places;
  - an hourly timeline strip coloured by tone;
  - key entities and themes;
  - quotes and key figures (after D2);
  - image strip.
- **Globe:** the "Threads" layer draws arcs from where a thread first appeared to where it spread.
- **"Replay spread"** animates the first report, then each new place lighting up in order of publication.
- **Cluster panel:** shows "Part of thread: X (also in Kyiv, Brussels, Washington)". Clicking draws its arcs.

**Data and backend.**
- **Table:** `threads(id, title, synopsis, centroid vector(512), first_seen, last_seen, n_articles, n_sources, countries text[], places jsonb, top_entities text[], themes text[], status, summarized_at, summarized_n)` plus `articles.thread_id`.
- **Assignment** (an ingestion step after embeddings):
  1. For each new article, take the 5 nearest centroids among threads active in the last 72 hours. That set is small enough for a brute-force scan; no ANN index needed.
  2. Score = cosine similarity + a bonus for overlapping `names`, `persons` and `orgs`, + a small bonus for overlapping themes.
  3. Join the best thread if the score clears a threshold; otherwise start a new thread.
  4. Update the centroid as a running mean, and update the counters.
  5. A nightly pass merges near-duplicate threads.
- **Summaries:** for threads with 5 or more articles and 2 or more countries, or the top 50 by velocity, generate title and synopsis hourly through Message Batches. Regenerate when a thread grows by 50%. Prompt only with headlines and sources, and require the synopsis to stay within them.
- **Endpoints:**
  - `GET /api/threads?start&end&min_countries&topic&limit=20` → list with `places` (ready for arcs);
  - `GET /api/threads/{id}` → detail, timeline buckets, entities, paginated articles;
  - `GET /api/threads/{id}/spread` → ordered `(time, place)` events for replay.
- Tune the threshold offline first: label about 100 article pairs as same story or not.

**Frontend surface.** Thread rail, thread panel, arcs layer, replay controls on the time slider, and a "part of thread" chip in the cluster panel.

**Effort.** L (M for a v1 without the merge pass, quotes or media).

**Cost.**
- DB CPU per cycle is modest because matching runs against threads, not all articles.
- LLM: about 225 synopses/day, roughly $15/month on Haiku 4.5 ($7.6 batched) or $2 on Haiku 5.5 ($1 batched).
- Embeddings: under $2/month.

**Risks.**
- Generic headlines ("Police arrest man") over-merge, so require entity or name overlap and skip very short titles.
- Threshold drift.
- Burstable DB credits during heavy cycles.
- Synopsis hallucination: keep it grounded and show the source list.
- Batch results usually arrive well within an hour but are not guaranteed, so the panel needs a "synopsis pending" state that falls back to the lead headline.
- "Same story" is not causation.

**Depends on.** D2, D4 (and D6).

#### F2. Entity radar (track a person, org or named event across the globe)

**User sees and does.**
- A "Track..." search with autocomplete covers people, orgs and named events such as "COP30" or "Paris Agreement". Clicking any entity chip anywhere does the same.
- **Globe:** everything else dims. Places where the entity appears light up, sized by mentions, with arcs from the entity's centre of gravity.
- **Entity dossier panel:**
  - mentions per day (7 days, or 30 with D5);
  - top places;
  - **co-mention network**: a small force graph of about 15 nodes; clicking a node pivots to that entity;
  - tone by region;
  - latest headlines;
  - quotes (after D2, attribution approximate).
- A **"Trending entities"** list in the HUD, ranked by mention velocity against baseline.

**Data and backend.**
- **v0 works on today's knowledge graph:** `entity_lookup` SQL already returns connections and articles.
- **v1 after D2:** GIN array queries (`WHERE persons @> ARRAY[$1]`) aggregated by cell give the geodistribution. Co-mentions are computed on demand by unnesting the matched articles' `persons`/`orgs` and counting. `entity_daily` (D5) provides trends and autocomplete.
- **Endpoints:**
  - `GET /api/entities/search?q=` (pg_trgm);
  - `GET /api/entities/trending?hours=24`;
  - `GET /api/entities/{type}/{name}` → `{counts, timeline, places:[{lat,lng,name,n,avg_sentiment}], co_mentions:[{name,type,n}], articles:[...]}`.
- Optional cached one-line "who is this" blurb per entity per day.

**Frontend surface.** Search in the HUD, dim-and-highlight globe mode, entity dossier panel with a mini network graph, entity chips everywhere (hover card, panels, thread panel).

**Effort.** M.

**Cost.** None required. Blurbs about $4/month on Haiku 4.5, $0.5 on Haiku 5.5.

**Risks.**
- GDELT name noise and aliases ("Biden" vs "Joe Biden"): use the frequency threshold from the codebook and a small manual alias map for the top 200 names.
- Implying wrongdoing by association: the copy should say "appears in the same coverage as", never "linked to".

**Depends on.** D2 (v1), D5 (trends).

#### F3. Co-pilot: an agent that sees the screen and drives the globe

**User sees and does.**
- The agent becomes a docked **CO-PILOT** console. Context-aware quick actions: "Brief me on this region", "What connects these two places?", "What's new in this thread?"
- Answers stream immediately and end with **action chips**: "Fly to Kyiv", "Show links", "Open thread", "Set window to last 6h", "Track entity". Chips run on click; flying the camera can run automatically.
- **Proactive callouts.** When a surge or a fast-growing thread crosses a threshold, the console offers "Coverage of X is spiking. Brief me?" Nothing runs until the user clicks.

**Data and backend.**
- `AskRequest.context = {view:{lat,lng,altitude}, time:{start,end}, selection:{type:'cell'|'thread'|'entity'|'link', ref}, pinned:[ids]}`.
- **Retrieval tools gain filters and new tools:**
  - `semantic_search(query, start, end, lat, lng, radius_km, country_iso)`. This implements the spec's "time travel scoped to a region".
  - New tools: `thread_lookup`, `entity_profile`, `region_stats` and `links_between`.
- **Typed actions:** `{type: flyTo|highlight|showLinks|openThread|openEntity|setTime|setLayer, ...}`, enforced with structured outputs. Only whitelisted, non-destructive actions are allowed, and the model never supplies URLs to open (fixes B1).
- **Real token streaming** from the synthesis call (fixes B10), with actions delivered in a final structured event.

**Frontend surface.** Docked console (left rail or bottom drawer), quick-action buttons that depend on the current selection, an action-chip row per answer, a "thinking" HUD showing the tools in use (already exists), and proactive callout toasts.

**Effort.** M.

**Cost.**
- About $0.01 per question on Haiku 4.5, about $0.0015 on Haiku 5.5, about $0.02 with Sonnet 5.5 synthesis.
- At 300 questions/month: about $3.5 / $0.5 / $6.
- Callouts cost nothing until clicked.

**Risks.**
- **Prompt injection:** `read_article` pulls untrusted web text into context, which is why actions must stay whitelisted and harmless.
- Latency on 0.25 vCPU.
- Public endpoint cost abuse, so D7 is required.

**Depends on.** D6 (B1, B10), D3; F1 and F2 for their tools.

#### F4. Investigation board ("evidence wall")

**User sees and does.**
- A **Board** workspace (full-screen overlay or split view). Pin anything: articles, places, entities, threads, links.
- Pins appear as cards in a node-link layout. The system **draws typed edges between them automatically**:
  - same thread;
  - shared person, org or name (with a label);
  - same place or co-coverage link;
  - close in time.
- The globe mirrors the board: pins are highlighted and edges become arcs.
- **"Analyze"** produces an AI memo (possible links, contradictions, open questions) that cites the pins.
- Export as Markdown; share via a link encoding up to 20 pin IDs.

**Data and backend.**
- `POST /api/board/links {items:[{type,id}]}` → edges computed in SQL from the array, thread and country overlaps. No LLM.
- `POST /api/board/analyze {items}` → LLM memo, `ai` rate group.
- The board itself lives in `localStorage`.

**Frontend surface.** A board canvas (node-link with draggable cards, typed edge styles, legend), pin buttons on every card and chip, a board badge in the HUD, an analysis memo panel. On mobile, a list view rather than a canvas.

**Effort.** M (mostly frontend).

**Cost.** About 100 analyses/month: about $0.65 on Haiku 4.5, $0.1 on Haiku 5.5.

**Risks.**
- Pins expire after 7 days of retention, which breaks shared boards; snapshot pins (titles and URLs) into the board state.
- Speculative AI connections: the memo must cite pins and flag uncertainty.

**Depends on.** D2; F1 for thread edges.

#### F5. Region dossier and hotspot monitor

**User sees and does.**
- Click a country (polygon highlight) or "Dossier" from the hover card.
- **Dossier panel:**
  - 7- or 30-day volume and tone trend;
  - top threads and entities;
  - **reported incident tallies** (killed, wounded, arrested, protesters, from GKG COUNTS), clearly labelled "as reported in coverage, unverified";
  - key figures (amounts);
  - notable quotes;
  - image strip;
  - AI situation brief, cached for 3 hours.
- **Hotspot monitor:** a ranked list of countries by an intensity index (volume surge × negativity × share of conflict/crisis themes × reported counts), with escalation arrows. A "Hotspots" globe layer pulses the top 10.

**Data and backend.**
- `country_daily` (D5) with count aggregates. **Use per-thread or per-day maximums, not sums,** because 30 articles repeating "47 killed" must not become 1,410.
- **Endpoints:** `GET /api/regions/{iso}/dossier?days=7`, `GET /api/hotspots?window=24h`.
- A Natural Earth 110m countries GeoJSON served statically by the frontend.

**Frontend surface.** Country polygon layer with hover and select, dossier panel (dense, scrollable sections), hotspot list with sparklines, hotspots globe layer.

**Effort.** M.

**Cost.** About 300 briefs/month: about $1.4 on Haiku 4.5, $0.2 on Haiku 5.5.

**Risks.**
- GDELT counts are noisy and include historical numbers.
- Geocoding errors ("Paris, Texas").
- Ethical framing: avoid "leaderboards of suffering"; neutral copy, methodology shown.

**Depends on.** D2, D3, D5; F1 for top threads.

### C. Later and stretch

| ID | Feature | Sketch | Effort | Cost and risk |
|---|---|---|---|---|
| S1 | **Relation arcs ("who is acting on whom")** | Ingest the GDELT Events export each cycle. Keep only daily rollups `event_pairs_daily(a_iso, b_iso, quad_class, day, n_events, mentions, avg_goldstein, avg_tone, sample_urls)`. Draw country-to-country arcs: blue for cooperation, red for conflict, thickness by mentions. Click shows events and their source articles (joined by URL). Shares the arc grammar with Q2 and F1. | M | Negligible storage; more parse CPU. CAMEO machine coding is error-prone, and actor codes are CAMEO 3-letter, so they need mapping. |
| S2 | **Compare mode** | Select 2–3 places, entities or threads. Side-by-side columns: volume on a shared axis, tone, theme overlap, shared versus unique entities, lead headlines, plus an AI "how coverage differs" paragraph. | M | Uses F2/F5 endpoints. LLM on demand, under $1/month. |
| S3 | **Watchlists and alerts** | Star places, entities, threads or themes; watchlist stored in `localStorage`. `POST /api/watch/check {items, since}` returns new counts and the lead headline per item. Tab-title badge; browser notifications only while the app is open. | S/M | No auth needed. Web Push needs a service worker, VAPID keys, a subscription table and a job (M/L). Email digests need auth and an email provider (V4). |
| S4 | **Story memory: time travel and narratives beyond 7 days** | Keep D5 rollups and thread digests (title, synopsis, top 10 URLs per day; about 1 KB per thread-day) indefinitely. The co-pilot can then answer "What happened in Sudan over the last 3 months?". A "Narrative" view shows weekly chapters for long threads. Implements the spec's "RAG time travel" and "regional narrative generator" without keeping every article. | M/L | Storage tiny. Weekly narratives about $2/month on Haiku 4.5. Changes the "rolling 7-day pulse" positioning, so it needs the owner's decision. |
| S5 | **Perspective lens (multilingual)** | Ingest the translingual GKG feed. For each thread, show which countries and languages cover it and how tone differs ("European outlets negative, Gulf outlets neutral"). `text-embedding-3-small` is multilingual, so cross-language thread matching is plausible. | L | At least doubles ingestion volume, ML function cost and rows. Original-language titles need translation for display, which costs LLM per title. Budget risk. |
| S6 | **Voices (quotes)** | Quote cards in the hover card, entity dossier and thread panel, plus a "What leaders said today" ticker, from `V2.1QUOTATIONS`. | S/M | Attributing a quote to a speaker is a nearest-name heuristic. Default to "quoted in [outlet]" unless confident. |
| S7 | **Briefing tour ("morning spin")** | "Brief me" makes the camera fly through the top 5 threads and hotspots, each with a 2-sentence narration from F1 digests. Optional browser text-to-speech (Web Speech API, free). Progress HUD. | S after F1 | No extra LLM. Very demo-friendly for the portfolio. |
| S8 | **Look-ahead calendar and emotion layers** | Upcoming dates from `V2.1ENHANCEDDATES` (needs context extraction). GCAM emotion layers (anxiety, anger) aggregated per cell. | M each | Noisy. The GCAM field is large, so parse only a few dimensions. |

---

## 5. Recommended roadmap

### Order

**Phase 0: foundations** (mostly S; do first)
1. D6 bug fixes (B1–B4, B7–B9), D1 expose images and per-cell mix, D3 FIPS-to-ISO, D7 budget guard. Decide on Haiku 5.5.
2. D2 GKG fields and `PAGE_TITLE`, D4 full embeddings, D5 rollups. (D8 only if needed.)

**Phase 1: quick wins** (visible quickly; little or no LLM)
3. Q1 hover recon card (Phase A right after D1; Phase B after D2/D5).
4. Q2 connection arcs v0. It can ship right after D3 on the existing knowledge graph, before D2.
5. Q5 mood and intensity layers, Q6 share links.
6. Q3 since-last-visit and Q4 surge pings (after D5).

**Phase 2: flagships**
7. F2 entity radar. Lower risk, built on D2, and the first full "track it across the world" moment.
8. F1 story threads, cross-region arcs and replay. The core connections engine. **If only one flagship gets built, build this one.**
9. F3 co-pilot upgrade (actions, scoped retrieval, streaming, callouts).
10. F4 investigation board.
11. F5 region dossier and hotspot monitor.

**Phase 3: later and stretch**
12. S7 briefing tour (cheap once F1 exists; strong demo value), S1 relation arcs, S2 compare, S3 watchlists.
13. S4 story memory (needs a retention decision), S6 voices, S5 multilingual, S8.

### Dependencies

```
D1 ──► Q1(A) ─────────────────────────────┐
D3 ──► Q2 v0 ──► (D2) Q2 v1 city links     │
D2 ──┬► Q1(B) ─┬► F2 ──┬► F3 ──► S2        │
     │         │       └► F4               ├─► Section 6 UI surfaces
     ├► F5 ◄───┘                           │
     └► S6                                 │
D4 ──► F1 ──┬► F4 (thread edges)           │
D2 ──► F1   ├► S7 briefing tour            │
            ├► S4 story memory             │
            └► F3 thread tools             │
D5 ──► Q3, Q4, Q5 history, F2 trends, F5 ──┘
D7 ──► every AI surface
D6(B1,B10) ──► F3        D6(B2,B3) ──► Q1(B), Q3
```

### Summary table

| ID | Feature | Effort | Added infra cost | Added LLM/month (Haiku 4.5 / 5.5) | Depends on | Priority |
|---|---|---|---|---|---|---|
| D1–D7 | Foundations | S–M | ~$0 (storage within plan; embeddings under $2) | $0 | none | **Now** |
| Q1 | Hover recon card | S → M | $0 | $0 (optional pre-gen $3.8 / $0.5) | D1; D2, D5 | **Quick win** |
| Q2 | Connection arcs v0 | S/M | $0 | $0.9 / $0.13 | D3 | **Quick win** |
| Q3 | Since last visit | S/M | $0 | $4 / $0.5 (digest) | D5 | Quick win |
| Q4 | Surge pings | S/M | $0 | $0 (captions $1.7 / $0.2) | D5 | Quick win |
| Q5 | Mood and intensity layers | S | $0 | $0 | D1 | Quick win |
| Q6 | Share links | S | $0 | $0 | none | Quick win |
| F1 | Story threads and arcs | L | DB CPU (watch B1ms credits) | $15 / $2 (batch: $7.6 / $1) | D2, D4 | **Flagship #1** |
| F2 | Entity radar | M | $0 | $0 (blurbs $4 / $0.5) | D2, D5 | **Flagship #2** |
| F3 | Co-pilot | M | $0 | $3.5 / $0.5 | D6, D3, F1/F2 | **Flagship #3** |
| F4 | Investigation board | M | $0 | $0.65 / $0.1 | D2, F1 | Flagship #4 |
| F5 | Dossier and hotspots | M | $0 | $1.4 / $0.2 | D2, D3, D5 | Flagship #5 |
| S1–S8 | Stretch | S–L | S5: significant | small, except S5 | various | Later |

---

## 6. For the UI agent: the top 6 features to design for

These features should shape the cockpit layout. Shared constraints:
- The globe stays full-bleed and is the primary surface.
- Everything else is a HUD element or a panel that can stack or dock.
- Panels must handle these states: loading, empty, AI unavailable or paused (D7 budget hit), rate-limited (HTTP 429), image missing, and item expired (older than 7 days).
- On mobile, hover becomes tap, docked panels become bottom sheets, and the board becomes a list.

### 1. Hover recon card (Q1)
- **Type:** floating HUD card anchored to the hovered dot. It must not block clicking the dot itself.
- **Content density** (about 320×220 px on desktop):
  - place name and country code;
  - story count and window;
  - 16:9 thumbnail (about 40% width), or a topic glyph when no image;
  - lead headline (clamped to 2 lines), source and age;
  - topic-mix stacked bar (up to 7 segments);
  - tone meter (-1..1);
  - 24-bar sparkline;
  - up to 3 entity chips;
  - optional AI brief (2 lines, labelled "AI");
  - hint "click to open, P to pin".
- **Interactions:** dwell 150 ms to show; the Phase B fields (chips, sparkline, brief) load in after 400 ms; images for conflict topics are blurred until clicked; keyboard Tab cycles dots.
- **Data:** `lead`, `topic_mix`, `avg_sentiment`, `place` come with `/api/news`; `spark`, `top_entities`, `brief` come from `/api/news/preview`.

### 2. Links and arcs layer plus link inspector (Q2, later F1 and S1)
- **Type:** a globe layer with an arc hover label, plus an inspector panel.
- **Shared arc grammar** for three link kinds, which the UI should differentiate by style:
  - co-coverage (Q2): neutral, thickness = count;
  - same story thread (F1): topic colour, directional dash from origin;
  - actor relations (S1): blue for cooperation, red for conflict.
- **Density:** draw at most 30–60 arcs at once. Provide a legend and a count/lift toggle.
- **Inspector:** endpoints A↔B with flags or place names, count, lift, dominant topic, shared entities (chips), the list of linking articles (10 shown, paginated), and an "Explain this link" AI button with a loading state and a cached flag.

### 3. Story thread panel and spread replay (F1)
- **Type:** an "Active threads" rail (compact list of 10–20 threads: title, velocity, country-flag row, size) plus a large thread panel.
- **Panel sections:**
  - AI title and synopsis (labelled), status pill, first seen, counts (articles, outlets, countries);
  - mini map of places;
  - timeline strip (hourly bars coloured by tone; clicking a bar filters the list);
  - key entities;
  - quotes and key figures;
  - media strip;
  - paginated article list.
- **Replay:** a transport control (play, pause, scrub) that drives the globe in "spread mode". The first place glows, then arcs extend to each new place in time order. The time slider can host the control.

### 4. Entity radar and dossier (F2)
- **Type:** a search box with typeahead in the HUD (results grouped by person, org or named event, with mention counts), a globe "focus mode" (dim the rest, light up the entity's places, arcs from its centre of gravity), and an entity dossier panel.
- **Dossier density:**
  - header (name, type, total mentions, countries);
  - 7/30-day sparkline;
  - top places list (up to 10);
  - co-mention mini force graph (about 15 nodes; clicking pivots);
  - tone-by-region bars;
  - latest headlines (10);
  - quotes.
- **Entity chips appear everywhere**: hover card, panels, threads, the co-pilot. Clicking a chip opens the radar. Copy must say "appears in coverage with", not "linked to".

### 5. Co-pilot console with action chips and proactive callouts (F3, Q4)
- **Type:** a docked console, replacing today's slide-out chat.
- **Header:** a context strip showing what the co-pilot "sees", for example "Selected: Kyiv cell, last 6h".
- **Quick actions** that change with the selection.
- **Message stream:** streaming text, citation chips that fly the globe, and an action-chip row per answer (flyTo, showLinks, openThread, openEntity, setTime, setLayer).
- **Tool-activity HUD** (existing feature), shown in a more instrument-like style.
- **Proactive callouts:** toasts or ticker items ("Coverage of X spiking. Brief me?") that never auto-run AI.
- **Alert ticker (Q4) and since-last-visit strip (Q3)** sit naturally next to this console as status readouts.

### 6. Investigation board (F4)
- **Type:** a full-screen overlay or split view (board on the left, globe on the right) with a draggable node-link canvas.
- **Pin cards:** article (thumbnail and headline), place, entity, thread or link, each about 200×90 px. Up to about 20 pins.
- **Auto-drawn edges:** typed and labelled ("shared: Wagner Group", "same thread", "co-covered", "2h apart"), with a legend and per-type toggles.
- **Globe mirror:** pins highlighted, edges drawn as arcs.
- **"Analyze" memo panel** that cites pins. Export and share buttons.
- **Pin affordance** (a pin icon and the `P` key) on every card, chip, arc and thread. A board badge with the pin count in the HUD.

### Cross-cutting HUD elements to reserve space for
- **Layer switcher:** Dots, Intensity, Mood, Topics, Links, Threads, Hotspots, Relations.
- **Time scrubber:** existing, with presets and day stepping; add a replay transport and a since-last-visit marker.
- **Alert ticker** for surges (Q4).
- **"Since last visit" strip** (Q3).
- **Global search:** entities and places (F2), plus threads.
- **Country polygon highlight on hover** for F5. The globe can render this with `polygonsData`.
- Available globe primitives in the installed `globe.gl` 2.45: points, rings, hex bins, **arcs (animated dashes)**, **heatmaps**, **polygons**, paths, labels, **HTML-element markers**, particles. Hover via `onPointHover`; anchor HUD cards with `getScreenCoords`.

### New endpoints, for the UI agent's data assumptions

| Endpoint | Shape (abridged) |
|---|---|
| `GET /api/news` (extended) | `[{lat,lng,article_count,place,topic,topic_mix:{politics:12,...},avg_sentiment,lead:{title,source,published_at,image_url}}]` (≤500) |
| `GET /api/news/preview` | `{spark:[24], top_entities:[{name,type,n}], brief:string\|null}` |
| `GET /api/news/delta?since` | `{new_articles, cells:[{lat,lng,new,ratio,lead}], top:[...]}` |
| `GET /api/alerts?since` | `[{id,kind:'surge',place,lat,lng,ratio,started_at,lead,themes}]` |
| `GET /api/links` | `[{a:{name,lat,lng,iso}, b:{...}, n, lift, topic, avg_sentiment, lead_title}]` (≤40) |
| `POST /api/links/explain` | `{text, cached:boolean}` |
| `GET /api/threads` / `/{id}` / `/{id}/spread` | list with `places[]`; detail with `timeline[]`, `entities[]`, `articles[]`; `[{t, lat, lng, place, article_id}]` |
| `GET /api/entities/search` / `/trending` / `/{type}/{name}` | typeahead; trending with velocity; dossier with `timeline`, `places`, `co_mentions`, `articles` |
| `GET /api/regions/{iso}/dossier`, `GET /api/hotspots` | trends, threads, entities, counts (labelled "as reported"), quotes, brief; ranked list with index and arrow |
| `POST /api/board/links`, `POST /api/board/analyze` | `[{from,to,type,label}]`; `{memo, citations}` |
| `POST /api/agent/ask/stream` (extended) | request adds `context`; `done` event adds typed `actions[]` |

---

## 7. Cost model

**Assumptions:** about 1,000 sessions/month; 300 co-pilot questions/month; about 225 thread synopses/day; top-10 cell briefs every 3 hours. For Haiku 5.5, token counts are scaled by 1.3 (newer tokenizer) and output is raised about 50% for low-effort thinking. Prices are from section 2.6. All figures are monthly.

| Item | Haiku 4.5 | Haiku 4.5 + Batch API where possible | Haiku 5.5 | Notes |
|---|---|---|---|---|
| Existing cluster summaries (~1,500 calls) | $2.4 | n/a (interactive) | $0.3 | Baseline, not new |
| Existing agent (300 questions) | $3.1 | n/a | $0.4 | Baseline, not new |
| Q1 brief pre-generation (optional) | $3.8 | $1.9 | $0.5 | Skippable: reuse click-generated summaries |
| Q2 link explanations | $0.9 | n/a | $0.13 | On demand, cached 3h |
| Q3 hourly digest | $4.0 | $2.0 | $0.5 | Lazy, global, at most one per hour |
| Q4 alert captions (optional) | $1.7 | $0.85 | $0.2 | |
| F1 thread synopses | $15.2 | $7.6 | $2.1 | The largest item |
| F2 entity blurbs (optional) | $3.9 | $2.0 | $0.5 | |
| F3 co-pilot extra context | +$0.4 | n/a | +$0.1 | On top of the agent baseline |
| F4 board analyses | $0.65 | n/a | $0.1 | |
| F5 dossier briefs | $1.35 | n/a | $0.2 | |
| S4 weekly narratives | $2.0 | $1.0 | $0.3 | Stretch |
| **New features total** (excluding baseline) | **about $34** | **about $19** | **about $4.7** | |
| Embeddings, full coverage (OpenAI) | $0.5–2 | | | Independent of Claude model |

**Azure.**
- D2/D5 storage fits inside the provisioned 32 GiB.
- The real risk is **B1ms burstable CPU credits** once threads (F1), set-based knowledge-graph writes and more articles (from `PAGE_TITLE`) land. Watch the "CPU credits remaining" metric in Azure. The B1ms→B2s step costs roughly 4x B1ms compute (check the calculator); avoid it by keeping work set-based and incremental.
- More articles per cycle raises Flex Consumption ML cost roughly linearly. Measure after D2.
- If ingestion moves to a Container Apps Job (D8), expect a few dollars a month.

**Vercel.** Keep hover data in the main payload. Add `s-maxage` to public GETs (`/api/news`, `/api/links`, `/api/threads`, `/api/alerts`) so the CDN absorbs repeats; verify that Vercel caches responses from this proxied route.

---

## 8. Risks and open questions

**Risks**

1. **Unknown real volumes.** Articles per day, image coverage, knowledge-graph size and HNSW size drive several decisions. Run Appendix A first.
2. **Public, unauthenticated LLM endpoints.** Spend abuse is possible; D7 is a precondition.
3. **One small container does everything.** Heavier ingestion degrades API latency (see D8).
4. **GDELT noise.** Names, themes, counts and geocoding are all machine-extracted. The UI copy must signal "as reported" and "co-coverage".
5. **Images.** Privacy (hotlinking), broken or logo images, graphic imagery.
6. **Prompt injection** via scraped article text into the co-pilot. Actions must stay whitelisted and harmless.
7. **7-day retention vs. history-hungry features.** Rollups and digests (D5, S4) solve this at low cost, but change the product's "live pulse" positioning.
8. **Mobile.** Hover-centric and canvas-centric features need tap and list equivalents.

**Open questions for the owner**

1. Move to Haiku 5.5 (about 10x cheaper; small code changes; spot-check summary quality and refusal behaviour on conflict news)? Or keep Haiku 4.5 and skip the optional pre-generation items?
2. Is hotlinking publisher sharing images acceptable? Should conflict-topic images be blurred by default?
3. Keep compact rollups and thread digests beyond 7 days? This enables trends, narratives and time travel.
4. Is the GDELT Events feed (S1) in scope, or stay GKG-only?
5. Any appetite for accounts later? Watchlist notifications and email digests need them.

---

## Appendix A: read-only verification SQL

Run these against production with a read-only role to firm up the estimates above.

```sql
-- Article coverage of the fields discussed
SELECT count(*)                                                 AS total,
       count(*) FILTER (WHERE published_at > now() - interval '24 hours') AS last_24h,
       count(image_url)                                         AS with_image,
       count(*) FILTER (WHERE image_url LIKE 'https:%')         AS https_image,
       count(embedding)                                         AS with_embedding,
       count(*) FILTER (WHERE entities <> '{}'::jsonb)          AS with_entities,
       count(summary)                                           AS with_summary
FROM articles;

-- Ingestion rate per hour (about 4 cycles per hour)
SELECT date_trunc('hour', ingested_at) AS h, count(*)
FROM articles GROUP BY 1 ORDER BY 1 DESC LIMIT 24;

-- Logo-like images (same URL reused many times)
SELECT image_url, count(*) FROM articles
WHERE image_url IS NOT NULL GROUP BY 1 HAVING count(*) > 3
ORDER BY 2 DESC LIMIT 20;

-- Knowledge-graph size and shape
SELECT type, count(*) FROM kg_nodes GROUP BY 1;
SELECT rel_type, count(*), max(weight) FROM kg_edges GROUP BY 1;
SELECT pg_size_pretty(pg_total_relation_size('articles'))   AS articles,
       pg_size_pretty(pg_total_relation_size('kg_edges'))   AS kg_edges,
       pg_size_pretty(pg_relation_size('idx_articles_embedding')) AS hnsw;

-- Most-mentioned people and orgs (entity radar feasibility)
SELECT n.type, n.name, count(*) AS mentions
FROM kg_edges e JOIN kg_nodes n ON n.id = e.source_node_id
WHERE e.rel_type = 'MENTIONED_IN' AND n.type IN ('PERSON','ORG')
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 30;

-- Connection arcs v0 feasibility: article country -> mentioned country, last 24h
SELECT a.country_code AS from_fips,
       n.metadata->>'country_code' AS to_fips,
       count(*) AS n
FROM kg_edges e
JOIN kg_nodes n ON n.id = e.source_node_id AND n.type = 'LOCATION'
JOIN articles a ON a.id = e.article_id
WHERE e.rel_type = 'MENTIONED_IN'
  AND a.published_at > now() - interval '24 hours'
  AND a.country_code IS DISTINCT FROM n.metadata->>'country_code'
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 30;

-- FIPS check: expect UK, CH (China), GM (Germany), RS (Russia), IS (Israel)...
SELECT country_code, count(*) FROM articles GROUP BY 1 ORDER BY 2 DESC LIMIT 20;
```

## Appendix B: GKG 2.1 column reference (0-based, tab-delimited)

0 GKGRECORDID · 1 V2.1DATE · 2 V2SOURCECOLLECTIONIDENTIFIER · 3 V2SOURCECOMMONNAME · 4 V2DOCUMENTIDENTIFIER · 5 V1COUNTS · 6 V2.1COUNTS · 7 V1THEMES · 8 V2ENHANCEDTHEMES · 9 V1LOCATIONS · 10 V2ENHANCEDLOCATIONS · 11 V1PERSONS · 12 V2ENHANCEDPERSONS · 13 V1ORGANIZATIONS · 14 V2ENHANCEDORGANIZATIONS · 15 V1.5TONE · 16 V2.1ENHANCEDDATES · 17 V2GCAM · 18 V2.1SHARINGIMAGE · 19 V2.1RELATEDIMAGES · 20 V2.1SOCIALIMAGEEMBEDS · 21 V2.1SOCIALVIDEOEMBEDS · 22 V2.1QUOTATIONS · 23 V2.1ALLNAMES · 24 V2.1AMOUNTS · 25 V2.1TRANSLATIONINFO · 26 V2EXTRASXML

The current parser in `backend/app/services/gdelt.py` reads columns 1, 3, 4, 7 (then discards it), 9, 11, 13, 15 (first value only) and 18.

## Appendix C: sources

- GDELT GKG 2.1 codebook and Event 2.0 codebook: `docs/gdelt/*.pdf` (in repo).
- GDELT blog, "New GKG 2.0 Article Metadata Fields" (2016-04-22): page links, authors, precise timestamp, AMP URLs. https://blog.gdeltproject.org/?p=3176
- GDELT blog, page titles added to the GKG extras XML (2019-09-22). https://blog.gdeltproject.org/?p=7791
- GDELT blog, "GDELT 2.0: Our Global World in Realtime": `lastupdate.txt` and `lastupdate-translation.txt` file lists. https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
- Anthropic pricing (retrieved 2026-10-10). https://platform.claude.com/docs/en/about-claude/pricing
- Prior Orbis intent: `docs/project/orbis-product-spec.md` (AI features 1–7, V2–V4 roadmap), `docs/plans/2026-03-07-embedded-agent-design.md`, `docs/plans/2026-03-07-story-exploration-and-time-slider.md`, `docs/plans/2026-03-07-rolling-retention.md`.
