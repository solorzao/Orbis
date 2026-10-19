/**
 * Shared mock data and API route helpers for E2E tests.
 *
 * All tests run without a backend — Playwright intercepts API calls
 * and returns deterministic mock data.
 */
import { expect, type Page } from "@playwright/test";
import { GLOBE_OVERSCAN_PX, HOME_VIEW } from "../src/lib/globeView";
import { arcApex } from "../src/lib/links";
import type { ApiThread, ApiThreadDetail } from "../src/lib/threads";

// ── Mock data ───────────────────────────────────────────────────────

/** How long ago, as the API's ISO time. */
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

/** Lead images: served by mockAllApiRoutes as photo-sized SVGs (see mockImage). */
export const IMAGE_HOST = "https://images.orbis.test";

export const MOCK_GLOBE_POINTS = [
  {
    lat: 48.8566,
    lng: 2.3522,
    weight: 5,
    article_count: 5,
    top_headline: "France announces new climate policy",
    topic: "Climate",
    location_name: "Paris, France",
    country_code: "FR",
    lead: {
      title: "France announces new climate policy",
      source_name: "Reuters",
      published_at: ago(12),
      image_url: `${IMAGE_HOST}/paris-climate.jpg`,
      topic: "environment",
      sensitive: false,
    },
    topic_mix: { environment: 3, politics: 1, technology: 1 },
    tone: 0.42,
  },
  {
    lat: 40.7128,
    lng: -74.006,
    weight: 8,
    article_count: 8,
    top_headline: "Tech stocks surge on Wall Street",
    topic: "Economy",
    location_name: "New York, United States",
    country_code: "US",
    lead: {
      title: "Tech stocks surge on Wall Street",
      source_name: "Bloomberg",
      published_at: ago(35),
      image_url: `${IMAGE_HOST}/wall-street.jpg`,
      topic: "economy",
      sensitive: false,
    },
    topic_mix: { economy: 6, technology: 2 },
    tone: 0.18,
  },
  {
    lat: 51.5074,
    lng: -0.1278,
    weight: 3,
    article_count: 3,
    top_headline: "UK parliament debates trade deal",
    topic: "Politics",
    location_name: "London, United Kingdom",
    country_code: "GB",
    lead: {
      title: "UK parliament debates trade deal",
      source_name: "BBC News",
      published_at: ago(80),
      image_url: null,
      topic: "politics",
      sensitive: false,
    },
    topic_mix: { politics: 3 },
    tone: -0.05,
  },
];

/**
 * A place with a conflict lead, right of the globe's centre and near the
 * side panel at 1280 and 1440 wide. Not in MOCK_GLOBE_POINTS (whose counts
 * the globe tests read): add it with withCairo.
 */
export const CAIRO = {
  lat: 30.0444,
  lng: 31.2357,
  weight: 4,
  article_count: 4,
  top_headline: "Ceasefire talks resume in Cairo as shelling continues",
  topic: "conflict",
  location_name: "Cairo, Egypt",
  country_code: "EG",
  lead: {
    title: "Ceasefire talks resume in Cairo as shelling continues",
    source_name: "Al Jazeera",
    published_at: ago(25),
    image_url: `${IMAGE_HOST}/cairo-talks.jpg`,
    // Tagged [politics, conflict]: its first tag is politics, but it is still sensitive.
    topic: "politics",
    sensitive: true,
  },
  topic_mix: { conflict: 3, politics: 2 },
  tone: -0.46,
};

/** gotoStillGlobe/settle setup: the globe also shows CAIRO. */
export async function withCairo(page: Page) {
  await page.route("**/api/news?*", (route) =>
    route.fulfill({ json: [...mockGlobeNews(route.request().url()), CAIRO] }),
  );
}

/** /api/news/preview's dwell data: a sparkline, three names and a cached brief. */
export const MOCK_PREVIEW = {
  spark: [2, 1, 0, 0, 1, 0, 0, 1, 3, 4, 2, 3, 5, 4, 6, 3, 2, 4, 5, 7, 6, 4, 5, 8],
  entities: [
    { name: "Emmanuel Macron", type: "person", n: 4 },
    { name: "European Union", type: "org", n: 3 },
    { name: "Anne Hidalgo", type: "person", n: 2 },
  ],
  brief:
    "France set tougher carbon targets for 2035 as EU leaders met in Paris to discuss trade and security.",
};

