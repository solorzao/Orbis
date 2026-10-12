import { NewsArticle, GlobePoint, Topic } from "@/types/news";
import type { ApiGlobePoint } from "./api";

// Canvas colours can't be CSS variables, so these copy the Soft Orbit tokens
// (--topic-*, --sentiment-*); clustering.test.ts fails if they drift.
/** Each topic's dot colour; every topic but All also has a --topic-* token. */
export const TOPIC_COLORS: Record<Topic, string> = {
  All: "#c0c3e0",
  Politics: "#ab9dff",
  Conflict: "#ff8f9c",
  Technology: "#7db9ff",
  Climate: "#72ddb2",
  Economy: "#f4c97c",
  Health: "#f5a0d0",
};

const SENTIMENT_COLORS = {
  n3: "#f08a94",
  n2: "#e6a5aa",
  n1: "#cdb8c4",
  neutral: "#a9abc8",
  p1: "#acd4d2",
  p2: "#8bdcc9",
  p3: "#62dcbc",
} as const;

export function getTopicColor(topic: Topic): string {
  return TOPIC_COLORS[topic];
}

export function getPrimaryTopicColor(article: NewsArticle): string {
  const tag = article.topicTags[0] as Topic | undefined;
  if (tag && tag in TOPIC_COLORS) {
    return TOPIC_COLORS[tag];
  }
  return TOPIC_COLORS.All;
}

export type SentimentKey = keyof typeof SENTIMENT_COLORS;

/** Soft Orbit's diverging sentiment bin (tokens.md "Sentiment"), as in --sentiment-{key}. */
export function sentimentKey(score: number): SentimentKey {
  if (score <= -0.6) return "n3";
  if (score <= -0.3) return "n2";
  if (score <= -0.1) return "n1";
  if (score < 0.1) return "neutral";
  if (score < 0.3) return "p1";
  if (score < 0.6) return "p2";
  return "p3";
}

export function getSentimentColor(score: number): string {
  return SENTIMENT_COLORS[sentimentKey(score)];
}

export type SentimentBucket = "positive" | "neutral" | "negative";

/** The news panel's three sentiment filters, on the same bins: n1-n3, neutral, p1-p3. */
export function sentimentBucket(score: number): SentimentBucket {
  const key = sentimentKey(score);
  return key === "neutral" ? "neutral" : key.startsWith("p") ? "positive" : "negative";
}

/** A signed score as printed next to its colour (mockup fmtScore): "+0.60", "−0.42", "±0.00". */
export function formatScore(score: number): string {
  const rounded = Math.round(score * 100) / 100;
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "±";
  return sign + Math.abs(rounded).toFixed(2);
}

/**
 * Cluster articles by geographic proximity based on zoom level.
 * Higher altitude (zoomed out) = larger clustering radius.
 */
export function clusterArticles(articles: NewsArticle[], altitude: number): GlobePoint[] {
  // Clustering radius in degrees - increases as we zoom out
  const radius = Math.max(2, altitude * 8);

  const used = new Set<string>();
  const clusters: GlobePoint[] = [];

  for (const article of articles) {
    if (used.has(article.id)) continue;

    // Find all nearby articles not yet clustered
    const nearby = articles.filter((other) => {
      if (used.has(other.id)) return false;
      const dlat = article.latitude - other.latitude;
      const dlng = article.longitude - other.longitude;
      return Math.sqrt(dlat * dlat + dlng * dlng) <= radius;
    });

    // Mark them as used
    nearby.forEach((a) => used.add(a.id));

    // Compute centroid
    const lat = nearby.reduce((sum, a) => sum + a.latitude, 0) / nearby.length;
    const lng = nearby.reduce((sum, a) => sum + a.longitude, 0) / nearby.length;

    const isCluster = nearby.length > 1;
    const count = nearby.length;

    // Determine dominant topic for color
    const topicCounts: Record<string, number> = {};
    nearby.forEach((a) =>
      a.topicTags.forEach((t) => {
        topicCounts[t] = (topicCounts[t] || 0) + 1;
      }),
    );
    const dominantTopic = Object.entries(topicCounts).sort((a, b) => b[1] - a[1])[0]?.[0] as
      | Topic
      | undefined;
    const color = dominantTopic
      ? TOPIC_COLORS[dominantTopic] || TOPIC_COLORS.All
      : TOPIC_COLORS.All;

    clusters.push({
      id: isCluster ? `cluster-${lat.toFixed(2)}-${lng.toFixed(2)}` : article.id,
      lat,
      lng,
      size: Math.min(1.5, 0.4 + count * 0.15),
      color,
      articles: nearby,
      isCluster,
      count,
      topic: dominantTopic ?? "All",
    });
  }

  return clusters;
}

const API_TOPIC_MAP: Record<string, Topic> = {
  politics: "Politics",
  conflict: "Conflict",
  technology: "Technology",
  climate: "Climate",
  environment: "Climate",
  economy: "Economy",
  health: "Health",
};

function mapApiTopic(apiTopic: string): Topic {
  return API_TOPIC_MAP[apiTopic.toLowerCase()] ?? "All";
}

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
    topics: [...new Set((p.topics ?? []).map(mapApiTopic))],
  }));
}

/** Points with any story on *topic*; a point without `topics` matches on `topic`. */
export function filterPointsByTopic(points: GlobePoint[], topic: Topic): GlobePoint[] {
  if (topic === "All") return points;
  return points.filter((p) => (p.topics?.length ? p.topics : [p.topic]).includes(topic));
}
