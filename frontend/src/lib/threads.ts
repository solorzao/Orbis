/**
 * Story threads (/api/threads): the same developing story across outlets and
 * places. Their types, the two fetches, the spread's aurora arcs (first place
 * to each later one, in order of first report) and the rail's words.
 */
import { apiFetch, type ApiGlobeLead } from "@/lib/api";
import { mapApiTopic, mapLead } from "@/lib/clustering";
import type { GlobeArc } from "@/lib/links";
import type { LiveHours } from "@/lib/timeWindow";
import type { GlobeLead, Topic } from "@/types/news";

/** Threads asked for: the rail's first request, which the server warms (24 h, all topics, 20). */
export const THREADS_LIMIT = 20;
/** Rows the rail lists. */
export const THREADS_SHOWN = 10;
/** A thread's stories come 20 a page (/api/threads/{id}?offset=). */
export const THREAD_PAGE = 20;

/** The active thread's arcs (tokens.md "Connection arc"): stroke 0.55, a long slow dash. */
export const SPREAD_STROKE = 0.55;
export const SPREAD_DASH_LENGTH = 0.9;
export const SPREAD_DASH_GAP = 0.12;
/** A replay lights one place about every 600 ms. */
export const SPREAD_STEP_MS = 600;

// ── The API's shapes (backend app/models/threads.py) ────────────────

export interface ApiThreadPlace {
  lat: number;
  lng: number;
  place: string;
  country_code: string;
  /** The cell's first report. */
  first_seen: string;
  /** Distinct stories there. */
  n: number;
}

export interface ApiThread {
  id: number;
  /** The AI title, else the lead story's headline. */
  title: string;
  /** Null until summarised. */
  synopsis: string | null;
  status: "emerging" | "developing" | "fading";
  first_seen: string;
  last_seen: string;
  n_stories: number;
  n_sources: number;
  /** Distinct stories in the last 6 hours. */
  velocity: number;
  countries: string[];
  /** Up to 20, first report first. */
  places: ApiThreadPlace[];
  /** Its stories' dominant tag ("general" if none). */
  topic: string;
  lead: ApiGlobeLead | null;
}

export interface ApiThreadArticle {
  title: string;
  source_name: string;
  published_at: string;
  source_url: string;
  place: string;
}

export interface ApiThreadDetail extends ApiThread {
  entities: { name: string; n: number }[];
  /** Every place kept (up to 30), first report first. */
  spread: ApiThreadPlace[];
  timeline: { hour: string; n: number; tone: number | null }[];
  /** 20 stories a page, newest first. */
  articles: ApiThreadArticle[];
}

/** The thread a cluster article is part of (/api/news/cluster), when it would be listed. */
export interface ArticleThread {
  id: number;
  title: string;
  /** Its first three place names. */
  places: string[];
}

// ── The app's ───────────────────────────────────────────────────────

export type ThreadStatus = "Emerging" | "Developing" | "Fading";

export interface ThreadPlace {
  lat: number;
  lng: number;
  place: string;
  countryCode: string;
  firstSeen: string;
  n: number;
}

export interface Thread {
  id: number;
  title: string;
  synopsis: string | null;
  status: ThreadStatus;
  firstSeen: string;
  lastSeen: string;
  stories: number;
  outlets: number;
  velocity: number;
  countries: string[];
  places: ThreadPlace[];
  topic: Topic;
  lead: GlobeLead | null;
}

export interface ThreadArticle {
  title: string;
  sourceName: string;
  publishedAt: string;
  sourceUrl: string;
  place: string;
}

export interface ThreadDetail extends Thread {
  entities: { name: string; n: number }[];
  spread: ThreadPlace[];
  articles: ThreadArticle[];
}

const STATUS: Record<ApiThread["status"], ThreadStatus> = {
  emerging: "Emerging",
  developing: "Developing",
  fading: "Fading",
};

function toPlace(p: ApiThreadPlace): ThreadPlace {
  return {
    lat: p.lat,
    lng: p.lng,
    place: p.place,
    countryCode: p.country_code,
    firstSeen: p.first_seen,
    n: p.n,
  };
}

export function toThread(api: ApiThread): Thread {
  return {
    id: api.id,
    title: api.title,
    synopsis: api.synopsis,
    status: STATUS[api.status],
    firstSeen: api.first_seen,
    lastSeen: api.last_seen,
    stories: api.n_stories,
    outlets: api.n_sources,
    velocity: api.velocity,
    countries: api.countries,
    places: api.places.map(toPlace),
    topic: mapApiTopic(api.topic),
    lead: mapLead(api.lead) ?? null,
  };
}