/** A 640x360 "photo" for a lead image URL: an SVG landscape, tinted by its name. */
export function mockImage(url: string): string {
  const hue = [...new URL(url).pathname].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="hsl(${hue} 70% 72%)"/><stop offset="1" stop-color="hsl(${(hue + 40) % 360} 35% 28%)"/>
</linearGradient></defs>
<rect width="640" height="360" fill="url(#sky)"/>
<circle cx="500" cy="96" r="38" fill="hsl(${(hue + 20) % 360} 90% 88%)" opacity=".85"/>
<path d="M0 262 L70 214 L140 246 L220 176 L300 236 L380 168 L460 226 L540 186 L640 236 V360 H0 Z" fill="hsl(${(hue + 200) % 360} 30% 16%)" opacity=".9"/>
<path d="M0 310 L120 282 L260 300 L400 276 L520 296 L640 280 V360 H0 Z" fill="hsl(${(hue + 210) % 360} 25% 10%)"/>
</svg>`;
}

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

// ── Links (co-coverage arcs) ────────────────────────────────────────

/** Label points as the backend has them (country_centroids.py). */
export const COUNTRIES = {
  CA: { iso: "CA", name: "Canada", lat: 57.75, lng: -101.57 },
  CN: { iso: "CN", name: "China", lat: 36.61, lng: 103.87 },
  EG: { iso: "EG", name: "Egypt", lat: 26.51, lng: 29.84 },
  FR: { iso: "FR", name: "France", lat: 46.61, lng: 2.34 },
  GB: { iso: "GB", name: "United Kingdom", lat: 53.88, lng: -2.66 },
  IL: { iso: "IL", name: "Israel", lat: 30.95, lng: 34.88 },
  IR: { iso: "IR", name: "Iran", lat: 32.52, lng: 54.29 },
  RU: { iso: "RU", name: "Russia", lat: 61.69, lng: 99.22 },
  SA: { iso: "SA", name: "Saudi Arabia", lat: 24.12, lng: 44.52 },
  UA: { iso: "UA", name: "Ukraine", lat: 49.15, lng: 31.23 },
  US: { iso: "US", name: "United States", lat: 39.5, lng: -99.06 },
  YE: { iso: "YE", name: "Yemen", lat: 15.91, lng: 47.54 },
} as const;

type Iso = keyof typeof COUNTRIES;

/** A link as /api/links sends it: its ends in code order. */
function mockLink(x: Iso, y: Iso, n: number, lift: number, topic: string, tone: number, from: Iso) {
  const [a, b] = [x, y].sort() as [Iso, Iso];
  return { a: COUNTRIES[a], b: COUNTRIES[b], n, lift, topic, tone, from };
}

/** /api/links?rank=lift: the surprising pairs first. */
export const MOCK_LINKS_LIFT = [
  mockLink("SA", "YE", 46, 6.2, "conflict", -0.52, "SA"),
  mockLink("EG", "IL", 23, 5.1, "conflict", -0.41, "IL"),
  mockLink("RU", "UA", 64, 3.4, "conflict", -0.55, "UA"),
  mockLink("FR", "GB", 18, 2.6, "economy", 0.06, "GB"),
  mockLink("FR", "UA", 15, 2.2, "conflict", -0.35, "FR"),
  mockLink("IR", "US", 41, 1.8, "politics", -0.32, "US"),
];

/** /api/links?rank=count: the most covered pairs first (hubs included). */
export const MOCK_LINKS_COUNT = [
  mockLink("RU", "US", 69, 1.2, "politics", -0.28, "US"),
  mockLink("RU", "UA", 64, 3.4, "conflict", -0.55, "UA"),
  mockLink("GB", "US", 62, 1.1, "politics", -0.08, "US"),
  mockLink("SA", "YE", 46, 6.2, "conflict", -0.52, "SA"),
  mockLink("IR", "US", 41, 1.8, "politics", -0.32, "US"),
  mockLink("CA", "US", 38, 1.3, "economy", -0.12, "CA"),
  mockLink("CN", "US", 35, 1.1, "economy", -0.1, "US"),
];

/** /api/links as the backend answers it, by ?rank= (lift by default). */
export function mockLinks(url: string) {
  return new URL(url).searchParams.get("rank") === "count" ? MOCK_LINKS_COUNT : MOCK_LINKS_LIFT;
}

/** Whether a request is for the arcs (/api/links), not a link's detail or explanation. */
export const isLinksList = (url: URL) => url.pathname === "/api/links";

/** A story that links two countries, as /api/links/detail lists it. */
function linkStory(
  id: string,
  title: string,
  source: string,
  region: string,
  cc: Iso,
  mins: number,
  tone: number,
) {
  return {
    id,
    title,
    summary: null,
    source_url: `https://example.com/${id}`,
    source_name: source,
    source_language: "en",
    published_at: ago(mins),
    ingested_at: ago(mins),
    latitude: COUNTRIES[cc].lat,
    longitude: COUNTRIES[cc].lng,
    country_code: cc,
    region,
    topic_tags: ["politics"],
    sentiment_score: tone,
    entities: {},
  };
}

