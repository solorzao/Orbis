import type { PanelQuery, Topic } from "@/types/news";
import { windowQuery, type TimeWindow } from "@/lib/timeWindow";
import { queryWindow } from "@/lib/panelQuery";
import { LINKS_LIMIT, type LinkRank } from "@/lib/links";

// Same-origin /api/* routes are proxied to the backend by
// src/app/api/[...path]/route.ts, which adds the API key server-side.
function apiUrl(path: string): URL {
  return new URL(path, window.location.origin);
}

/** A place's lead story: its newest, preferring one with an https image. */
export interface ApiGlobeLead {
  title: string;
  source_name: string;
  published_at: string;
  image_url: string | null;
  /** The story's first tag, e.g. "conflict" or "environment". */
  topic: string;
  /** Conflict is among its tags (not only the first). */
  sensitive?: boolean;
}

export interface ApiGlobePoint {
  lat: number;
  lng: number;
  weight: number;
  article_count: number;
  top_headline: string;
  /** The place's most common topic, or the topic asked for: it sets the dot colour. */
  topic: string;
  location_name?: string;
  country_code?: string;
  lead?: ApiGlobeLead | null;
  /** Tag -> stories with it, for the six topics' tags. */
  topic_mix?: Record<string, number>;
  /** Mean sentiment, -1 to 1. */
  tone?: number;
}

