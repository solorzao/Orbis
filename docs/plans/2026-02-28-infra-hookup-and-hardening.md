# Infrastructure Hookup & Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the frontend to the live backend API, fix the migration pipeline, lock down database/Redis firewall rules, and improve the health endpoint.

**Architecture:** The frontend (Next.js on Vercel) will gain an API client that calls the FastAPI backend (Azure Container Apps). Infrastructure security will be hardened by restricting database/Redis network access. The deploy pipeline's migration step will track applied migrations. The health endpoint will verify downstream connectivity.

**Tech Stack:** Next.js 16, React 19, FastAPI, asyncpg, redis.asyncio, Terraform (azurerm ~> 4.0), GitHub Actions

---

## Task 1: Create the Frontend API Client

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/.env.example`
- Create: `frontend/.env.local`

**Step 1: Create the API client module**

Create `frontend/src/lib/api.ts`:

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export interface ApiGlobePoint {
  lat: number;
  lng: number;
  weight: float;
  article_count: number;
  top_headline: string;
  topic: string;
}

export interface ApiNewsArticle {
  id: string;
  title: string;
  summary: string | null;
  source_url: string;
  source_name: string;
  source_language: string;
  published_at: string;
  ingested_at: string;
  latitude: number;
  longitude: number;
  country_code: string;
  region: string;
  topic_tags: string[];
  sentiment_score: number;
  entities: Record<string, unknown>;
}

export interface ApiClusterSummary {
  lat: number;
  lng: number;
  article_count: number;
  summary: string;
}

export interface ApiTopicCount {
  topic: string;
  count: number;
}

async function apiFetch<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_BASE);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function fetchGlobeNews(
  topic?: string,
  timespan = "24h",
  limit = 100
): Promise<ApiGlobePoint[]> {
  const params: Record<string, string> = { timespan, limit: String(limit) };
  if (topic && topic !== "All") params.topic = topic;
  return apiFetch<ApiGlobePoint[]>("/api/news", params);
}

export function fetchClusterArticles(
  lat: number,
  lng: number,
  radius = 2.0,
  topic?: string
): Promise<ApiNewsArticle[]> {
  const params: Record<string, string> = {
    lat: String(lat),
    lng: String(lng),
    radius: String(radius),
  };
  if (topic && topic !== "All") params.topic = topic;
  return apiFetch<ApiNewsArticle[]>("/api/news/cluster", params);
}

export function fetchClusterSummary(
  lat: number,
  lng: number,
  radius = 2.0
): Promise<ApiClusterSummary> {
  return apiFetch<ApiClusterSummary>("/api/news/summary", {
    lat: String(lat),
    lng: String(lng),
    radius: String(radius),
  });
}

export function fetchTopics(): Promise<ApiTopicCount[]> {
  return apiFetch<ApiTopicCount[]>("/api/topics");
}
```

**Step 2: Create frontend environment files**

Create `frontend/.env.example`:
```
# Backend API URL (include protocol, no trailing slash)
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Create `frontend/.env.local`:
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

**Step 3: Commit**

```bash
git add frontend/src/lib/api.ts frontend/.env.example frontend/.env.local
git commit -m "feat(frontend): add API client for backend endpoints"
```

---

## Task 2: Write Tests for the API Client

**Files:**
- Create: `frontend/src/lib/api.test.ts`

**Step 1: Write tests using fetch mocking**

Create `frontend/src/lib/api.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchGlobeNews, fetchClusterArticles, fetchClusterSummary, fetchTopics } from "./api";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  });
}

describe("fetchGlobeNews", () => {
  it("calls /api/news with default params", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews();
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news");
    expect(url.searchParams.get("timespan")).toBe("24h");
    expect(url.searchParams.get("limit")).toBe("100");
    expect(url.searchParams.has("topic")).toBe(false);
  });

  it("includes topic param when not All", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews("Politics");
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.searchParams.get("topic")).toBe("Politics");
  });

  it("omits topic param for All", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews("All");
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.searchParams.has("topic")).toBe(false);
  });

  it("throws on non-OK response", async () => {
    mockFetch.mockReturnValue(jsonResponse(null, 500));
    await expect(fetchGlobeNews()).rejects.toThrow("API 500");
  });
});

