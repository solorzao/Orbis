# Day Navigation for Time Slider — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add left/right arrow buttons to the time slider so users can page through up to 7 days of news in 24-hour windows.

**Architecture:** Introduce a `dayOffset` state (0=today, 1=yesterday, …6) in the TimeSlider. Arrows shift the window. The density endpoint gains an optional `offset_days` param so the sparkline updates per day. All existing time-range slider behavior (sub-24h selection, presets, reset) continues to work within the active day window. Arrows are visually disabled when no data exists in that direction.

**Tech Stack:** React, FastAPI, PostgreSQL

---

## Context

- **Data retention:** 7 days (`backend/app/config.py:82` — `retention_days: int = 7`)
- **Density endpoint:** `GET /api/news/density` → calls `get_hourly_density()` in `backend/app/services/database.py:332`. Currently hardcoded to last 24h.
- **Globe endpoint:** `GET /api/news` already accepts `start_time` and `end_time` ISO params.
- **Frontend API:** `fetchGlobeNews()` in `frontend/src/lib/api.ts:60` already passes `startTime`/`endTime`.
- **Frontend density:** `fetchDensity()` in `frontend/src/lib/api.ts:123` — no params currently.
- **TimeSlider:** `frontend/src/components/TimeSlider.tsx` — manages 0-24h range with sparkline, presets, dual-handle slider.
- **Page:** `frontend/src/app/page.tsx` — owns `timeRange` state, calls `fetchGlobeNews` and `fetchDensity`, passes props to TimeSlider.

---

### Task 1: Backend — Add `offset_days` param to density endpoint

**Files:**
- Modify: `backend/app/services/database.py:332-347` (`get_hourly_density`)
- Modify: `backend/app/routers/news.py:248-261` (`get_article_density`)
- Modify: `backend/tests/test_news_router.py` (add density offset test)

**Step 1: Write the failing test**

Add to `backend/tests/test_news_router.py`:

```python
@pytest.mark.asyncio
async def test_density_offset_days(client):
    """Density endpoint accepts offset_days param."""
    resp = await client.get("/api/news/density?offset_days=1")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_news_router.py::test_density_offset_days -v`