/** /api/links/detail for Iran and the United States, in code order (IR, US). */
export const MOCK_LINK_DETAIL = {
  a: COUNTRIES.IR,
  b: COUNTRIES.US,
  n: 41,
  lift: 1.8,
  topic_mix: { politics: 24, conflict: 12, economy: 5 },
  tone: -0.32,
  shared: [
    { name: "IAEA", type: "org", n: 9 },
    { name: "State Department", type: "org", n: 6 },
    { name: "Revolutionary Guard", type: "org", n: 4 },
  ],
  themes: ["nuclear talks", "sanctions", "diplomacy"],
  articles: [
    linkStory(
      "link-001",
      "US and Iran resume indirect nuclear talks in Oman",
      "Reuters",
      "Washington, United States",
      "US",
      18,
      -0.1,
    ),
    linkStory(
      "link-002",
      "Tehran rejects new sanctions as talks stall",
      "Al Jazeera",
      "Tehran, Iran",
      "IR",
      64,
      -0.48,
    ),
    linkStory(
      "link-003",
      "Oil climbs as Washington weighs Iran waivers",
      "Bloomberg",
      "New York, United States",
      "US",
      150,
      0.12,
    ),
  ],
};

/** /api/links/detail as the backend answers it: Iran and the US, else a pair's arc numbers. */
export function mockLinkDetail(url: string) {
  const params = new URL(url).searchParams;
  const [a, b] = [params.get("a"), params.get("b")].map((c) => (c ?? "").toUpperCase()).sort();
  if (a === "IR" && b === "US") return MOCK_LINK_DETAIL;
  const link = [...MOCK_LINKS_LIFT, ...MOCK_LINKS_COUNT].find(
    (l) => l.a.iso === a && l.b.iso === b,
  );
  return {
    a: COUNTRIES[a as Iso],
    b: COUNTRIES[b as Iso],
    n: link?.n ?? 0,
    lift: link?.lift ?? 0,
    topic_mix: link ? { [link.topic]: link.n } : {},
    tone: link?.tone ?? 0,
    shared: [],
    themes: [],
    articles: [],
  };
}

/** /api/links/explain's answer for Iran and the United States. */
export const MOCK_LINK_EXPLAIN = {
  text: "Coverage links the two over renewed indirect nuclear talks and new sanctions, with US outlets writing most of the stories.",
};

/** Mock the Links layer's endpoints: the arcs, a link's detail and its explanation. */
export async function mockLinkRoutes(page: Page) {
  await page.route(isLinksList, (route) =>
    route.fulfill({ json: mockLinks(route.request().url()) }),
  );
  await page.route("**/api/links/detail*", (route) =>
    route.fulfill({ json: mockLinkDetail(route.request().url()) }),
  );
  await page.route("**/api/links/explain", (route) => route.fulfill({ json: MOCK_LINK_EXPLAIN }));
}

// ── Story threads ───────────────────────────────────────────────────

/** A place a thread reached: its first report there `hoursAgo` hours ago, and its stories. */
function threadPlace(
  place: string,
  country_code: string,
  lat: number,
  lng: number,
  hoursAgo: number,
  n: number,
) {
  return { lat, lng, place, country_code, first_seen: ago(hoursAgo * 60), n };
}

