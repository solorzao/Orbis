const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export interface ApiGlobePoint {
  lat: number;
  lng: number;
  weight: number;
  article_count: number;
  top_headline: string;
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
): Promise<ApiClusterSummary> {
  const params: Record<string, string> = {
    lat: String(lat),
    lng: String(lng),
    radius: String(radius),
  };
  if (locationName) params.location_name = locationName;
  if (topic && topic !== "All") params.topic = topic;
  return apiFetch<ApiClusterSummary>("/api/news/summary", params);
}

export interface ApiHourlyDensity {
  hour: number;
  count: number;
}

export function fetchDensity(): Promise<ApiHourlyDensity[]> {
  return apiFetch<ApiHourlyDensity[]>("/api/news/density");
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
  const url = new URL("/api/news/summarize-selection", API_BASE);
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
