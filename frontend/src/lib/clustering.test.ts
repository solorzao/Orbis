import { describe, it, expect } from "vitest";
import { clusterArticles, getTopicColor, getSentimentColor } from "./clustering";
import { mockArticles } from "./mockData";
import type { Topic } from "@/types/news";

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
