import { describe, it, expect } from "vitest";
import {
  apiPointsToGlobePoints,
  clusterArticles,
  filterPointsByTopic,
  getTopicColor,
  getSentimentColor,
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
  it("maps every topic in the cell, keeping the newest story's topic", () => {
    const [point] = apiPointsToGlobePoints([
      apiPoint({ topic: "conflict", topics: ["conflict", "environment", "climate", "sport"] }),
    ]);
    expect(point.topic).toBe("Conflict");
    expect(point.topics).toEqual(expect.arrayContaining(["Conflict", "Climate"]));
    expect(point.topics?.filter((t) => t === "Climate")).toHaveLength(1);
  });
});

describe("filterPointsByTopic", () => {
  it("keeps a cell whose newest story is off-topic but which has on-topic stories", () => {
    const points = apiPointsToGlobePoints([apiPoint({ topics: ["conflict", "sport"] })]);
    expect(filterPointsByTopic(points, "Conflict")).toHaveLength(1);
    expect(filterPointsByTopic(points, "Health")).toHaveLength(0);
  });

  it("falls back to the point's topic when topics are absent or empty", () => {
    const points = apiPointsToGlobePoints([
      apiPoint({ topic: "conflict" }),
      apiPoint({ topic: "conflict", topics: [] }),
      apiPoint({ topic: "health" }),
    ]);
    expect(filterPointsByTopic(points, "Conflict")).toHaveLength(2);
  });

  it("keeps every point for All", () => {
    const points = apiPointsToGlobePoints([apiPoint(), apiPoint({ topic: "health" })]);
    expect(filterPointsByTopic(points, "All")).toHaveLength(2);
  });
});

describe("getTopicColor", () => {
  it("returns correct color for known topics", () => {
    expect(getTopicColor("Politics" as Topic)).toBeTruthy();
    expect(getTopicColor("Conflict" as Topic)).toBeTruthy();
    expect(getTopicColor("Technology" as Topic)).toBeTruthy();
    expect(getTopicColor("Climate" as Topic)).toBeTruthy();
  });

  it("returns a color for the All topic", () => {
    const color = getTopicColor("All" as Topic);
    expect(color).toBeTruthy();
  });
});

describe("getSentimentColor", () => {
  it("returns green-ish for positive sentiment", () => {
    const color = getSentimentColor(0.8);
    expect(color).toBeTruthy();
  });

  it("returns red-ish for negative sentiment", () => {
    const color = getSentimentColor(-0.8);
    expect(color).toBeTruthy();
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