/** The Red Sea thread's spread, first report first: four places, three arcs from Yemen. */
export const RED_SEA_SPREAD = [
  threadPlace("Yemen", "YE", 15.5, 48.5, 30, 7),
  threadPlace("Suez, Egypt", "EG", 30.5, 32.5, 26, 6),
  threadPlace("Rotterdam, Netherlands", "NL", 51.5, 4.5, 20, 6),
  threadPlace("Mombasa, Kenya", "KE", -4.5, 39.5, 9, 5),
];

function mockThread(
  over: Pick<ApiThread, "id" | "title" | "n_stories" | "n_sources" | "velocity"> &
    Partial<ApiThread>,
): ApiThread {
  return {
    synopsis: null,
    status: "developing",
    first_seen: ago(30 * 60),
    last_seen: ago(20),
    countries: [],
    places: [],
    topic: "general",
    lead: null,
    ...over,
  };
}

/** /api/threads: four developing stories, fastest first, as the API orders them. */
export const MOCK_THREADS: ApiThread[] = [
  mockThread({
    id: 7,
    title: "Red Sea shipping attacks",
    synopsis:
      "Outlets in Yemen first reported attacks on ships in the Red Sea. Coverage then spread to Egypt, the Netherlands and Kenya, where reports describe rerouted cargo.",
    n_stories: 24,
    n_sources: 11,
    velocity: 6,
    countries: ["YE", "EG", "NL", "KE"],
    places: RED_SEA_SPREAD,
    topic: "conflict",
    lead: {
      title: "Ships divert from the Red Sea after new attacks",
      source_name: "Reuters",
      published_at: ago(40),
      image_url: null,
      topic: "conflict",
    },
  }),
  mockThread({
    id: 12,
    title: "Typhoon nears Luzon",
    status: "emerging",
    first_seen: ago(4 * 60),
    n_stories: 9,
    n_sources: 6,
    velocity: 4,
    countries: ["PH", "TW"],
    places: [
      threadPlace("Manila, Philippines", "PH", 14.5, 120.5, 4, 6),
      threadPlace("Taipei, Taiwan", "TW", 25.5, 121.5, 2, 3),
    ],
    topic: "environment",
  }),
  mockThread({
    id: 15,
    title: "EU summit on energy prices",
    n_stories: 12,
    n_sources: 8,
    velocity: 3,
    countries: ["BE", "FR", "DE"],
    places: [
      threadPlace("Brussels, Belgium", "BE", 50.5, 4.5, 28, 6),
      threadPlace("Paris, France", "FR", 48.5, 2.5, 22, 4),
      threadPlace("Berlin, Germany", "DE", 52.5, 13.5, 18, 2),
    ],
    topic: "economy",
  }),
  mockThread({
    id: 21,
    title: "Mpox cases in Kinshasa",
    status: "fading",
    n_stories: 6,
    n_sources: 4,
    velocity: 0,
    countries: ["CD", "UG"],
    places: [
      threadPlace("Kinshasa, DR Congo", "CD", -4.5, 15.5, 60, 4),
      threadPlace("Kampala, Uganda", "UG", 0.5, 32.5, 50, 2),
    ],
    topic: "health",
  }),
];

/** A thread's stories, 20 a page (the Red Sea thread has 24). */
function threadArticles(thread: ApiThread, offset: number) {
  const total = thread.n_stories;
  const places = thread.places.map((p) => p.place);
  return Array.from({ length: Math.max(0, Math.min(20, total - offset)) }, (_, i) => {
    const k = offset + i + 1;
    return {
      title: `${thread.title}: report ${k}`,
      source_name: ["Reuters", "AP", "BBC News", "Al Jazeera"][k % 4],
      published_at: ago(20 + k * 30),
      source_url: `https://example.com/thread-${thread.id}/${k}`,
      place: places[k % places.length] ?? "",
    };
  });
}

/** /api/threads/{id}: the list item, its key entities, its whole spread and a page of stories. */
export function mockThreadDetail(url: string): ApiThreadDetail | null {
  const u = new URL(url);
  const id = Number(u.pathname.split("/").pop());
  const thread = MOCK_THREADS.find((t) => t.id === id);
  if (!thread) return null;
  const offset = Number(u.searchParams.get("offset") ?? 0);
  return {
    ...thread,
    entities: [
      { name: "Suez Canal Authority", n: 9 },
      { name: "Houthis", n: 7 },
      { name: "Maersk", n: 5 },
    ],
    spread: thread.places,
    timeline: [],
    articles: threadArticles(thread, offset),
  };
}