describe("fetchClusterArticles", () => {
  it("calls /api/news/cluster with lat/lng", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchClusterArticles(40.7, -74.0);
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news/cluster");
    expect(url.searchParams.get("lat")).toBe("40.7");
    expect(url.searchParams.get("lng")).toBe("-74");
  });
});

describe("fetchClusterSummary", () => {
  it("calls /api/news/summary with lat/lng/radius", async () => {
    mockFetch.mockReturnValue(jsonResponse({ summary: "test" }));
    await fetchClusterSummary(51.5, -0.1, 3.0);
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news/summary");
    expect(url.searchParams.get("radius")).toBe("3");
  });
});

describe("fetchTopics", () => {
  it("calls /api/topics with no params", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchTopics();
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/topics");
    expect([...url.searchParams.keys()]).toHaveLength(0);
  });
});
```

**Step 2: Run tests to verify they pass**

Run: `cd frontend && npm run test -- src/lib/api.test.ts`
Expected: All 7 tests PASS

**Step 3: Commit**

```bash
git add frontend/src/lib/api.test.ts
git commit -m "test(frontend): add unit tests for API client"
```

---

## Task 3: Wire page.tsx to the Live API with Mock Fallback

**Files:**
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/lib/clustering.ts` (add adapter function)

**Step 1: Add an adapter in clustering.ts to convert API points to GlobePoints**

The backend returns `ApiGlobePoint` (flat, no articles array). The frontend's `GlobePoint` type expects `articles`, `isCluster`, `count`, `size`, `color`. Add a converter at the bottom of `frontend/src/lib/clustering.ts`:

```typescript
import type { ApiGlobePoint } from "./api";

export function apiPointsToGlobePoints(apiPoints: ApiGlobePoint[]): GlobePoint[] {
  return apiPoints.map((p, i) => ({
    id: `api-${i}`,
    lat: p.lat,
    lng: p.lng,
    size: Math.min(0.4 + p.article_count * 0.15, 1.5),
    color: getTopicColor((p.topic || "All") as Topic),
    articles: [],
    isCluster: p.article_count > 1,
    count: p.article_count,
  }));
}
```

**Step 2: Update page.tsx to fetch from API with mock fallback**

Replace the data source logic in `frontend/src/app/page.tsx`. The key changes:
- Add `useState` for `points` and `loading`
- Add `useEffect` that calls `fetchGlobeNews(activeTopic)` on mount and when `activeTopic` changes
- On API failure, fall back to mock data with `clusterArticles(mockArticles, altitude)`
- Remove the `useMemo` that clusters mock data (replaced by API call)

Replace the data-fetching section of page.tsx (the `filteredArticles` and `points` useMemo blocks) with:

```typescript
import { fetchGlobeNews } from "@/lib/api";
import { apiPointsToGlobePoints } from "@/lib/clustering";

// Replace existing useMemo blocks with:
const [points, setPoints] = useState<GlobePoint[]>([]);
const [loading, setLoading] = useState(true);
const [usingMockData, setUsingMockData] = useState(false);

useEffect(() => {
  let cancelled = false;
  setLoading(true);

  fetchGlobeNews(activeTopic)
    .then((apiPoints) => {
      if (cancelled) return;
      setPoints(apiPointsToGlobePoints(apiPoints));
      setUsingMockData(false);
    })
    .catch(() => {
      if (cancelled) return;
      // Fallback to mock data
      const filtered = activeTopic === "All"
        ? mockArticles
        : mockArticles.filter((a) => a.topicTags.includes(activeTopic));
      setPoints(clusterArticles(filtered, altitude));
      setUsingMockData(true);
    })
    .finally(() => {
      if (!cancelled) setLoading(false);
    });

  return () => { cancelled = true; };
}, [activeTopic, altitude]);
```