Expected: FAIL (endpoint doesn't accept `offset_days` yet)

**Step 3: Update `get_hourly_density` to accept offset**

In `backend/app/services/database.py`, modify `get_hourly_density`:

```python
async def get_hourly_density(*, timespan_hours: int = 24, offset_days: int = 0) -> dict[int, int]:
    """Return article counts bucketed by hour for a 24h window.

    offset_days=0 means the last 24h, offset_days=1 means 24-48h ago, etc.
    """
    pool = await get_pool()
    window_end = datetime.now(timezone.utc) - timedelta(days=offset_days)
    window_start = window_end - timedelta(hours=timespan_hours)
    rows = await pool.fetch(
        """
        SELECT EXTRACT(HOUR FROM published_at) AS hour,
               COUNT(*) AS count
        FROM articles
        WHERE published_at >= $1 AND published_at < $2
        GROUP BY hour
        ORDER BY hour
        """,
        window_start,
        window_end,
    )
    return {int(r["hour"]): int(r["count"]) for r in rows}
```

**Step 4: Update the density endpoint in `news.py`**

```python
@router.get("/news/density", response_model=list[HourlyDensity])
async def get_article_density(
    offset_days: int = Query(0, ge=0, le=6, description="Day offset (0=today, 1=yesterday, …6)"),
) -> list[HourlyDensity]:
    """Return article counts per hour for the time slider sparkline."""
    cache_k = f"db:density:{offset_days}"
    cached = await get_cached(cache_k)
    if cached:
        return [HourlyDensity(**d) for d in cached]

    data = await get_hourly_density(offset_days=offset_days)
    result = [HourlyDensity(hour=h, count=data.get(h, 0)) for h in range(24)]

    if result:
        await set_cached(cache_k, [d.model_dump() for d in result], settings.db_cache_ttl)
    return result
```

**Step 5: Run tests to verify everything passes**

Run: `cd backend && python -m pytest tests/ -q`
Expected: All pass

**Step 6: Commit**

```bash
git add backend/app/services/database.py backend/app/routers/news.py backend/tests/test_news_router.py
git commit -m "feat: add offset_days param to density endpoint for day navigation"
```

---

### Task 2: Frontend API — Add `offsetDays` to `fetchDensity`

**Files:**
- Modify: `frontend/src/lib/api.ts:123-125` (`fetchDensity`)

**Step 1: Update `fetchDensity` to accept `offsetDays`**

```typescript
export function fetchDensity(offsetDays = 0): Promise<ApiHourlyDensity[]> {
  const params: Record<string, string> = {};
  if (offsetDays > 0) params.offset_days = String(offsetDays);
  return apiFetch<ApiHourlyDensity[]>("/api/news/density", params);
}
```

**Step 2: Verify the app still compiles**

Run: `cd frontend && npx next build`
Expected: Build succeeds (existing call sites pass no args, matching the default)

**Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add offsetDays param to fetchDensity API call"
```

---

### Task 3: TimeSlider — Add day offset state, arrows, and window label

This is the main UI task. The TimeSlider gains:
- `dayOffset` state (0-6)
- Left arrow (go back one day) / right arrow (go forward one day)
- A window description label like "Today", "Yesterday", "Mon, Mar 3"
- Arrows disabled at boundaries (right disabled at offset 0, left disabled at offset 6 or when no data exists)

**Files:**
- Modify: `frontend/src/components/TimeSlider.tsx`

**Step 1: Add new props and state**

Add to `TimeSliderProps`:

```typescript
interface TimeSliderProps {
  density: { hour: number; count: number }[];
  onChange: (range: { startTime: string; endTime: string } | null) => void;
  onDayChange: (offsetDays: number) => void;  // NEW
  dayOffset: number;                            // NEW
  hasOlderData: boolean;                        // NEW — controls left arrow
  totalStories: number;
  totalLocations: number;
  isLive: boolean;
  isLoading: boolean;
  isOffline: boolean;
}
```

**Step 2: Update internal logic for day-aware time calculations**

The key insight: when `dayOffset > 0`, all hours-ago calculations need to be relative to the day window, not "now". The `hoursAgoToISO` function must offset by `dayOffset` days.

```typescript
// Convert hours-ago within the current day window to ISO string
const hoursAgoToISO = useCallback((hoursAgo: number): string => {
  const windowEnd = new Date(Date.now() - dayOffset * 86400000);
  const d = new Date(windowEnd.getTime() - hoursAgo * 3600000);
  return d.toISOString();
}, [dayOffset]);
```

Update `isFullRange` check and `emitChange` — when `dayOffset > 0`, even a "full range" selection should emit start/end times (since it's not "now"):

```typescript
const isFullRange = rangeStart === 24 && rangeEnd === 0;

const emitChange = useCallback(
  (start: number, end: number) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (start === 24 && end === 0 && dayOffset === 0) {
        onChange(null); // full range on today = no filter
      } else {
        onChange({
          startTime: hoursAgoToISO(start),
          endTime: hoursAgoToISO(end),
        });
      }
    }, 300);
  },
  [onChange, hoursAgoToISO, dayOffset],
);
```

**Step 3: Add the window description label**

```typescript
const windowLabel = useMemo(() => {
  if (dayOffset === 0) return "Today";
  if (dayOffset === 1) return "Yesterday";
  const d = new Date(Date.now() - dayOffset * 86400000);
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}, [dayOffset]);
```

**Step 4: Add arrow buttons to the JSX**

Wrap the existing slider container in a flex layout with arrows on each side. Place them **outside** the rounded panel, positioned to the left and right:

```tsx
<div className="fixed bottom-3 left-1/2 z-30 -translate-x-1/2 sm:bottom-6 flex items-center gap-2">
  {/* Left arrow — go back one day */}
  <button
    onClick={() => onDayChange(dayOffset + 1)}
    disabled={!hasOlderData || dayOffset >= 6}
    className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--border-subtle)] text-[var(--text-muted)] transition-all hover:border-blue-500/30 hover:text-blue-400 disabled:opacity-20 disabled:pointer-events-none"
    style={{
      background: "var(--surface-overlay)",
      backdropFilter: "blur(12px)",
    }}
    aria-label="Previous day"
  >
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 2L4 7l5 5" />
    </svg>
  </button>

  {/* Existing slider panel */}
  <div className="w-[80vw] max-w-2xl">
    <div className="rounded-2xl border ..." > ... </div>
  </div>

  {/* Right arrow — go forward one day */}
  <button
    onClick={() => onDayChange(dayOffset - 1)}
    disabled={dayOffset <= 0}
    className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--border-subtle)] text-[var(--text-muted)] transition-all hover:border-blue-500/30 hover:text-blue-400 disabled:opacity-20 disabled:pointer-events-none"
    style={{
      background: "var(--surface-overlay)",
      backdropFilter: "blur(12px)",
    }}
    aria-label="Next day"
  >
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 2l5 5-5 5" />
    </svg>
  </button>
</div>
```

**Step 5: Replace the "Last 24 hours" label with the window description**

In the top-right of the status bar, change:

```tsx
<span className="text-[var(--text-secondary)] font-medium">
  {isFullRange
    ? windowLabel
    : `${formatTime(rangeStart)} — ${formatTime(rangeEnd)}`}
</span>
```

Also show the window label alongside when a sub-range is selected:

```tsx
<span className="text-[var(--text-secondary)] font-medium">
  {isFullRange
    ? windowLabel
    : `${windowLabel} · ${formatTime(rangeStart)} — ${formatTime(rangeEnd)}`}
