import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";
import {
  apiArticlesToNewsArticles,
  apiPointsToGlobePoints,
  clusterArticles,
  getTopicColor,
  getSentimentColor,
  sentimentKey,
  sentimentBucket,
  formatScore,
  TOPIC_COLORS,
} from "./clustering";
import { mockArticles } from "./mockData";
import type { ApiGlobePoint } from "./api";
import type { Topic } from "@/types/news";

const apiPoint = (overrides: Partial<ApiGlobePoint> = {}): ApiGlobePoint => ({
  lat: 33.5,
  lng: 44.5,
  weight: 50,
  article_count: 5,
  top_headline: "Cup final tonight",
  topic: "sport",
  ...overrides,
});

describe("apiPointsToGlobePoints", () => {
  it("colours and sizes a dot by the server's topic and count", () => {
    // A topic-filtered cell: the server sends the topic's tag and its stories' count.
    const [climate, other] = apiPointsToGlobePoints([
      apiPoint({ topic: "environment", article_count: 2 }),
      apiPoint({ topic: "sport" }),
    ]);
    expect(climate.topic).toBe("Climate");
    expect(climate.color).toBe(TOPIC_COLORS.Climate);
    expect(climate.count).toBe(2);
    expect(climate.size).toBeCloseTo(0.7);
    expect(other.topic).toBe("All");
    expect(other.color).toBe(TOPIC_COLORS.All);
  });

  it("colours a dot by the server's topic, the cell's most common (not its newest story's)", () => {
    const [point] = apiPointsToGlobePoints([
      apiPoint({
        topic: "politics",
        topic_mix: { politics: 3, conflict: 2 },
        lead: {
          title: "Talks resume",
          source_name: "Reuters",
          published_at: "2026-10-12T09:45:00Z",
          image_url: null,
          topic: "conflict",
        },
      }),
    ]);
    expect(point.topic).toBe("Politics");
    expect(point.color).toBe(TOPIC_COLORS.Politics);
    expect(point.lead?.topic).toBe("Conflict");
  });

  it("maps the hover card's lead, topic mix, tone and country", () => {
    const [point] = apiPointsToGlobePoints([
      apiPoint({
        location_name: "Wellington, New Zealand",
        country_code: "NZ",
        lead: {
          title: "Talks resume",
          source_name: "Reuters",
          published_at: "2026-10-12T09:45:00Z",
          image_url: "https://cdn.example.com/a.jpg",
          topic: "environment",
          sensitive: false,
        },
        topic_mix: { politics: 3, environment: 2, climate: 1, sport: 4 },
        tone: -0.25,
      }),
    ]);
    expect(point.countryCode).toBe("NZ");
    expect(point.lead).toEqual({
      title: "Talks resume",
      sourceName: "Reuters",
      publishedAt: "2026-10-12T09:45:00Z",
      imageUrl: "https://cdn.example.com/a.jpg",
      topic: "Climate",
      sensitive: false,
    });
    // Tags become topic pills; only the six topics count.
    expect(point.topicMix).toEqual({ Politics: 3, Climate: 3 });
    expect(point.tone).toBe(-0.25);
  });

  it("marks a lead sensitive as the server says, else by its conflict topic", () => {
    const lead = {
      title: "Talks resume",
      source_name: "Reuters",
      published_at: "2026-10-12T09:45:00Z",
      image_url: null,
    };
    const [tagged, conflict, other] = apiPointsToGlobePoints([
      apiPoint({ lead: { ...lead, topic: "politics", sensitive: true } }),
      apiPoint({ lead: { ...lead, topic: "conflict" } }), // cached before `sensitive`
      apiPoint({ lead: { ...lead, topic: "politics" } }),
    ]);
    expect(tagged.lead?.sensitive).toBe(true);
    expect(conflict.lead?.sensitive).toBe(true);
    expect(other.lead?.sensitive).toBe(false);
  });

  it("leaves the hover fields empty for a point without them", () => {
    const [point] = apiPointsToGlobePoints([apiPoint()]);
    expect(point.lead).toBeUndefined();
    expect(point.topicMix).toEqual({});
    expect(point.tone).toBe(0);
    expect(point.countryCode).toBeUndefined();
  });
});

// The globe paints on a canvas, so it can't read CSS variables per frame;
// these tests keep its colours equal to the Soft Orbit tokens.
const TOKENS_CSS = readFileSync(path.resolve(__dirname, "../app/tokens.css"), "utf8");

