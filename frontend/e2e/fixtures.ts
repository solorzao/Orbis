/**
 * Shared mock data and API route helpers for E2E tests.
 *
 * All tests run without a backend — Playwright intercepts API calls
 * and returns deterministic mock data.
 */
import { type Page } from "@playwright/test";

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

export const MOCK_DENSITY = Array.from({ length: 24 }, (_, i) => ({
  hour: i,
  count: Math.floor(Math.random() * 20) + 1,
}));

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
    title: string;
    url: string;
    source_name: string;
    lat: number;
    lng: number;
  }>;
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
      globe_actions: [],
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
  // Globe points
  await page.route("**/api/news?*", (route) => route.fulfill({ json: MOCK_GLOBE_POINTS }));
  await page.route("**/api/news", (route) => {
    if (route.request().url().includes("/api/news/")) return route.fallback();
    return route.fulfill({ json: MOCK_GLOBE_POINTS });
  });

  // Cluster articles
  await page.route("**/api/news/cluster*", (route) => route.fulfill({ json: MOCK_ARTICLES }));

  // Cluster summary
  await page.route("**/api/news/summary*", (route) => route.fulfill({ json: MOCK_SUMMARY }));

  // Density
  await page.route("**/api/news/density*", (route) => route.fulfill({ json: MOCK_DENSITY }));

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