</span>
```

**Step 6: Reset slider range when day changes**

When `dayOffset` changes, reset the sub-range to full 24h. Add a `useEffect`:

```typescript
useEffect(() => {
  setRangeStart(24);
  setRangeEnd(0);
}, [dayOffset]);
```

**Step 7: Verify the app compiles**

Run: `cd frontend && npx next build`
Expected: Build fails — `page.tsx` doesn't pass the new props yet (Task 4 fixes this)

**Step 8: Commit**

```bash
git add frontend/src/components/TimeSlider.tsx
git commit -m "feat: add day navigation arrows and window label to TimeSlider"
```

---

### Task 4: Page — Wire up day offset state and data fetching

**Files:**
- Modify: `frontend/src/app/page.tsx`

**Step 1: Add `dayOffset` state and `hasOlderData` logic**

```typescript
const [dayOffset, setDayOffset] = useState(0);
const [hasOlderData, setHasOlderData] = useState(true); // optimistic default
```

**Step 2: Update density fetching to use `dayOffset`**

Find the existing `fetchDensity()` call and update:

```typescript
// Fetch density when dayOffset changes
useEffect(() => {
  fetchDensity(dayOffset)
    .then((d) => {
      setDensity(d);
      // Check if older data exists (for left arrow)
      if (dayOffset < 6) {
        fetchDensity(dayOffset + 1).then((older) => {
          setHasOlderData(older.some((h) => h.count > 0));
        }).catch(() => setHasOlderData(false));
      } else {
        setHasOlderData(false);
      }
    })
    .catch(() => setDensity([]));
}, [dayOffset]);
```

**Step 3: Update globe data fetch to respect day offset**

When `dayOffset > 0` and no sub-range is selected (timeRange is null), send the full day window:

```typescript
useEffect(() => {
  if (timeRange) {
    // Sub-range selection — use those times directly
    fetchGlobeNews("24h", 500, timeRange.startTime, timeRange.endTime)
      .then(...)
  } else if (dayOffset > 0) {
    // Full day window for a past day
    const windowEnd = new Date(Date.now() - dayOffset * 86400000);
    const windowStart = new Date(windowEnd.getTime() - 86400000);
    fetchGlobeNews("24h", 500, windowStart.toISOString(), windowEnd.toISOString())
      .then(...)
  } else {
    // Today, full range — no time filter
    fetchGlobeNews("24h", 500)
      .then(...)
  }
}, [timeRange, dayOffset]);
```

**Step 4: Handle `onDayChange` callback**

```typescript
const handleDayChange = useCallback((newOffset: number) => {
  const clamped = Math.max(0, Math.min(6, newOffset));
  setDayOffset(clamped);
  setTimeRange(null); // reset sub-range when changing days
}, []);
```

**Step 5: Pass new props to TimeSlider**

```tsx
<TimeSlider
  density={density}
  onChange={setTimeRange}
  onDayChange={handleDayChange}
  dayOffset={dayOffset}
  hasOlderData={hasOlderData}
  totalStories={points.reduce((sum, p) => sum + p.count, 0)}
  totalLocations={points.length}
  isLive={!apiError && !loading && dayOffset === 0}
  isLoading={loading}
  isOffline={apiError}
/>
```

Note: `isLive` is only true when viewing today (dayOffset === 0).

**Step 6: Verify the app builds and runs**

Run: `cd frontend && npx next build`
Expected: Build succeeds

Run: `cd frontend && npm run dev`
Manual test:
- Click left arrow → slider shows "Yesterday", globe loads previous day's data
- Click left again → shows date label like "Thu, Mar 6"
- Click right arrow → goes back toward today
- Right arrow disabled when on today
- Left arrow disabled when at 6 days back or no data
- Selecting a sub-range within a past day works
- "Reset" returns to full 24h of that day (not back to today)

**Step 7: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: wire day offset state to TimeSlider and API calls"
```

---

### Task 5: Polish — LIVE indicator and cluster panels respect day offset

**Files:**
- Modify: `frontend/src/app/page.tsx` (cluster article fetches)

**Step 1: Update cluster article fetches to respect day offset**

When a user clicks a cluster while viewing a past day, the article fetch should use the day window's time boundaries. Find the cluster article fetch calls and ensure they pass appropriate `startTime`/`endTime` when `dayOffset > 0`.

The existing code already passes `timeRange?.startTime` and `timeRange?.endTime` to cluster fetches. When `dayOffset > 0` and the user hasn't narrowed the range (timeRange is null), we need to compute and pass the day window boundaries.

Create a helper:

```typescript
const dayWindow = useMemo(() => {
  if (dayOffset === 0) return null;
  const windowEnd = new Date(Date.now() - dayOffset * 86400000);
  const windowStart = new Date(windowEnd.getTime() - 86400000);
  return { startTime: windowStart.toISOString(), endTime: windowEnd.toISOString() };
}, [dayOffset]);

// Then use: timeRange ?? dayWindow for all API calls that take start/end time
```

Update all places that reference `timeRange?.startTime` and `timeRange?.endTime` to use `(timeRange ?? dayWindow)?.startTime` etc.

**Step 2: Verify cluster clicks work on past days**

Manual test: Navigate to yesterday, click a cluster → articles should be from yesterday, not today.

**Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: cluster panels respect day offset time window"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Backend density offset | `database.py`, `news.py`, tests |
| 2 | Frontend API param | `api.ts` |
| 3 | TimeSlider UI (arrows, label, state) | `TimeSlider.tsx` |
| 4 | Page wiring (state, fetches, props) | `page.tsx` |
| 5 | Polish (clusters respect offset) | `page.tsx` |