/** What the hover card adds after a dwell (/api/news/preview). */
export interface ApiPlacePreview {
  /** Stories per UTC hour over the 24 hours up to the window's end, oldest first. */
  spark: number[];
  /** Up to 3 names the place's stories mention most. */
  entities: { name: string; type: "person" | "org"; n: number }[];
  /** The AI summary a click on the place has cached, or null. */
  brief: string | null;
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
  image_url?: string | null;
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

async function apiFetch<T>(
  path: string,
  params?: Record<string, string>,
  signal?: AbortSignal,
): Promise<T> {
  const url = apiUrl(path);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString(), signal ? { signal } : undefined);
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export interface GlobeNewsQuery {
  /** A live window, e.g. "24h"; a range's bounds take its place on the server. */
  timespan?: string;
  /** Most places returned (the busiest). */
  limit?: number;
  /** A range's ISO bounds. */
  startTime?: string;
  endTime?: string;
  topic?: Topic;
  signal?: AbortSignal;
}

/**
 * The globe's places for a window. A topic other than All is filtered on the
 * server, before it picks the busiest `limit` places: each place's count,
 * headline and topic are then that topic's stories alone.
 */
export function fetchGlobeNews({
  timespan = "24h",
  limit = 500,
  startTime,
  endTime,
  topic = "All",
  signal,
}: GlobeNewsQuery = {}): Promise<ApiGlobePoint[]> {
  const params: Record<string, string> = { timespan, limit: String(limit) };
  if (startTime) params.start_time = startTime;
  if (endTime) params.end_time = endTime;
  if (topic !== "All") params.topic = topic;
  return apiFetch<ApiGlobePoint[]>("/api/news", params, signal);
}

/**
 * An event many outlets have just started covering (/api/news/breaking): its
 * most covered story's headline, its place (the 1° cell's centre, as the
 * cell's dot has it) and how many outlets and stories are on it.
 */
export interface ApiBreakingStory {
  headline: string;
  place: string;
  lat: number;
  lng: number;
  outlets: number;
  stories: number;
  /** The earliest story, clamped to the 2-hour window's start: not when it broke. */
  first_seen: string;
  /** The stories' most common topic tag ("general" if none); not always right. */
  topic: string;
  lead: ApiGlobeLead;
}

/**
 * What is breaking now, at most 8, most outlets first; for one topic pill, or
 * every topic. The server keeps one list for every topic and filters it.
 */
export function fetchBreaking({
  topic,
  signal,
}: {
  topic: Topic;
  signal?: AbortSignal;
}): Promise<ApiBreakingStory[]> {
  const params: Record<string, string> = {};
  if (topic !== "All") params.topic = topic;
  return apiFetch<ApiBreakingStory[]>("/api/news/breaking", params, signal);
}

export interface PlacePreviewQuery {
  lat: number;
  lng: number;
  window: TimeWindow;
  topic: Topic;
  signal?: AbortSignal;
}

/**
 * The hover card's dwell data for a dot's place: sparkline, names and the
 * cached AI brief, for the globe's window and topic. Live windows ask by
 * timespan, so every visitor's request for a place is the same URL (cached
 * at the edge).
 */
export function fetchPlacePreview({
  lat,
  lng,
  window,
  topic,
  signal,
}: PlacePreviewQuery): Promise<ApiPlacePreview> {
  const params: Record<string, string> = { lat: String(lat), lng: String(lng) };
  Object.assign(params, windowParams(window));
  if (topic !== "All") params.topic = topic;
  return apiFetch<ApiPlacePreview>("/api/news/preview", params, signal);
}

/**
 * A window as query params: a range's bounds, or a live window's timespan
 * (which the backend counts back from its own now, so every visitor's
 * request is the same URL, cached at the edge).
 */
function windowParams(window: TimeWindow): Record<string, string> {
  const { timespan, startTime, endTime } = windowQuery(window);
  if (startTime && endTime) return { start_time: startTime, end_time: endTime };
  return { timespan };
}

/** One end of a link (/api/links): a country and its label point. */
export interface ApiLinkCountry {
  iso: string;
  name: string;
  lat: number;
  lng: number;
}

/** Two countries the window's stories cover together. `a` < `b` by code. */
export interface ApiLink {
  a: ApiLinkCountry;
  b: ApiLinkCountry;
  n: number;
  lift: number;
  /** The stories' most common topic tag, or the filter's. */
  topic: string;
  tone: number;
  /** The end most of the stories come from. */
  from: string;
}

export interface LinksQuery {
  window: TimeWindow;
  topic: Topic;
  /** lift: surprisingly often together; count: most stories. */
  rank: LinkRank;
  /** Most links returned (1 to 60). */
  limit?: number;
  signal?: AbortSignal;
}

/** The co-coverage links for a window and topic, for the Links layer's arcs. */
export function fetchLinks({
  window,
  topic,
  rank,
  limit = LINKS_LIMIT,
  signal,
}: LinksQuery): Promise<ApiLink[]> {
  const params = windowParams(window);
  if (topic !== "All") params.topic = topic;
  params.rank = rank;
  params.limit = String(limit);
  return apiFetch<ApiLink[]>("/api/links", params, signal);
}

/** One link for the inspector (/api/links/detail): the pair always in code order. */
export interface ApiLinkDetail {
  a: ApiLinkCountry;
  b: ApiLinkCountry;
  n: number;
  lift: number;
  /** Stories per topic tag (a story may count twice). */
  topic_mix: Record<string, number>;
  tone: number;
  shared: { name: string; type: "person" | "org"; n: number }[];
  themes: string[];
  articles: ApiNewsArticle[];
}

export interface LinkQuery {
  a: string;
  b: string;
  /** The query the link was opened with (panelQuery). */
  query: PanelQuery;
}

/**
 * A link's numbers, shared names, themes and newest stories, for the window
 * and topic it was opened on: a live window by its timespan (as the arc was
 * fetched, and one URL for everyone at the edge), a range by its bounds.
 */
export function fetchLinkDetail({ a, b, query }: LinkQuery): Promise<ApiLinkDetail> {
  const params: Record<string, string> = { a, b, ...windowParams(queryWindow(query)) };
  if (query.topic) params.topic = query.topic;
  return apiFetch<ApiLinkDetail>("/api/links/detail", params);
}

/**
 * Claude's 2-3 sentences on what links two countries' coverage, for the
 * window the link was opened on (its bounds as fixed then) and its topic.
 * It may answer with a message instead (see isExplainFallback).
 */
export async function explainLink({ a, b, query }: LinkQuery): Promise<{ text: string }> {
  const res = await fetch(apiUrl("/api/links/explain").toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      a,
      b,
      start_time: query.startTime,
      end_time: query.endTime,
      ...(query.topic ? { topic: query.topic } : {}),
    }),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<{ text: string }>;
}