export const isThreadsList = (url: URL) => url.pathname === "/api/threads";
export const isThreadDetail = (url: URL) => /^\/api\/threads\/\d+$/.test(url.pathname);

/** Mock the Threads layer's endpoints: the list and each thread's detail (404 if unknown). */
export async function mockThreadRoutes(page: Page) {
  await page.route(isThreadsList, (route) => route.fulfill({ json: MOCK_THREADS }));
  await page.route(isThreadDetail, (route) => {
    const detail = mockThreadDetail(route.request().url());
    return detail
      ? route.fulfill({ json: detail })
      : route.fulfill({ status: 404, json: { detail: "No such thread." } });
  });
}

/** The thread Paris's first story is part of, as /api/news/cluster sends it. */
export const PARIS_THREAD = {
  id: 15,
  title: "EU summit on energy prices",
  places: ["Brussels, Belgium", "Paris, France", "Berlin, Germany"],
};

/**
 * gotoStillGlobe/settle setup: a place's first story is part of a thread (the
 * EU summit), so its panel shows the "Part of" chip.
 */
export async function withThreads(page: Page) {
  await page.route("**/api/news/cluster*", (route) =>
    route.fulfill({
      json: MOCK_ARTICLES.map((a, i) => ({ ...a, thread: i === 0 ? PARIS_THREAD : null })),
    }),
  );
}

// ── Breaking stories ────────────────────────────────────────────────

/** A breaking story's lead, as /api/news/breaking sends it. */
const breakingLead = (title: string, source: string, minutes: number, topic: string) => ({
  title,
  source_name: source,
  published_at: ago(minutes),
  image_url: null,
  topic,
  sensitive: false,
});

/**
 * /api/news/breaking with three stories, most outlets first: one at Paris (a
 * dot on the globe), one somewhere with no dot (San Antonio), and one more.
 * The San Antonio one is real data's shape: a long headline, a mislabelled
 * topic, first_seen at the window's start.
 */
export const MOCK_BREAKING = [
  {
    headline: "Riot police clear a Paris square after a night of protests over pension reform",
    place: "Paris, France",
    lat: 48.8566,
    lng: 2.3522,
    outlets: 23,
    stories: 6,
    first_seen: ago(120),
    topic: "politics",
    lead: breakingLead("Riot police clear a Paris square", "Reuters", 14, "politics"),
  },
  {
    headline:
      "A U.S. Military Airman Tragically Dies After Rappelling Accident at UTSA-Navy Game in San Antonio",
    place: "Alamodome, Texas, United States",
    lat: 29.5,
    lng: -98.5,
    outlets: 17,
    stories: 7,
    first_seen: ago(120),
    topic: "economy",
    lead: breakingLead("Airman dies after rappelling accident", "AP", 31, "economy"),
  },
  {
    headline: "Port strike halts container traffic in Rotterdam",
    place: "Rotterdam, Netherlands",
    lat: 51.5,
    lng: 4.5,
    outlets: 9,
    stories: 3,
    first_seen: ago(95),
    topic: "economy",
    lead: breakingLead("Port strike halts Rotterdam", "NOS", 40, "economy"),
  },
];

/** Whether a request is for the breaking stories. */
export const isBreaking = (url: URL) => url.pathname === "/api/news/breaking";

/**
 * gotoStillGlobe/settle setup: three stories are breaking (by default none
 * are), and the delta counts them, as the server's does.
 */
export async function withBreaking(page: Page) {
  await page.route(isBreaking, (route) => route.fulfill({ json: MOCK_BREAKING }));
  await page.route(isDelta, (route) =>
    route.fulfill({ json: { ...MOCK_DELTA, breaking: MOCK_BREAKING.length } }),
  );
}

/**
 * The ring meshes alive in the globe's scene now. WebGL objects aren't in the
 * DOM, so this finds the globe.gl instance through React's fiber for the
 * globe's container (a ref holding an object with ringsData) and counts the
 * children of three-globe's ring groups: one per ring on screen.
 */
