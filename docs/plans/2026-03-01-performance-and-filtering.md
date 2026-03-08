# Performance & Filtering Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make globe news load instantly (warm cache), fix topic filtering (client-side), and improve status text.

**Architecture:** Backend fetches all news once (no topic param), caches for 2 hours, and pre-warms cache on startup. Frontend fetches once on mount, stores all points, and filters locally by topic. Status changes from "CONNECTING" to "LOADING".

**Tech Stack:** Python FastAPI (backend), React/Next.js (frontend), Upstash Redis (cache)

---

### Task 1: Bump cache TTL from 15 min to 2 hours

**Files:**
- Modify: `backend/app/config.py:65`

**Step 1: Change the default TTL**

In `backend/app/config.py`, line 65, change:
```python
gdelt_cache_ttl: int = field(default_factory=lambda: _env_int("GDELT_CACHE_TTL", 900))
```
to:
```python
gdelt_cache_ttl: int = field(default_factory=lambda: _env_int("GDELT_CACHE_TTL", 7200))
```

**Step 2: Verify**

Run: `cd backend && python -c "from app.config import settings; print(settings.gdelt_cache_ttl)"`
Expected: `7200`

**Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "perf: bump GDELT cache TTL from 15 min to 2 hours"
```

---

### Task 2: Add startup cache warm-up

**Files:**
- Modify: `backend/app/main.py:50-55`

**Step 1: Add pre-fetch to startup event**

In `backend/app/main.py`, replace the `startup` function (lines 50-55) with:

```python
@app.on_event("startup")
async def startup() -> None:
    """Warm up Redis, database, and GDELT cache on startup."""
    logger.info("Starting Orbis API …")
    await get_redis()
    await get_pool()

    # Pre-warm the globe news cache so first request is instant
    import asyncio
    from app.services.gdelt import fetch_geo_points

    async def _warm_cache():
        try:
            points = await fetch_geo_points(query="sourcelang:english", timespan="24h")
            logger.info("Cache warm-up complete: %d globe points loaded.", len(points))
        except Exception:
            logger.warning("Cache warm-up failed — first request will be slower.", exc_info=True)

    asyncio.create_task(_warm_cache())
```

Key detail: `asyncio.create_task` fires the warm-up in background so the server starts accepting requests immediately. The warm-up runs concurrently.

**Step 2: Verify**

Start the backend and check logs for: `Cache warm-up complete: N globe points loaded.`

**Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "perf: pre-warm GDELT cache on backend startup"
```

---

### Task 3: Remove topic filtering from `/api/news` endpoint

**Files:**
- Modify: `backend/app/routers/news.py:59-77`

**Step 1: Simplify the route**

Replace the `get_globe_data` function (lines 59-77) with:

```python
@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    timespan: str = Query("24h", description="GDELT timespan, e.g. 24h, 48h"),
    limit: int = Query(500, ge=1, le=500, description="Max data points"),
) -> list[GlobeDataPoint]:
    """Return all globe data points from the GDELT GEO 2.0 API.

    Returns all topics — filtering is done client-side for instant switching.
    """
    points = await fetch_geo_points(query="sourcelang:english", timespan=timespan)
    points.sort(key=lambda p: p.article_count, reverse=True)
    return points[:limit]
```

Changes:
- Removed `topic` query param entirely
- Always fetches all news (no GDELT keyword filtering)
- Bumped default limit from 100 to 500 so frontend gets all points
- The `_TOPIC_TO_GDELT_QUERY` dict, `_TOPIC_ALIASES` dict, and `_resolve_topic` function can stay — they're still used by `/api/news/cluster`

**Step 2: Verify**

Run: `curl "http://localhost:8000/api/news?limit=5" | python -m json.tool | head -20`
Expected: JSON array of GlobeDataPoint objects with mixed topics.

**Step 3: Commit**

```bash
git add backend/app/routers/news.py
git commit -m "perf: remove server-side topic filtering from /api/news"
```

---

### Task 4: Frontend — fetch once, filter locally

**Files:**
- Modify: `frontend/src/lib/api.ts:57-65`
- Modify: `frontend/src/app/page.tsx:14-46`
- Modify: `frontend/src/lib/clustering.ts:108-120`

**Step 1: Simplify `fetchGlobeNews` in api.ts**

Replace lines 57-65 in `frontend/src/lib/api.ts` with:

