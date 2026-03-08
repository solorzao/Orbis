# Story Exploration & Time Slider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add load-more pagination to article panels, a global time slider for filtering globe data by time window, and in-panel topic/sentiment filters.

**Architecture:** Backend gains `offset`/`limit` on cluster endpoint and `start_time`/`end_time` on globe + cluster endpoints, plus a new `/api/news/density` endpoint. Frontend adds a "Show more" button in NewsPanel, a TimeSlider component with dual-handle range selection and sparkline, and filter pills inside the panel.

**Tech Stack:** Python FastAPI (backend), React/Next.js + Tailwind CSS + Framer Motion (frontend), asyncpg (database), Upstash Redis (cache).

---

## Phase 1: Load More

### Task 1: Backend — Add offset/limit to cluster endpoint

**Files:**
- Modify: `backend/app/routers/news.py:126-136`
- Test: `backend/tests/test_news_router.py`

**Step 1: Write failing tests**

Add to `TestGetClusterArticles` in `backend/tests/test_news_router.py`:

```python
@pytest.mark.asyncio
async def test_offset_skips_articles(self):
    from app.routers.news import get_cluster_articles

    rows = [_make_db_row(f"Article {i}") for i in range(20)]

    with patch("app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows):
        result = await get_cluster_articles(
            lat=40.0, lng=-74.0, topic=None, location_name=None,
            offset=5, limit=3,
        )
        assert len(result) == 3
        assert result[0].title == "Article 5"

@pytest.mark.asyncio
async def test_default_offset_is_zero(self):
    from app.routers.news import get_cluster_articles

    rows = [_make_db_row(f"Article {i}") for i in range(5)]

    with patch("app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows):
        result = await get_cluster_articles(
            lat=40.0, lng=-74.0, topic=None, location_name=None,
        )
        assert result[0].title == "Article 0"
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_news_router.py::TestGetClusterArticles::test_offset_skips_articles tests/test_news_router.py::TestGetClusterArticles::test_default_offset_is_zero -v`
Expected: FAIL — `get_cluster_articles()` doesn't accept `offset`/`limit` params.

**Step 3: Implement offset/limit**

In `backend/app/routers/news.py`, modify `get_cluster_articles`:

```python
@router.get("/news/cluster", response_model=list[NewsArticle])
async def get_cluster_articles(
    lat: float = Query(..., description="Latitude of cluster center"),
    lng: float = Query(..., description="Longitude of cluster center"),
    radius: float = Query(0.75, description="Deprecated — ignored, uses grid cell"),
    topic: str | None = Query(None, description="Optional topic filter"),
    location_name: str | None = Query(None, description="Location name"),
    offset: int = Query(0, ge=0, description="Number of articles to skip"),
    limit: int = Query(10, ge=1, le=50, description="Max articles to return"),
) -> list[NewsArticle]:
    """Return full articles in the grid cell around (lat, lng)."""
    articles = await _fetch_cell_articles(lat, lng, topic)
    return articles[offset:offset + limit]
```

Also update the existing `test_caps_results_at_max` test — it currently checks against `_MAX_CLUSTER_ARTICLES` which we're replacing with the `limit` param. Update it to check default limit of 10:

```python
@pytest.mark.asyncio
async def test_caps_results_at_default_limit(self):
    from app.routers.news import get_cluster_articles

    rows = [_make_db_row(f"Article {i}") for i in range(50)]

    with patch("app.routers.news.get_articles_in_bounds", new_callable=AsyncMock, return_value=rows):
        result = await get_cluster_articles(
            lat=40.0, lng=-74.0, topic=None, location_name=None,
        )
        assert len(result) == 10
```

Remove `_MAX_CLUSTER_ARTICLES` constant (no longer needed — `limit` param replaces it). Also update the summary endpoint to use a local `_SUMMARY_ARTICLE_CAP = 10` since it still needs a fixed cap.

**Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/test_news_router.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add backend/app/routers/news.py backend/tests/test_news_router.py
git commit -m "feat: add offset/limit pagination to cluster articles endpoint"
```

---

### Task 2: Frontend — Add offset/limit to API client

**Files:**
- Modify: `frontend/src/lib/api.ts:61-76`

**Step 1: Update `fetchClusterArticles` signature**

```typescript
export function fetchClusterArticles(
  lat: number,
  lng: number,
  radius = 0.75,
  topic?: string,
  locationName?: string,
  offset = 0,
  limit = 10,
): Promise<ApiNewsArticle[]> {
  const params: Record<string, string> = {
    lat: String(lat),
    lng: String(lng),
    radius: String(radius),
  };
  if (topic && topic !== "All") params.topic = topic;
  if (locationName) params.location_name = locationName;
  if (offset > 0) params.offset = String(offset);
  if (limit !== 10) params.limit = String(limit);
  return apiFetch<ApiNewsArticle[]>("/api/news/cluster", params);
}
```

**Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add offset/limit params to fetchClusterArticles"
```

---

### Task 3: Frontend — "Show more" button in NewsPanel

**Files:**
- Modify: `frontend/src/components/NewsPanel.tsx:8-15` (props), `246-255` (button area)
- Modify: `frontend/src/components/PanelQueue.tsx:31-39` (pass callback)
- Modify: `frontend/src/app/page.tsx:55-103` (load-more handler)

**Step 1: Add `onLoadMore` prop and loading state to NewsPanel**

In `frontend/src/components/NewsPanel.tsx`, add to the interface:

```typescript
interface NewsPanelProps {
  point: GlobePoint | null;
  onClose: () => void;
  onMinimize?: () => void;
  onLoadMore?: () => void;
  loadingMore?: boolean;
  clusterSummary?: string | null;
  summaryLoading?: boolean;
  articlesLoading?: boolean;
}
```

Update the component signature to accept these props.

After the `AnimatePresence` block closing tag for article cards (after line ~338) and before the closing `</div>` of the scrollable area, add the "Show more" button:

```tsx
{/* Show more button */}
{!articlesLoading && point.articles.length > 0 &&
  point.articles.length < point.count && (
  <div className="mt-3 flex justify-center">
    <button
      onClick={onLoadMore}
      disabled={loadingMore}
      className="flex items-center gap-2 rounded-full border border-[var(--border-subtle)] px-4 py-2 text-xs font-medium text-blue-400 transition-colors hover:border-blue-500/30 hover:bg-blue-500/5 disabled:opacity-50"
    >
      {loadingMore ? (
        <>
          <span className="h-3 w-3 animate-spin rounded-full border border-blue-400/30 border-t-blue-400" />
          Loading...
        </>
      ) : (
        `Show more (${point.count - point.articles.length} remaining)`
      )}
    </button>
  </div>
)}
```

**Step 2: Wire through PanelQueue**

In `frontend/src/components/PanelQueue.tsx`:

- Add `onLoadMore: (panelId: string) => void` to props interface.
- Pass to the expanded `NewsPanel`: `onLoadMore={() => onLoadMore(expandedPanel.panelId)}`
- Also pass `loadingMore={expandedPanel.loadingMore}` (we'll add this field next).

**Step 3: Add `loadingMore` to PanelEntry type**

In `frontend/src/types/news.ts`, add to `PanelEntry`:

```typescript
loadingMore?: boolean;
```

**Step 4: Add load-more handler in page.tsx**

In `frontend/src/app/page.tsx`, add a `handleLoadMore` callback:

```typescript
const handleLoadMore = useCallback(
  async (panelId: string) => {
    const panel = panelQueue.find((p) => p.panelId === panelId);
    if (!panel || panel.loadingMore) return;

    updatePanel(panelId, { loadingMore: true });

    const topicFilter = activeTopic !== "All" ? activeTopic : undefined;
    try {
      const apiArticles = await fetchClusterArticles(
        panel.point.lat,
        panel.point.lng,
        0.75,
        topicFilter,
        panel.point.locationName,
        panel.articles.length, // offset
        20, // batch size
      );
      const mapped: NewsArticle[] = apiArticles.map((a) => ({
        id: a.id,
        title: a.title,
        summary: a.summary ?? undefined,
        sourceUrl: a.source_url,
        sourceName: a.source_name,
        publishedAt: a.published_at,
        latitude: a.latitude,
        longitude: a.longitude,
        countryCode: a.country_code,
        topicTags: a.topic_tags,
        sentimentScore: a.sentiment_score,
      }));
      const allArticles = [...panel.articles, ...mapped];
      updatePanel(panelId, {
        articles: allArticles,
        point: { ...panel.point, articles: allArticles },
        loadingMore: false,
      });
    } catch {
      updatePanel(panelId, { loadingMore: false });
    }
  },
  [panelQueue, activeTopic, updatePanel],
);
```

Pass `onLoadMore={handleLoadMore}` to `PanelQueue`.

**Step 5: Run frontend dev and verify manually**

Run: `cd frontend && npm run build`
Expected: No type errors, builds cleanly.

**Step 6: Commit**

```bash
git add frontend/src/components/NewsPanel.tsx frontend/src/components/PanelQueue.tsx frontend/src/types/news.ts frontend/src/app/page.tsx
git commit -m "feat: add show-more button for paginated article loading"
```

---

## Phase 2: Global Time Slider

### Task 4: Backend — Add start_time/end_time to globe and cluster endpoints

**Files:**
- Modify: `backend/app/routers/news.py:73-94` (globe endpoint), `126-136` (cluster endpoint)
- Modify: `backend/app/services/database.py:240-305` (get_globe_points)
- Test: `backend/tests/test_news_router.py`

**Step 1: Write failing test**

Add to `TestGetGlobeData` in `backend/tests/test_news_router.py`:

```python
@pytest.mark.asyncio
async def test_passes_start_end_time_to_db(self):
    from app.routers.news import get_globe_data

    with patch(
        "app.routers.news.get_globe_points",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_db:
        await get_globe_data(
            timespan="24h", limit=100,
            start_time="2026-03-07T14:00:00Z",
            end_time="2026-03-07T18:00:00Z",
        )
        call_kwargs = mock_db.call_args[1]
        assert call_kwargs["start_time"].hour == 14
        assert call_kwargs["end_time"].hour == 18
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_news_router.py::TestGetGlobeData::test_passes_start_end_time_to_db -v`
Expected: FAIL — `get_globe_data()` doesn't accept `start_time`/`end_time`.

**Step 3: Implement time range support**

In `backend/app/routers/news.py`, update `get_globe_data`:

```python
@router.get("/news", response_model=list[GlobeDataPoint])
async def get_globe_data(
    timespan: str = Query("24h", description="Timespan, e.g. 24h, 48h"),
    limit: int = Query(500, ge=1, le=500, description="Max data points"),
    start_time: str | None = Query(None, description="ISO start time"),
    end_time: str | None = Query(None, description="ISO end time"),
) -> list[GlobeDataPoint]:
```

Parse `start_time`/`end_time` into datetime objects when present, pass them to `get_globe_points`. Update cache key to include time range.

In `backend/app/services/database.py`, update `get_globe_points` to accept optional `start_time`/`end_time` datetime params. When both are provided, use `published_at BETWEEN $1 AND $X` instead of `published_at >= $1`.

Similarly update `get_cluster_articles` and `_fetch_cell_articles` to accept and forward `start_time`/`end_time`.

**Step 4: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add backend/app/routers/news.py backend/app/services/database.py backend/tests/test_news_router.py
git commit -m "feat: add start_time/end_time params to globe and cluster endpoints"
```

---

### Task 5: Backend — Add /api/news/density endpoint

**Files:**
- Modify: `backend/app/routers/news.py` (new endpoint)
- Modify: `backend/app/services/database.py` (new query function)
- Modify: `backend/app/models/news.py` (new response model)
- Test: `backend/tests/test_news_router.py`

**Step 1: Write failing test**

```python
class TestGetDensity:
    @pytest.mark.asyncio
    async def test_returns_24_hourly_buckets(self):
        from app.routers.news import get_article_density

        # Mock returns a dict of hour -> count
        mock_data = {i: i * 5 for i in range(24)}

        with patch(
            "app.routers.news.get_hourly_density",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            result = await get_article_density()
            assert len(result) == 24
            assert result[0].hour == 0
            assert result[0].count == 0
```

**Step 2: Implement density endpoint**

Add response model to `backend/app/models/news.py`:

```python
class HourlyDensity(BaseModel):
    hour: int
    count: int
```

Add to `backend/app/services/database.py`:

```python
async def get_hourly_density(*, timespan_hours: int = 24) -> dict[int, int]:
    """Return article counts bucketed by hour for the last N hours."""
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
    rows = await pool.fetch(
        """
        SELECT EXTRACT(HOUR FROM published_at) AS hour,
               COUNT(*) AS count
        FROM articles
        WHERE published_at >= $1
        GROUP BY hour
        ORDER BY hour
        """,
        cutoff,
    )
    return {int(r["hour"]): int(r["count"]) for r in rows}
```

Add endpoint in `backend/app/routers/news.py`:

```python
@router.get("/news/density", response_model=list[HourlyDensity])
async def get_article_density() -> list[HourlyDensity]:
    """Return article counts per hour for the sparkline."""
    cache_k = "db:density"
    cached = await get_cached(cache_k)
    if cached:
        return [HourlyDensity(**d) for d in cached]

    data = await get_hourly_density()
    result = [HourlyDensity(hour=h, count=data.get(h, 0)) for h in range(24)]

    await set_cached(cache_k, [d.model_dump() for d in result], settings.db_cache_ttl)
    return result
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS.

**Step 4: Commit**

```bash
git add backend/app/routers/news.py backend/app/services/database.py backend/app/models/news.py backend/tests/test_news_router.py
git commit -m "feat: add /api/news/density endpoint for hourly article counts"
```

---

### Task 6: Frontend — API client updates for time range and density

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Step 1: Update `fetchGlobeNews` and add `fetchDensity`**

```typescript
export function fetchGlobeNews(
  timespan = "24h",
  limit = 500,
  startTime?: string,
  endTime?: string,
): Promise<ApiGlobePoint[]> {
  const params: Record<string, string> = { timespan, limit: String(limit) };
  if (startTime) params.start_time = startTime;
  if (endTime) params.end_time = endTime;
  return apiFetch<ApiGlobePoint[]>("/api/news", params);
}

export interface ApiHourlyDensity {
  hour: number;
  count: number;
}

export function fetchDensity(): Promise<ApiHourlyDensity[]> {
  return apiFetch<ApiHourlyDensity[]>("/api/news/density");
}
```

Also update `fetchClusterArticles` to accept optional `startTime`/`endTime` and forward them.

**Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add time range and density to API client"
```

---

### Task 7: Frontend — TimeSlider component

**Files:**
- Create: `frontend/src/components/TimeSlider.tsx`

**Step 1: Build the TimeSlider component**

This is a dual-handle range slider with:
- 24-hour range (now - 24h to now)
- Sparkline density bars behind the track
- Debounced `onChange` callback with `{ startTime: string, endTime: string } | null`
- `null` means "full range" (no filter)
- Time labels at 6h tick marks
- Label showing current window: "4:00 PM - 8:00 PM" or "Last 24 hours"

Implementation uses native HTML range inputs (two overlapping `<input type="range">` elements) styled with Tailwind. The sparkline is a row of 24 thin bars with height proportional to density data. No external slider library needed.

Props:

```typescript
interface TimeSliderProps {
  density: { hour: number; count: number }[];
  onChange: (range: { startTime: string; endTime: string } | null) => void;
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/TimeSlider.tsx
git commit -m "feat: add TimeSlider component with dual handles and sparkline"
```

---

### Task 8: Frontend — Wire TimeSlider into page.tsx

**Files:**
- Modify: `frontend/src/app/page.tsx`

**Step 1: Add state and effects**

```typescript
const [timeRange, setTimeRange] = useState<{ startTime: string; endTime: string } | null>(null);
const [density, setDensity] = useState<{ hour: number; count: number }[]>([]);
```

- Fetch density on mount (alongside globe data).
- When `timeRange` changes (debounced by the slider), refetch globe data with `startTime`/`endTime`.
- Pass `timeRange` to `fetchPanelData` so new panels respect the window.
- Replace the static status bar with the TimeSlider, keeping the status info (LIVE indicator, counts) integrated into or near the slider.

**Step 2: Build and test manually**

Run: `cd frontend && npm run build`
Expected: Builds cleanly.

**Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: wire TimeSlider into globe page with time-filtered data"
```

---

## Phase 3: In-Panel Filters

### Task 9: Frontend — Add filter bar to NewsPanel

**Files:**
- Modify: `frontend/src/components/NewsPanel.tsx`

**Step 1: Add filter state and UI**

Inside NewsPanel, add local state:

```typescript
const [selectedTopics, setSelectedTopics] = useState<Set<string>>(new Set());
const [selectedSentiment, setSelectedSentiment] = useState<string | null>(null);
```

Derive available topics from loaded articles:

```typescript
const availableTopics = useMemo(() => {
  const tags = new Set<string>();
  point.articles.forEach((a) => a.topicTags.forEach((t) => tags.add(t)));
  return Array.from(tags).sort();
}, [point.articles]);
```

Filter articles client-side:

```typescript
const filteredArticles = useMemo(() => {
  let result = point.articles;
  if (selectedTopics.size > 0) {
    result = result.filter((a) =>
      a.topicTags.some((t) => selectedTopics.has(t))
    );
  }
  if (selectedSentiment) {
    result = result.filter((a) => {
      if (selectedSentiment === "positive") return a.sentimentScore >= 0.5;
      if (selectedSentiment === "neutral") return a.sentimentScore >= 0 && a.sentimentScore < 0.5;
      return a.sentimentScore < 0; // negative
    });
  }
  return result;
}, [point.articles, selectedTopics, selectedSentiment]);
```

Show filter bar only when >10 articles loaded. Render topic pills as horizontally scrollable row. Render 3 sentiment dots (green/amber/red). Update header to show "X of Y Stories" when filters active.

Use `filteredArticles` instead of `point.articles` in the article list rendering.

**Step 2: Build and verify**

Run: `cd frontend && npm run build`
Expected: Builds cleanly.

**Step 3: Commit**

```bash
git add frontend/src/components/NewsPanel.tsx
git commit -m "feat: add in-panel topic and sentiment filters"
```

---

## Implementation Order

1. **Task 1** → Backend offset/limit (test + implement)
2. **Task 2** → Frontend API client offset/limit
3. **Task 3** → Frontend "Show more" button (biggest frontend change in Phase 1)
4. **Task 4** → Backend time range params
5. **Task 5** → Backend density endpoint
6. **Task 6** → Frontend API client time range + density
7. **Task 7** → Frontend TimeSlider component
8. **Task 8** → Frontend wire TimeSlider into page
9. **Task 9** → Frontend in-panel filters

Tasks 1-3 (Phase 1) should be committed and pushed before starting Tasks 4-8 (Phase 2). Task 9 (Phase 3) can follow immediately after.