export function ringCircles(page: Page): Promise<number> {
  return page.evaluate(() => {
    type Hook = { memoizedState: unknown; next: Hook | null };
    type Fiber = { memoizedState: Hook | null; return: Fiber | null };
    type Obj = { __globeObjType?: string; children: unknown[] };
    type GlobeLike = { ringsData: unknown; scene(): { traverse(f: (o: Obj) => void): void } };
    const el = document.querySelector('[data-testid="globe"]') as unknown as Record<string, Fiber>;
    const key = Object.keys(el).find((k) => k.startsWith("__reactFiber$"));
    let fiber: Fiber | null = key ? el[key] : null;
    let globe: GlobeLike | null = null;
    while (fiber && !globe) {
      for (let h = fiber.memoizedState; h && !globe; h = h.next) {
        const ref = h.memoizedState as { current?: GlobeLike } | null;
        if (ref && typeof ref === "object" && typeof ref.current?.ringsData === "function") {
          globe = ref.current;
        }
      }
      fiber = fiber.return;
    }
    if (!globe) throw new Error("no globe instance found");
    let n = 0;
    globe.scene().traverse((o) => {
      if (o.__globeObjType === "ring") n += o.children.length;
    });
    return n;
  });
}

/** `ringCircles` sampled `times` times, `everyMs` apart. */
export async function sampleRings(page: Page, times = 8, everyMs = 400): Promise<number[]> {
  const samples: number[] = [];
  for (let i = 0; i < times; i++) {
    samples.push(await ringCircles(page));
    await page.waitForTimeout(everyMs);
  }
  return samples;
}

// ── Since your last visit ───────────────────────────────────────────

/** /api/news/delta: what changed since the visit, with the top places. */
export const MOCK_DELTA = {
  new_stories: 1286,
  new_places: 212,
  breaking: 0, // as the default breaking mock: none (withBreaking makes it 3)
  top: [
    {
      lat: 48.8566,
      lng: 2.3522,
      place: "Paris, France",
      new: 64,
      lead: breakingLead("Riot police clear a Paris square", "Reuters", 14, "politics"),
    },
    {
      lat: 29.5,
      lng: -98.5,
      place: "Alamodome, Texas, United States",
      new: 31,
      lead: breakingLead("Airman dies after rappelling accident", "AP", 31, "economy"),
    },
    {
      lat: 51.5074,
      lng: -0.1278,
      place: "London, United Kingdom",
      new: 27,
      lead: breakingLead("UK parliament debates trade deal", "BBC News", 80, "politics"),
    },
  ],
};

/** Whether a request asks what changed since a visit. */
export const isDelta = (url: URL) => url.pathname === "/api/news/delta";

/** localStorage, as useLastVisit keeps it. */
export const LAST_VISIT_KEY = "orbis-last-visit";

/**
 * A last visit `hours` ago, seeded before each page load (as a returning
 * visitor's browser has it; the page writes its own visit on leaving).
 */
export async function seedLastVisit(page: Page, hours: number) {
  await page.addInitScript(
    ([key, h]) => localStorage.setItem(key, new Date(Date.now() - h * 3_600_000).toISOString()),
    [LAST_VISIT_KEY, hours] as const,
  );
}

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

  // The hover card's dwell data, and its lead images
  await page.route("**/api/news/preview*", (route) => route.fulfill({ json: MOCK_PREVIEW }));
  await page.route(`${IMAGE_HOST}/**`, (route) =>
    route.fulfill({ contentType: "image/svg+xml", body: mockImage(route.request().url()) }),
  );

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

  // The Links layer
  await mockLinkRoutes(page);

  // The Threads layer
  await mockThreadRoutes(page);

  // Breaking stories: none, as often (withBreaking adds some)
  await page.route(isBreaking, (route) => route.fulfill({ json: [] }));

  // What changed since a visit (asked only when seedLastVisit made one)
  await page.route(isDelta, (route) => route.fulfill({ json: MOCK_DELTA }));
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

/** A dot from MOCK_GLOBE_POINTS (or CAIRO). */
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

// ── Hovering and clicking an arc ────────────────────────────────────

type MockLink = (typeof MOCK_LINKS_LIFT)[number];

/**
 * Where the top of a link's arc is on screen while the globe rests at
 * HOME_VIEW: the midpoint of the curve three-globe draws from the link's
 * origin (lib/links arcApex).
 */