```typescript
export function fetchGlobeNews(
  timespan = "24h",
  limit = 500,
): Promise<ApiGlobePoint[]> {
  return apiFetch<ApiGlobePoint[]>("/api/news", { timespan, limit: String(limit) });
}
```

Changes: removed `topic` param entirely, bumped default limit to 500.

**Step 2: Add `topic` field to GlobePoint type**

In `frontend/src/types/news.ts`, add `topic` to the `GlobePoint` interface:

```typescript
export interface GlobePoint {
  id: string;
  lat: number;
  lng: number;
  size: number;
  color: string;
  articles: NewsArticle[];
  isCluster: boolean;
  count: number;
  locationName?: string;
  topic: Topic;
}
```

**Step 3: Store topic in `apiPointsToGlobePoints`**

In `frontend/src/lib/clustering.ts`, update `apiPointsToGlobePoints` (lines 108-120) to include the mapped topic:

```typescript
export function apiPointsToGlobePoints(apiPoints: ApiGlobePoint[]): GlobePoint[] {
  return apiPoints.map((p, i) => ({
    id: `api-${i}`,
    lat: p.lat,
    lng: p.lng,
    size: Math.min(0.4 + p.article_count * 0.15, 1.5),
    color: getTopicColor(mapApiTopic(p.topic)),
    articles: [],
    isCluster: p.article_count > 1,
    count: p.article_count,
    locationName: p.location_name,
    topic: mapApiTopic(p.topic),
  }));
}
```

**Step 4: Rewrite page.tsx data flow**

Replace the state and useEffect in `frontend/src/app/page.tsx` (lines 14-46) with:

```typescript
export default function Home() {
  const [activeTopic, setActiveTopic] = useState<Topic>("All");
  const [selectedPoint, setSelectedPoint] = useState<GlobePoint | null>(null);

  const [allPoints, setAllPoints] = useState<GlobePoint[]>([]);
  const [apiError, setApiError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [clusterSummary, setClusterSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Fetch all points once on mount
  useEffect(() => {
    let cancelled = false;
    setApiError(false);
    setLoading(true);
    fetchGlobeNews()
      .then((apiPoints) => {
        if (cancelled) return;
        setAllPoints(apiPointsToGlobePoints(apiPoints));
      })
      .catch(() => {
        if (cancelled) return;
        setAllPoints([]);
        setApiError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Filter points client-side — instant, no API call
  const points = activeTopic === "All"
    ? allPoints
    : allPoints.filter((p) => p.topic === activeTopic);
```

Key changes:
- `allPoints` stores the full dataset (fetched once)
- `points` is a derived filtered view (no state, just computed)
- `useEffect` dependency is `[]` (mount only), not `[activeTopic]`
- `fetchGlobeNews()` called with no topic param

Also update the status bar (line 174) to use `allPoints` for the total count:
```typescript
<span>{allPoints.reduce((sum, p) => sum + p.count, 0)} stories tracked</span>
```

**Step 5: Verify**

1. Load the page — should show all colored dots
2. Click "Conflict" — should instantly show only red dots
3. Click "All" — all dots return instantly, no spinner

**Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/page.tsx frontend/src/lib/clustering.ts frontend/src/types/news.ts
git commit -m "perf: client-side topic filtering for instant switching"
```

---

### Task 5: Change status text from CONNECTING to LOADING

**Files:**
- Modify: `frontend/src/app/page.tsx:161`

**Step 1: Replace the status text**

In `frontend/src/app/page.tsx`, in the status bar JSX, change:
```tsx
<span className="text-blue-400 text-xs font-semibold tracking-wider">CONNECTING</span>
```
to:
```tsx
<span className="text-blue-400 text-xs font-semibold tracking-wider">LOADING</span>
```

**Step 2: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "fix: change status text from CONNECTING to LOADING"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `backend/app/config.py` | TTL 900 → 7200 |
| `backend/app/main.py` | Add startup cache warm-up task |
| `backend/app/routers/news.py` | Remove topic param from `/api/news` |
| `frontend/src/lib/api.ts` | Remove topic param from `fetchGlobeNews` |
| `frontend/src/types/news.ts` | Add `topic` field to `GlobePoint` |
| `frontend/src/lib/clustering.ts` | Pass `topic` through in `apiPointsToGlobePoints` |
| `frontend/src/app/page.tsx` | Fetch once + local filter + "LOADING" status |