export function toThreadArticles(api: readonly ApiThreadArticle[]): ThreadArticle[] {
  return api.map((a) => ({
    title: a.title,
    sourceName: a.source_name,
    publishedAt: a.published_at,
    sourceUrl: a.source_url,
    place: a.place,
  }));
}

export function toThreadDetail(api: ApiThreadDetail): ThreadDetail {
  return {
    ...toThread(api),
    entities: api.entities,
    spread: api.spread.map(toPlace),
    articles: toThreadArticles(api.articles),
  };
}

/** A live window's developing stories, fastest first. Only live windows have threads. */
export function fetchThreads({
  hours,
  topic,
  limit = THREADS_LIMIT,
  signal,
}: {
  hours: LiveHours;
  topic: Topic;
  limit?: number;
  signal?: AbortSignal;
}): Promise<ApiThread[]> {
  const params: Record<string, string> = { timespan: `${hours}h` };
  if (topic !== "All") params.topic = topic;
  params.limit = String(limit);
  return apiFetch<ApiThread[]>("/api/threads", params, signal);
}

/** One thread, with its stories from `offset` (20 a page). */
export function fetchThread({
  id,
  offset = 0,
  signal,
}: {
  id: number;
  offset?: number;
  signal?: AbortSignal;
}): Promise<ApiThreadDetail> {
  const params = offset > 0 ? { offset: String(offset) } : undefined;
  return apiFetch<ApiThreadDetail>(`/api/threads/${id}`, params, signal);
}

/** The aurora arcs' look, from tokens (a canvas can't use CSS variables). */
export interface SpreadColors {
  /** --aurora-start (faint), --aurora-mid, --aurora-end: a gradient along each arc. */
  aurora: string[];
  /** --dur-arc-flow, in ms */
  flowMs: number;
}

/**
 * A thread's spread as aurora arcs: from the first place it was reported to
 * each later place, in order of first report, flowing when motion allows.
 */
export function spreadArcs(
  thread: number,
  spread: readonly ThreadPlace[],
  { colors, flow }: { colors: SpreadColors; flow: boolean },
): GlobeArc[] {
  const [first, ...later] = spread;
  if (!first) return [];
  return later.map((p, i) => ({
    thread,
    key: `thread-${thread}-${i + 1}`,
    startLat: first.lat,
    startLng: first.lng,
    endLat: p.lat,
    endLng: p.lng,
    color: colors.aurora,
    stroke: SPREAD_STROKE,
    dashLength: flow ? SPREAD_DASH_LENGTH : 1,
    dashGap: flow ? SPREAD_DASH_GAP : 0,
    dashAnimateTime: flow ? colors.flowMs : 0,
  }));
}

/**
 * The arcs a replay has revealed with `lit` places lit (null: not replaying,
 * all of them): the arcs to each lit place after the first, the same objects,
 * so three-globe keeps the meshes it has drawn.
 */
export function revealedArcs(arcs: GlobeArc[], lit: number | null): GlobeArc[] {
  return lit === null ? arcs : arcs.slice(0, Math.max(0, lit - 1));
}

/** Whether the spread's `i`th place is lit (null: not replaying, all are). */
export function stopLit(i: number, lit: number | null): boolean {
  return lit === null || i < lit;
}

/**
 * What the rail says when it lists nothing: off or loading, nothing. A range
 * or a replay has no threads (they follow the live windows).
 */
export function threadsStatus({
  on,
  live,
  threads,
  loading,
  error,
}: {
  on: boolean;
  live: boolean;
  threads: readonly Thread[];
  loading: boolean;
  error: boolean;
}): string | null {
  if (!on) return null;
  if (!live) return "Threads follow the live windows: pick 1h, 6h, 24h or 7d";
  if (loading) return null;
  if (error) return "Threads unavailable right now";
  return threads.length === 0 ? "No developing stories in this window" : null;
}

/** A row's velocity bar: its velocity against the fastest listed, as a percentage. */
export function velocityShare(thread: Thread, threads: readonly Thread[]): number {
  const most = Math.max(0, ...threads.map((t) => t.velocity));
  return most > 0 ? Math.round((thread.velocity / most) * 100) : 0;
}

/**
 * The place panel's chip: "Part of: {title} (also in A and B)", leaving out
 * the panel's place. "and", not a comma: place names hold commas ("Suez, Egypt").
 */
export function partOfLabel(thread: ArticleThread, here: string | undefined): string {
  const others = thread.places.filter((p) => p !== here).slice(0, 2);
  return others.length > 0
    ? `Part of: ${thread.title} (also in ${others.join(" and ")})`
    : `Part of: ${thread.title}`;
}
