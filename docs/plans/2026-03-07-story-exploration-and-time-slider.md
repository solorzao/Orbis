# Story Exploration & Global Time Slider

**Date:** 2026-03-07
**Status:** Planned

## Problem

Clusters on the globe show real article counts (e.g., "100 stories") but clicking
caps the panel at 10 articles. This creates a trust/expectation mismatch — the core
UX feels broken even though data exists. Users also lack tools to explore dense
regions or understand how stories evolved over time.

## Design

Three independently shippable phases, ordered by impact.

---

### Phase 1: Honest Panel + Load More

**Goal:** Fix the expectation mismatch. Show real counts, let users load more.

**Backend:**
- Add `offset` (default 0) and `limit` (default 10) query params to
  `GET /api/news/cluster`.
- The SQL adds `OFFSET $n` to the existing bounded query.

**Frontend:**
- Panel header already shows `point.count` from the globe data (real count) — no
  change needed there.
- Initial fetch loads 10 articles (fast, enough for AI summary).
- Below the last article card, a **"Show more stories"** button appears when
  `point.count > loadedArticles.length`.
- Button label: "Show more (N remaining)".
- Clicking fetches the next batch (`offset=currentCount, limit=20`) and appends to
  the existing list.
- Explicit button, not infinite scroll — keeps user in control.

**AI summary stays on the first 10** — it's a briefing, not exhaustive analysis.

---

### Phase 2: Global Time Slider

**Goal:** Let users control the time window for all data on the globe.

**UI:**
- Horizontal slider at the bottom of the screen, centered, above/replacing the
  status bar.
- Represents the last 24 hours (left = oldest, right = now).
- **Dual handles** forming a draggable range window. Default: full 24h range.
- Tick marks at 6h intervals with time labels ("6am", "12pm", "6pm", "Now").
- Mini sparkline/density bar behind the slider track showing article volume per
  hour — taller bars = more articles published in that period.
- Label above slider: "4:00 PM - 8:00 PM" or "Last 24 hours" when full.

**Behavior:**
- Dragging handles re-filters globe points to the selected time window.
- Debounced: 300ms after user stops dragging before fetching.
- Globe dots fade in/out smoothly as the window changes.
- Status bar updates to reflect filtered counts.
- Open panels are NOT retroactively filtered — they keep fetched data. New panels
  respect the current time window.

**Backend:**
- `GET /api/news` gains optional `start_time` and `end_time` ISO params. The
  `get_globe_points` SQL swaps `published_at >= cutoff` for a `BETWEEN` clause.
  `timespan` param kept as fallback for backwards compat.
- `GET /api/news/cluster` also gains `start_time` / `end_time` so panel fetches
  respect the window.
- New endpoint `GET /api/news/density` returns 24 hourly buckets with article
  counts for the sparkline. Lightweight query, cached aggressively.
- Cache keys include the time range.

---

### Phase 3: In-Panel Filters

**Goal:** Let users filter articles within the panel once the list grows large.

**Appears conditionally** when >10 articles are loaded in the panel. Sits between
the AI briefing card and the article list.

**Topic tag pills:**
- Horizontal scrollable row of pills built from tags present in loaded articles.
- Tapping filters client-side. Multiple selection allowed (OR logic).
- "All" pill always first, selected by default.

**Sentiment quick-filter:**
- Three dot-buttons (green/amber/red) next to topic pills.
- Composes with topic filters via AND logic (must match both).

**Behavior:**
- All filtering is client-side only — no API calls.
- Header updates to "X of Y Stories" when filters active.
- "Show more" button loads unfiltered; new articles get filtered automatically.
- Filters reset when panel closes.

---

## Interaction Flow

Example: User drags time slider to "2pm-6pm", clicks a Ukraine cluster showing
"23 Stories".

1. Globe shows only points with articles published 2pm-6pm.
2. Panel opens, fetches first 10 of 23 time-filtered articles. AI summary runs.
3. Header shows "23 Stories".
4. User clicks "Show more (13 remaining)" — all 23 loaded.
5. Filter bar appears. User taps "Conflict" — list narrows to 8.
   Header: "8 of 23 Stories".
6. User drags time slider wider — globe updates, open panel stays as-is.

## Out of Scope

- Per-panel time slider (global slider is sufficient)
- Live-updating open panels when global slider changes (too complex)
- Infinite scroll (explicit load-more preferred)
- Server-side filtering within panels (client-side is fast enough for <100 articles)
- Per-cluster timeline histogram (can add later without rework)

## Dependencies

- Phase 1 and Phase 2 can be built in parallel.
- Phase 3 depends on Phase 1 (needs >10 articles loaded to be useful).
