/**
 * Shared mock data and API route helpers for E2E tests.
 *
 * All tests run without a backend — Playwright intercepts API calls
 * and returns deterministic mock data.
 */
import { expect, type Page } from "@playwright/test";
import { GLOBE_OVERSCAN_PX, HOME_VIEW } from "../src/lib/globeView";

// ── Mock data ───────────────────────────────────────────────────────

export const MOCK_GLOBE_POINTS = [
  {
    lat: 48.8566,
    lng: 2.3522,
    weight: 5,
    article_count: 5,
    top_headline: "France announces new climate policy",
    topic: "Climate",
    location_name: "Paris, France",
  },
  {
    lat: 40.7128,
    lng: -74.006,
    weight: 8,
    article_count: 8,
    top_headline: "Tech stocks surge on Wall Street",
    topic: "Economy",
    location_name: "New York, United States",
  },
  {
    lat: 51.5074,
    lng: -0.1278,
    weight: 3,
    article_count: 3,
    top_headline: "UK parliament debates trade deal",
    topic: "Politics",
    location_name: "London, United Kingdom",
  },
];

/** Each mocked place's stories per topic pill; they add up to its article_count. */
const MOCK_TOPIC_COUNTS: Record<string, Partial<Record<string, number>>> = {
  "Paris, France": { Climate: 3, Politics: 1, Technology: 1 },
  "New York, United States": { Economy: 6, Technology: 2 },
  "London, United Kingdom": { Politics: 3 },
};

/**
 * /api/news as the backend answers it: a topic other than All keeps only the
 * places with stories on it, each counted by those stories and carrying the
 * topic's article tag (Climate is tagged "environment") as its colour.
 */
export function mockGlobeNews(url: string) {
  const topic = new URL(url).searchParams.get("topic");
  if (!topic || topic === "All") return MOCK_GLOBE_POINTS;
  const tag = topic === "Climate" ? "environment" : topic.toLowerCase();
  return MOCK_GLOBE_POINTS.flatMap((point) => {
    const count = MOCK_TOPIC_COUNTS[point.location_name]?.[topic] ?? 0;
    return count ? [{ ...point, topic: tag, article_count: count, weight: count }] : [];
  });
}

export const MOCK_ARTICLES = [
  {
    id: "art-001",
    title: "France announces new climate policy",
    summary: "France unveils ambitious targets for carbon reduction.",
    source_url: "https://example.com/france-climate",
    source_name: "Reuters",
    source_language: "en",
    published_at: new Date(Date.now() - 3600000).toISOString(),
    ingested_at: new Date().toISOString(),
    latitude: 48.8566,
    longitude: 2.3522,
    country_code: "FR",
    region: "Paris, France",
    topic_tags: ["Climate"],
    sentiment_score: 0.6,
    entities: {},
  },
  {
    id: "art-002",
    title: "EU leaders meet in Paris for summit",
    summary: "European leaders gather to discuss trade and security.",
    source_url: "https://example.com/eu-summit",
    source_name: "BBC News",
    source_language: "en",
    published_at: new Date(Date.now() - 7200000).toISOString(),
    ingested_at: new Date().toISOString(),
    latitude: 48.8566,
    longitude: 2.3522,
    country_code: "FR",
    region: "Paris, France",
    topic_tags: ["Politics"],
    sentiment_score: 0.1,
    entities: {},
  },
  {
    id: "art-003",
    title: "Paris tech startup raises $50M",
    summary: "A French AI startup secures major funding round.",
    source_url: "https://example.com/paris-tech",
    source_name: "TechCrunch",
    source_language: "en",
    published_at: new Date(Date.now() - 10800000).toISOString(),
    ingested_at: new Date().toISOString(),
    latitude: 48.8566,
    longitude: 2.3522,
    country_code: "FR",
    region: "Paris, France",
    topic_tags: ["Technology"],
    sentiment_score: 0.8,
    entities: {},
  },
];