/** What the inspector shows when the explanation request itself fails. */
export const LINK_EXPLAIN_FAILED = "Couldn't explain this link right now. Try again in a moment.";

/** links.py NOT_ENOUGH_COVERAGE (api.test.ts keeps it equal). */
const NOT_ENOUGH_COVERAGE = "Not enough coverage in this window to explain the link.";

/** Whether an explanation's text is a message (paused, failed, too few stories), not Claude's. */
export function isExplainFallback(text: string): boolean {
  const t = text.trim();
  return isSummaryFallback(t) || t === NOT_ENOUGH_COVERAGE || t === LINK_EXPLAIN_FAILED;
}

export function fetchClusterArticles(
  lat: number,
  lng: number,
  radius = 0.75,
  topic?: string,
  locationName?: string,
  offset = 0,
  limit = 10,
  startTime?: string,
  endTime?: string,
  sentiment?: string,
  search?: string,
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
  if (startTime) params.start_time = startTime;
  if (endTime) params.end_time = endTime;
  if (sentiment) params.sentiment = sentiment;
  if (search) params.search = search;
  return apiFetch<ApiNewsArticle[]>("/api/news/cluster", params);
}

/**
 * What /api/news/summary sends as `summary` when Claude gave none: the
 * messages ai_summary.py raises SummaryUnavailable with (api.test.ts keeps
 * the two lists equal). The panel shows them; they are never a place's brief.
 */
export const SUMMARY_FALLBACKS: readonly string[] = [
  "AI summary unavailable (API key not configured).",
  "AI summaries are paused until 00:00 UTC (daily limit reached).",
  "Summary temporarily unavailable due to rate limits.",
  "Summary generation failed.",
];

export function isSummaryFallback(summary: string): boolean {
  return SUMMARY_FALLBACKS.includes(summary.trim());
}

export function fetchClusterSummary(
  lat: number,
  lng: number,
  radius = 0.75,
  locationName?: string,
  topic?: string,
  startTime?: string,
  endTime?: string,
): Promise<ApiClusterSummary> {
  const params: Record<string, string> = {
    lat: String(lat),
    lng: String(lng),
    radius: String(radius),
  };
  if (locationName) params.location_name = locationName;
  if (topic && topic !== "All") params.topic = topic;
  if (startTime) params.start_time = startTime;
  if (endTime) params.end_time = endTime;
  return apiFetch<ApiClusterSummary>("/api/news/summary", params);
}

/** Stories in one UTC hour; `hour` is its start, e.g. "2026-10-11T14:00:00Z". */
export interface ApiHourlyVolume {
  hour: string;
  count: number;
}

/** Stories per hour over the last `days` days (1-7), oldest first, zero hours included. */
export function fetchVolume(days = 7, signal?: AbortSignal): Promise<ApiHourlyVolume[]> {
  return apiFetch<ApiHourlyVolume[]>("/api/news/volume", { days: String(days) }, signal);
}

export function fetchTopics(): Promise<ApiTopicCount[]> {
  return apiFetch<ApiTopicCount[]>("/api/topics");
}

export interface ApiSelectionSummary {
  summary: string;
  article_count: number;
}

export async function fetchSelectionSummary(
  headlines: string[],
  locationName?: string,
): Promise<ApiSelectionSummary> {
  const url = apiUrl("/api/news/summarize-selection");
  const res = await fetch(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      headlines,
      ...(locationName ? { location_name: locationName } : {}),
    }),
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<ApiSelectionSummary>;
}
