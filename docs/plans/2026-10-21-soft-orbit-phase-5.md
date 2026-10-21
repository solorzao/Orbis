# Soft Orbit Phase 5 (GDELT Events) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add relation arcs between countries from GDELT's machine-coded Events. Ingestion keeps only daily country-pair rollups of root events. The globe draws cooperation and conflict arcs over a fixed **7-day lens**, always labelled as *reported events*, with an inspector that shows how the events split, day by day, and samples of the reports they came from.

**Architecture:**
- **Ingestion.** Each ingestion cycle reads GDELT's `lastupdate.txt` and fetches the newest 15-minute `export.CSV.zip`, plus any earlier slots no cycle has added (at most 4 files, from the last 2 hours). It parses them in memory, keeps root events between two different mapped countries, and aggregates them in Python by (actor 1 country, actor 2 country, UTC day, QuadClass). It then writes the cycle's rollups to a narrow table `event_pairs_daily` in **one batched upsert**. The same transaction records the files in `event_files`, so a file is never added twice. Nothing is stored per event, and nothing touches `articles`.
- **Reading.** `/api/relations` and `/api/relations/detail` always answer for the last 7 UTC days, whatever the timeline shows. They read only the rollups, and are cached in PR #108's hourly `wk:*` family.
- **The layer.** A Relations overlay sits beside Links. The two are mutually exclusive: both draw country-to-country arcs between the same label points.
  - It has a class switch (All / Cooperation / Conflict) and a persistent legend ("Relations · last 7 days").
  - The 5 strongest arcs carry persistent labels.
  - It's unavailable under a range or a replay.
  - An inspector opens in the side panel's Inspect tab.

**Tech Stack:**
- Backend: FastAPI and asyncpg on Azure PostgreSQL 16 B1ms (P4 disk: about 120 IOPS, 25 MB/s); Upstash Redis; httpx; the standard library's `zipfile`.
- Frontend: Next.js 16, React 19, Tailwind v4, globe.gl/three-globe 2.45 (pinned).
- Tests: pytest, with opt-in DB tests that CI runs against Postgres 16 + pgvector 0.8.1 + PostGIS; Vitest with Testing Library; Playwright.

**Parent plan:** `docs/plans/2026-10-10-soft-orbit-redesign.md` (Phase 5, PRs 19–20, and "Risks to watch"). This plan splits PR 19 into 19a/19b/19c and keeps PR 20 whole.

**Design sources (read before starting):**
- `docs/redesign/features/feature-exploration.md`: §2.4 "GDELT feeds not used" (lines 124–133), S1 relation arcs (line 564), and the shared arc grammar in §6 (lines 662–668).
- `docs/redesign/ui/soft-orbit/tokens.md`, "Connection arcs" (lines 101–109): `--arc-relation-cooperation` `#8fb8ff` and `--arc-relation-conflict` `#f2949c`. These are **already defined** in `frontend/src/app/tokens.css:54-55` (verified 2026-10-21).
- `docs/plans/2026-10-12-soft-orbit-phase-3.md`, PR 13a–c: the links layer the relation arcs sit beside, and copy each pattern from: `useLinks`, `LinkInspector`, `LinkList`, `ArcPill`, `LinksChip`, `data-arcs`.
- `docs/plans/2026-10-18-soft-orbit-phase-4.md`: "What Phase 3 taught us" and the working rules, extended below.

---

## Decisions (owner-approved, 2026-10-21)

The controller proposed these and the owner approved all 13 on 2026-10-21. The tasks below follow them.

| # | Decision | Why |
|---|---|---|
| 1 | **Windows.** Relations is a **7-day lens**: always the last 7 UTC days (today and the 6 before), labelled "Relations · last 7 days", whatever the timeline shows. Under a range or a replay it's unavailable, with a short note. The inspector shows the daily breakdown. Daily rollups stay; no hourly rollups. | One honest, fixed window reads better than day-granular rollups stretched to fit 1h or 6h. It also keeps every read in the cheap, hourly `wk:*` family. |
| 2 | **Topic pill.** Ignored for relations. The legend has a one-line note that topics don't apply. | Events carry no topic tags. |
| 3 | **Root events.** Count only `IsRootEvent = 1`. | Lead-paragraph events are the higher signal; the rest add machine-coding noise. |
| 4 | **Domestic events.** Drop them (`a_iso == b_iso`). | They can't be drawn as arcs. |
| 5 | **Exclusivity.** Relations and Links are mutually exclusive. Relation arcs are muted under entity focus and the board, as links are. | Both draw arcs between the same label points. |
| 6 | **Labels.** The 5 strongest arcs carry persistent labels. Every arc is labelled on hover or focus, and all of them in the keyboard list and the inspector. | Arcs are always labelled, without cluttering the globe. |
| 7 | **Arcs.** One arc per pair, coloured by the dominant class under All. The Cooperation and Conflict switch filters to that class's counts. The inspector always shows both classes. | One arc per pair stays readable; the inspector keeps the full picture. |
| 8 | **Thresholds.** `MIN_EVENTS` 5, `MIN_REPORTS` 3 and `MIN_OUTLETS` 2 are starting values, kept as named constants that "Measure on prod" (19b+) recalibrates. | They can only be tuned on live data. |
| 9 | **Board.** Relations are not pinnable in Phase 5 (see "After Phase 5"). | It would need a new board item kind in 18a's API. |
| 10 | **#108.** It's merging now, so 19c relies on its `WEEK_TTL`, `single_flight` and `cached_model`. Fallback, should it not land: keep the lens under `db:*` with `cycle_ttl` and plain get and set, since it's cheap either way. | The 7-day lens is a week read. |
| 11 | **CAMEO reference downloads.** The generator runs **on CI** (a workflow step on the runner), which commits the generated table. Nothing is downloaded locally. | The owner approves downloads case by case. |
| 12 | **GKG cadence finding.** Out of Phase 5's scope: catching up the GKG roughly doubles embeddings and their IOPS, an owner decision on cost, recorded with its numbers under "After Phase 5". The events path keeps its own catch-up, since its files are small. | Cost and IOPS are the owner's call. |
| 13 | **Phones.** Relations is unavailable at phone width, like Links. | As Links today. |

**Migration number:** #106 (merged) used `020_synopsis_retries.sql`, so this phase's migration is **021**. Before writing it, check `ls database/migrations` on the latest `origin/main`. If 021 is taken by then, use the next free number and rename it everywhere: file, static test and commit message.

---

## Research: the GDELT 2.0 Event export

Sources:
- the GDELT Event Codebook V2.0 (`http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf`);
- the CAMEO country lookup (`https://www.gdeltproject.org/data/lookups/CAMEO.country.txt`);
- the live `lastupdate.txt` index (three lines, read once on 2026-10-21).

No data file was downloaded on the owner's machine. 19b's CI repro measures real files on a CI runner.

**Files.**
- `http://data.gdeltproject.org/gdeltv2/lastupdate.txt` has three lines, each `SIZE MD5 URL`: the export first, then mentions, then GKG. All three share one 15-minute timestamp. On 2026-10-21 at 12:30 UTC:
  ```
  80351 4e89d1d989499fe69f4f102292247399 http://data.gdeltproject.org/gdeltv2/20261021123000.export.CSV.zip
  119531 ae8ab8e83b1347bb8fae2af1f9b8c6dd http://data.gdeltproject.org/gdeltv2/20261021123000.mentions.CSV.zip
  4631710 f231d70b0b4425c19613644c5d48cfc8 http://data.gdeltproject.org/gdeltv2/20261021123000.gkg.csv.zip
  ```
- The export zip is about **80 KB**, against the GKG's 4.6 MB. It holds one member, `YYYYMMDDHHMMSS.export.CSV`. Despite the `.CSV` name it is **tab-delimited, with no header**, one event per line.
- The file URL is predictable from its slot (`…/gdeltv2/{YYYYMMDDHHMMSS}.export.CSV.zip`, every 15 minutes), so a missed slot can be fetched later.
- The index lists `http://` URLs. As for the GKG, they're rewritten to `https://data.gdeltproject.org` and pinned to that host (`gdelt._gdelt_https_url`).

**Columns** (0-based; 61 in all). Only these are read:

| # | Field | Use |
|---|---|---|
| 7 | `Actor1CountryCode` | 3-character CAMEO country code. Blank when unknown ("unidentified gunmen"). It reflects the actor's affiliation, not where it is: "French minister in Moscow" is FRA. |
| 17 | `Actor2CountryCode` | The same, for the actor acted upon. |
| 25 | `IsRootEvent` | 1 when found in the lead paragraph, a rough importance proxy. **Only root events are kept** (decision 3). The rest are counted as "not root" in the log and the repro. |
| 29 | `QuadClass` | 1 verbal cooperation, 2 material cooperation, 3 verbal conflict, 4 material conflict. |
| 30 | `GoldsteinScale` | −10 to +10, scored by **event type**, not magnitude: two riots score the same whatever their size. |
| 31 | `NumMentions` | Mentions **during the 15-minute update in which the event was first seen** only. Later mentions go to the Mentions table. |
| 34 | `AvgTone` | −100 to +100, usually −10 to +10, for the first reports only. |
| 59 | `DATEADDED` | `YYYYMMDDHHMMSS` UTC, the slot that added the event. The rollup's `day` uses this, not `SQLDATE` (col 1, the day the event happened, which can be years ago for anniversaries). |
| 60 | `SOURCEURL` | "URL or citation" of the first report. It can be a print or broadcast citation, so it's kept only when it is an http(s) URL. |

The other columns are not read: `ActionGeo_*` (51–58, FIPS country and coordinates), `EventCode` (26–28), and the actor names and types. The arcs join countries by affiliation, as the feature report specifies. `ActionGeo` is a possible later "where it happened" view.

**Duplicates.** The export lists events newly added in its slot, and later mentions go to the Mentions table. So summing exports doesn't double-count an event, but a missed slot loses its events for good. 19b's repro checks for repeated `GLOBALEVENTID`s across a day of files (expected: 0).

**CAMEO country codes:**
- Mostly ISO 3166-1 alpha-3, so they map to alpha-2 through GeoNames' `ISO3` column. GeoNames' `countryInfo.txt` already backs `country_codes.py`.
- Exceptions in CAMEO's list:
  - `ROM` Romania (ISO ROU)
  - `TMP` East Timor (TLS)
  - `MTN` Montenegro (MNE)
  - `WSB` West Bank and `GZS` Gaza Strip (both PS)
  - `BAG` Baghdad (IQ)
  - `ANT` Netherlands Antilles (dissolved, so left unmapped)
- **Regional codes name no country** and are left unmapped: `AFR ASA BLK CRB CAU CFR CAS CEU EIN EAF EEU EUR LAM MEA MDT NAF NMR PGS SCN SAM SAS SEA SAF WAF WST`.
- The mapping ships as a generated static table, `backend/app/services/cameo_countries.py`. It's built by `scripts/gen_cameo_countries.py`, which **runs on CI**, never locally, and CI commits the table (decision 11, Task 19b.1). The repro reports the unmapped codes a day of real data contains.