export const MOCK_SUMMARY = {
  lat: 48.8566,
  lng: 2.3522,
  article_count: 3,
  summary:
    "Paris is at the center of multiple stories today, including France's new climate policy, an EU summit on trade and security, and a major tech funding round.",
};

/**
 * /api/news/volume?days=7 as the backend returns it: every hour from the hour
 * seven days ago to the current one (169), oldest first, with a daily swell.
 */
export function mockVolume(now = Date.now()) {
  const hour = 3_600_000;
  const current = Math.floor(now / hour) * hour;
  return Array.from({ length: 169 }, (_, i) => {
    const t = current - (168 - i) * hour;
    const h = new Date(t).getUTCHours();
    return {
      hour: new Date(t).toISOString().replace(".000Z", "Z"),
      count: 20 + Math.round(15 * Math.sin(((h - 8) / 24) * 2 * Math.PI)) + (i % 5),
    };
  });
}

export const MOCK_TOPICS = [
  { topic: "Politics", count: 42 },
  { topic: "Conflict", count: 28 },
  { topic: "Technology", count: 35 },
  { topic: "Climate", count: 19 },
  { topic: "Economy", count: 31 },
  { topic: "Health", count: 14 },
];

// ── SSE helper for agent mock ───────────────────────────────────────

export function buildAgentSSE(options: {
  answer: string;
  tools?: string[];
  citations?: Array<{
    index?: number;
    title: string;
    url: string;
    source_name: string;
    lat: number;
    lng: number;
  }>;
  globe_actions?: Array<{ type: "flyTo"; lat: number; lng: number; label?: string }>;
}): string {
  const lines: string[] = [];

  if (options.tools?.length) {
    lines.push(`event: planning`);
    lines.push(`data: ${JSON.stringify({ tools: options.tools })}`);
    lines.push("");
  }

  // Send answer as a single token for simplicity
  lines.push(`event: token`);
  lines.push(`data: ${JSON.stringify({ token: options.answer })}`);
  lines.push("");

  lines.push(`event: done`);
  lines.push(
    `data: ${JSON.stringify({
      citations: options.citations ?? [],
      globe_actions: options.globe_actions ?? [],
      tools_used: options.tools ?? [],
    })}`,
  );
  lines.push("");

  return lines.join("\n");
}

// ── Route interceptors ──────────────────────────────────────────────

/**
 * Mock all API routes so the app renders with deterministic data.
 * Call this in beforeEach for tests that need the full app.
 */
export async function mockAllApiRoutes(page: Page) {
  // Globe points, filtered by ?topic= as the backend does
  await page.route("**/api/news?*", (route) =>
    route.fulfill({ json: mockGlobeNews(route.request().url()) }),
  );
  await page.route("**/api/news", (route) => {
    if (route.request().url().includes("/api/news/")) return route.fallback();
    return route.fulfill({ json: mockGlobeNews(route.request().url()) });
  });

  // Cluster articles
  await page.route("**/api/news/cluster*", (route) => route.fulfill({ json: MOCK_ARTICLES }));

  // Cluster summary
  await page.route("**/api/news/summary*", (route) => route.fulfill({ json: MOCK_SUMMARY }));

  // Story volume for the timeline
  await page.route("**/api/news/volume*", (route) => route.fulfill({ json: mockVolume() }));

  // Topics
  await page.route("**/api/topics*", (route) => route.fulfill({ json: MOCK_TOPICS }));

  // Selection summary
  await page.route("**/api/news/summarize-selection*", (route) =>
    route.fulfill({
      json: { summary: "A mock filtered summary.", article_count: 2 },
    }),
  );
}

/**
 * Mock the agent streaming endpoint.
 */