function arcTop(page: Page, link: MockLink) {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("arcs need a fixed viewport");
  const [start, end] = link.from === link.b.iso ? [link.b, link.a] : [link.a, link.b];
  const apex = arcApex(start, end);
  return homeViewScreenPoint(apex.lat, apex.lng, viewport, apex.altitude);
}

/**
 * Click the top of a link's arc, as a visitor would, until its inspector
 * opens. As with clickPlace, the pointer rests first (globe.gl finds the arc
 * under it on its next frame) and nearby pixels are tried: the arc is thin.
 */
export async function clickArc(page: Page, link: MockLink, heading: string) {
  const { x, y } = arcTop(page, link);
  const opened = page
    .getByTestId("link-inspector")
    .getByRole("heading", { name: heading, exact: true });
  for (const [dx, dy] of NEARBY) {
    await page.mouse.move(x + dx, y + dy);
    await page.waitForTimeout(150);
    await page.mouse.down();
    await page.mouse.up();
    const shown = await opened
      .waitFor({ state: "visible", timeout: 1000 })
      .then(() => true)
      .catch(() => false);
    if (shown) return;
  }
  throw new Error(
    `No arc for ${link.a.iso}-${link.b.iso} (around ${Math.round(x)}, ${Math.round(y)})`,
  );
}

/**
 * Rest the pointer on the top of a link's arc (lib/links arcApex, the curve
 * three-globe draws) until its pill shows. The arc is a thin tube, so nearby
 * pixels are tried too. Returns the pill.
 */
export async function hoverArc(page: Page, link: MockLink) {
  const { x, y } = arcTop(page, link);
  const pill = page.locator('[data-testid="arc-pill"][data-placed="true"]');
  for (const [dx, dy] of NEARBY) {
    await page.mouse.move(x + dx, y + dy);
    const shown = await pill
      .waitFor({ state: "visible", timeout: 1000 })
      .then(() => true)
      .catch(() => false);
    if (shown) return { pill, x, y };
  }
  throw new Error(
    `No arc pill for ${link.a.iso}-${link.b.iso} (around ${Math.round(x)}, ${Math.round(y)})`,
  );
}

// ── Hovering and tapping a dot ──────────────────────────────────────

/** Pixels around a dot's projected centre to try, nearest first: a dot is a few pixels wide. */
const NEARBY = [
  [0, 0],
  [0, -1],
  [0, 1],
  [-1, 0],
  [1, 0],
  [0, -2],
  [0, 2],
];

/** The hover card for a place, once GlobeHud has placed it. */
function placedCard(page: Page, place: MockPlace) {
  return page.locator(
    `[data-testid="hover-card"][data-placed="true"][aria-label^="${place.location_name}:"]`,
  );
}

/**
 * Rest the pointer on a dot, as a visitor would, until its hover card shows
 * (globe.gl finds the hovered dot on its next frame; the card follows 150 ms
 * later). Returns the card.
 */
export async function hoverPlace(page: Page, place: MockPlace) {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("hoverPlace needs a fixed viewport");
  const { x, y } = homeViewScreenPoint(place.lat, place.lng, viewport);
  const card = placedCard(page, place);
  for (const [dx, dy] of NEARBY) {
    await page.mouse.move(x + dx, y + dy);
    const shown = await card
      .waitFor({ state: "visible", timeout: 1000 })
      .then(() => true)
      .catch(() => false);
    if (shown) return card;
  }
  throw new Error(
    `No hover card for ${place.location_name} (around ${Math.round(x)}, ${Math.round(y)})`,
  );
}

/**
 * Tap a dot on a touch screen until its card shows. The finger rests a
 * moment, as a real tap does, so globe.gl finds the dot before it lifts.
 */
export async function tapPlace(page: Page, place: MockPlace) {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("tapPlace needs a fixed viewport");
  const { x, y } = homeViewScreenPoint(place.lat, place.lng, viewport);
  const card = placedCard(page, place);
  const cdp = await page.context().newCDPSession(page);
  for (const [dx, dy] of NEARBY) {
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ x: x + dx, y: y + dy }],
    });
    await page.waitForTimeout(120);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    const shown = await card
      .waitFor({ state: "visible", timeout: 1000 })
      .then(() => true)
      .catch(() => false);
    if (shown) return card;
  }
  throw new Error(
    `No tap card for ${place.location_name} (around ${Math.round(x)}, ${Math.round(y)})`,
  );
}