**Volumes (estimates; 19b's repro replaces them with measurements):**

The root share is unknown until the repro runs. The kept and row estimates below assume about half of all events are root events. Rows shrink less than events do, because busy pairs keep their rows and the long tail thins.

| Quantity | Estimate | Basis |
|---|---|---|
| Events per file | 1,000–1,500 | an 80 KB zip at about 6:1 is about 0.5 MB of tab-separated text, at about 400 B a row |
| Events per day | 100K–140K | 96 files |
| Kept per file (root, both actors' countries mapped, and different) | 75–250 (7–17%) | many events lack an actor country; domestic pairs (USA→USA) and non-root events are dropped |
| Rollup groups per file | 60–200 | grouped by (a, b, day, quad) |
| **Rows upserted per cycle** | **120–400** | the cycle starts about every 30 min, so about 2 files a cycle (see the scheduler finding below) |
| **Rows per day** | **2K–5K** | distinct directed (a, b, quad) per day |
| **Rows kept** (8 UTC days) | **16K–40K**, about 10–25 MB with indexes | about 500 B a row with 3 sample URLs and up to 8 outlets |
| Download per cycle | about 160 KB | 2 × 80 KB, plus a 300 B index |
| Parse CPU per file | 10–50 ms | `str.split` of about 1,200 lines × 61 fields, in a worker thread |

**Scheduler finding (pre-existing, not changed here).**
- `scheduler._ingestion_loop` sleeps `ingestion_interval_seconds` (900) **after** each cycle, and cycles take 13–16 min (mostly embeddings).
- So cycles start about every **28–31 minutes**, and the GKG path, which reads only the newest file, misses about half of GDELT's 15-minute files.
- Events can't afford that, since rollups are counts, so 19b catches up missed slots: their files are about 80 KB.
- The GKG is left as it is: it's an owner decision on cost (decision 12; the numbers are under "After Phase 5").

---

## What Phases 3 and 4 taught us (constraints for every PR)

1. **Narrow tables only; the `articles` heap is off limits.**
   - No `ALTER`, index or foreign key on `articles`.
   - The new tables carry only what their reads need. Events are not joined to articles, except to look up titles of at most 10 sample URLs by `articles_source_url_key`.
   - Migrations set `lock_timeout` before their first `CREATE`. Indexes on busy tables are built `CONCURRENTLY`; 021 creates brand-new, empty tables, so it doesn't need to.
   - Static migration tests in `tests/test_migrations.py`.
2. **Every hot query is index-bounded, and a test proves it the way production will run it.**
   - DB plan tests fill **production-like row counts** (the week fixture, sized from the repro) and assert the planner's **natural** choice, under custom and generic plans.
   - `enable_seqscan = off` is never the only check: #93's incident was a plan that passed with it and seq-scanned without it.
   - A buffers bound (`EXPLAIN (ANALYZE, BUFFERS)`) applies wherever a cold read matters.
   - **Mutation checks:** each plan test has a twin that drops the index inside a savepoint and shows the check fails, so it can't pass vacuously.
3. **Per-cycle cost is a budget.**
   - The cycle already spends 13–16 min on embeddings, with disk IOPS peaking at 100%.
   - The events step streams and is bounded: capped downloads, an in-memory unzip, aggregation in Python, **one batched upsert per cycle**, about 120–400 rows.
   - There are no per-event rows, and none are planned.
   - It runs before embeddings so it never contends with them, and it logs its own timing.
   - 19b's CI repro measures rows per cycle and per day, upsert time, table size and the HOT-update ratio.
4. **Week reads refresh hourly outside `db:*`** (PR #108's pattern: `wk:*`, `WEEK_TTL`, `single_flight`, `cached_model`), never per cycle.
   - Relations is a 7-day lens (decision 1), so every relations answer is a week read. They read rollups, so they're cheap by design, but they still live under `wk:`, refreshed at most hourly.
   - 19c relies on #108, which is merging. The fallback is in decision 10.
5. **Input from GDELT is untrusted.**
   - Only https URLs on `data.gdeltproject.org` are fetched, and no redirects are followed.
   - The index MD5 is checked on the newest file.
   - The zip is capped at 2 MB, the CSV at 20 MB, and rows at 30,000 per file. The zip must hold exactly one member named like an export.
   - Malformed rows (wrong field count, bad numbers, bad dates) are counted and skipped, never fatal.
   - `SOURCEURL`s are kept only when `web_url` accepts them: absolute http(s), a host, no control characters, at most 1,000 characters.
   - The frontend opens them only through `isWebUrl`, with `rel="noopener noreferrer"`.
6. **Tests and CI.**
   - DB tests are opt-in via `ORBIS_TEST_DATABASE_URL`, and CI's Backend Checks runs them against Postgres.
   - **Docker is unreliable on the owner's machine:** don't spend time on a local Postgres. Push a draft PR and read Backend Checks (0 skipped), or reproduce on a throwaway branch's CI run.
   - **E2E runs on slow runners** (software WebGL, 8–23 min a suite, Playwright's 30 s per-test timeout). Keep each test to a few steps.
     - Activate controls with the keyboard (`locator.press("Enter")`), not WebGL clicks.
     - Wait on deterministic `data-*` attributes (`data-relation-arcs`, `data-relation-highlight`, `data-relation-muted`, `data-relation-labels`), never on timing.
     - Use `test.slow()` only with a comment giving the reason. None is expected here.
7. **Copy.**
   - Never "linked to", "caused" or "attacked".
   - Arcs are always labelled (decision 6):
     - the 5 strongest carry persistent labels;
     - every arc is labelled on hover or keyboard focus, and in the list and the inspector;
     - the class is always in words, so colour never carries the meaning alone;
     - a legend shows while the layer is on.
   - Relation meaning comes only from QuadClass (verbal or material, cooperation or conflict).
   - The UI says these are **reported events, machine-coded from news reports, not verified facts**, and that one report can yield several events.
   - Goldstein is described as an event-type score.
8. **One focus at a time on the globe.** Relations follow the links' rules exactly, and Links and Relations are mutually exclusive (see the table in PR 20).

## Working rules for every PR

- **Branches and merging:** branch from `origin/main`, one branch per PR, no stacked PRs. Work test-first. Run the checks, open the PR, and wait for every check to finish green. The controller merges once the reviews (spec compliance, then code quality) approve.
- **Backend checks:**
  ```
  cd backend && python -m pytest tests -q && python -m ruff check app && python -m ruff format --check app
  ```
  - Expected locally: all pass, with the DB tests skipped ("ORBIS_TEST_DATABASE_URL is not set").
  - On CI, Backend Checks must show **0 skipped** for the new `*_db.py` files.
- **Frontend checks:**
  ```
  cd frontend && npm run lint && npx vitest run && npm run build && npx prettier --check --end-of-line auto <changed files>
  ```
  - Then the full `CI=1 npx playwright test` before pushing (port 3000 free).
  - On Windows, `format:check` flags every file because of CRLF checkouts; check changed files with the prettier command above.
- **Migrations:** the Deploy workflow runs migrations first and the backend waits for them (#77). A migration that hits its 5 s `lock_timeout` fails safely: rerun the Deploy workflow.
- **Never deploy by hand:** merging to `main` deploys.
- **Production data writes** (anything beyond ingestion's own) need the owner's per-operation yes. Production measurements are read-only.

---

## Roadmap

| PR | What | Depends on |
|---|---|---|
| 19a | Migration 021: `event_pairs_daily` and `event_files`; static and DB schema tests; README | none |
| 19b | Events ingestion: CAMEO→ISO table, capped fetch and catch-up, parse and aggregate, one batched upsert, purge, kill switch, **CI repro** | 19a deployed |
| 19b+ | **Measure on prod** (the controller, no code) | 19b deployed, then 24 h |
| 19c | `/api/relations`, `/api/relations/detail`: the 7-day lens over rollups, `wk:` caching, production-scale plan tests | 19b merged; #108 merged (merging 2026-10-21) |
| 20 | Relations layer UI: toggle, class switch, legend, arcs with persistent labels, list, inspector, focus rules | 19c merged (it can start earlier against this plan's contract and mocked routes) |

**Parallelism:**
- 19c can be written while 19b's data accrues; its tests use fixtures, not production data.
- PR 20 can start from the API contract in 19c (it's fixed here) with mocked routes, and merges after 19c.

## Design choices (technical)

These follow from the Decisions above.
- **Rollup grain:**
  - Directed pairs: `a_iso` acts on `b_iso`.
  - The UTC day of `DATEADDED`.
  - QuadClass.
- **Sums, not averages:** `goldstein_sum` and `tone_sum` add up across files; reads divide by `n_events`. The roadmap's `avg_goldstein, avg_tone` are derived this way, because averages can't be updated incrementally without drift.
- **What's dropped:**
  - Non-root events (decision 3).
  - Domestic events (`a = b`, decision 4).
  - Events with a missing or unmapped actor country.
  - Events added more than `retention_days` before today.
- **Robustness guards,** as "outlets beat stories":
  - `n_reports`: distinct first-report URLs, summed per cycle;
  - `outlets`: up to 8 distinct hosts per row.
  - The read path requires `MIN_EVENTS`, `MIN_REPORTS` and `MIN_OUTLETS` (decision 8).
- **The lens** (decision 1):
  - The API computes its days as `today - 6 .. today` (UTC) and names them (`first_day`, `last_day`). The UI labels them "Relations · last 7 days (15–21 Oct)".
  - Retention keeps 8 UTC days, as for articles, so the lens is always fully covered.
  - The lens moves at UTC midnight. Cache keys carry the days, so the new day is a new entry.
- **One arc per unordered pair** (decision 7):
  - coloured by its majority class: conflict when conflict events outnumber cooperation; on a tie, by the Goldstein sign;
  - stroked by mentions;
  - starting at the country whose actors act in most of the events.
  - The class switch shows only cooperation or only conflict events. The inspector shows both whatever the switch says: the detail takes no class.

---

## PR 19a: Migration 021, rollup tables

Branch: `claude/p5-events-schema`.

### Task 19a.1: the static migration test (failing first)

**Files:**
- Modify: `backend/tests/test_migrations.py`

**Step 1: Write the failing test.** Add `"021_event_pairs_daily.sql"` to `TABLE_MIGRATIONS`, and append:

```python
def test_events_migration_creates_only_its_two_tables():
    """New tables only (nothing references articles or anything else), room on each
    page for HOT updates, and no data statements."""
    sql = " ".join(_sql_without_comments("021_event_pairs_daily.sql").split())
    assert sql.startswith("SET lock_timeout = '5s';")
    creates = re.findall(r"CREATE (TABLE|INDEX) IF NOT EXISTS (\w+)", sql)
    assert creates == [
        ("TABLE", "event_pairs_daily"),
        ("INDEX", "idx_event_pairs_day"),
        ("TABLE", "event_files"),
    ]
    assert "WITH (fillfactor = 70)" in sql
    assert "REFERENCES" not in sql.upper()
    assert not re.search(r"\b(ALTER|DROP|DELETE|UPDATE|INSERT)\b", sql, re.IGNORECASE)
```

**Step 2: Run it to verify it fails.**

Run: `cd backend && python -m pytest tests/test_migrations.py -q`
Expected: 2 FAILED, with `FileNotFoundError: … 021_event_pairs_daily.sql`: the parametrised `TABLE_MIGRATIONS` case and the new test.

### Task 19a.2: `database/migrations/021_event_pairs_daily.sql`

**Step 3: Write the migration.**

```sql
-- 021_event_pairs_daily.sql
-- GDELT Events (Phase 5, PR 19): daily country-pair rollups of the
-- machine-coded events in GDELT 2.0's 15-minute export files, and the log
-- of the files added. Ingestion (app/services/events.py) adds each file's
-- events into these rows; nothing is stored per event.
--
-- One row per (actor 1 country, actor 2 country, UTC day, QuadClass):
--   a_iso, b_iso   ISO 3166-1 alpha-2 of Actor1CountryCode and
--                  Actor2CountryCode (CAMEO codes mapped by
--                  app/services/cameo_countries.py). Never equal: domestic
--                  events are not stored.
--   day            the UTC day GDELT added the events (DATEADDED), not the
--                  day they happened (SQLDATE), so retention and windows
--                  follow reporting, as articles.published_at does.
--   quad_class     1 verbal cooperation, 2 material cooperation,
--                  3 verbal conflict, 4 material conflict.
--   n_events, n_reports (distinct first-report URLs, summed per cycle),
--   mentions (NumMentions: each event's first 15 minutes only),
--   goldstein_sum, tone_sum: sums, so each file adds to them; reads divide
--   by n_events.
--   sample_urls    up to 3 first-report URLs (http(s) only), first seen first.
--   outlets        up to 8 distinct outlet hosts, first seen first.
-- About 3K-6K rows a day, kept for retention_days (ingestion deletes older
-- days). fillfactor 70 leaves room on each page, so a cycle's additions,
-- which change no indexed column, are HOT updates.
--
-- event_files: one row per 15-minute export added (or found missing), so a
-- file is never added twice: rollups are sums.
--
-- New tables only, and nothing references articles or any other table:
-- safe while the previous backend still serves.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS event_pairs_daily (
    a_iso         TEXT NOT NULL,
    b_iso         TEXT NOT NULL,
    day           DATE NOT NULL,
    quad_class    SMALLINT NOT NULL CHECK (quad_class BETWEEN 1 AND 4),
    n_events      INT NOT NULL,
    n_reports     INT NOT NULL,
    mentions      INT NOT NULL,
    goldstein_sum DOUBLE PRECISION NOT NULL,
    tone_sum      DOUBLE PRECISION NOT NULL,
    sample_urls   TEXT[] NOT NULL DEFAULT '{}',
    outlets       TEXT[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (a_iso, b_iso, day, quad_class),
    CHECK (a_iso <> b_iso)
) WITH (fillfactor = 70);
-- The relations list and the retention purge read by day; the primary key
-- serves a pair's detail and the upsert.
CREATE INDEX IF NOT EXISTS idx_event_pairs_day ON event_pairs_daily (day);

CREATE TABLE IF NOT EXISTS event_files (
    slot         TIMESTAMPTZ PRIMARY KEY,   -- the file's 15-minute timestamp (UTC)
    status       TEXT NOT NULL CHECK (status IN ('ok', 'missing')),
    n_rows       INT NOT NULL DEFAULT 0,    -- events in the file
    n_kept       INT NOT NULL DEFAULT 0,    -- events added to the rollups
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Step 4: Run the static tests.**

Run: `cd backend && python -m pytest tests/test_migrations.py -q`
Expected: all PASSED.

### Task 19a.3: DB schema tests (opt-in; they run on CI)

**Files:**
- Create: `backend/tests/test_events_schema_db.py`

**Step 5: Write the tests.**

```python
"""event_pairs_daily and event_files on a real PostgreSQL (migration 021).

Opt-in: set ORBIS_TEST_DATABASE_URL to a throwaway database with the
migrations applied. Every test runs in a transaction that is rolled back.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
import pytest_asyncio

DATABASE_URL = os.environ.get("ORBIS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ORBIS_TEST_DATABASE_URL is not set (opt-in database tests)"
)


@pytest_asyncio.fixture
async def conn():
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    if not await connection.fetchval("SELECT to_regclass('event_pairs_daily') IS NOT NULL"):
        await connection.close()
        pytest.skip("event_pairs_daily is missing: apply migration 021")
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()


async def _columns(conn, table: str) -> list[tuple[str, str]]:
    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_name = $1 ORDER BY ordinal_position",
        table,
    )
    return [(r["column_name"], r["data_type"]) for r in rows]


@pytest.mark.asyncio
async def test_each_table_has_exactly_its_planned_columns(conn):
    assert await _columns(conn, "event_pairs_daily") == [
        ("a_iso", "text"),
        ("b_iso", "text"),
        ("day", "date"),
        ("quad_class", "smallint"),
        ("n_events", "integer"),
        ("n_reports", "integer"),
        ("mentions", "integer"),
        ("goldstein_sum", "double precision"),
        ("tone_sum", "double precision"),
        ("sample_urls", "ARRAY"),
        ("outlets", "ARRAY"),
    ]
    assert await _columns(conn, "event_files") == [
        ("slot", "timestamp with time zone"),
        ("status", "text"),
        ("n_rows", "integer"),
        ("n_kept", "integer"),
        ("processed_at", "timestamp with time zone"),
    ]


@pytest.mark.asyncio
async def test_keys_indexes_and_storage(conn):
    pk = await conn.fetch(
        "SELECT a.attname FROM pg_index i"
        " JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)"
        " WHERE i.indrelid = 'event_pairs_daily'::regclass AND i.indisprimary"
        " ORDER BY array_position(i.indkey::int2[], a.attnum)"
    )
    assert [r["attname"] for r in pk] == ["a_iso", "b_iso", "day", "quad_class"]
    assert await conn.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_event_pairs_day'"
    ) == "CREATE INDEX idx_event_pairs_day ON public.event_pairs_daily USING btree (day)"
    assert await conn.fetchval(
        "SELECT reloptions FROM pg_class WHERE oid = 'event_pairs_daily'::regclass"
    ) == ["fillfactor=70"]
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f'"
            " AND conrelid IN ('event_pairs_daily'::regclass, 'event_files'::regclass)"
        )
        == 0
    )


_ROW = (
    "INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events, n_reports,"
    " mentions, goldstein_sum, tone_sum) VALUES ($1, $2, $3, $4, 1, 1, 1, 0, 0)"
)


@pytest.mark.asyncio
async def test_checks_reject_a_bad_quad_class_and_a_domestic_pair(conn):
    import asyncpg

    await conn.execute(_ROW, "US", "IR", date(2026, 10, 21), 3)
    for args in (("US", "IR", date(2026, 10, 21), 5), ("US", "US", date(2026, 10, 21), 1)):
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():  # a savepoint
                await conn.execute(_ROW, *args)
    with pytest.raises(asyncpg.CheckViolationError):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO event_files (slot, status) VALUES (now(), 'other')"
            )
```

**Step 6: Run locally.**

Run: `cd backend && python -m pytest tests/test_events_schema_db.py -q`
Expected: `3 skipped`. They run on CI.

### Task 19a.4: README and PR

**Step 7:** In `database/README.md`, after the `articles` table section, add `### event_pairs_daily and event_files` with a column table copied from the migration's comments. Add one line saying they're filled by `app/services/events.py` from PR 19b.

**Step 8: Commit.**

```bash
git add database/migrations/021_event_pairs_daily.sql backend/tests/test_migrations.py backend/tests/test_events_schema_db.py database/README.md
git commit -m "feat(db): migration 021 adds GDELT event rollups (event_pairs_daily, event_files)"
```

**Step 9:** Push, then open the PR `feat(db): GDELT event rollup tables (PR 19a)`.
- CI's Backend Checks must show `test_events_schema_db.py` as 3 passed, not skipped.
- The description repeats the note about rerunning the Deploy workflow if the lock timeout trips.

**After merge:** the controller confirms that the Deploy log shows `Applied: 021_event_pairs_daily.sql`. Only then does 19b merge.

**Rollback:** nothing reads or writes the tables until 19b, so reverting the PR is harmless; the empty tables can stay. If Phase 5 is abandoned, a later migration drops them.

---

## PR 19b: Events ingestion, rollups and the CI repro

Branch: `claude/p5-events-ingest`. Merge only after 19a is deployed.

### Task 19b.1: CAMEO → ISO table (generated on CI, with tests)

The generator downloads two small reference files, so it **runs only on CI** (decision 11). A workflow on the PR generates the table on the runner and commits it to the branch. Nothing is downloaded on the owner's machine.

**Files:**
- Create: `scripts/gen_cameo_countries.py`, `.github/workflows/cameo-countries.yml`, `backend/tests/test_cameo_countries.py`
- Generated by CI (never by hand): `backend/app/services/cameo_countries.py`

**Step 1: Write the failing tests** (`backend/tests/test_cameo_countries.py`).

```python
from app.services.cameo_countries import CAMEO_TO_ISO2, cameo_to_iso2
from app.services.country_centroids import centroid


def test_iso_alpha3_codes_map_to_alpha2():
    assert cameo_to_iso2("USA") == "US"
    assert cameo_to_iso2("GBR") == "GB"
    assert cameo_to_iso2("RUS") == "RU"
    assert cameo_to_iso2("CHN") == "CN"
    assert cameo_to_iso2("IRN") == "IR"
    assert cameo_to_iso2("UKR") == "UA"
    assert cameo_to_iso2("COD") == "CD"
    assert cameo_to_iso2("COG") == "CG"


def test_cameo_exceptions_map_to_their_country():
    assert cameo_to_iso2("ROM") == "RO"
    assert cameo_to_iso2("TMP") == "TL"
    assert cameo_to_iso2("MTN") == "ME"
    assert cameo_to_iso2("WSB") == "PS"
    assert cameo_to_iso2("GZS") == "PS"
    assert cameo_to_iso2("PSE") == "PS"
    assert cameo_to_iso2("BAG") == "IQ"


def test_regional_withdrawn_and_unknown_codes_are_unmapped():
    for code in ("AFR", "EUR", "MEA", "WST", "SAS", "ANT", "SCG", "XYZ", "US", "", None):
        assert cameo_to_iso2(code) == "", code


def test_case_and_spaces_are_ignored():
    assert cameo_to_iso2(" usa ") == "US"


def test_mapped_countries_without_a_label_point_are_few_and_small():
    """The relations read drops a pair whose code has no label point, as /api/links
    does. Only small territories may lack one; list them in the PR."""
    missing = sorted({iso for iso in CAMEO_TO_ISO2.values() if centroid(iso) is None})
    assert len(missing) <= 10, missing
    assert not set(missing) & {"US", "CN", "RU", "UA", "IL", "PS", "IR", "IN", "GB", "FR"}
```

**Step 2: Run them to verify they fail.**

Run: `cd backend && python -m pytest tests/test_cameo_countries.py -q`
Expected: ERROR collecting, `ModuleNotFoundError: No module named 'app.services.cameo_countries'`.

**Step 3: Write the generator** (`scripts/gen_cameo_countries.py`).

```python
"""Generate backend/app/services/cameo_countries.py: GDELT Events' CAMEO actor
country codes (Actor1CountryCode, Actor2CountryCode) to ISO 3166-1 alpha-2.

CAMEO country codes are ISO alpha-3 with a few exceptions (OVERRIDES), plus
regional codes (REGIONAL) that name no country. Every GeoNames ISO3 maps to
its ISO2, so a code CAMEO's list lacks but GDELT emits (e.g. SSD) still maps.

Run on CI only, by .github/workflows/cameo-countries.yml, which commits the
table. It downloads two small reference files (about 31 KB and 5 KB) on the
runner. Don't run it locally: the owner approves downloads case by case.
"""

import hashlib
import re
import urllib.request
from pathlib import Path

GEONAMES = "https://download.geonames.org/export/dump/countryInfo.txt"
CAMEO = "https://www.gdeltproject.org/data/lookups/CAMEO.country.txt"
OUT = Path(__file__).resolve().parents[1] / "backend/app/services/cameo_countries.py"

# CAMEO codes that are not the country's ISO alpha-3.
OVERRIDES = {
    "ROM": "RO",  # Romania (ISO ROU)
    "TMP": "TL",  # East Timor (ISO TLS)
    "MTN": "ME",  # Montenegro (ISO MNE)
    "WSB": "PS",  # West Bank
    "GZS": "PS",  # Gaza Strip
    "BAG": "IQ",  # Baghdad: CAMEO's code for Iraq's seat of government
}
# Withdrawn codes GeoNames still lists: no country today, so unmapped.
UNMAPPED = {"ANT", "SCG"}  # Netherlands Antilles (2010), Serbia and Montenegro (2006)
REGIONAL = set(
    "AFR ASA BLK CRB CAU CFR CAS CEU EIN EAF EEU EUR LAM MEA MDT NAF NMR PGS SCN SAM "
    "SAS SEA SAF WAF WST".split()
)
ANCHORS = {
    "USA": "US", "GBR": "GB", "RUS": "RU", "CHN": "CN", "IRN": "IR", "ISR": "IL",
    "PSE": "PS", "UKR": "UA", "COD": "CD", "ROM": "RO", "TMP": "TL", "XKX": "XK",
}


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"refusing to write {OUT.name}: {message}")


def fetch(url: str) -> bytes:
    return urllib.request.urlopen(url, timeout=30).read()


geonames_raw, cameo_raw = fetch(GEONAMES), fetch(CAMEO)
table: dict[str, str] = {}
for line in geonames_raw.decode("utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    cols = line.split("\t")
    iso2, iso3 = cols[0].strip(), cols[1].strip()
    if iso2 and iso3:
        table[iso3] = iso2

collisions = sorted(code for code in OVERRIDES if code in table)
check(not collisions, f"overrides replace GeoNames codes: {collisions}")
table.update(OVERRIDES)
for code in UNMAPPED | REGIONAL:
    table.pop(code, None)

unknown = []
for line in cameo_raw.decode("utf-8", errors="replace").splitlines()[1:]:  # header: CODE LABEL
    code, _, label = line.partition("\t")
    code = code.strip()
    if code and code not in table and code not in UNMAPPED | REGIONAL:
        unknown.append(f"{code} ({label.strip()})")
check(not unknown, f"CAMEO codes with no decision (map, UNMAPPED or REGIONAL): {unknown}")

check(240 <= len(table) <= 270, f"{len(table)} codes, expected 240 to 270")
for cameo, iso in ANCHORS.items():
    check(table.get(cameo) == iso, f"{cameo} maps to {table.get(cameo)!r}, expected {iso}")
bad = sorted(
    f"{c}->{i}"
    for c, i in table.items()
    if not (re.fullmatch(r"[A-Z]{3}", c) and re.fullmatch(r"[A-Z]{2}", i))
)
check(not bad, f"malformed codes: {bad}")

body = "\n".join(f'    "{c}": "{i}",' for c, i in sorted(table.items()))
with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(
        '"""CAMEO actor country codes (GDELT Events) to ISO 3166-1 alpha-2.\n\n'
        "Generated by scripts/gen_cameo_countries.py from GeoNames countryInfo.txt\n"
        "(ISO3 to ISO2) plus that script's CAMEO overrides. Regional codes (AFR,\n"
        "EUR, MEA, ...) and withdrawn ones map to nothing. Do not edit by hand.\n\n"
        f"Source: {GEONAMES}\n"
        f"Source SHA-256: {hashlib.sha256(geonames_raw).hexdigest()}\n"
        f"Source: {CAMEO}\n"
        f"Source SHA-256: {hashlib.sha256(cameo_raw).hexdigest()}\n"
        '"""\n\nfrom __future__ import annotations\n\n'
        f"CAMEO_TO_ISO2: dict[str, str] = {{\n{body}\n}}\n\n\n"
        "def cameo_to_iso2(code: str | None) -> str:\n"
        '    """The ISO alpha-2 code for a CAMEO country code, or "" for none."""\n'
        '    return CAMEO_TO_ISO2.get((code or "").strip().upper(), "")\n'
    )
print(f"wrote {len(table)} codes to {OUT}")
```

**Step 4: Write the workflow** (`.github/workflows/cameo-countries.yml`).

```yaml
name: CAMEO country table

# Generates backend/app/services/cameo_countries.py on the runner: the generator
# downloads GeoNames countryInfo.txt and GDELT's CAMEO.country.txt, which never
# happens on a developer's machine. On a PR that changes the generator or the
# table, a table that differs from the generator's output (or is missing) is
# committed to the PR branch by the bot, and this check fails once: pull the
# commit and push again, and it passes.
on:
  pull_request:
    branches: [main]
    paths:
      - scripts/gen_cameo_countries.py
      - backend/app/services/cameo_countries.py
      - .github/workflows/cameo-countries.yml

permissions:
  contents: write

jobs:
  generate:
    name: CAMEO country table
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install ruff
      - name: Generate the table
        run: |
          python scripts/gen_cameo_countries.py
          ruff format backend/app/services/cameo_countries.py
      - name: Commit it when it changed
        run: |
          table=backend/app/services/cameo_countries.py
          if git ls-files --error-unmatch "$table" >/dev/null 2>&1 && git diff --quiet -- "$table"; then
            echo "The committed table matches the generator."
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898283+github-actions[bot]@users.noreply.github.com"
          git add "$table"
          git commit -m "chore(events): generate the CAMEO country table on CI"
          git push origin "HEAD:${{ github.head_ref }}"
          echo "::error::Generated the table and pushed it to this branch: pull it and push again."
          exit 1
```

**Step 5: Commit the generator, the workflow and the tests, and push.**

```bash
git add scripts/gen_cameo_countries.py .github/workflows/cameo-countries.yml backend/tests/test_cameo_countries.py
git commit -m "feat(events): CAMEO actor country codes to ISO alpha-2, generated on CI"
git push -u origin claude/p5-events-ingest
```

Expected on the PR:
- **"CAMEO country table" fails once,** as designed: its log shows `wrote 2xx codes to …/cameo_countries.py`, and the branch gains a bot commit `chore(events): generate the CAMEO country table on CI`.
- **Backend Checks fails on this commit** (`test_cameo_countries.py`: no module yet). That's expected; the next push fixes it.
- **If the generator refuses** because a CAMEO code has no decision, the log names it. Add it to `OVERRIDES`, `UNMAPPED` or `REGIONAL` with a comment, push, and the job runs again.
- **If the bot's push is refused** (the repository's workflow permissions are read-only), stop and ask the controller: the owner either allows write access for workflows or runs the generator.

**Step 6: Pull the generated table and run the tests.**

Run: `git pull --ff-only && cd backend && python -m pytest tests/test_cameo_countries.py -q`
Expected: 5 passed. Put the `missing` list (the countries with no label point) in the PR description.

This pulls a commit from our own repository. It isn't a data download.

**Step 7:** The next push (the following tasks' commits) reruns the check, and it passes ("The committed table matches the generator."). Never edit `cameo_countries.py` by hand: change the generator, and CI regenerates it.

### Task 19b.2: one URL sanitiser, shared (`app/services/urls.py`)

`board.web_url` is the strict sanitiser: absolute http(s), a host, no control or space characters, at most 2,048 characters. Move it to a shared module rather than copy it.

**Files:**
- Create: `backend/app/services/urls.py`, `backend/tests/test_urls.py`
- Modify: `backend/app/services/board.py` (import `web_url` from `urls`, and delete its copy, `_MAX_URL` and `_URL_UNSAFE`)

**Step 1: Write the failing tests** (`backend/tests/test_urls.py`).

```python
from app.services.urls import outlet, web_url


def test_web_url_keeps_http_and_https_links_only():
    assert web_url("https://example.com/a") == "https://example.com/a"
    assert web_url("http://example.com/a?b=1") == "http://example.com/a?b=1"
    for bad in ("javascript:alert(1)", "ftp://x.test/a", "//example.com/a", "https://",
                "https://exa mple.com/", "https://example.com/\x00", "BBC Monitoring, 21 Oct",
                "https://example.com/" + "a" * 2100, None, 42):
        assert web_url(bad) is None, bad


def test_outlet_is_the_host_without_www():
    assert outlet("https://www.Reuters.com/world/x") == "reuters.com"
    assert outlet("http://news.bbc.co.uk/a") == "news.bbc.co.uk"
    assert outlet("not a url") == ""


def test_board_still_uses_the_shared_sanitiser():
    from app.services import board

    assert board.web_url is web_url
```

**Step 2: Run them to verify they fail.**

Run: `cd backend && python -m pytest tests/test_urls.py -q`
Expected: ERROR collecting, `ModuleNotFoundError: No module named 'app.services.urls'`.

**Step 3: Implement** `backend/app/services/urls.py`. Move `board.web_url` here verbatim, with its `_MAX_URL` and `_URL_UNSAFE`, and add:

```python
def outlet(url: str) -> str:
    """The outlet an http(s) URL comes from: its host, lowercased, without "www."."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")
```

In `board.py`: `from app.services.urls import web_url`, and delete the moved definitions.

**Step 4: Run the tests.**

Run: `cd backend && python -m pytest tests/test_urls.py tests/test_board.py -q`
Expected: all pass.

**Step 5: Commit:** `refactor(api): one shared http(s) URL sanitiser`.

### Task 19b.3: the GDELT index and capped downloads (`gdelt.py`)

**Files:**
- Modify: `backend/app/services/gdelt.py`
- Test: `backend/tests/test_gdelt.py`

`fetch_raw_gkg` stays as it is: the GKG path's behaviour and tests don't change. The events step reads the same `lastupdate.txt` URL through the new parser.

**Step 1: Write the failing tests** (append to `backend/tests/test_gdelt.py`).

```python
import httpx

from app.services.gdelt import Download, download_capped, parse_lastupdate

LASTUPDATE = (
    "80351 4e89d1d989499fe69f4f102292247399 "
    "http://data.gdeltproject.org/gdeltv2/20261021123000.export.CSV.zip\n"
    "119531 ae8ab8e83b1347bb8fae2af1f9b8c6dd "
    "http://data.gdeltproject.org/gdeltv2/20261021123000.mentions.CSV.zip\n"
    "4631710 f231d70b0b4425c19613644c5d48cfc8 "
    "http://data.gdeltproject.org/gdeltv2/20261021123000.gkg.csv.zip\n"
)


class TestParseLastupdate:
    def test_reads_each_kind(self):
        entries = parse_lastupdate(LASTUPDATE)
        assert entries["export"].size == 80351
        assert entries["export"].md5 == "4e89d1d989499fe69f4f102292247399"
        assert entries["export"].url.endswith("20261021123000.export.CSV.zip")
        assert entries["gkg"].size == 4631710

    def test_skips_malformed_lines(self):
        assert parse_lastupdate("garbage\nabc def http://x/1.export.CSV.zip\n") == {}


def _client_with(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        gdelt.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(gdelt.asyncio, "sleep", AsyncMock())


class TestDownloadCapped:
    @pytest.mark.asyncio
    async def test_returns_the_body_under_the_cap(self, monkeypatch):
        _client_with(monkeypatch, lambda req: httpx.Response(200, content=b"x" * 10))
        assert await download_capped("https://data.gdeltproject.org/a", 10) == Download("ok", b"x" * 10)

    @pytest.mark.asyncio
    async def test_refuses_a_body_over_the_cap(self, monkeypatch):
        _client_with(monkeypatch, lambda req: httpx.Response(200, content=b"x" * 11))
        assert (await download_capped("https://data.gdeltproject.org/a", 10)).status == "too_big"

    @pytest.mark.asyncio
    async def test_a_404_is_missing_and_not_retried(self, monkeypatch):
        calls = []
        _client_with(monkeypatch, lambda req: calls.append(req) or httpx.Response(404))
        assert (await download_capped("https://data.gdeltproject.org/a", 10)).status == "missing"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_never_follows_a_redirect(self, monkeypatch):
        _client_with(
            monkeypatch,
            lambda req: httpx.Response(302, headers={"location": "https://evil.test/a"}),
        )
        assert (await download_capped("https://data.gdeltproject.org/a", 10)).status == "failed"
```

**Step 2: Run them to verify they fail.**

Run: `cd backend && python -m pytest tests/test_gdelt.py -q`
Expected: ERROR collecting, `ImportError: cannot import name 'Download' from 'app.services.gdelt'`.

**Step 3: Implement** in `gdelt.py`, after `_download_bytes`. Add `from typing import NamedTuple` to the imports.

```python
class LastUpdateEntry(NamedTuple):
    """One file lastupdate.txt lists: its size in bytes, MD5 and URL."""

    size: int
    md5: str
    url: str


_LASTUPDATE_KINDS = (
    ("export", ".export.csv.zip"),
    ("mentions", ".mentions.csv.zip"),
    ("gkg", ".gkg.csv.zip"),
)


def parse_lastupdate(text: str) -> dict[str, LastUpdateEntry]:
    """lastupdate.txt's lines (``SIZE MD5 URL``), keyed by kind: export, mentions, gkg."""
    entries: dict[str, LastUpdateEntry] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        name = parts[2].lower()
        for kind, suffix in _LASTUPDATE_KINDS:
            if name.endswith(suffix) and kind not in entries:
                entries[kind] = LastUpdateEntry(int(parts[0]), parts[1].lower(), parts[2])
    return entries


async def fetch_lastupdate() -> dict[str, LastUpdateEntry] | None:
    """The newest 15-minute files, from the lastupdate.txt the GKG path reads too."""
    raw = await _download_bytes(_GKG_LASTUPDATE_URL)
    return parse_lastupdate(raw.decode("utf-8", errors="replace")) if raw else None


class Download(NamedTuple):
    """A capped download: ok (with its bytes), missing (404), too_big or failed."""

    status: str
    body: bytes = b""


_CAPPED_TIMEOUT = 30.0  # seconds


async def download_capped(url: str, max_bytes: int) -> Download:
    """GET *url*, reading at most *max_bytes*, and never following a redirect.

    A 404 is "missing" (GDELT skips the odd slot) and isn't retried. Other
    errors (a redirect, 5xx, a timeout) are retried as _download_bytes does,
    then "failed".
    """
    name = url.rsplit("/", 1)[-1]
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_CAPPED_TIMEOUT) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code == 404:
                        return Download("missing")
                    resp.raise_for_status()  # raises on 3xx too: redirects are refused
                    length = resp.headers.get("content-length", "")
                    if length.isdigit() and int(length) > max_bytes:
                        return Download("too_big")
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            return Download("too_big")
                    return Download("ok", bytes(body))
        except Exception as exc:
            logger.warning(
                "Download attempt %d/%d failed for %s (%s).", attempt, _MAX_RETRIES, name, exc
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF_BASE**attempt)
    return Download("failed")
```

**Step 4: Run the tests.**

Run: `cd backend && python -m pytest tests/test_gdelt.py -q`
Expected: all pass, the existing GKG tests included.

**Step 5: Commit:** `feat(gdelt): read lastupdate.txt's entries and download with a size cap`.

### Task 19b.4: parse and aggregate (`app/services/events.py`, pure functions)

**Files:**
- Create: `backend/app/services/events.py`, `backend/tests/test_events.py`

**Step 1: Write the failing tests** (`backend/tests/test_events.py`).

```python
"""GDELT Events parsing and aggregation (no database, no network)."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import events
from app.services.events import Rollup, parse_events, plan_slots, read_export, slot_of, slot_url

TODAY = date(2026, 10, 21)


def _event(**over) -> str:
    """One 61-column export row: USA acts on IRN, verbal conflict, unless overridden."""
    fields = [""] * events.COLUMNS
    fields[0] = str(over.pop("event_id", 1))
    fields[events._ACTOR1_COUNTRY] = over.pop("a", "USA")
    fields[events._ACTOR2_COUNTRY] = over.pop("b", "IRN")
    fields[events._IS_ROOT] = over.pop("root", "1")
    fields[events._QUAD_CLASS] = over.pop("quad", "3")
    fields[events._GOLDSTEIN] = over.pop("goldstein", "-2.0")
    fields[events._NUM_MENTIONS] = over.pop("mentions", "10")
    fields[events._AVG_TONE] = over.pop("tone", "-3.5")
    fields[events._DATE_ADDED] = over.pop("added", "20261021121500")
    fields[events._SOURCE_URL] = over.pop("url", "https://www.example.com/a")
    assert not over, over
    return "\t".join(fields)


def _parse(*rows: str) -> tuple[dict, events.ParseStats]:
    rollups: dict = {}
    stats = parse_events("\n".join(rows) + "\n", TODAY, rollups)
    return rollups, stats


def test_one_event_makes_one_rollup():
    rollups, stats = _parse(_event())
    r = rollups[("US", "IR", TODAY, 3)]
    assert (r.n_events, r.mentions, r.goldstein_sum, r.tone_sum) == (1, 10, -2.0, -3.5)
    assert r.reports == {"https://www.example.com/a"}
    assert r.samples == ["https://www.example.com/a"]
    assert r.outlets == ["example.com"]
    assert (stats.rows, stats.kept, stats.not_root) == (1, 1, 0)


def test_only_root_events_count():
    """Decision 3: an event outside the lead paragraph adds nothing."""
    rollups, stats = _parse(_event(root="0"), _event(root=""))
    assert rollups == {}
    assert (stats.rows, stats.kept, stats.not_root) == (2, 0, 2)


def test_events_add_up_and_a_report_counts_once():
    rollups, _ = _parse(_event(), _event(mentions="5", goldstein="-4.0"))
    r = rollups[("US", "IR", TODAY, 3)]
    assert (r.n_events, r.mentions, r.goldstein_sum, len(r.reports)) == (2, 15, -6.0, 1)


def test_unmapped_blank_and_regional_actors_are_dropped_and_counted():
    rollups, stats = _parse(_event(a=""), _event(b="AFR"), _event(a="EUR", b="XYZ"))
    assert rollups == {}
    assert stats.no_pair == 3
    assert stats.unmapped == {"AFR": 1, "EUR": 1, "XYZ": 1}


def test_domestic_events_are_dropped():
    rollups, stats = _parse(_event(a="USA", b="USA"))
    assert rollups == {} and stats.same_country == 1


@pytest.mark.parametrize(
    "row",
    [
        "too\tfew\tfields",
        _event(quad="5"),
        _event(quad="x"),
        _event(goldstein="nan"),
        _event(goldstein="11"),
        _event(mentions="-1"),
        _event(tone="inf"),
        _event(added="2026"),
        _event(added="2026102112150"),
    ],
)
def test_malformed_rows_are_counted_and_skipped(row):
    rollups, stats = _parse(row)
    assert rollups == {} and stats.malformed == 1


def test_events_added_before_retention_are_stale():
    old = (TODAY - timedelta(days=9)).strftime("%Y%m%d") + "000000"
    rollups, stats = _parse(_event(added=old))
    assert rollups == {} and stats.stale == 1


def test_a_non_web_source_still_counts_but_is_never_kept():
    rollups, _ = _parse(_event(url="javascript:alert(1)"), _event(url="BBC Monitoring, 21 Oct"))
    r = rollups[("US", "IR", TODAY, 3)]
    assert r.n_events == 2 and r.reports == set() and r.samples == [] and r.outlets == []


def test_samples_and_outlets_are_capped_first_seen_first():
    urls = [f"https://site{i}.test/a" for i in range(10)]
    rollups, _ = _parse(*(_event(url=u) for u in urls))
    r = rollups[("US", "IR", TODAY, 3)]
    assert r.samples == urls[: events.MAX_SAMPLES]
    assert r.outlets == [f"site{i}.test" for i in range(events.MAX_OUTLETS)]
    assert len(r.reports) == 10


def test_mentions_and_tone_are_clamped():
    rollups, _ = _parse(_event(mentions="999999", tone="250"))
    r = rollups[("US", "IR", TODAY, 3)]
    assert r.mentions == events.MAX_EVENT_MENTIONS and r.tone_sum == 100.0


def test_rows_past_the_cap_are_not_read(monkeypatch):
    monkeypatch.setattr(events, "MAX_ROWS", 3)
    _, stats = _parse(*(_event() for _ in range(5)))
    assert stats.rows == 3 and stats.truncated


def test_windows_line_endings_parse():
    rollups, _ = _parse(_event() + "\r")
    assert ("US", "IR", TODAY, 3) in rollups


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestReadExport:
    def test_reads_the_one_export_member(self):
        body = _zip({"20261021123000.export.CSV": b"a\tb\x00\n"})
        assert read_export(body) == "a\tb\n"

    @pytest.mark.parametrize(
        "body",
        [
            b"not a zip",
            _zip({"20261021123000.export.CSV": b"a", "x.txt": b"b"}),
            _zip({"evil.sh": b"a"}),
        ],
    )
    def test_refuses_anything_else(self, body):
        assert read_export(body) is None

    def test_refuses_an_oversized_member(self, monkeypatch):
        monkeypatch.setattr(events, "MAX_CSV_BYTES", 4)
        assert read_export(_zip({"20261021123000.export.CSV": b"12345"})) is None


T = datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)
Q = timedelta(minutes=15)


class TestSlots:
    def test_slot_round_trip(self):
        assert slot_url(T) == "https://data.gdeltproject.org/gdeltv2/20261021123000.export.CSV.zip"
        assert slot_of(slot_url(T)) == T
        assert slot_of("http://data.gdeltproject.org/gdeltv2/20261021123000.gkg.csv.zip") is None

    def test_first_run_takes_only_the_newest(self):
        assert plan_slots(T, set()) == [T]

    def test_catches_up_missed_slots_newest_first(self):
        done = {T - 3 * Q}
        assert plan_slots(T, done) == [T, T - Q, T - 2 * Q, T - 4 * Q]

    def test_skips_done_slots_and_the_newest_when_done(self):
        assert plan_slots(T, {T, T - Q}) == [T - 2 * Q, T - 3 * Q, T - 4 * Q, T - 5 * Q]

    def test_never_reaches_past_the_catch_up_window(self, monkeypatch):
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 100)
        slots = plan_slots(T, {T - 30 * Q})
        assert min(slots) > T - timedelta(hours=events.CATCHUP_HOURS)


def test_a_rollup_records_each_event():
    r = Rollup()
    r.add(3, 1.5, 2.0, None)
    assert (r.n_events, r.mentions, r.goldstein_sum, r.tone_sum) == (1, 3, 1.5, 2.0)
```

**Step 2: Run them to verify they fail.**

Run: `cd backend && python -m pytest tests/test_events.py -q`
Expected: ERROR collecting, `ModuleNotFoundError: No module named 'app.services.events'`.

**Step 3: Implement** the pure half of `backend/app/services/events.py`.

```python
"""GDELT 2.0 Events: daily country-pair rollups (Phase 5, PR 19).

Each ingestion cycle adds the newest 15-minute Event export (the
export.CSV.zip line of lastupdate.txt) to event_pairs_daily, plus earlier
slots no cycle has added: a cycle starts about every half hour, so every
other file would otherwise be missed, and rollups are counts. Nothing is
stored per event. Each file is parsed in memory; its root events between two
different mapped countries are aggregated in Python by (actor 1 country,
actor 2 country, UTC day added, QuadClass); the cycle's rollups go to the
database in one batched upsert, in the transaction that records the files in
event_files, so no file is ever added twice.

GDELT data is untrusted: only https URLs on GDELT's data host are fetched
(no redirects), the zip, its CSV and its rows are capped, malformed rows are
counted and skipped, and source URLs are kept only when they are http(s).
"""

from __future__ import annotations

import io
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

from app.config import settings
from app.services.cameo_countries import cameo_to_iso2
from app.services.gdelt import _GDELT_HOST
from app.services.urls import outlet, web_url

# GDELT 2.0 Event export (Event Codebook V2.0): 61 tab-separated columns, no header.
COLUMNS = 61
_ACTOR1_COUNTRY = 7
_ACTOR2_COUNTRY = 17
_IS_ROOT = 25
_QUAD_CLASS = 29
_GOLDSTEIN = 30
_NUM_MENTIONS = 31
_AVG_TONE = 34
_DATE_ADDED = 59
_SOURCE_URL = 60

SLOT = timedelta(minutes=15)
# The newest file plus missed ones: a cycle starts about every 30 minutes, so
# about 2 files a cycle; 4 covers a long cycle. Never further back than this.
MAX_FILES_PER_CYCLE = 4
CATCHUP_HOURS = 2
# Caps on untrusted input. Exports are about 80 KB zipped (2026-10-21), about
# 1,200 rows; these leave 25x headroom and bound the work.
MAX_ZIP_BYTES = 2_000_000
MAX_CSV_BYTES = 20_000_000
MAX_ROWS = 30_000
MAX_EVENT_MENTIONS = 10_000  # one event's NumMentions, clamped
MAX_URL_CHARS = 1_000
MAX_SAMPLES = 3  # per rollup row: sample_urls
MAX_OUTLETS = 8  # per rollup row: outlets

_EXPORT_URL = re.compile(r"/(\d{14})\.export\.CSV\.zip$", re.IGNORECASE)
_EXPORT_MEMBER = re.compile(r"\d{14}\.export\.CSV", re.IGNORECASE)

Key = tuple[str, str, date, int]  # (a_iso, b_iso, day, quad_class)


@dataclass
class Rollup:
    """One (a, b, day, quad) group's sums from this cycle's files."""

    n_events: int = 0
    mentions: int = 0
    goldstein_sum: float = 0.0
    tone_sum: float = 0.0
    reports: set[str] = field(default_factory=set)
    samples: list[str] = field(default_factory=list)
    outlets: list[str] = field(default_factory=list)

    def add(self, mentions: int, goldstein: float, tone: float, url: str | None) -> None:
        self.n_events += 1
        self.mentions += mentions
        self.goldstein_sum += goldstein
        self.tone_sum += tone
        if url is None:
            return
        self.reports.add(url)
        if len(self.samples) < MAX_SAMPLES and url not in self.samples:
            self.samples.append(url)
        host = outlet(url)
        if host and len(self.outlets) < MAX_OUTLETS and host not in self.outlets:
            self.outlets.append(host)


@dataclass
class ParseStats:
    """What a file held, for the cycle's log line and the repro."""

    rows: int = 0
    kept: int = 0
    malformed: int = 0
    not_root: int = 0
    no_pair: int = 0
    same_country: int = 0
    stale: int = 0
    truncated: bool = False
    unmapped: Counter = field(default_factory=Counter)

    def add(self, other: ParseStats) -> None:
        for name in ("rows", "kept", "malformed", "not_root", "no_pair", "same_country", "stale"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.truncated = self.truncated or other.truncated
        self.unmapped.update(other.unmapped)


class _Event(NamedTuple):
    a: str
    b: str
    quad: int
    goldstein: float
    mentions: int
    tone: float
    day: date
    root: bool
    url: str | None


def _event(fields: list[str]) -> _Event | None:
    """The fields this module reads from one export row, or None when it is malformed."""
    if len(fields) != COLUMNS:
        return None
    added = fields[_DATE_ADDED].strip()
    if len(added) != 14 or not (added.isascii() and added.isdigit()):
        return None
    try:
        quad = int(fields[_QUAD_CLASS])
        goldstein = float(fields[_GOLDSTEIN])
        mentions = int(fields[_NUM_MENTIONS])
        tone = float(fields[_AVG_TONE])
        day = datetime.strptime(added, "%Y%m%d%H%M%S").date()
    except ValueError:
        return None
    if quad not in (1, 2, 3, 4) or mentions < 0:
        return None
    if not (math.isfinite(goldstein) and -10 <= goldstein <= 10 and math.isfinite(tone)):
        return None
    url = fields[_SOURCE_URL].strip()
    return _Event(
        a=fields[_ACTOR1_COUNTRY].strip(),
        b=fields[_ACTOR2_COUNTRY].strip(),
        quad=quad,
        goldstein=goldstein,
        mentions=min(mentions, MAX_EVENT_MENTIONS),
        tone=max(-100.0, min(100.0, tone)),
        day=day,
        root=fields[_IS_ROOT].strip() == "1",
        url=web_url(url) if len(url) <= MAX_URL_CHARS else None,
    )


def parse_events(raw: str, today: date, rollups: dict[Key, Rollup]) -> ParseStats:
    """Add a decoded export file's events to *rollups*; return what the file held.

    Kept: a root event (IsRootEvent = 1, the lead paragraph: the higher signal),
    whose actors' countries both map to ISO and differ, added within retention
    (up to a day ahead, for clock skew). CPU-bound: run it in a worker thread.
    """
    stats = ParseStats()
    oldest = today - timedelta(days=settings.retention_days)
    newest = today + timedelta(days=1)
    for line in raw.splitlines():
        if not line:
            continue
        if stats.rows == MAX_ROWS:
            stats.truncated = True
            break
        stats.rows += 1
        event = _event(line.split("\t"))
        if event is None:
            stats.malformed += 1
            continue
        if not event.root:
            stats.not_root += 1
            continue
        if not oldest <= event.day <= newest:
            stats.stale += 1
            continue
        a, b = cameo_to_iso2(event.a), cameo_to_iso2(event.b)
        if not a or not b:
            stats.no_pair += 1
            for code, iso in ((event.a, a), (event.b, b)):
                if code and not iso:
                    stats.unmapped[code] += 1
            continue
        if a == b:
            stats.same_country += 1
            continue
        stats.kept += 1
        key = (a, b, event.day, event.quad)
        rollups.setdefault(key, Rollup()).add(event.mentions, event.goldstein, event.tone, event.url)
    return stats


def read_export(body: bytes) -> str | None:
    """A downloaded export zip's CSV, decoded, or None unless the zip holds exactly
    one export member within MAX_CSV_BYTES (whatever size it declares)."""
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            members = zf.infolist()
            if len(members) != 1 or not _EXPORT_MEMBER.fullmatch(members[0].filename):
                return None
            if members[0].file_size > MAX_CSV_BYTES:
                return None
            with zf.open(members[0]) as fh:
                data = fh.read(MAX_CSV_BYTES + 1)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, RuntimeError):
        return None
    if len(data) > MAX_CSV_BYTES:
        return None
    # NUL survives decoding, and Postgres TEXT rejects it.
    return data.decode("utf-8", errors="replace").replace("\x00", "")


def slot_of(url: str) -> datetime | None:
    """The 15-minute slot an export file URL is for, or None if it isn't one."""
    match = _EXPORT_URL.search(url)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def slot_url(slot: datetime) -> str:
    """The export file for *slot*, on GDELT's data host over https."""
    return f"https://{_GDELT_HOST}/gdeltv2/{slot:%Y%m%d%H%M%S}.export.CSV.zip"


def plan_slots(newest: datetime, done: set[datetime]) -> list[datetime]:
    """The slots to add this cycle, newest first.

    The newest file, then each earlier 15-minute slot no cycle has added, at
    most MAX_FILES_PER_CYCLE, and none older than CATCHUP_HOURS before the
    newest. Before any file has been added (*done* is empty), only the
    newest: there is no backfill.
    """
    if not done:
        return [newest]
    earliest = newest - timedelta(hours=CATCHUP_HOURS)
    slots: list[datetime] = []
    slot = newest
    while slot > earliest and len(slots) < MAX_FILES_PER_CYCLE:
        if slot not in done:
            slots.append(slot)
        slot -= SLOT
    return slots
```

**Step 4: Run the tests.**

Run: `cd backend && python -m pytest tests/test_events.py -q`
Expected: all pass.

**Step 5: Commit:** `feat(events): parse GDELT event exports into daily country-pair rollups`.

### Task 19b.5: store, purge and the cycle step

**Files:**
- Modify: `backend/app/services/events.py`, `backend/app/services/ingestion.py`, `backend/app/config.py`
- Test: `backend/tests/test_events.py`, `backend/tests/test_ingestion.py`

**Step 1: Write the failing tests.** Append to `test_events.py`, for the orchestration with fakes. (The real SQL is covered by the DB tests in Task 19b.6.)

```python
import hashlib
import logging
from unittest.mock import AsyncMock, patch

from app.services.gdelt import Download, LastUpdateEntry


def _export_zip(*rows: str) -> bytes:
    return _zip({"20261021123000.export.CSV": ("\n".join(rows) + "\n").encode()})


class _Pool:
    def __init__(self, done=()):
        self.done = [{"slot": s} for s in done]

    async def fetch(self, sql, *args):
        return self.done


def _index(body: bytes, size: int | None = None) -> dict:
    return {
        "export": LastUpdateEntry(
            len(body) if size is None else size,
            hashlib.md5(body).hexdigest(),
            "http://data.gdeltproject.org/gdeltv2/20261021123000.export.CSV.zip",
        )
    }


def _patches(index, downloads, pool, store):
    return (
        patch("app.services.events.fetch_lastupdate", AsyncMock(return_value=index)),
        patch("app.services.events.download_capped", AsyncMock(side_effect=downloads)),
        patch("app.services.events.get_pool", AsyncMock(return_value=pool)),
        patch("app.services.events.store_rollups", store),
    )


class TestIngestEvents:
    @pytest.mark.asyncio
    async def test_first_run_adds_only_the_newest_file(self):
        body = _export_zip(_event())
        store = AsyncMock(return_value=1)
        p = _patches(_index(body), [Download("ok", body)], _Pool(), store)
        with p[0], p[1], p[2], p[3]:
            await events.ingest_events(now=T + timedelta(minutes=5))
        _, rollups, files = store.await_args.args
        assert list(rollups) == [("US", "IR", TODAY, 3)]
        assert files == [events.FileResult(T, "ok", 1, 1)]

    @pytest.mark.asyncio
    async def test_a_newest_file_failing_its_md5_is_not_added(self, caplog):
        body = _export_zip(_event())
        store = AsyncMock()
        p = _patches(_index(body), [Download("ok", body + b"x")], _Pool(), store)
        with p[0], p[1], p[2], p[3], caplog.at_level(logging.WARNING, logger="orbis.events"):
            await events.ingest_events(now=T)
        store.assert_not_awaited()
        assert "MD5" in caplog.text

    @pytest.mark.asyncio
    async def test_a_newest_file_over_the_cap_is_never_downloaded(self):
        body = _export_zip(_event())
        download = AsyncMock()
        with (
            patch("app.services.events.fetch_lastupdate", AsyncMock(return_value=_index(body, size=events.MAX_ZIP_BYTES + 1))),
            patch("app.services.events.download_capped", download),
            patch("app.services.events.get_pool", AsyncMock(return_value=_Pool())),
            patch("app.services.events.store_rollups", AsyncMock()),
        ):
            await events.ingest_events(now=T)
        download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_older_slot_is_recorded_missing(self, monkeypatch):
        monkeypatch.setattr(events, "MAX_FILES_PER_CYCLE", 2)  # the newest and one before
        body = _export_zip(_event())
        store = AsyncMock(return_value=1)
        downloads = [Download("ok", body), Download("missing")]
        p = _patches(_index(body), downloads, _Pool(done=[T - 2 * Q]), store)
        with p[0], p[1], p[2], p[3]:
            await events.ingest_events(now=T)
        _, _, files = store.await_args.args
        assert files == [events.FileResult(T, "ok", 1, 1), events.FileResult(T - Q, "missing", 0, 0)]

    @pytest.mark.asyncio
    async def test_switched_off_it_does_nothing(self, monkeypatch):
        monkeypatch.setattr(events.settings, "events_ingestion_enabled", False)
        fetch = AsyncMock()
        with patch("app.services.events.fetch_lastupdate", fetch):
            await events.ingest_events(now=T)
        fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_failure_is_a_warning(self, caplog):
        with (
            patch("app.services.events.fetch_lastupdate", AsyncMock(side_effect=RuntimeError("boom"))),
            caplog.at_level(logging.WARNING, logger="orbis.events"),
        ):
            await events.ingest_events(now=T)  # does not raise
        assert "Events ingestion failed" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_one_summary_line(self, caplog):
        body = _export_zip(_event(), _event(a="USA", b="USA"), "bad")
        p = _patches(_index(body), [Download("ok", body)], _Pool(), AsyncMock(return_value=1))
        with p[0], p[1], p[2], p[3], caplog.at_level(logging.INFO, logger="orbis.events"):
            await events.ingest_events(now=T)
        [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Events: 1 file")]
        assert "3 rows, 1 kept (0 not root" in line and "1 same country, 1 malformed" in line
```

In `backend/tests/test_ingestion.py`:
- Add a module-level autouse fixture, so no cycle test reaches the network:
  ```python
  @pytest.fixture(autouse=True)
  def _no_events():
      with patch("app.services.ingestion.ingest_events", new_callable=AsyncMock) as ingest:
          yield ingest
  ```
- Extend `test_steps_run_in_order`: add `patch("app.services.ingestion.ingest_events", side_effect=_record("events"))`, and expect `["ingest", "purge", "events", "embed", ("threads", pool, embedded)]`.
- In `TestPurgeOldArticles`, patch `app.services.ingestion.purge_events` in both tests:
  - the first expects `[("threads", …), ("events", (pool, settings.retention_days)), ("articles", …)]`;
  - add `test_a_failed_events_purge_still_purges_the_articles`, which asserts the articles delete and "Events purge failed" in the log.

**Step 2: Run them to verify they fail.**

Run: `cd backend && python -m pytest tests/test_events.py tests/test_ingestion.py -q`
Expected: FAILs, with `AttributeError: module 'app.services.events' has no attribute 'ingest_events'` and `… has no attribute 'ingest_events'` on `app.services.ingestion`.

**Step 3: Implement.**

`backend/app/config.py`, under `# --- Ingestion ---`:

```python
    # GDELT Events rollups (app/services/events.py); false switches the step off.
    events_ingestion_enabled: bool = field(
        default_factory=lambda: (
            _env("EVENTS_INGESTION_ENABLED", "true").lower() in ("true", "1", "yes")
        )
    )
```

Append to `events.py`. Add `import asyncio`, `hashlib`, `logging`, `time`; `from typing import Any`; `from app.services.database import get_pool`; and `from app.services.gdelt import _gdelt_https_url, download_capped, fetch_lastupdate`.

```python
logger = logging.getLogger("orbis.events")

_MD5 = re.compile(r"[0-9a-f]{32}")
# pg_advisory_xact_lock key: one events writer at a time, even when two
# revisions overlap during a deploy.
_EVENTS_LOCK = 20_261_021


class FileResult(NamedTuple):
    slot: datetime
    status: str  # ok | missing
    n_rows: int
    n_kept: int


class AlreadyIngested(RuntimeError):
    """Another process added one of this cycle's files first; nothing was written."""


DONE_SQL = "SELECT slot FROM event_files WHERE slot >= $1"

CLAIM_SQL = """
INSERT INTO event_files (slot, status, n_rows, n_kept)
SELECT * FROM unnest($1::timestamptz[], $2::text[], $3::int[], $4::int[])
ON CONFLICT (slot) DO NOTHING
RETURNING slot
"""

# Sums add up. Sample URLs and outlets keep the first seen, without repeats,
# up to their caps ($12, $13: MAX_SAMPLES, MAX_OUTLETS).
UPSERT_SQL = """
INSERT INTO event_pairs_daily AS e
    (a_iso, b_iso, day, quad_class, n_events, n_reports, mentions,
     goldstein_sum, tone_sum, sample_urls, outlets)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (a_iso, b_iso, day, quad_class) DO UPDATE SET
    n_events      = e.n_events + EXCLUDED.n_events,
    n_reports     = e.n_reports + EXCLUDED.n_reports,
    mentions      = e.mentions + EXCLUDED.mentions,
    goldstein_sum = e.goldstein_sum + EXCLUDED.goldstein_sum,
    tone_sum      = e.tone_sum + EXCLUDED.tone_sum,
    sample_urls   = ARRAY(
        SELECT u FROM unnest(e.sample_urls || EXCLUDED.sample_urls) WITH ORDINALITY AS s(u, i)
        GROUP BY u ORDER BY min(i) LIMIT $12),
    outlets       = ARRAY(
        SELECT o FROM unnest(e.outlets || EXCLUDED.outlets) WITH ORDINALITY AS s(o, i)
        GROUP BY o ORDER BY min(i) LIMIT $13)
"""

PURGE_PAIRS_SQL = "DELETE FROM event_pairs_daily WHERE day < $1::date - $2::int"
PURGE_FILES_SQL = "DELETE FROM event_files WHERE slot < $1::timestamptz - interval '2 days'"


async def store_rollups(pool: Any, rollups: dict[Key, Rollup], files: list[FileResult]) -> int:
    """Record *files* and add *rollups* in one transaction; return the rows upserted.

    One executemany (asyncpg pipelines the rows), as upsert_articles does. The
    advisory lock and the claim keep a file from being added twice; if any file
    was already recorded, nothing is written (AlreadyIngested).
    """
    rows = [
        (a, b, day, quad, r.n_events, len(r.reports), r.mentions, r.goldstein_sum,
         r.tone_sum, r.samples, r.outlets, MAX_SAMPLES, MAX_OUTLETS)
        for (a, b, day, quad), r in sorted(rollups.items())
    ]
    slots = [f.slot for f in files]
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _EVENTS_LOCK)
            claimed = await conn.fetch(
                CLAIM_SQL,
                slots,
                [f.status for f in files],
                [f.n_rows for f in files],
                [f.n_kept for f in files],
            )
            if len(claimed) != len(files):
                taken = sorted(set(slots) - {r["slot"] for r in claimed})
                raise AlreadyIngested(", ".join(f"{s:%Y%m%d%H%M%S}" for s in taken))
            if rows:
                await conn.executemany(UPSERT_SQL, rows)
    return len(rows)


async def purge_events(pool: Any, retention_days: int, now: datetime | None = None) -> None:
    """Delete rollups older than *retention_days* UTC days, and the file log after 2 days.

    Custom plans only: a generic plan guesses that ``day < $1`` matches a third of
    the table and seq-scans it every cycle, as 18a found for place lookups. With
    the values, it is an index range that is empty on all but one cycle a day.
    """
    now = now or datetime.now(timezone.utc)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
        await conn.execute(PURGE_PAIRS_SQL, now.date(), retention_days)
        await conn.execute(PURGE_FILES_SQL, now)


async def ingest_events(now: datetime | None = None) -> None:
    """Add the newest export, and missed ones, to the rollups. Never raises."""
    if not settings.events_ingestion_enabled:
        return
    try:
        await _ingest(now or datetime.now(timezone.utc))
    except AlreadyIngested as exc:
        logger.warning("Events: another process added %s; nothing added this cycle.", exc)
    except Exception:
        logger.warning("Events ingestion failed; continuing.", exc_info=True)


async def _ingest(now: datetime) -> None:
    began = time.monotonic()
    index = await fetch_lastupdate()
    entry = (index or {}).get("export")
    newest = slot_of(entry.url) if entry and _gdelt_https_url(entry.url) else None
    if newest is None:
        logger.warning("Events: no GDELT export file in lastupdate.txt.")
        return
    pool = await get_pool()
    since = newest - timedelta(hours=CATCHUP_HOURS)
    done = {r["slot"] for r in await pool.fetch(DONE_SQL, since)}
    rollups: dict[Key, Rollup] = {}
    files: list[FileResult] = []
    totals = ParseStats()
    download_s = parse_s = 0.0
    for slot in plan_slots(newest, done):
        name = slot_url(slot).rsplit("/", 1)[-1]
        if slot == newest and entry.size > MAX_ZIP_BYTES:
            logger.warning("Events: %s is %d bytes, over %d; skipped.", name, entry.size, MAX_ZIP_BYTES)
            continue
        started = time.monotonic()
        got = await download_capped(slot_url(slot), MAX_ZIP_BYTES)
        download_s += time.monotonic() - started
        if got.status == "missing" and slot != newest:
            files.append(FileResult(slot, "missing", 0, 0))
            continue
        if got.status != "ok":
            logger.warning("Events: %s download %s; retried next cycle.", name, got.status)
            continue
        if (
            slot == newest
            and _MD5.fullmatch(entry.md5)
            and hashlib.md5(got.body, usedforsecurity=False).hexdigest() != entry.md5
        ):
            logger.warning("Events: %s failed its MD5 check; retried next cycle.", name)
            continue
        raw = read_export(got.body)
        if raw is None:
            logger.warning("Events: %s is not one capped export CSV; skipped.", name)
            continue
        started = time.monotonic()
        stats = await asyncio.to_thread(parse_events, raw, now.date(), rollups)
        parse_s += time.monotonic() - started
        totals.add(stats)
        files.append(FileResult(slot, "ok", stats.rows, stats.kept))
    if not files:
        return
    started = time.monotonic()
    upserted = await store_rollups(pool, rollups, files)
    store_s = time.monotonic() - started
    ok = sum(f.status == "ok" for f in files)
    logger.info(
        "Events: %d file%s (%d caught up, %d missing), %d rows, %d kept (%d not root, "
        "%d no country pair, %d same country, %d malformed, %d stale%s), %d rollups in %.2f s "
        "(download %.2f s, parse %.2f s, store %.2f s).",
        ok,
        "" if ok == 1 else "s",
        sum(f.status == "ok" and f.slot != newest for f in files),
        sum(f.status == "missing" for f in files),
        totals.rows,
        totals.kept,
        totals.not_root,
        totals.no_pair,
        totals.same_country,
        totals.malformed,
        totals.stale,
        ", truncated" if totals.truncated else "",
        upserted,
        time.monotonic() - began,
        download_s,
        parse_s,
        store_s,
    )
    if totals.unmapped:
        top = ", ".join(f"{c} {n}" for c, n in totals.unmapped.most_common(5))
        logger.info("Events: unmapped actor codes: %s.", top)
```

`backend/app/services/ingestion.py`:
- Import `from app.services.events import ingest_events, purge_events`.
- In `_purge_old_articles`, after the thread purge:
  ```python
      try:
          await purge_events(pool, settings.retention_days)
      except Exception:
          logger.warning("Events purge failed; continuing.", exc_info=True)
  ```
- In `run_ingestion_cycle`, between the purge and the embeddings:
  ```python
              await _purge_old_articles()
              await ingest_events()  # never raises; seconds, before the embeddings' IOPS peak
              embedded = await generate_embeddings()
  ```
- Mention the events step in the module and `run_ingestion_cycle` docstrings.

**Step 4: Run the tests.**

Run: `cd backend && python -m pytest tests -q`
Expected: all pass; the DB tests are skipped locally.

**Step 5: Commit:** `feat(ingest): add GDELT event exports to daily rollups each cycle`.

### Task 19b.6: DB tests, including the production-scale plan checks

**Files:**
- Create: `backend/tests/events_fixture.py` (shared with 19c), `backend/tests/test_events_db.py`
- Create: `backend/tests/db_plans.py`. Move `_walk`, `_summary`, `_custom_plan`, `_generic_plan`, `_literal` and `_pages` here from `tests/test_board_db.py` unchanged, as public names (`summary`, `custom_plan`, `generic_plan`, `literal`, `pages`), with the prepared statement names `zzplan_q` and `zzplan_plan`. `test_board_db.py` imports them. No behaviour change: its tests must pass as before.

**`events_fixture.py`:**

```python
"""About a week of production's event rollups, for plan tests.

ROWS_PER_DAY comes from 19b's repro (rows a day): update it from the repro's
report and from production's measure. Rows are as wide as ingestion writes
them: three sample URLs and four outlets each.
"""

from __future__ import annotations

from datetime import date

from app.services.country_centroids import COUNTRY_CENTROIDS

ROWS_PER_DAY = 5000
ISO = sorted(COUNTRY_CENTROIDS)[:150]

FILL_SQL = """
INSERT INTO event_pairs_daily (a_iso, b_iso, day, quad_class, n_events, n_reports, mentions,
                               goldstein_sum, tone_sum, sample_urls, outlets)
SELECT ($3::text[])[1 + g % 150],
       ($3::text[])[1 + (g % 150 + 1 + (g / 150) % 149) % 150],
       $1::date - d, q,
       1 + g % 40, 1 + g % 20, 10 + g % 400, -1.5 * (1 + g % 40), -2.0 * (1 + g % 40),
       ARRAY['https://zzevents' || g % 97 || '.test/2026/10/21/a-story-slug-of-usual-length-'
             || g || '-' || q,
             'https://zzevents' || g % 89 || '.test/2026/10/21/another-story-slug-' || g || '-' || q,
             'https://zzevents' || g % 83 || '.test/2026/10/21/a-third-story-slug-' || g || '-' || q],
       ARRAY['zzevents' || g % 97 || '.test', 'zzevents' || g % 89 || '.test',
             'zzevents' || g % 83 || '.test', 'zzevents' || g % 79 || '.test']
FROM generate_series(0, $2::int - 1) d, generate_series(1, $4::int) g, generate_series(1, 4) q
"""


async def fill_week(conn, today: date, days: int = 8, per_day: int = ROWS_PER_DAY) -> None:
    """*days* UTC days of rollups ending *today*, then ANALYZE, as autovacuum leaves them."""
    await conn.execute(FILL_SQL, today, days, ISO, per_day // 4)
    await conn.execute("ANALYZE event_pairs_daily")
```

**`test_events_db.py`.** Use the opt-in `conn` fixture as in 19a's tests. Add a `week` fixture modelled on `test_board_db.big`: roll back, then `VACUUM (ANALYZE) event_pairs_daily` outside the transaction, since ANALYZE's counts outlive a rollback.

`store_rollups` and `purge_events` take a pool, so pass `_OnePool(conn)`: its `acquire()` is an `asynccontextmanager` that yields the test's connection, as `test_board_db._Recorder.acquire` does. Their `conn.transaction()` then becomes a savepoint inside the test's transaction, and everything still rolls back.

A **mutation check** raises a sentinel exception inside `async with conn.transaction():` (a savepoint), after the `DROP` and the assertion, and catches it outside, so the dropped index comes back.

**Step 1: Write the tests:**
1. **Two cycles add up:**
   - store `{("US","IR",D,3): Rollup(n=1, …, samples [u1], outlets [o1])}`, then `{… n=2, samples [u1, u2, u3, u4], outlets [o2 … o9]}`;
   - the row then has `n_events = 3`, the summed `mentions`, `goldstein_sum` and `n_reports`;
   - `sample_urls = [u1, u2, u3]` (first seen, no repeat, capped at 3);
   - `outlets` has 8 entries, starting with `o1`.
2. **A file is never added twice:** `store_rollups` with a slot already in `event_files` raises `AlreadyIngested`, and the rollup row is unchanged.
3. **Missing files:** they're recorded with `status = 'missing'` and add no rows.
4. **Purge:** with rows on `today - 8` and `today - 7`, `purge_events(_OnePool(conn), 7, now)` deletes only `today - 8`. `event_files` rows older than 2 days go too.
5. **HOT updates at production scale:**
   - Fill the week (`fill_week`, 8 days).
   - Store a cycle that updates 500 existing keys of `today`.
   - `SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 'event_pairs_daily'` gives `hot / upd >= 0.9`.
6. **The steady-state purge is index-bounded, the natural plan:**
   - Fill 8 days (nothing is older than retention: the state every cycle but the first after midnight).
   - `custom_plan(PURGE_PAIRS_SQL, today, 7)` has no Seq Scan on `event_pairs_daily` and uses `idx_event_pairs_day`.
   - The generic plan isn't asserted, because `purge_events` forces custom plans. A unit test in `test_events.py` checks that it does: a fake connection records `SET LOCAL plan_cache_mode = force_custom_plan` before the `DELETE`.
   - No `enable_seqscan` change anywhere.
7. **Mutation check:**
   - In a savepoint, `DROP INDEX idx_event_pairs_day`. The same plan helper now reports `event_pairs_daily` in `seq_scans`, which proves test 6 can fail.
   - Roll back the savepoint.

**Step 2: Run locally.**

Run: `cd backend && python -m pytest tests/test_events_db.py tests/test_board_db.py -q`
Expected: all skipped locally (`ORBIS_TEST_DATABASE_URL is not set`).

**Step 3: Push the branch as a draft PR** and read Backend Checks. Expected: `test_events_db.py` 7 passed and `test_board_db.py` unchanged, with 0 skipped.

**Step 4: Commit:** `test(events): rollups add up once, purge by index, update in place`.

### Task 19b.7: the CI repro of per-cycle cost

**Files:**
- Create: `backend/scripts/events_repro.py`, `.github/workflows/events-repro.yml`

**What it does.** On a CI runner (never on the owner's machine), it downloads the last `--files` exports (default 96, one day, about 8 MB) and runs them through the real code paths: `download_capped`, `read_export`, `parse_events` and `store_rollups`, two files per simulated cycle. That's the ~30-minute cadence. It writes into CI's throwaway Postgres, under B1ms-like session settings, and reports:

| Measure | How |
|---|---|
| Zip KB, CSV KB, rows per file (median, max) | per file |
| Rows with exactly 61 fields (%) | its own `split("\t")` count |
| Kept / not root / no country pair / same country / malformed / stale (%), and the root share | `ParseStats` |
| Repeated `GLOBALEVENTID`s across files (expect 0) | its own first-column `Counter` |
| Top 10 unmapped actor codes | `ParseStats.unmapped` |
| Parse ms per file (median, p95) | timed |
| Rows upserted and store ms per cycle (first cycle, then median and p95) | timed |
| Rows after a day (an upper bound for rows a day) | `count(*)` |
| HOT ratio during the day | `pg_stat_user_tables` after `pg_stat_force_next_flush()` |
| Size of a week | Replicate the day to the 7 previous days (`INSERT … SELECT … day - k … ON CONFLICT DO NOTHING`, k = 1..7), `VACUUM ANALYZE`, then `pg_total_relation_size`, `pg_relation_size` and each index's size. |

**Step 1: Write the script.**

```python
"""Measure GDELT Events ingestion on CI: what a cycle costs and what a week stores.

Run by .github/workflows/events-repro.yml against CI's throwaway Postgres
(ORBIS_TEST_DATABASE_URL, migrations applied). Downloads the last --files
15-minute exports from GDELT (about 80 KB each) on the runner. Prints a
Markdown report, also written to $GITHUB_STEP_SUMMARY on CI. Exits 1 only
if a file can't be read or more than 1% of rows are malformed.

Usage: cd backend && python -m scripts.events_repro --files 96
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import asyncpg

from app.services import events
from app.services.gdelt import download_capped, fetch_lastupdate

# One vCore and little memory, as on the B1ms (production numbers otherwise look better).
B1MS = ("SET max_parallel_workers_per_gather = 0", "SET jit = off", "SET work_mem = '4MB'")


async def _b1ms(conn) -> None:
    for statement in B1MS:
        await conn.execute(statement)


def _p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=20)[-1] if len(values) >= 2 else (values or [0])[0]


async def main(n_files: int) -> int:
    pool = await asyncpg.create_pool(
        os.environ["ORBIS_TEST_DATABASE_URL"], min_size=1, max_size=1, init=_b1ms
    )
    newest = events.slot_of((await fetch_lastupdate())["export"].url)
    slots = [newest - k * events.SLOT for k in range(n_files)][::-1]  # oldest first
    now = datetime.now(timezone.utc)
    per_file: list[dict] = []
    ids: Counter = Counter()
    totals = events.ParseStats()
    cycles: list[tuple[int, float]] = []
    rollups: dict = {}
    files: list[events.FileResult] = []
    failed = 0
    for i, slot in enumerate(slots):
        got = await download_capped(events.slot_url(slot), events.MAX_ZIP_BYTES)
        raw = events.read_export(got.body) if got.status == "ok" else None
        if raw is None:
            failed += got.status != "missing"
            files.append(events.FileResult(slot, "missing", 0, 0))
        else:
            lines = [line for line in raw.splitlines() if line]
            ids.update(line.split("\t", 1)[0] for line in lines)
            started = time.perf_counter()
            stats = events.parse_events(raw, now.date(), rollups)
            per_file.append(
                {
                    "zip_kb": len(got.body) / 1024,
                    "csv_kb": len(raw) / 1024,
                    "rows": stats.rows,
                    "fields_61": sum(len(line.split("\t")) == events.COLUMNS for line in lines),
                    "parse_ms": (time.perf_counter() - started) * 1000,
                }
            )
            totals.add(stats)
            files.append(events.FileResult(slot, "ok", stats.rows, stats.kept))
        if len(files) == 2 or i == len(slots) - 1:
            started = time.perf_counter()
            upserted = await events.store_rollups(pool, rollups, files)
            cycles.append((upserted, (time.perf_counter() - started) * 1000))
            rollups, files = {}, []
    async with pool.acquire() as conn:
        day_rows = await conn.fetchval("SELECT count(*) FROM event_pairs_daily")
        await conn.execute("SELECT pg_stat_force_next_flush()")
        await conn.execute("SELECT pg_stat_clear_snapshot()")
        upd, hot = await conn.fetchrow(
            "SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables"
            " WHERE relname = 'event_pairs_daily'"
        )
        await conn.execute(
            "INSERT INTO event_pairs_daily SELECT a_iso, b_iso, day - k, quad_class, n_events,"
            " n_reports, mentions, goldstein_sum, tone_sum, sample_urls, outlets"
            " FROM event_pairs_daily, generate_series(1, 7) k ON CONFLICT DO NOTHING"
        )
        await conn.execute("VACUUM (ANALYZE) event_pairs_daily")
        week = await conn.fetchrow(
            "SELECT count(*) AS rows,"
            " pg_size_pretty(pg_total_relation_size('event_pairs_daily')) AS total,"
            " pg_size_pretty(pg_relation_size('event_pairs_daily')) AS heap,"
            " pg_size_pretty(pg_relation_size('event_pairs_daily_pkey')) AS pkey,"
            " pg_size_pretty(pg_relation_size('idx_event_pairs_day')) AS day_index"
            " FROM event_pairs_daily"
        )
    await pool.close()

    rows = max(totals.rows, 1)
    malformed_share = totals.malformed / rows
    store_ms = [ms for _, ms in cycles[1:]] or [cycles[0][1]]
    report = [
        f"## GDELT Events repro: {len(per_file)} files ({n_files - len(per_file)} missing)",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Zip KB per file (median / max) | {statistics.median(f['zip_kb'] for f in per_file):.0f} / {max(f['zip_kb'] for f in per_file):.0f} |",
        f"| CSV KB per file (median / max) | {statistics.median(f['csv_kb'] for f in per_file):.0f} / {max(f['csv_kb'] for f in per_file):.0f} |",
        f"| Rows per file (median / max) | {statistics.median(f['rows'] for f in per_file):.0f} / {max(f['rows'] for f in per_file)} |",
        f"| Rows with 61 fields | {100 * sum(f['fields_61'] for f in per_file) / rows:.2f}% |",
        f"| Kept / not root / no pair / same country / malformed / stale | {100 * totals.kept / rows:.1f}% / {100 * totals.not_root / rows:.1f}% / {100 * totals.no_pair / rows:.1f}% / {100 * totals.same_country / rows:.1f}% / {100 * malformed_share:.2f}% / {100 * totals.stale / rows:.2f}% |",
        f"| Root events among valid rows (only these are kept) | {100 * (1 - totals.not_root / max(rows - totals.malformed, 1)):.1f}% |",
        f"| Repeated event ids across files | {sum(n - 1 for n in ids.values() if n > 1)} |",
        f"| Unmapped actor codes (top 10) | {', '.join(f'{c} {n}' for c, n in totals.unmapped.most_common(10))} |",
        f"| Parse ms per file (median / p95) | {statistics.median(f['parse_ms'] for f in per_file):.0f} / {_p95([f['parse_ms'] for f in per_file]):.0f} |",
        f"| Rows upserted per cycle (median / max) | {statistics.median(n for n, _ in cycles):.0f} / {max(n for n, _ in cycles)} |",
        f"| Store ms per cycle (first / median / p95) | {cycles[0][1]:.0f} / {statistics.median(store_ms):.0f} / {_p95(store_ms):.0f} |",
        f"| Rows after the day (upper bound for rows a day) | {day_rows} |",
        f"| HOT updates during the day | {hot} of {upd} ({100 * hot / max(upd, 1):.0f}%) |",
        f"| Week (8 days): rows, total, heap, pkey, day index | {week['rows']}, {week['total']}, {week['heap']}, {week['pkey']}, {week['day_index']} |",
    ]
    text = "\n".join(report) + "\n"
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if failed or malformed_share > 0.01 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=96)
    sys.exit(asyncio.run(main(parser.parse_args().files)))
```

**Step 2: Write the workflow** (`.github/workflows/events-repro.yml`). The Postgres service, PostGIS install and migration steps are copied verbatim from `ci.yml`'s backend job.

```yaml
name: Events repro

# Measures GDELT Events ingestion against CI's throwaway Postgres: on PRs that
# change it, and on demand. GDELT files are downloaded on the runner only.
on:
  pull_request:
    branches: [main]
    paths:
      - backend/app/services/events.py
      - backend/app/services/relations.py
      - backend/app/services/cameo_countries.py
      - backend/scripts/events_repro.py
      - database/migrations/021_event_pairs_daily.sql
      - .github/workflows/events-repro.yml
  workflow_dispatch:
    inputs:
      files:
        description: "15-minute export files to ingest (96 = a day)"
        default: "96"

jobs:
  repro:
    name: Events ingestion repro
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    services:
      postgres:
        image: pgvector/pgvector:0.8.1-pg16-bookworm
        env:
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements.txt
      - run: pip install -r requirements.txt
      - name: Install PostGIS in the database service
        run: >-
          docker exec ${{ job.services.postgres.id }} sh -c
          "apt-get update -qq && apt-get install -y -qq --no-install-recommends postgresql-16-postgis-3"
      - name: Apply database migrations
        working-directory: .
        run: |
          set -euo pipefail
          for f in database/migrations/*.sql; do
            docker exec -i ${{ job.services.postgres.id }} psql -U postgres -v ON_ERROR_STOP=1 -q < "$f"
          done
      - name: Ingest GDELT exports and measure
        run: python -m scripts.events_repro --files "${{ inputs.files || '96' }}"
        env:
          ORBIS_TEST_DATABASE_URL: postgresql://postgres:test@localhost:5432/postgres
```

**Step 3: Push and read the job summary.** Paste the report into the PR description, then check it against these gates. If any gate fails, **stop and report to the controller**:

| Gate | Expected | If not |
|---|---|---|
| Rows with 61 fields | ≥ 99.9% | the format changed: stop |
| Repeated event ids | 0 | rollups would double-count: stop |
| Parse ms per file, p95 | ≤ 100 | profile `parse_events` before going on |
| Rows upserted per cycle, max | ≤ 1,500 | revisit the grain (drop `outlets`, or the caps) |
| Store ms per cycle, p95 (CI's disk is faster than P4) | ≤ 500 | batch differently before going on |
| Rows after the day | ≤ 10,000 | update `ROWS_PER_DAY`; re-check the 19c bounds |
| HOT updates | ≥ 90% | lower `fillfactor` in a follow-up migration |
| Week total size | ≤ 40 MB | revisit what the rows carry |

Then set `events_fixture.ROWS_PER_DAY` to the measured rows a day, rounded up to a multiple of 1,000, and commit that with the report.

**Step 4: Commit:** `test(events): CI repro of the per-cycle cost and a week's size`.

### Task 19b.8: the PR

**Step 1:** Run every backend check (expected: all pass).

**Step 2:** Open the PR `feat(ingest): GDELT event rollups each cycle (PR 19b)`. The description includes:
- the repro report;
- the gates;
- the `missing` label points (19b.1);
- the per-cycle estimate against the measurement;
- how to switch it off.

**Step 3:** After the reviews and green CI, the controller merges.

**Rollback:**
- **Switch it off without a code change:** set `EVENTS_INGESTION_ENABLED=false` on the backend Container App. This makes a new revision; it's owner-approved infra, not a hand deploy of code. The cycle then skips the step, and the rows age out within 8 days.
- **Otherwise:** revert the PR. The tables stay, unread.

---

## 19b+: Measure on prod (the controller, after 19b deploys)

No code. Read-only. Report back before 19c merges.

**First 3 cycles,** from the backend's logs:
- Each cycle logs one `Events: N files (C caught up, M missing), R rows, K kept (…), U rollups in X s (download …, parse …, store …).` line, then possibly `Events: unmapped actor codes: …`.
- Expected:
  - X ≤ 5 s;
  - store ≤ 2 s;
  - N mostly 2, since the cycle starts about every 30 min;
  - no `Events ingestion failed` and no `another process added`.
- The `Ingestion cycle complete` spacing is unchanged ± a few seconds.
- Azure Monitor shows no IOPS rise during the step, which runs before the embeddings.

**After 24 h,** read-only SQL. Run it the way the threads calibration did: `az containerapp exec`, with the script uploaded in ~600-character chunks.

```sql
SELECT count(*) AS rows, count(DISTINCT day) AS days,
       pg_size_pretty(pg_total_relation_size('event_pairs_daily')) AS total
FROM event_pairs_daily;

SELECT day, count(*) AS rows, sum(n_events) AS events, sum(n_reports) AS reports
FROM event_pairs_daily GROUP BY day ORDER BY day;

SELECT n_tup_ins, n_tup_upd, n_tup_hot_upd, n_dead_tup, last_autovacuum
FROM pg_stat_user_tables WHERE relname = 'event_pairs_daily';

-- About 4 files an hour means the catch-up works (a missed file is a lost count).
SELECT date_trunc('hour', slot) AS hour,
       count(*) FILTER (WHERE status = 'ok') AS ok,
       count(*) FILTER (WHERE status = 'missing') AS missing
FROM event_files GROUP BY 1 ORDER BY 1 DESC LIMIT 24;

-- Calibration of MIN_EVENTS, MIN_REPORTS, MIN_OUTLETS (decision 8): how the
-- lens's pairs spread by events, reports and outlets. Run once 7 days exist
-- (sooner, over the days there are, for a first look).
WITH r AS (
  SELECT least(a_iso, b_iso) a, greatest(a_iso, b_iso) b, n_events, n_reports, outlets
  FROM event_pairs_daily WHERE day >= current_date - 6),
p AS (SELECT a, b, sum(n_events) n, sum(n_reports) rep FROM r GROUP BY 1, 2),
o AS (SELECT a, b, count(DISTINCT x) outl FROM r, unnest(r.outlets) x GROUP BY 1, 2)
SELECT width_bucket(p.n, ARRAY[1, 5, 10, 25, 100]) AS events_bucket,
       width_bucket(p.rep, ARRAY[1, 3, 5, 10, 25]) AS reports_bucket,
       width_bucket(coalesce(o.outl, 0), ARRAY[1, 2, 3, 5]) AS outlets_bucket,
       count(*) AS pairs, sum(p.n) AS events
FROM p LEFT JOIN o USING (a, b) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

-- Sanity: today's busiest pairs (expect pairs like US-IR, RU-UA, IL-PS).
SELECT least(a_iso, b_iso) a, greatest(a_iso, b_iso) b, sum(n_events) n, sum(mentions) m
FROM event_pairs_daily WHERE day = current_date GROUP BY 1, 2 ORDER BY m DESC LIMIT 15;
```

**Gates:**

| Gate | Expected |
|---|---|
| Rows a day | within 2× the repro's |
| HOT share | ≥ 0.9 |
| Files an hour | ~4 ok, few missing |
| Total size | ≤ 40 MB at 8 days |

The busiest pairs should be plausible. If `ROWS_PER_DAY` differs by more than 2×, update `events_fixture.ROWS_PER_DAY` in 19c. Post the numbers in the 19c PR.

**Recalibrating the thresholds** (decision 8). From the calibration query, choose values that:
- keep roughly the 40–80 strongest pairs above the line, enough to fill the 40-arc list after the per-country cap;
- drop the single-report long tail.

Put the new `MIN_EVENTS`, `MIN_REPORTS` and `MIN_OUTLETS`, each with the measured distribution in a comment, in 19c, or in a follow-up PR if 19c has merged. Re-check them once the lens holds 7 full days.

---

## PR 19c: The relations read API

Branch: `claude/p5-relations-api`.

**Depends on:** #108, since the router uses `cache.WEEK_TTL`, `single_flight` and `cached_model` (decision 10: it's merging). Check with `gh pr view 108 --json state`.
- **If it has merged,** go on.
- **If it hasn't landed,** use the fallback: the lens under `db:relations:…` with `cycle_ttl(600)` and plain `get_cached`/`set_cached`. Then tell the controller.

### API contract (fixed here; PR 20 builds against it)

**Every answer is the 7-day lens** (decision 1): the last 7 UTC days, `today - 6 .. today`, whatever the timeline shows. There are no window parameters, and any others sent are ignored.

`GET /api/relations` takes:
- `kind=all|cooperation|conflict` (default `all`);
- `limit=1..60` (default 40).

It returns:

```json
{
  "first_day": "2026-10-15",
  "last_day": "2026-10-21",
  "relations": [
    {
      "a": {"iso": "IR", "name": "Iran", "lat": 32.52, "lng": 54.29},
      "b": {"iso": "US", "name": "United States", "lat": 39.5, "lng": -99.06},
      "n": 312, "reports": 140, "outlets": 23, "mentions": 2100,
      "quad": {"verbal_cooperation": 40, "material_cooperation": 12,
               "verbal_conflict": 210, "material_conflict": 50},
      "kind": "conflict", "goldstein": -3.1, "tone": -4.2, "from": "US"
    }
  ]
}
```

- **Pairs** come in code order (`a < b`). `from` is the country whose actors act in most of the pair's events, and the arc starts there.
- **Ordering:** by mentions, then events, then codes. At most `MAX_ARCS_PER_COUNTRY` (6, shared with links) per country.
- **Filtering:**
  - pairs need `n ≥ MIN_EVENTS` (5), `reports ≥ MIN_REPORTS` (3) and `outlets ≥ MIN_OUTLETS` (2);
  - pairs whose code has no label point are dropped.
- **`kind`:**
  - `cooperation` counts quad 1–2 only and `conflict` counts 3–4 only, so `n`, `quad` and `kind` describe the filtered events;
  - with `all`, `kind` is the majority class: conflict when quad 3+4 outnumber 1+2, and on a tie conflict when `goldstein < 0`.

`GET /api/relations/detail?a=US&b=IR` returns, for the same 7 days, the list item's fields for that pair over **all classes** (the detail takes no `kind`), plus:

```json
{
  "directions": [{"from": "US", "to": "IR", "n": 200, "quad": {…}},
                 {"from": "IR", "to": "US", "n": 112, "quad": {…}}],
  "daily": [{"day": "2026-10-15", "cooperation": 30, "conflict": 120},
            …,
            {"day": "2026-10-21", "cooperation": 22, "conflict": 140}],
  "samples": [{"url": "https://…", "outlet": "reuters.com", "title": "Iran says … " | null,
               "day": "2026-10-21", "quad_class": 3, "from": "US"}]
}
```

- **Field details:**
  - `directions` lists only directions that have events, a→b first;
  - `daily` holds all 7 days, `first_day..last_day`, zero-filled: the inspector's daily breakdown;
  - `samples` holds up to 10, from the newest day first, then quad class, then direction. They're distinct and http(s) only (sanitised again), with `title` from our own article with that URL when we have one (`articles_source_url_key`, at most 10 lookups), else null.
- **Errors:**
  - **422** for an unknown code, `a = b`, a bad `kind` or `limit`;
  - **404** when the pair has no events in the 7 days (not cached).

**Caching:** every answer is a week read, so all of it lives in #108's hourly family.

| Answer | Key | TTL |
|---|---|---|
| List | `wk:relations:v1:{YYYYMMDD}-{YYYYMMDD}:{kind}:{limit}` | `WEEK_TTL` (an empty list too: it's refreshed hourly anyway) |
| Detail | `wk:relations:detail:v1:{a}:{b}:{YYYYMMDD}-{YYYYMMDD}` | `WEEK_TTL` |

- The days in the key move the entry at UTC midnight.
- Every miss goes through `single_flight`. A cached entry that no longer fits its model is a miss (`cached_model`).
- `edge_cached` on both routes.
- Rate group `data` (the default for `/api/`).
- No `db:*` key, so the cycle's invalidation never touches these: they're up to about an hour old, which the legend's "last 7 days" tolerates.
- No warmer: the layer is off on first load, and a miss reads rollups only. If production's cold list exceeds 1 s, add `warm_relations_7d` after `warm_links_7d`, following #108's `week_fresh` pattern.

### Task 19c.1: `app/services/relations.py` (pure parts first)

**Files:**
- Create: `backend/app/services/relations.py`, `backend/tests/test_relations.py`

**Step 1: Write the failing tests** (`backend/tests/test_relations.py`).

```python
from datetime import date, datetime, timezone

from app.services.relations import (
    MIN_EVENTS,
    lens_days,
    rank_relations,
    summarise_detail,
)

UTC = timezone.utc


def test_the_lens_is_the_last_7_utc_days_including_today():
    assert lens_days(datetime(2026, 10, 21, 0, 30, tzinfo=UTC)) == (
        date(2026, 10, 15),
        date(2026, 10, 21),
    )


def test_the_lens_follows_utc_not_local_time():
    # 23:30 on the 21st in UTC-5 is 04:30 on the 22nd in UTC.
    from datetime import timedelta

    local = datetime(2026, 10, 21, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert lens_days(local) == (date(2026, 10, 16), date(2026, 10, 22))


def _row(a="IR", b="US", n=20, q=(2, 1, 12, 5), from_a=5, mentions=300, **over):
    row = {"a": a, "b": b, "n": n, "reports": 9, "outlets": 4, "mentions": mentions,
           "goldstein": -2.0, "tone": -3.0, "q1": q[0], "q2": q[1], "q3": q[2], "q4": q[3],
           "from_a": from_a}
    row.update(over)
    return row


def test_rank_names_the_class_the_acting_country_and_the_label_points():
    [rel] = rank_relations([_row()], limit=40)
    assert rel["kind"] == "conflict"
    assert rel["from"] == "US"  # IR acts in 5 of 20
    assert rel["a"]["name"] == "Iran" and rel["b"]["iso"] == "US"
    assert rel["quad"] == {"verbal_cooperation": 2, "material_cooperation": 1,
                           "verbal_conflict": 12, "material_conflict": 5}


def test_a_tie_goes_by_the_goldstein_sign():
    assert rank_relations([_row(q=(5, 5, 5, 5), goldstein=1.0)], 40)[0]["kind"] == "cooperation"
    assert rank_relations([_row(q=(5, 5, 5, 5), goldstein=-1.0)], 40)[0]["kind"] == "conflict"


def test_pairs_without_a_label_point_are_dropped_and_hubs_are_capped():
    rows = [_row(a="ZZ")] + [_row(a=c, b="US", mentions=100 - i) for i, c in
                             enumerate(["CN", "DE", "FR", "GB", "IL", "IN", "JP"])]
    ranked = rank_relations(rows, 40)
    assert all(r["a"]["iso"] != "ZZ" for r in ranked)
    assert sum("US" in (r["a"]["iso"], r["b"]["iso"]) for r in ranked) == 6


def test_detail_sums_directions_days_and_samples():
    d = date(2026, 10, 21)
    rows = [
        {"a_iso": "US", "b_iso": "IR", "day": d, "quad_class": 3, "n_events": 4,
         "n_reports": 2, "mentions": 40, "goldstein_sum": -8.0, "tone_sum": -12.0,
         "sample_urls": ["https://a.test/1", "javascript:x"], "outlets": ["a.test"]},
        {"a_iso": "IR", "b_iso": "US", "day": date(2026, 10, 20), "quad_class": 1,
         "n_events": 1, "n_reports": 1, "mentions": 5, "goldstein_sum": 1.0, "tone_sum": 2.0,
         "sample_urls": ["https://b.test/2", "https://a.test/1"], "outlets": ["b.test"]},
    ]
    detail = summarise_detail("IR", "US", date(2026, 10, 19), d, rows, {"https://a.test/1": "Talks - Reuters"})
    assert detail["n"] == 5 and detail["outlets"] == 2 and detail["from"] == "US"
    assert [x["from"] for x in detail["directions"]] == ["IR", "US"]
    assert [x["day"] for x in detail["daily"]] == [date(2026, 10, 19), date(2026, 10, 20), d]
    assert [s["url"] for s in detail["samples"]] == ["https://a.test/1", "https://b.test/2"]
    assert detail["samples"][0]["title"] == "Talks" and detail["samples"][1]["title"] is None


def test_detail_of_no_rows_is_none():
    assert summarise_detail("IR", "US", date(2026, 10, 21), date(2026, 10, 21), [], {}) is None


def test_thresholds_are_named():
    assert MIN_EVENTS == 5
```

**Step 2: Run them to verify they fail.**

Run: `cd backend && python -m pytest tests/test_relations.py -q`
Expected: ERROR collecting, `ModuleNotFoundError: No module named 'app.services.relations'`.

**Step 3: Implement** `backend/app/services/relations.py`.

```python
"""Relations between countries from GDELT's reported events (Phase 5, PR 19c).

Reads only event_pairs_daily: the rollups ingestion keeps (app/services/events.py).
Relations are a 7-day lens: always the last 7 UTC days, whatever the timeline
shows. Events are machine-coded from news reports; nothing here calls them facts.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from app.services.country_centroids import centroid
from app.services.database import get_pool
from app.services.links import MAX_ARCS_PER_COUNTRY, _country
from app.services.titles import display_title
from app.services.urls import outlet, web_url

# A pair needs this much behind it to be drawn: one article can yield many
# events. Starting values (Phase 5 decision 8), recalibrated from production's
# spread by "Measure on prod" (19b+).
MIN_EVENTS = 5
MIN_REPORTS = 3
MIN_OUTLETS = 2
MAX_SAMPLES = 10
LENS_DAYS = 7  # the lens: today and the 6 UTC days before

QUADS = {"all": [1, 2, 3, 4], "cooperation": [1, 2], "conflict": [3, 4]}
QUAD_NAMES = {1: "verbal_cooperation", 2: "material_cooperation",
              3: "verbal_conflict", 4: "material_conflict"}

LIST_SQL = """
WITH r AS MATERIALIZED (
    SELECT least(a_iso, b_iso) AS a, greatest(a_iso, b_iso) AS b, a_iso, quad_class,
           n_events, n_reports, mentions, goldstein_sum, tone_sum, outlets
    FROM event_pairs_daily
    WHERE day BETWEEN $1 AND $2 AND quad_class = ANY($3::smallint[])
),
p AS (
    SELECT a, b,
           sum(n_events)::int AS n,
           sum(n_reports)::int AS reports,
           sum(mentions)::bigint AS mentions,
           sum(goldstein_sum) / sum(n_events) AS goldstein,
           sum(tone_sum) / sum(n_events) AS tone,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 1), 0)::int AS q1,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 2), 0)::int AS q2,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 3), 0)::int AS q3,
           coalesce(sum(n_events) FILTER (WHERE quad_class = 4), 0)::int AS q4,
           coalesce(sum(n_events) FILTER (WHERE a_iso = a), 0)::int AS from_a
    FROM r
    GROUP BY a, b
    HAVING sum(n_events) >= $4 AND sum(n_reports) >= $5
),
o AS (
    SELECT r.a, r.b, count(DISTINCT x)::int AS outlets
    FROM r JOIN p USING (a, b) CROSS JOIN LATERAL unnest(r.outlets) AS x
    GROUP BY r.a, r.b
)
SELECT p.*, o.outlets
FROM p JOIN o USING (a, b)
WHERE o.outlets >= $6
ORDER BY p.mentions DESC, p.n DESC, p.a, p.b
"""

DETAIL_SQL = """
SELECT a_iso, b_iso, day, quad_class, n_events, n_reports, mentions,
       goldstein_sum, tone_sum, sample_urls, outlets
FROM event_pairs_daily
WHERE ((a_iso = $1 AND b_iso = $2) OR (a_iso = $2 AND b_iso = $1))
  AND day BETWEEN $3 AND $4
"""

TITLES_SQL = "SELECT source_url, title FROM articles WHERE source_url = ANY($1::text[])"


def lens_days(now: datetime | None = None) -> tuple[date, date]:
    """The lens's first and last UTC days: the last LENS_DAYS, today included."""
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    return today - timedelta(days=LENS_DAYS - 1), today


def _quad(counts: dict[int, int]) -> dict[str, int]:
    return {name: int(counts.get(q, 0)) for q, name in QUAD_NAMES.items()}


def _kind(cooperation: int, conflict: int, goldstein: float) -> str:
    if conflict != cooperation:
        return "conflict" if conflict > cooperation else "cooperation"
    return "conflict" if goldstein < 0 else "cooperation"


async def get_relation_pairs(first: date, last: date, kind: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        LIST_SQL, first, last, QUADS[kind], MIN_EVENTS, MIN_REPORTS, MIN_OUTLETS
    )
    return [dict(r) for r in rows]


def rank_relations(rows: list[dict], limit: int) -> list[dict]:
    """The pairs to draw, in order: label points known, at most MAX_ARCS_PER_COUNTRY each."""
    ranked: list[dict] = []
    per_country: Counter = Counter()
    for row in rows:
        a, b = row["a"], row["b"]
        if centroid(a) is None or centroid(b) is None:  # links._country raises on these
            continue
        if per_country[a] >= MAX_ARCS_PER_COUNTRY or per_country[b] >= MAX_ARCS_PER_COUNTRY:
            continue
        per_country.update((a, b))
        ends = _country(a), _country(b)
        ranked.append(
            {
                "a": ends[0],
                "b": ends[1],
                "n": row["n"],
                "reports": row["reports"],
                "outlets": row["outlets"],
                "mentions": row["mentions"],
                "quad": _quad({1: row["q1"], 2: row["q2"], 3: row["q3"], 4: row["q4"]}),
                "kind": _kind(row["q1"] + row["q2"], row["q3"] + row["q4"], row["goldstein"]),
                "goldstein": round(row["goldstein"], 2),
                "tone": round(row["tone"], 2),
                "from": a if 2 * row["from_a"] >= row["n"] else b,
            }
        )
        if len(ranked) == limit:
            break
    return ranked
```

`links._country` raises on a code with no label point (it reads `centroid(iso).name`), hence the `centroid` check first. The detail's codes come through the router's `_pair`, which already rejects them.

The detail half:

```python
def _samples(rows: list[dict]) -> list[dict]:
    """Up to MAX_SAMPLES distinct http(s) report URLs, newest day first."""
    picked: list[dict] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda r: (-r["day"].toordinal(), r["quad_class"], r["a_iso"])):
        for url in row["sample_urls"]:
            if url in seen or web_url(url) is None:
                continue
            seen.add(url)
            picked.append({"url": url, "outlet": outlet(url), "title": None, "day": row["day"],
                           "quad_class": row["quad_class"], "from": row["a_iso"]})
            if len(picked) == MAX_SAMPLES:
                return picked
    return picked


def summarise_detail(a: str, b: str, first: date, last: date, rows: list[dict],
                     titles: dict[str, str]) -> dict | None:
    """One pair's numbers, both directions, each day and sample reports; None without rows."""
    if not rows:
        return None
    quad: Counter = Counter()
    directions = {(a, b): Counter(), (b, a): Counter()}
    daily = {first + timedelta(days=i): [0, 0] for i in range((last - first).days + 1)}
    n = reports = mentions = 0
    goldstein = tone = 0.0
    outlets: dict[str, None] = {}
    for row in rows:
        q, k = row["quad_class"], row["n_events"]
        quad[q] += k
        directions[(row["a_iso"], row["b_iso"])][q] += k
        daily.setdefault(row["day"], [0, 0])[0 if q <= 2 else 1] += k
        n += k
        reports += row["n_reports"]
        mentions += row["mentions"]
        goldstein += row["goldstein_sum"]
        tone += row["tone_sum"]
        outlets.update(dict.fromkeys(row["outlets"]))
    samples = _samples(rows)
    for sample in samples:
        title = titles.get(sample["url"])
        sample["title"] = display_title(title) if title else None
    by_a = sum(directions[(a, b)].values())
    return {
        "a": _country(a), "b": _country(b), "first_day": first, "last_day": last,
        "n": n, "reports": reports, "outlets": len(outlets), "mentions": mentions,
        "quad": _quad(quad), "kind": _kind(quad[1] + quad[2], quad[3] + quad[4], goldstein / n),
        "goldstein": round(goldstein / n, 2), "tone": round(tone / n, 2),
        "from": a if 2 * by_a >= n else b,
        "directions": [
            {"from": x, "to": y, "n": sum(c.values()), "quad": _quad(c)}
            for (x, y), c in directions.items() if c
        ],
        "daily": [{"day": d, "cooperation": v[0], "conflict": v[1]}
                  for d, v in sorted(daily.items()) if first <= d <= last],
        "samples": samples,
    }


async def get_relation_detail(a: str, b: str, first: date, last: date) -> dict | None:
    pool = await get_pool()
    rows = [dict(r) for r in await pool.fetch(DETAIL_SQL, a, b, first, last)]
    if not rows:
        return None
    urls = [s["url"] for s in _samples(rows)]
    titles = {r["source_url"]: r["title"] for r in await pool.fetch(TITLES_SQL, urls)} if urls else {}
    return summarise_detail(a, b, first, last, rows, titles)
```

The detail test's `samples[0]["title"] == "Talks"` relies on `display_title` dropping the outlet suffix: `display_title("Talks - Reuters") == "Talks"` (checked 2026-10-21).

**Step 4: Run the tests.**

Run: `cd backend && python -m pytest tests/test_relations.py -q`
Expected: all pass.

**Step 5: Commit:** `feat(api): relations from GDELT event rollups`.

### Task 19c.2: models and router

**Files:**
- Create: `backend/app/models/relations.py`, `backend/app/routers/relations.py`, `backend/tests/test_relations_router.py`
- Modify: `backend/app/main.py` (`app.include_router(relations_router)` after the links router)

**Step 1: Write the failing router tests.** Model them on `tests/test_links_router.py`: the same `_client`, a fixed `_now`, Redis and the pool mocked.
- **Shapes:**
  - `/api/relations` returns `first_day`, `last_day` and items with `from` (the alias);
  - the detail returns `directions`, `daily` (7 entries) and `samples`.
- **The lens:**
  - At `NOW = 2026-10-21T00:30Z` both routes ask the pool for `2026-10-15..2026-10-21`.
  - `?timespan=24h` and `?start_time=…&end_time=…` change nothing: same days, same key.
- **422s:** `kind=war`, `limit=0`, `limit=61`, `a=b`, `a=ZZ`.
- **Cache keys:**
  - `wk:relations:v1:20261015-20261021:all:40`, TTL `WEEK_TTL`, an empty list included;
  - `kind=conflict` → `wk:relations:v1:20261015-20261021:conflict:40`;
  - the detail of `b=US&a=IR` and of `a=US&b=IR` share `wk:relations:detail:v1:IR:US:20261015-20261021`;
  - after UTC midnight (`NOW = 2026-10-22T00:05Z`) the key is `…:20261016-20261022:…`.
  - No key starts `db:`, so a cycle's `invalidate("db:*")` leaves them alone (assert with #108's fake Redis).
- **Cache behaviour:**
  - a cached hit computes nothing;
  - an entry of the wrong shape is a miss, logged once (`cached_model`);
  - a detail 404 is not cached.
- **Headers and limits:**
  - `Cache-Control` is `EDGE_CACHE_CONTROL` on both routes;
  - `security._get_rate_group("/api/relations") == "data"`.
- **Concurrency:** two concurrent misses on one key run the query once (`single_flight`).

**Step 2: Run them to verify they fail.**

Run: `cd backend && python -m pytest tests/test_relations_router.py -q`
Expected: FAIL, 404s for `/api/relations` (the route doesn't exist yet).

**Step 3: Implement.**
- `app/models/relations.py`:
  - **List models:**
    - `QuadCounts` (four ints);
    - `Relation`: `a`, `b` (`LinkCountry`), `n`, `reports`, `outlets`, `mentions`, `quad`, `kind: Literal["cooperation", "conflict"]`, `goldstein`, `tone`, and `from_` with `alias="from"`; `populate_by_name=True`;
    - `Relations` (`first_day: date`, `last_day: date`, `relations: list[Relation]`).
  - **Detail models:**
    - `RelationDirection` (`from_`/`from`, `to`, `n`, `quad`);
    - `RelationDay` (`day`, `cooperation`, `conflict`);
    - `RelationReport` (`url`, `outlet`, `title: str | None`, `day`, `quad_class: int = Field(ge=1, le=4)`, `from_`/`from`);
    - `RelationDetail`: `Relation`'s fields plus `first_day`, `last_day`, `directions`, `daily` and `samples`.
  - Each field has a `description` that uses the copy rules: "reported events", "first reports", "event-type score".
- `app/routers/relations.py`:
  - Reuse `_pair` and `Country` from `app.routers.links`.
  - There are no window parameters: the lens is fixed (decision 1).

```python
DEFAULT_KIND = "all"
DEFAULT_LIMIT = 40
Kind = Annotated[
    Literal["all", "cooperation", "conflict"],
    Query(description="Which reported events: all, cooperation (quad 1-2) or conflict (3-4)"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days(first: date, last: date) -> str:
    return f"{first:%Y%m%d}-{last:%Y%m%d}"


@router.get("/relations", response_model=Relations, dependencies=[Depends(edge_cached)])
async def get_relations(
    kind: Kind = DEFAULT_KIND,
    limit: Annotated[int, Query(ge=1, le=60, description="Most relations to return")] = DEFAULT_LIMIT,
) -> Relations:
    """Pairs of countries in GDELT's reported events over the last 7 UTC days.

    Machine-coded from news reports (not verified): who did what to whom, as
    reported. A week read, so it lives under wk: (cache.WEEK_TTL), refreshed
    about hourly; the days in the key move it at UTC midnight.
    """
    first, last = lens_days(_now())
    key = f"wk:relations:v1:{_days(first, last)}:{kind}:{limit}"
    cached = await get_cached(key)
    if cached is not None:
        found = cached_model(key, cached, Relations.model_validate)
        if found is not None:
            return found

    async def load() -> Relations:
        rows = await get_relation_pairs(first, last, kind)
        result = Relations(
            first_day=first,
            last_day=last,
            relations=[Relation.model_validate(r) for r in rank_relations(rows, limit)],
        )
        await set_cached(key, result.model_dump(mode="json", by_alias=True), WEEK_TTL)
        return result

    return await single_flight(key, load)
```

  - The detail route follows the same pattern:
    - `a, b = sorted(_pair(a, b))`;
    - the key is `f"wk:relations:detail:v1:{a}:{b}:{_days(first, last)}"`;
    - `get_relation_detail`: `None` → `HTTPException(404, "No reported events between them in the last 7 days.")`, not cached;
    - the result is cached for `WEEK_TTL`.
  - Fallback if #108 hasn't landed (decision 10): the same code with `db:` keys, `cycle_ttl(600)`, and no `single_flight` or `cached_model`.

**Step 4: Run the tests.**

Run: `cd backend && python -m pytest tests/test_relations.py tests/test_relations_router.py -q`
Expected: all pass.

**Step 5: Commit:** `feat(api): /api/relations and its detail, a 7-day lens cached hourly`.

### Task 19c.3: DB tests, with production-scale plan checks and their mutation twins

**Files:**
- Create: `backend/tests/test_relations_db.py`. It uses `events_fixture.fill_week`, `db_plans`, and a `week` fixture as in 19b.6.

**Step 1: Write the tests.**

*Semantics* (small hand-built rows, `conn` fixture):
1. Both directions merge into one pair, and `from` follows the majority.
2. The `kind=conflict` filter counts quad 3–4 only.
3. The thresholds:
   - 4 events are dropped and 5 kept;
   - 2 reports are dropped and 3 kept;
   - 1 outlet is dropped, and 2 distinct across days are kept, even when one day has only 1.
4. The lens's days only: a row on `today - 7` (still kept by retention) is not read.
5. The detail's titles come from an article with the sample's URL (insert one `zzrel` article).

*Plans at production scale.* Fill the week: 8 days × `ROWS_PER_DAY`, the retention's 8 days, of which the lens reads 7. Use no `enable_seqscan` changes anywhere; assert the planner's own choices, with custom and generic plans for each.

| Read | Natural plan must | Pages (`db_plans.pages`, custom and generic) |
|---|---|---|
| List: the lens, 7 of 8 days | any plan: it reads most of the table, once, by design (a seq scan is the right choice here) | ≤ `relpages + index pages + 100`: the table once, never once per pair |
| Detail, one pair, 7 days | use `event_pairs_daily_pkey`; no Seq Scan | ≤ 60 |
| Titles, 10 URLs (after inserting 20K `zzrel` articles and `ANALYZE articles`) | use `articles_source_url_key`; no Seq Scan on `articles` | ≤ 60 |

The list is a week read by design (decision 1). What keeps it cheap:
- the table is small and narrow;
- the answer is cached hourly under `wk:`;
- misses are single-flighted.

The page bound proves it reads the table once.

*Mutation twins,* each in a savepoint, rolled back:
- **List:** run a per-pair variant of `LIST_SQL`, with the outlets counted by a `LATERAL` subquery against `event_pairs_daily` for each pair, the shape this plan rejected. Its pages exceed the bound.
- **Detail:** `ALTER TABLE event_pairs_daily DROP CONSTRAINT event_pairs_daily_pkey`, and the detail now seq-scans.
- **Purge:** 19b.6's `DROP INDEX idx_event_pairs_day` twin covers the day index.

Each twin proves its check can fail.

*Timing,* printed rather than asserted: the list's execution time under `db_plans`' B1ms-like settings (`SET LOCAL max_parallel_workers_per_gather = 0, jit = off, work_mem = '4MB'`). Put it in the PR description.

**Step 2: Push and read Backend Checks.** Expected: `test_relations_db.py` all passed, 0 skipped.

**Step 3: Extend the repro.** After building the week, `events_repro.py` also runs `relations.LIST_SQL` over the lens's 7 days and `DETAIL_SQL` for the busiest pair under `EXPLAIN (ANALYZE, BUFFERS)`, and reports ms and buffers. Gate: the list ≤ 300 ms on CI.

**Step 4: Commit:** `test(api): relations reads are index-bounded at production scale`.

### Task 19c.4: the PR

**Step 1:** Run every backend check.

**Step 2:** Open the PR `feat(api): relations between countries from GDELT events (PR 19c)`, with:
- the contract;
- the plan-test table with the measured pages;
- the repro's read timings.

**After deploy (the controller):**
- Time `/api/relations` cold and warm, and one detail.
- Expected: warm < 0.3 s; cold < 1 s (else add the warmer).
- Spot-check the top 10 pairs for plausibility, and that no sample URL is non-http(s).
- Apply 19b+'s threshold recalibration, if it isn't in this PR.

**Rollback:** revert. Nothing reads the API until PR 20, so revert PR 20 first if it has merged.

---

## PR 20: The Relations layer and inspector

Branch: `claude/p5-relations-ui`. Frontend only. It builds against 19c's contract, with mocked routes until 19c merges.

### One focus at a time (decisions 1, 5, 6 and 13)

| Situation | Relations arcs | Links arcs |
|---|---|---|
| Relations turned on (a live window) | drawn: the 7-day lens, whatever the live preset; the 5 strongest labelled | **turned off**: Links and Relations are mutually exclusive overlays |
| Links turned on | **turned off** | drawn |
| A range, or a replay running | **unavailable**: hidden; the toggle is `aria-disabled` with the note "Relations cover the last 7 days: not available for a range or replay"; back on a live window they return | (unchanged) |
| Threads on, no thread selected | drawn | (unchanged) |
| A thread selected | drawn; the inspected relation's highlight hidden, as an inspected link's is | (unchanged) |
| An entity tracked, or the board open | **muted** (`--arc-muted`), no highlight, no flow, no persistent labels, as links are | (unchanged) |
| A relation opened (arc click, list row) or a list row focused | its arc highlighted, its pill shown | n/a |
| Phone width (≤ 760 px) | unavailable to turn on, like Links. If it was on at a wider width, the "Relations ✕" chip turns it off. | (unchanged) |

- Opening a relation also ends the selected thread and the tracked entity, and closes the board, exactly as `handleLinkOpen` does.
- Turning Relations off keeps opened relations in Inspect, as panels. Their arcs simply aren't drawn.
- The topic pill never changes the arcs (decision 2).

### Task 20.1: API client and `lib/relations.ts`

**Files:**
- Modify: `frontend/src/lib/api.ts` (`ApiQuadCounts`, `ApiRelation`, `ApiRelations`, `ApiRelationDetail`, `fetchRelations`, `fetchRelationDetail`), `frontend/src/lib/links.ts` (`GlobeArc` gains `relation?: Relation`)
- Create: `frontend/src/lib/relations.ts`, `frontend/src/lib/relations.test.ts`

**Step 1: Write the failing tests** (`frontend/src/lib/relations.test.ts`).

```ts
import { describe, expect, it } from "vitest";
import {
  RELATIONS_UNAVAILABLE,
  relationArcs,
  relationDaysWords,
  relationKey,
  relationPillText,
  relationTag,
  relationWords,
  relationsStatus,
  relationsUnavailable,
  strongestRelations,
  type Relation,
} from "@/lib/relations";

const US = { iso: "US", name: "United States", lat: 39.5, lng: -99.06 };
const IR = { iso: "IR", name: "Iran", lat: 32.0, lng: 53.7 };

function rel(over: Partial<Relation> = {}): Relation {
  return {
    a: IR, b: US, n: 100, reports: 40, outlets: 6, mentions: 900,
    quad: { verbal_cooperation: 10, material_cooperation: 5, verbal_conflict: 60, material_conflict: 25 },
    kind: "conflict", goldstein: -3.2, tone: -4.1, from: "US",
    ...over,
  };
}

const colors = {
  cooperation: "#8fb8ff",
  conflict: "#f2949c",
  highlight: "#7fe6ff",
  muted: "rgba(180, 190, 255, 0.10)",
  flowMs: 6000,
};

describe("relationWords", () => {
  it("names the main class when it has half the events", () => {
    expect(relationWords(rel())).toBe("mostly verbal conflict");
  });
  it("falls back to the side with 60% or more", () => {
    const quad = { verbal_cooperation: 30, material_cooperation: 10, verbal_conflict: 35, material_conflict: 25 };
    expect(relationWords(rel({ quad }))).toBe("mostly conflict");
  });
  it("says mixed in between", () => {
    const quad = { verbal_cooperation: 30, material_cooperation: 20, verbal_conflict: 30, material_conflict: 20 };
    expect(relationWords(rel({ quad }))).toBe("mixed cooperation and conflict");
  });
});

describe("relationPillText", () => {
  it("counts reported events, from the acting country", () => {
    expect(relationPillText(rel())).toEqual({
      n: 100,
      text: "reported events between United States and Iran, mostly verbal conflict",
    });
  });
  it("is singular for one event", () => {
    expect(relationPillText(rel({ n: 1 })).text).toMatch(/^reported event between/);
  });
});

describe("relationArcs", () => {
  it("colours each arc by its class and starts it at the acting country", () => {
    const [arc] = relationArcs([rel()], { inspected: null, colors, flow: true, muted: false });
    expect(arc.color).toBe(colors.conflict);
    expect([arc.startLat, arc.startLng]).toEqual([US.lat, US.lng]);
    expect(arc.key).toBe("IR-US");
    expect(arc.relation?.n).toBe(100);
    expect(arc.dashGap).toBeGreaterThan(0);
  });
  it("highlights the inspected one", () => {
    const [arc] = relationArcs([rel()], { inspected: relationKey("US", "IR"), colors, flow: false, muted: false });
    expect(arc.color).toBe(colors.highlight);
  });
  it("mutes every arc, with no highlight or flow, while another focus leads", () => {
    const [arc] = relationArcs([rel()], { inspected: "IR-US", colors, flow: true, muted: true });
    expect(arc.color).toBe(colors.muted);
    expect(arc.dashGap).toBe(0);
  });
  it("strokes by mentions", () => {
    const arcs = relationArcs([rel(), rel({ a: { ...IR, iso: "IQ" }, mentions: 450 })], {
      inspected: null, colors, flow: false, muted: false,
    });
    expect(arcs.map((a) => a.stroke)).toEqual([0.66, 0.41]);
  });
});

describe("relationDaysWords", () => {
  it("names one UTC day", () => expect(relationDaysWords("2026-10-21", "2026-10-21")).toBe("21 Oct (UTC)"));
  it("names a span", () => expect(relationDaysWords("2026-10-15", "2026-10-21")).toBe("15–21 Oct (UTC days)"));
  it("names a span across months", () =>
    expect(relationDaysWords("2026-09-28", "2026-10-02")).toBe("28 Sep – 2 Oct (UTC days)"));
});

describe("relationsStatus", () => {
  it("says why nothing is drawn, and nothing while loading", () => {
    expect(relationsStatus({ loading: true, error: false, count: 0 })).toBeNull();
    expect(relationsStatus({ loading: false, error: false, count: 0 })).toBe(
      "No reported events between countries in the last 7 days",
    );
    expect(relationsStatus({ loading: false, error: true, count: 0 })).toBe("Relations couldn't load");
    expect(relationsStatus({ loading: false, error: false, count: 3 })).toBeNull();
  });
});

describe("persistent labels (decision 6)", () => {
  it("labels the 5 strongest by mentions", () => {
    const many = Array.from({ length: 7 }, (_, i) =>
      rel({ a: { ...IR, iso: `X${i}` }, mentions: 100 * (i + 1) }),
    );
    expect(strongestRelations(many).map((r) => r.mentions)).toEqual([700, 600, 500, 400, 300]);
  });
  it("puts the class in words, from the acting country", () => {
    expect(relationTag(rel())).toBe("US–IR · 100 · conflict");
  });
});

describe("relationsUnavailable (decision 1)", () => {
  it("is available on any live window, and not under a range or a replay", () => {
    expect(relationsUnavailable({ kind: "live", hours: 1 }, false)).toBeNull();
    expect(relationsUnavailable({ kind: "live", hours: 24 }, true)).toBe(RELATIONS_UNAVAILABLE);
    expect(
      relationsUnavailable(
        { kind: "range", startTime: "2026-10-19T00:00:00Z", endTime: "2026-10-20T00:00:00Z" },
        false,
      ),
    ).toBe(RELATIONS_UNAVAILABLE);
  });
});
```

**Step 2: Run them to verify they fail.**

Run: `cd frontend && npx vitest run src/lib/relations.test.ts`
Expected: FAIL, `Failed to resolve import "@/lib/relations"`.

**Step 3: Implement** `frontend/src/lib/relations.ts`.

```ts
/**
 * Relations between countries (/api/relations): GDELT's reported events over a
 * fixed 7-day lens, the Relations layer's arcs, and the words that name one.
 * Events are machine-coded from news reports: the UI calls them reported events,
 * never facts, and the class is always in words, so colour never carries the
 * meaning alone.
 */
import type { ApiRelation, ApiRelations } from "@/lib/api";
import { arcStroke, linkKey, type GlobeArc } from "@/lib/links";
import type { TimeWindow } from "@/lib/timeWindow";
import type { LinkCountry } from "@/types/news";

export type RelationKind = "all" | "cooperation" | "conflict";
export const RELATIONS_LIMIT = 40;

export const QUAD_LABELS = {
  verbal_cooperation: "Verbal cooperation",
  material_cooperation: "Material cooperation",
  verbal_conflict: "Verbal conflict",
  material_conflict: "Material conflict",
} as const;
export type QuadKey = keyof typeof QUAD_LABELS;

export interface Relation {
  a: LinkCountry;
  b: LinkCountry;
  /** Reported events between the two, either way. */
  n: number;
  reports: number;
  outlets: number;
  /** Mentions in each event's first 15 minutes, summed: the arc's width. */
  mentions: number;
  quad: Record<QuadKey, number>;
  kind: "cooperation" | "conflict";
  goldstein: number;
  tone: number;
  /** ISO code of the country whose actors act in most of the events. */
  from: string;
}

export const relationKey = linkKey;

export function toRelations(api: ApiRelations): { firstDay: string; lastDay: string; relations: Relation[] } {
  return { firstDay: api.first_day, lastDay: api.last_day, relations: api.relations.map(toRelation) };
}

export function toRelation(r: ApiRelation): Relation {
  return { ...r, quad: { ...r.quad } };
}

/** The relation's ends, starting at the acting country. */
export function relationEnds(rel: Relation): [LinkCountry, LinkCountry] {
  return rel.from === rel.b.iso ? [rel.b, rel.a] : [rel.a, rel.b];
}

export function relationWords(rel: Relation): string {
  const total = Math.max(rel.n, 1);
  const [top, topN] = (Object.entries(rel.quad) as [QuadKey, number][]).reduce((best, e) =>
    e[1] > best[1] ? e : best,
  );
  if (topN / total >= 0.5) return `mostly ${QUAD_LABELS[top].toLowerCase()}`;
  const conflict = (rel.quad.verbal_conflict + rel.quad.material_conflict) / total;
  if (conflict >= 0.6) return "mostly conflict";
  if (conflict <= 0.4) return "mostly cooperation";
  return "mixed cooperation and conflict";
}

export function relationPillText(rel: Relation): { n: number; text: string } {
  const [from, to] = relationEnds(rel);
  const noun = rel.n === 1 ? "reported event" : "reported events";
  return { n: rel.n, text: `${noun} between ${from.name} and ${to.name}, ${relationWords(rel)}` };
}

export interface RelationColors {
  cooperation: string;
  conflict: string;
  highlight: string;
  muted: string;
  flowMs: number;
}

export function relationArcs(
  relations: readonly Relation[],
  { inspected, colors, flow, muted }: { inspected: string | null; colors: RelationColors; flow: boolean; muted: boolean },
): GlobeArc[] {
  const max = Math.max(0, ...relations.map((r) => r.mentions));
  const flowing = flow && !muted;
  return relations.map((rel) => {
    const [start, end] = relationEnds(rel);
    const key = relationKey(rel.a.iso, rel.b.iso);
    return {
      relation: rel,
      key,
      startLat: start.lat,
      startLng: start.lng,
      endLat: end.lat,
      endLng: end.lng,
      color: muted ? colors.muted : key === inspected ? colors.highlight : colors[rel.kind],
      stroke: Math.round(arcStroke(rel.mentions, max) * 100) / 100,
      dashLength: flowing ? 0.9 : 1,
      dashGap: flowing ? 0.1 : 0,
      dashAnimateTime: flowing ? colors.flowMs : 0,
    };
  });
}

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/** The UTC days a relations answer covers, in words. */
export function relationDaysWords(first: string, last: string): string {
  const a = new Date(`${first}T00:00:00Z`);
  const b = new Date(`${last}T00:00:00Z`);
  if (first === last) return `${DAY.format(a)} (UTC)`;
  const sameMonth = a.getUTCMonth() === b.getUTCMonth();
  return sameMonth
    ? `${a.getUTCDate()}–${DAY.format(b)} (UTC days)`
    : `${DAY.format(a)} – ${DAY.format(b)} (UTC days)`;
}

export function relationsStatus(s: { loading: boolean; error: boolean; count: number }): string | null {
  if (s.loading) return null;
  if (s.error) return "Relations couldn't load";
  return s.count === 0 ? "No reported events between countries in the last 7 days" : null;
}

/** How many arcs carry a persistent label (decision 6). */
export const LABELLED_ARCS = 5;

/** The strongest relations, by mentions then events: those labelled on the globe. */
export function strongestRelations(relations: readonly Relation[], n = LABELLED_ARCS): Relation[] {
  return [...relations].sort((x, y) => y.mentions - x.mentions || y.n - x.n).slice(0, n);
}

/** A persistent label: "US–IR · 312 · conflict", from the acting country, the class in words. */
export function relationTag(rel: Relation): string {
  const [from, to] = relationEnds(rel);
  return `${from.iso}–${to.iso} · ${rel.n} · ${rel.kind}`;
}

export const RELATIONS_UNAVAILABLE =
  "Relations cover the last 7 days: not available for a range or replay";

/** Why the 7-day lens can't show now (a range, or a replay running), or null. */
export function relationsUnavailable(window: TimeWindow, replaying: boolean): string | null {
  return window.kind !== "live" || replaying ? RELATIONS_UNAVAILABLE : null;
}
```

- **`api.ts`:** the types follow the contract exactly.
  - `fetchRelations({ kind, limit = RELATIONS_LIMIT, signal })` calls `apiFetch("/api/relations", { kind, limit: String(limit) }, signal)`. There are no window parameters: the lens is fixed.
  - `fetchRelationDetail({ a, b })` calls `apiFetch("/api/relations/detail", { a, b })`.
  - Add both to `api.test.ts`'s URL tests, including that no `timespan` is sent.
- **`links.ts`:** export `arcStroke` if it isn't exported, and document `GlobeArc.relation`.

**Step 4: Run the tests.**

Run: `cd frontend && npx vitest run src/lib/relations.test.ts src/lib/api.test.ts src/lib/links.test.ts`
Expected: all pass.

**Step 5: Commit:** `feat(ui): relations data and arc helpers`.

### Task 20.2: `useRelations`

**Files:**
- Create: `frontend/src/hooks/useRelations.ts`, `frontend/src/hooks/useRelations.test.ts`

Copy `useLinks`, keyed on `kind` only, since the lens doesn't follow the timeline:
- it fetches only while enabled, after `FETCH_DEBOUNCE_MS`;
- it aborts and ignores late answers;
- it forgets the answer when turned off.
- While on, it refetches every 30 minutes, so a page left open keeps up with the hourly lens.
- `enabled` is false under a range or a replay (decision 1), so nothing is fetched then.

It returns `{ relations, firstDay, lastDay, loading, error }`.

**Tests** (mirror `useLinks.test.ts`, with fake timers):
- off fetches nothing;
- on fetches once with `kind=all&limit=40`;
- a kind change refetches and ignores the late first answer;
- a timeline change alone fetches nothing;
- 30 minutes on refetches once;
- an error is reported, and turning off then on doesn't show the old error.

**Commands:**
- Run `cd frontend && npx vitest run src/hooks/useRelations.test.ts`: FAIL first (`Failed to resolve import`), then pass.
- Commit: `feat(ui): fetch relations while the layer is on`.

### Task 20.3: Layer switcher, legend and phone chip

**Files:**
- Modify: `frontend/src/components/LayerSwitcher.tsx` (+ test), `frontend/src/components/LinksChip.tsx` (+ test), `frontend/src/app/soft-orbit.css`

**Behaviour:**
- **The toggle:**
  - a **Relations** `.tg` toggle after Threads, `aria-pressed`, with the title "Reported events between countries over the last 7 days (GDELT)";
  - new props: `relations`, `onRelationsChange`, `relationKind`, `onRelationKindChange`, `relationsStatus`, `relationDays`, `relationsUnavailable` (the note, or null).
- **Unavailable** (a range or a replay, decision 1): the toggle is `aria-disabled` and keeps its pressed state. The note comes from `relationsUnavailable` and is shown and announced through the same `aria-describedby` and `sr-only` pattern the base layers' `unavailable` uses. While it's unavailable, the kind switch and the legend are hidden.
- **While Relations is on and available, beside the pill** (as `.link-rank` floats):
  - a `.seg` group "Show relations": **All / Cooperation / Conflict** (`data-testid="relation-kind"`).
  - a legend `p.relations-legend` (`data-testid="relations-legend"`), three short lines:
    1. **"Relations · last 7 days ({days})"**;
    2. a cooperation swatch "Cooperation" and a conflict swatch "Conflict", then "Reported events from news, machine-coded by GDELT. Not verified.";
    3. **"Topic filters don't apply to relations."** (decision 2).
  - its status, when it draws nothing, as `linksStatus` is shown.
- **Phones:** unavailable to turn on at ≤ 760 px, like Links (decision 13). `LinksChip` gains `label` ("Links" | "Relations") and `aria-label` "Turn {label} off". Phones show it for whichever overlay is on.
- **CSS:**
  - `.relations-legend` and its `.sw-coop`/`.sw-conf` swatches use `--arc-relation-cooperation`/`--arc-relation-conflict`;
  - `.relation-kind` copies `.link-rank`'s rules, including the 760 and 1180 breakpoints and `.board-open:has(...)`.

**Tests** (`LayerSwitcher.test.tsx`):
- the toggle's state and title;
- the kind switch and legend only while on and available;
- the legend reads "Relations · last 7 days", "Not verified", and "Topic filters don't apply";
- unavailable: `aria-disabled`, the note described, no switch or legend, and a press calls nothing;
- choosing Conflict calls `onRelationKindChange("conflict")`.

The mutual exclusion is the page's job and is tested in e2e.

**Commands:**
- Run `cd frontend && npx vitest run src/components/LayerSwitcher.test.tsx src/components/LinksChip.test.tsx`: the new cases FAIL first, then pass.
- Commit: `feat(ui): relations toggle, kind switch and legend`.

### Task 20.4: Globe arcs, the arc pill and persistent labels

**Files:**
- Modify: `frontend/src/components/Globe.tsx`, `frontend/src/components/ArcPill.tsx` (+ test)
- Create: `frontend/src/components/ArcLabels.tsx` (+ test)

**Globe:**
- **New props:** `relations: Relation[]`, `inspectedRelation: string | null` (the opened relation, else the focused list row's: decision 6), `onRelationHover`, `onRelationClick`.
- **Tokens:** read `--arc-relation-cooperation` and `--arc-relation-conflict` (fallbacks `#8fb8ff` and `#f2949c`) into `tokens.relations`.
- **Arcs:** in the arcs effect, build them with `relationArcs` under their own memo key `[relations, inspectedRelation, flow, focused]`. `muted` is the existing `focused` (entity focus or the board). The highlight is hidden while a thread is selected (`inspected: thread ? null : inspectedRelation`). Concatenate them with the other sets.
- **Events:** `onArcHover` and `onArcClick` dispatch on `arc.relation` versus `arc.link`.
- **Test attributes:**
  - `data-relation-arcs` (the count);
  - `data-relation-highlight` (the key drawn highlighted, or "");
  - `data-relation-muted` ("true"/"false").
- **The flow and drag effects** count relation arcs as drawn.

**ArcPill:**
- Generalise it to take `label: { start, end, n, text } | null` instead of a `CountryLink`.
- Callers pass `linkPill(link)` (from `arcPillText`/`linkEnds`) or `relationPill(rel)` (from `relationPillText`/`relationEnds`).
- Update `ArcPill.test.tsx` and add a relation case: "312 reported events between United States and Iran, mostly verbal conflict".

**ArcLabels** (decision 6: the 5 strongest arcs carry persistent labels):
- **What:** up to `LABELLED_ARCS` small `.arc-tag` chips, one per `strongestRelations(relations)`, reading `relationTag(rel)` ("US–IR · 312 · conflict"). Each sits at its arc's apex (`arcApex`, as `ArcPill` uses).
- **One frame loop** places them all, the way `ArcPill` places its pill. A label whose apex is on the far side of the globe is hidden.
- **They yield** when that arc is hovered, focused or inspected (its pill says more), when another focus mutes the arcs (entity, board), and at ≤ 760 px (CSS).
- **Accessibility:** `aria-hidden="true"` and `pointer-events: none`. The keyboard list and the inspector carry the same words to everyone.
- **Test attribute:** the globe container's `data-relation-labels` is the number of labels rendered.
- **Unit tests:**
  - 7 relations give 5 labels, the strongest;
  - muted gives none;
  - the inspected one's label yields;
  - the label text names the class.

**Commands:**
- Run `cd frontend && npx vitest run src/components/ArcPill.test.tsx src/components/ArcLabels.test.tsx`: the new cases FAIL first, then pass.
- Commit: `feat(ui): relation arcs on the globe, the strongest labelled`.

### Task 20.5: `RelationList` and `RelationInspector`

**Files:**
- Create: `frontend/src/hooks/useRowFocus.ts` (+ test), `frontend/src/components/RelationList.tsx` (+ test), `frontend/src/components/RelationInspector.tsx` (+ test)
- Modify: `frontend/src/components/LinkList.tsx`: its focus-keeping (the layout effect, `onFocus` and `onBlur`) moves into `useRowFocus(keys, rowSelector)`, unchanged. `LinkList.test.tsx` must pass untouched.

**RelationList:**
- Shown in Inspect while nothing is open there and Relations is on, as `LinkList` is.
- A labelled list of buttons, "Relations · last 7 days": "{From} and {To}: {n} reported events, {words}". Every arc is listed, so every arc is labelled here (decision 6). Each opens the relation.
- **Focusing a row labels its arc on the globe** (decision 6, "on focus"): `onFocusRelation(rel | null)` lets the page highlight that arc and show its pill, as hovering does. Blur clears it.
- Rows carry `data-relation="IR-US"`.

**RelationInspector** (`data-testid="relation-inspector"`, the `.insp` structure of `LinkInspector`):
- **Header:**
  - kicker "Relation · last 7 days ({days words})";
  - heading "{From} and {To}" (focused on open, as the link's is);
  - caption: **"Events GDELT machine-coded from news reports: who did what to whom, as reported. Not verified facts; one report can yield several events."**
- **Readouts:**
  - Events ({n});
  - Reports ({reports});
  - Outlets ({outlets}, titled "at least": rows keep up to 8 outlets each, so the union is a lower bound);
  - Goldstein ({goldstein}, with the sub-label "event-type score, −10 conflict to +10 cooperation");
  - Tone ({tone}, "first reports"). Its `.sent` colour uses `sentimentKey(clamp(tone / 10, -1, 1))`.
- **By class:** four rows, each with a label, a count, a percentage and a small bar coloured by side. They're text, so colour isn't the only signal. Both cooperation and conflict always show, whatever the layer's class switch says (decision 7).
- **Directions:** "{From} → {To}: {n} events, {words}" for each direction present.
- **By day (UTC), the daily breakdown** (decision 1): all 7 days, with small paired bars per day (cooperation, conflict) and an accessible table under them (`sr-only`).
- **Sample reports:**
  - `.art` rows with `title ?? outlet`, the outlet, the day, the class in words, and "{From} → {To}";
  - a link only when `isWebUrl(url)` (`target="_blank" rel="noopener noreferrer"`), else plain text.
- **Controls:**
  - Minimize and Close, as in `LinkInspector`;
  - Escape minimizes;
  - no Pin button: relations aren't pinnable in Phase 5 (decision 9).
- **Copy:** the component never renders "linked", "caused" or "attack". A unit test greps its rendered text for `/linked|caus|attack/i` and finds nothing.

**Tests** (Vitest):
- the list rows and Enter opening a relation;
- focusing a row calls `onFocusRelation` with it, and blur with null;
- the inspector:
  - renders the list item's numbers before the detail lands;
  - the class rows' text, all four, with the class switch on Conflict;
  - 7 day rows;
  - a `javascript:` sample renders as text, not a link;
  - the caption is present;
  - the copy grep.
- `useRowFocus` keeps the focus on a row still listed and hands it to the first row when its row drops out. These are `LinkList`'s existing cases, moved.

**Commands:**
- Run `cd frontend && npx vitest run src/components/RelationList.test.tsx src/components/RelationInspector.test.tsx src/hooks/useRowFocus.test.ts src/components/LinkList.test.tsx`: FAIL first, then pass.
- Commit: `feat(ui): relation list and inspector`.

### Task 20.6: Page wiring and the focus rules

**Files:**
- Modify: `frontend/src/app/page.tsx`, `frontend/src/types/news.ts` (`RelationEntry`, like `LinkEntry` without the explanation), `frontend/src/components/SidePanel.tsx`, `frontend/src/components/RecentPlaces.tsx` (+ tests)

**Wiring:**
- **State:** `relationsOn`, `relationKind`, `hoveredRelation`, `focusedRelation` (the focused list row), `relationQueue: RelationEntry[]`.
- **The lens's availability:**
  - `const unavailable = relationsUnavailable(timeWindow, replaying)`, then `const relationsShown = relationsOn && unavailable === null`;
  - `useRelations(relationKind, relationsShown)`.
  - Turning to a range or starting a replay hides the arcs and announces the note once. Going back to a live window shows them again without a click.
- **Exclusive toggles:** `handleLinksChange(on)` sets Links and, when on, turns Relations off; `handleRelationsChange(on)` mirrors it. The co-pilot's "Show links" uses `handleLinksChange(true)`. The announcer says "Relations on. Links off." (or the reverse) when one turns the other off.
- **`handleRelationOpen(rel)`:** copies `handleLinkOpen`:
  - reset the spread replay;
  - deselect the thread and stop tracking;
  - close the board (`showInspect`);
  - reuse an open entry for the same pair (the lens has one window, so the pair alone is the key);
  - else create `relation-{key}-{createdAt}` and fetch its detail.
- **Inspect:** an active id starting `relation-` renders `RelationInspector`. `RecentPlaces` shows relation pills "US ↔ IR · events" alongside places and links, under the same `MAX_PANELS`.
- **Globe:**
  - `relations={relationsShown ? relations : []}`;
  - `inspectedRelation` is the focused row's key, else the active relation's;
  - the hover and click callbacks are passed in.
  - `ArcPill` shows the hovered relation, else the focused or inspected one, else the link equivalents.
  - `ArcLabels` gets `strongestRelations(relations)` with the same yield rules.

**Tests:**
- unit tests where the logic is pure (the exclusive toggles as a small reducer `overlays(state, action)` in `lib/overlays.ts`, + test);
- the rest in e2e (Task 20.8).

**Commands:**
- Run `cd frontend && npx vitest run && npm run lint && npm run build`: all pass.
- Commit: `feat(ui): relations layer on the page, one focus at a time`.

### Task 20.7: CSS polish and the visual check

**CSS:** in `frontend/src/app/soft-orbit.css`, port the inspector's class rows (`.rel-classes`, `.rel-bar`), the day bars (`.rel-days`) and the legend. Use tokens only, with no new colours.

**Visual check:** a production build at 1440, 1280, 1180 and 390 with `mockAllApiRoutes`, with Relations on and a relation open. The 1440 screenshot goes in the PR.

**Commit:** `style(ui): relations legend and inspector`.

### Task 20.8: e2e

**Files:**
- Modify: `frontend/e2e/fixtures.ts`:
  - add `MOCK_RELATIONS` (3 relations: IR–US conflict, FR–US cooperation, NG–FR cooperation) and `MOCK_RELATIONS_CONFLICT` (IR–US only);
  - `mockRelations(url)` answers by `kind`;
  - `MOCK_RELATION_DETAIL` includes a `javascript:` sample;
  - add `isRelationsList`, `mockRelationRoutes`, and `mockRelationRoutes` inside `mockAllApiRoutes`.
- Create: `frontend/e2e/relations.spec.ts`
- Modify: `frontend/e2e/layout.spec.ts` (the `relation-kind` and `relations-legend` boxes against the timeline, bottom row and side panel at 1440, 1280 and 1180)

**`relations.spec.ts`** (viewport 1440×900 unless stated; each test a few steps; keyboard activation; waits on `data-*`):
1. **Relations draws the lens, labelled, and turns Links off.**
   - `gotoStillGlobe` with a recorder.
   - Relations → `press("Enter")`:
     - `data-relation-arcs="3"` and `data-relation-labels="3"`;
     - the request is exactly `{kind: "all", limit: "40"}`, with no window;
     - the legend contains "Relations · last 7 days", "Not verified" and "Topic filters don't apply".
   - Links → `press("Enter")`. Relations is `aria-pressed="false"` and `data-relation-arcs="0"`.
2. **The kind switch refetches; the timeline doesn't.**
   - Relations on, then Conflict → `press("Enter")`: the last request has `kind=conflict`, and `data-relation-arcs="1"`.
   - Then the 6h preset → Enter: no new relations request.
3. **A range makes the lens unavailable.**
   - Relations on. Choose a range: the timeline's day step, as `timeline.spec` does.
   - The toggle is `aria-disabled="true"`, its description holds the note, and `data-relation-arcs="0"`.
   - Back to the 24h preset: `data-relation-arcs="3"` again.
4. **A relation is labelled on focus, and opens from the list.**
   - Relations on.
   - Focus the first `[data-relation]` row in Inspect: `data-relation-highlight="IR-US"`, and `arc-pill` contains "reported events".
   - Press Enter:
     - `relation-inspector` shows the heading "United States and Iran", the caption "Not verified facts", the class row "Verbal conflict" and 7 day rows;
     - the `javascript:` sample isn't a link (`getByRole("link", { name: … })` count 0).
5. **Another focus mutes the arcs.**
   - Relations on, then `seedBoard` and the Board button → Enter.
   - `data-relation-muted="true"`, `data-relation-highlight=""` and `data-relation-labels="0"`.
6. **Phone, 390 wide** (decision 13).
   - The layer switcher is hidden at ≤ 760 px, as it is for Links. So start at 1180 wide, turn Relations on, then resize to 390.
   - The "Relations ✕" chip shows, and Enter on it turns Relations off (`data-relation-arcs="0"`).

**Commands:**
- Run `cd frontend && CI=1 npx playwright test e2e/relations.spec.ts e2e/layout.spec.ts`: all pass.
- Then the full `CI=1 npx playwright test`.
- None of these tests uses `test.slow()`. If one turns out to need it, give the reason in a comment.

**Commit:** `test(ui): relations layer e2e`.

### Task 20.9: the PR

**Step 1:** Run every frontend check, including the full e2e.

**Step 2:** Open the PR `feat(ui): relations layer and inspector (PR 20)`, with:
- the focus table;
- screenshots: 1440 with arcs and the inspector, and 390 with the chip;
- the copy rules followed.

**After deploy (the controller), on orbisapp.co:**
- Relations draws plausible arcs with the legend ("Relations · last 7 days") and 5 labels, and Links turns it off.
- A range makes it unavailable, with the note.
- The inspector's numbers match the arc's, and its 7 days add up to them.
- Sample links open the outlet in a new tab.
- At 390 the chip works.

**Rollback:** revert. The layer is off by default, so a bug reaches only visitors who turn it on.

---

## After Phase 5

- **The 7-day links reads (the open "links-7d" decision), noted, not in scope.** The same rollup pattern could back the 7-day links view:
  - a `link_pairs_daily(day, a_iso, b_iso, n_stories, from_a, tone_sum, topic counts, outlets[], exclusive_stories)` written at ingestion from each new article's `country_code` and `mentioned_countries`;
  - per-day country totals, for lift's `N`, `n_a` and `n_b`, which are additive.
  - The week's read would then be a rollup read, not a week of `articles` heap.
  - **Caveats:**
    - distinct stories (`story_key`) and outlet exclusivity aren't additive across days: a syndicated story that spans midnight counts twice;
    - the existing week would need a backfill (a production data write, the owner's call).
  - Measure the drift against the live list before deciding.
- **Board:** relations are not pinnable in Phase 5 (decision 9). Pinning them later needs a `relation:{AA}-{BB}` item kind in 18a's resolve and edges, and in 18b's pins.
- **Co-pilot:** a "Show relations" action pill, like "Show links".
- **The Mentions table** (`mentions.CSV.zip`) as a "these articles report the same event" signal: large, and measure it first.
- **Owner decision: the GKG cadence** (decision 12; pre-existing, out of Phase 5's scope).
  - **What happens:**
    - `scheduler._ingestion_loop` sleeps 900 s *after* each cycle, and a cycle takes 13–16 min, almost all of it embeddings.
    - So cycles start every 28–31 min, and the GKG path, which reads only the newest file, ingests about 46–51 of GDELT's 96 files a day: **about half**.
    - The site still takes in about 1,000 articles an hour (measured 2026-10-18). That's a uniform sample, so relative views (the globe, links, breaking, threads) hold; absolute counts are about half of GDELT's.
  - **What catching up would cost:**
    - It would roughly **double the articles**, to about 2,000 an hour.
    - With them double the embedding writes: non-HOT `UPDATE`s through the HNSW index, about 1 min per 100 rows on production, at 100% IOPS at peak. The cycle's 13–16 min of embeddings would become about 26–32 min, longer than a 15-minute slot, so the cycle would fall further behind.
    - OpenAI embedding spend roughly doubles too, though it stays small: under $2 a month becomes under $4.
  - **Options for the owner:**
    - (a) keep the half sample (no change);
    - (b) a fixed-rate scheduler (start every 15 min, skip while one runs), which changes little while embeddings take 13–16 min;
    - (c) catch the GKG up with a per-cycle cap *and* make embedding writes cheaper (batched writes, or a narrow embeddings table), which is a project of its own.
  - **Cost given to the owner (2026-10-21):**
    - Full ingestion adds about **$3 a month** in usage.
    - Realistically it also needs a **P10 disk**, about **+$10 a month**. Azure storage can only grow, so that's permanent.
  - **Recommendation:** stay at half until a disk upgrade happens for the 7-day reads anyway (the open links-7d disk decision), then revisit full ingestion on the bigger disk.
  - **The events path** keeps its own catch-up regardless: its files are about 80 KB, and its writes are a few hundred HOT updates.
- **Hourly rollups:** daily rollups stay (decision 1). Revisit only if the owner later wants relations to follow the timeline instead of the 7-day lens.

## Risks to watch

- **Machine-coding noise.** CAMEO coding is error-prone, and one article can yield many events. The mitigations are the thresholds (events, reports, outlets), copy that says "reported" and "not verified", and calibration on production (19b+).
- **Affiliation is not location.** Actor countries are affiliations ("French minister in Moscow" is France). The UI never says where an event happened.
- **Double counting.** Rollups are sums. The claim on `event_files` under an advisory lock prevents it, including during a deploy overlap. Watch for `another process added` lines.
- **Lost counts.** A missed slot's events are gone. The catch-up covers 2 hours; the 19b+ query checks about 4 files an hour.
- **Disk.** The step runs before the embeddings, writes a few hundred narrow rows as HOT updates, and reads a table that stays in `shared_buffers`. Watch the existing IOPS and bandwidth alerts after 19b.
- **#108.** 19c depends on its `wk:` helpers (decision 10). If #108 changes shape, 19c follows it; if it doesn't land, 19c uses the `db:*` fallback.
- **The lens lags.** Answers can be about an hour old (`wk:*`), and the lens moves at UTC midnight. The legend says "last 7 days" and names the dates, so neither misleads.
- **GDELT format changes.** The 61-field check and the malformed counter make a change visible in the log and the repro rather than silent.
- **Sensitive pairs** (IL–PS, RU–UA). Copy stays neutral: class words from QuadClass only, and no verbs of blame.