function token(name: string): string {
  const match = TOKENS_CSS.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6});`));
  if (!match) throw new Error(`--${name} not found in tokens.css`);
  return match[1];
}

const TOPICS: Topic[] = [
  "All",
  "Politics",
  "Conflict",
  "Technology",
  "Climate",
  "Economy",
  "Health",
];

describe("getTopicColor", () => {
  it.each(TOPICS)("%s matches its --topic-* token", (topic) => {
    expect(getTopicColor(topic)).toBe(token(`topic-${topic.toLowerCase()}`));
  });

  it("colours API points with the token of their topic", () => {
    const [point] = apiPointsToGlobePoints([apiPoint({ topic: "economy" })]);
    expect(point.color).toBe(token("topic-economy"));
  });
});

describe("getSentimentColor", () => {
  // tokens.md binning: n3 <= -0.6 < n2 <= -0.3 < n1 <= -0.1 < neutral < 0.1 <= p1 < 0.3 <= p2 < 0.6 <= p3
  it.each([
    [-1, "n3"],
    [-0.6, "n3"],
    [-0.59, "n2"],
    [-0.3, "n2"],
    [-0.29, "n1"],
    [-0.1, "n1"],
    [-0.09, "neutral"],
    [0, "neutral"],
    [0.09, "neutral"],
    [0.1, "p1"],
    [0.29, "p1"],
    [0.3, "p2"],
    [0.59, "p2"],
    [0.6, "p3"],
    [1, "p3"],
  ])("%s is --sentiment-%s", (score, bin) => {
    expect(getSentimentColor(score)).toBe(token(`sentiment-${bin}`));
  });
});

describe("sentimentKey", () => {
  it.each([
    [-1, "n3"],
    [-0.6, "n3"],
    [-0.59, "n2"],
    [-0.3, "n2"],
    [-0.29, "n1"],
    [-0.1, "n1"],
    [-0.09, "neutral"],
    [0, "neutral"],
    [0.09, "neutral"],
    [0.1, "p1"],
    [0.29, "p1"],
    [0.3, "p2"],
    [0.59, "p2"],
    [0.6, "p3"],
    [1, "p3"],
  ])("%s is %s", (score, key) => {
    expect(sentimentKey(score)).toBe(key);
  });
});

describe("sentimentBucket", () => {
  // The panel's three filters split the tokens.md bins: n1-n3, neutral, p1-p3.
  it.each([
    [-0.8, "negative"],
    [-0.1, "negative"],
    [-0.09, "neutral"],
    [0, "neutral"],
    [0.09, "neutral"],
    [0.1, "positive"],
    [0.9, "positive"],
  ])("%s is %s", (score, bucket) => {
    expect(sentimentBucket(score)).toBe(bucket);
  });
});

describe("formatScore", () => {
  it.each([
    [0.6, "+0.60"],
    [-0.42, "−0.42"],
    [0, "±0.00"],
    [0.004, "±0.00"],
    [-0.004, "±0.00"],
    [1, "+1.00"],
  ])("%s prints as %s", (score, text) => {
    expect(formatScore(score)).toBe(text);
  });
});

describe("clusterArticles", () => {
  it("returns clusters from mock data", () => {
    const clusters = clusterArticles(mockArticles, 2.5);
    expect(clusters.length).toBeGreaterThan(0);
  });

  it("returns fewer clusters at higher altitude (zoomed out)", () => {
    const closeUp = clusterArticles(mockArticles, 0.5);
    const farOut = clusterArticles(mockArticles, 4.0);
    expect(farOut.length).toBeLessThanOrEqual(closeUp.length);
  });

  it("each cluster has required fields", () => {
    const clusters = clusterArticles(mockArticles, 2.0);
    for (const cluster of clusters) {
      expect(cluster).toHaveProperty("id");
      expect(cluster).toHaveProperty("lat");
      expect(cluster).toHaveProperty("lng");
      expect(cluster).toHaveProperty("articles");
      expect(cluster.articles.length).toBeGreaterThan(0);
    }
  });
});

describe("apiArticlesToNewsArticles", () => {
  const api = {
    id: "art-001",
    title: "France announces new climate policy",
    summary: null,
    source_url: "https://example.com/france-climate",
    source_name: "Reuters",
    source_language: "en",
    published_at: "2026-10-18T14:00:00Z",
    ingested_at: "2026-10-18T14:05:00Z",
    latitude: 48.86,
    longitude: 2.35,
    country_code: "FR",
    region: "Paris, France",
    topic_tags: ["Climate"],
    sentiment_score: 0.6,
    entities: {},
  };

  it("keeps the thread a cluster story is part of, or none", () => {
    const thread = { id: 15, title: "EU summit on energy prices", places: ["Brussels, Belgium"] };
    const [part, plain, older] = apiArticlesToNewsArticles([
      { ...api, thread },
      { ...api, id: "art-002", thread: null },
      { ...api, id: "art-003" }, // a server before threads sends none
    ]);
    expect(part.thread).toEqual(thread);
    expect(plain.thread).toBeNull();
    expect(older.thread).toBeNull();
  });
});