export async function mockAgentRoute(page: Page, options?: Parameters<typeof buildAgentSSE>[0]) {
  const defaults = {
    answer:
      "Based on my research, France recently announced a new climate policy with ambitious carbon reduction targets.",
    tools: ["semantic_search"],
    citations: [
      {
        title: "France announces new climate policy",
        url: "https://example.com/france-climate",
        source_name: "Reuters",
        lat: 48.8566,
        lng: 2.3522,
      },
    ],
  };
  const body = buildAgentSSE(options ?? defaults);

  await page.route("**/api/agent/ask/stream", (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
      body,
    }),
  );
}

// ── Clicking a dot ──────────────────────────────────────────────────

/** three.js's default PerspectiveCamera fov, which globe.gl keeps (the app never sets it). */
const FOV_DEG = 50;
const CANVAS_TOP = -GLOBE_OVERSCAN_PX;

/**
 * Where a place sits on screen while the globe rests at HOME_VIEW (with
 * reduced motion it holds there): the camera is `altitude` globe radii above
 * the home point, looking at the centre.
 */
export function homeViewScreenPoint(
  lat: number,
  lng: number,
  viewport: { width: number; height: number },
  surfaceAltitude = 0.005, // half way up a dot (pointAltitude 0.01)
) {
  const rad = Math.PI / 180;
  const r = 1 + surfaceAltitude;
  const dLng = (lng - HOME_VIEW.lng) * rad; // turn the globe so the camera sits at lng 0
  const p = [
    r * Math.cos(lat * rad) * Math.sin(dLng),
    r * Math.sin(lat * rad),
    r * Math.cos(lat * rad) * Math.cos(dLng),
  ];
  const s = Math.sin(HOME_VIEW.lat * rad);
  const c = Math.cos(HOME_VIEW.lat * rad);
  const dist = 1 + HOME_VIEW.altitude;
  const d = [p[0], p[1] - dist * s, p[2] - dist * c]; // from the camera
  // Camera axes: right (1, 0, 0), up (0, c, -s), back (0, s, c).
  const right = d[0];
  const up = d[1] * c - d[2] * s;
  const depth = -(d[1] * s + d[2] * c);
  const height = viewport.height - CANVAS_TOP;
  const focal = height / 2 / Math.tan((FOV_DEG / 2) * rad);
  return {
    x: viewport.width / 2 + (right / depth) * focal,
    y: CANVAS_TOP + height / 2 - (up / depth) * focal,
  };
}

/** Load the app with the API mocked and the globe holding still at its home view. */
export async function gotoStillGlobe(page: Page, setup?: (page: Page) => Promise<void>) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockAllApiRoutes(page);
  await setup?.(page); // routes added later win over the defaults
  await page.goto("/");
  await expect(page.getByTestId("globe").locator("canvas")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible({ timeout: 10000 });
}

/** A dot from MOCK_GLOBE_POINTS. */
export type MockPlace = { lat: number; lng: number; location_name: string };
export const [PARIS, NEW_YORK, LONDON] = MOCK_GLOBE_POINTS;

/**
 * Click a dot, as a visitor would, and wait for its stories to open. globe.gl
 * finds the hovered dot on its next frame, so the pointer rests first; a dot
 * is a few pixels wide, so nearby pixels are tried too.
 */
export async function clickPlace(page: Page, place: MockPlace) {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("clickPlace needs a fixed viewport");
  const { x, y } = homeViewScreenPoint(place.lat, place.lng, viewport);
  const heading = page
    .getByTestId("news-panel")
    .getByRole("heading", { name: place.location_name, exact: true });
  for (const [dx, dy] of [
    [0, 0],
    [0, -1],
    [0, 1],
    [-1, 0],
    [1, 0],
    [0, -2],
    [0, 2],
  ]) {
    await page.mouse.move(x + dx, y + dy);
    await page.waitForTimeout(150);
    await page.mouse.down();
    await page.mouse.up();
    const opened = await heading
      .waitFor({ state: "visible", timeout: 1000 })
      .then(() => true)
      .catch(() => false);
    if (opened) return;
  }
  throw new Error(
    `No dot for ${place.location_name} (tried around ${Math.round(x)}, ${Math.round(y)})`,
  );
}
