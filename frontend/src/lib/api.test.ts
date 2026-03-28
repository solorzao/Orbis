import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchGlobeNews, fetchClusterArticles, fetchClusterSummary, fetchTopics } from "./api";

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  });
}

describe("fetchGlobeNews", () => {
  it("calls /api/news with default params", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews();
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news");
    expect(url.searchParams.get("timespan")).toBe("24h");
    expect(url.searchParams.get("limit")).toBe("500");
    expect(url.searchParams.has("topic")).toBe(false);
  });

  it("throws on non-OK response", async () => {
    mockFetch.mockReturnValue(jsonResponse(null, 500));
    await expect(fetchGlobeNews()).rejects.toThrow("API 500");
  });
});

describe("fetchClusterArticles", () => {
  it("calls /api/news/cluster with lat/lng", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchClusterArticles(40.7, -74.0);
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news/cluster");
    expect(url.searchParams.get("lat")).toBe("40.7");
    expect(url.searchParams.get("lng")).toBe("-74");
  });
});

describe("fetchClusterSummary", () => {
  it("calls /api/news/summary with lat/lng/radius", async () => {
    mockFetch.mockReturnValue(jsonResponse({ summary: "test" }));
    await fetchClusterSummary(51.5, -0.1, 3.0);
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news/summary");
    expect(url.searchParams.get("radius")).toBe("3");
  });
});

describe("fetchTopics", () => {
  it("calls /api/topics with no params", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchTopics();
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/topics");
    expect([...url.searchParams.keys()]).toHaveLength(0);
  });
});
