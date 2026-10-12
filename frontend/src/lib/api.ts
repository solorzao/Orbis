import type { Topic } from "@/types/news";

// Same-origin /api/* routes are proxied to the backend by
// src/app/api/[...path]/route.ts, which adds the API key server-side.
function apiUrl(path: string): URL {
  return new URL(path, window.location.origin);
}

export interface ApiGlobePoint {
  lat: number;
  lng: number;
  weight: number;
  article_count: number;
  top_headline: string;
  /** The newest story's topic, or the topic asked for: it sets the dot colour. */
  topic: string;
  location_name?: string;
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

/**
 * The globe's places for a window. A topic other than All is filtered on the
 * server, before it picks the busiest `limit` places: each place's count,
 * headline and topic are then that topic's stories alone.
 */
export function fetchGlobeNews(
  timespan = "24h",
  limit = 500,
  startTime?: string,
  endTime?: string,
  topic: Topic = "All",
  signal?: AbortSignal,
): Promise<ApiGlobePoint[]> {
  const params: Record<string, string> = { timespan, limit: String(limit) };
  if (startTime) params.start_time = startTime;
  if (endTime) params.end_time = endTime;
  if (topic !== "All") params.topic = topic;
  return apiFetch<ApiGlobePoint[]>("/api/news", params, signal);
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
