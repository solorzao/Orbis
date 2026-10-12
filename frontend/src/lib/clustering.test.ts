import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";
import {
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
      apiPoint({ topic: "environment", article_count: 2, topics: ["environment", "sport"] }),
      apiPoint({ topic: "sport" }),
    ]);
    expect(climate.topic).toBe("Climate");
    expect(climate.color).toBe(TOPIC_COLORS.Climate);
    expect(climate.count).toBe(2);
    expect(climate.size).toBeCloseTo(0.7);
    expect(other.topic).toBe("All");
    expect(other.color).toBe(TOPIC_COLORS.All);
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