Update the status bar to indicate data source:
```typescript
// In the status bar section, update the LIVE indicator:
{usingMockData ? (
  <span className="text-amber-400 text-xs font-semibold tracking-wider">DEMO</span>
) : (
  <>
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
    </span>
    <span className="text-emerald-400 text-xs font-semibold tracking-wider">LIVE</span>
  </>
)}
```

**Step 3: Run frontend tests and dev server**

Run: `cd frontend && npm run test`
Expected: All existing tests still pass

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add frontend/src/lib/clustering.ts frontend/src/app/page.tsx
git commit -m "feat(frontend): wire globe to live backend API with mock fallback"
```

---

## Task 4: Wire NewsPanel to Fetch Full Articles on Click

**Files:**
- Modify: `frontend/src/app/page.tsx`

**Step 1: Update handlePointClick to fetch cluster articles from API**

When a user clicks a globe point, the frontend should call `GET /api/news/cluster?lat=...&lng=...` to get full article details. Update the `handlePointClick` callback in page.tsx:

```typescript
import { fetchGlobeNews, fetchClusterArticles } from "@/lib/api";

// Replace handlePointClick with:
const handlePointClick = useCallback(
  async (point: GlobePoint) => {
    // Show panel immediately with what we have
    setSelectedPoint(point);

    if (usingMockData) return; // Mock data already has articles

    // Fetch full articles from API
    try {
      const articles = await fetchClusterArticles(point.lat, point.lng);
      const mapped: NewsArticle[] = articles.map((a) => ({
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
      setSelectedPoint((prev) =>
        prev ? { ...prev, articles: mapped, count: mapped.length } : null
      );
    } catch {
      // Keep the panel open with whatever we have
    }
  },
  [usingMockData]
);
```

**Step 2: Run build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat(frontend): fetch full articles from API on cluster click"
```

---

## Task 5: Add Frontend Environment to Vercel via CI/CD

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Step 1: Add change detection for frontend**

In the `changes` job path filters, add:

```yaml
frontend:
  - 'frontend/**'
```

**Step 2: Add Vercel deploy job**

Add a new job after `deploy-backend`:

```yaml
deploy-frontend:
  needs: [changes]
  if: needs.changes.outputs.frontend == 'true'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: amondnet/vercel-action@v25
      with:
        vercel-token: ${{ secrets.VERCEL_TOKEN }}
        vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
        vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
        working-directory: frontend
        vercel-args: '--prod'
```

> **Note:** The `NEXT_PUBLIC_API_BASE_URL` environment variable should be configured directly in the Vercel project dashboard (Settings → Environment Variables) since it's a build-time variable. Set it to the Container App URL from `terraform output container_app_url`.

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add Vercel frontend deployment to deploy pipeline"
```

---

## Task 6: Fix Database Migration Script (Add Version Tracking)

**Files:**
- Create: `database/migrations/005_migration_tracking.sql`
- Modify: `.github/workflows/deploy.yml`

**Step 1: Create migration tracking table**

Create `database/migrations/005_migration_tracking.sql`:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Backfill already-applied migrations
INSERT INTO schema_migrations (filename) VALUES
    ('001_extensions.sql'),
    ('002_articles.sql'),
    ('003_functions.sql'),
    ('004_rls_policies.sql'),
    ('005_migration_tracking.sql')
ON CONFLICT (filename) DO NOTHING;
```

**Step 2: Update the deploy.yml migration step**

Replace the `run-migrations` job's run step in `.github/workflows/deploy.yml`:

```yaml
- name: Run pending migrations
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
  run: |
    # Ensure tracking table exists (idempotent)
    psql "$DATABASE_URL" -f database/migrations/005_migration_tracking.sql

    # Run only unapplied migrations in order
    for f in database/migrations/*.sql; do
      fname=$(basename "$f")
      already=$(psql "$DATABASE_URL" -tAc "SELECT 1 FROM schema_migrations WHERE filename = '$fname'" 2>/dev/null || echo "")
      if [ "$already" != "1" ]; then
        echo "Applying: $fname"
        psql "$DATABASE_URL" -f "$f"
        psql "$DATABASE_URL" -c "INSERT INTO schema_migrations (filename) VALUES ('$fname')"
      else
        echo "Skipping (already applied): $fname"
      fi
    done
```

**Step 3: Verify the migration SQL is valid**

Run: `cat database/migrations/005_migration_tracking.sql` and check for syntax errors.

**Step 4: Commit**

```bash
git add database/migrations/005_migration_tracking.sql .github/workflows/deploy.yml
git commit -m "fix(ci): add migration version tracking to prevent re-runs"
```

---

## Task 7: Lock Down Database and Redis Firewall Rules

**Files:**
- Modify: `infra/postgres.tf`
- Modify: `infra/redis.tf`
- Modify: `infra/variables.tf`

**Step 1: Add a variable to control environment**

Add to `infra/variables.tf`:

```hcl
variable "environment" {
  description = "Deployment environment (dev or prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be 'dev' or 'prod'"
  }
}
```

**Step 2: Make PostgreSQL firewall conditional**

In `infra/postgres.tf`, replace the `AllowAllForDevelopment` firewall rule with a conditional:

```hcl
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_dev" {
  count            = var.environment == "dev" ? 1 : 0
  name             = "AllowAllForDevelopment"
  server_id        = azurerm_postgresql_flexible_server.orbis.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "255.255.255.255"
}
```

Remove the TODO comment since the code now handles it.

**Step 3: Make Redis public access conditional**

In `infra/redis.tf`, change the `public_network_access_enabled` line:

```hcl
public_network_access_enabled = var.environment == "dev" ? true : false
```

**Step 4: Enable Key Vault purge protection in prod**

In `infra/keyvault.tf`, update:

```hcl
purge_protection_enabled = var.environment == "prod" ? true : false
```

**Step 5: Run terraform validate**

Run: `cd infra && terraform init -backend=false && terraform validate`
Expected: "Success! The configuration is valid."

**Step 6: Commit**

```bash
git add infra/variables.tf infra/postgres.tf infra/redis.tf infra/keyvault.tf
git commit -m "security(infra): conditional firewall rules and purge protection by environment"
```

---

## Task 8: Improve Health Endpoint to Check Downstream Services

**Files:**
- Modify: `backend/app/main.py`

**Step 1: Update the health endpoint**

Replace the health endpoint in `backend/app/main.py`:

```python
@app.get("/health")
async def health():
    checks = {"api": "ok"}

    # Check database
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    # Check Redis
    try:
        r = await get_redis()
        if r:
            await r.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_configured"
    except Exception:
        checks["redis"] = "unavailable"

    all_ok = all(v in ("ok", "not_configured") for v in checks.values())
    status = "ok" if all_ok else "degraded"

    return JSONResponse(
        content={"status": status, "version": app.version, "checks": checks},
        status_code=200 if all_ok else 503,
    )
```

Add the import at the top of `main.py`:

```python
from starlette.responses import JSONResponse
```

**Step 2: Write a test for the health endpoint**

Create `backend/tests/test_health.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_health_ok():
    mock_pool = AsyncMock()
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("app.main.get_pool", return_value=mock_pool), \
         patch("app.main.get_redis", return_value=mock_redis):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["checks"]["database"] == "ok"
            assert data["checks"]["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_degraded_db():
    with patch("app.main.get_pool", side_effect=Exception("no db")), \
         patch("app.main.get_redis", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["checks"]["database"] == "unavailable"
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: 2 tests PASS

**Step 4: Commit**

```bash
git add backend/app/main.py backend/tests/test_health.py
git commit -m "feat(backend): health endpoint checks database and Redis connectivity"
```

---

## Task 9: Final Verification

**Step 1: Run all frontend tests**

Run: `cd frontend && npm run test`
Expected: All pass

**Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 3: Run all backend tests**

Run: `cd backend && python -m pytest -v`
Expected: All pass

**Step 4: Run Terraform validation**

Run: `cd infra && terraform validate`
Expected: Valid

**Step 5: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors

**Step 6: Run backend lint**

Run: `cd backend && ruff check app/`
Expected: No errors

**Step 7: Commit any remaining fixes from lint/test**

Only if needed.
