import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchGlobeNews,
  fetchClusterArticles,
  fetchClusterSummary,
  fetchTopics,
  fetchVolume,
} from "./api";

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

  it("calls the same-origin proxy and never sends an API key", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews();
    const [calledUrl, init] = mockFetch.mock.calls[0];
    expect(new URL(calledUrl).origin).toBe(window.location.origin);
    expect(JSON.stringify(init ?? {})).not.toMatch(/x-api-key/i);
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

  it("sends the selected time window", async () => {
    mockFetch.mockReturnValue(jsonResponse({ summary: "test" }));
    await fetchClusterSummary(
      51.5,
      -0.1,
      0.75,
      undefined,
      undefined,
      "2026-03-07T10:00:00.000Z",
      "2026-03-08T10:00:00.000Z",
    );
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.searchParams.get("start_time")).toBe("2026-03-07T10:00:00.000Z");
    expect(url.searchParams.get("end_time")).toBe("2026-03-08T10:00:00.000Z");
  });

  it("omits the window when none is selected", async () => {
    mockFetch.mockReturnValue(jsonResponse({ summary: "test" }));
    await fetchClusterSummary(51.5, -0.1);
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.searchParams.has("start_time")).toBe(false);
    expect(url.searchParams.has("end_time")).toBe(false);
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

describe("fetchVolume", () => {
  it("asks /api/news/volume for the given days and returns the hours", async () => {
    const hours = [{ hour: "2026-10-11T14:00:00Z", count: 31 }];
    mockFetch.mockReturnValue(jsonResponse(hours));
    await expect(fetchVolume(7)).resolves.toEqual(hours);
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news/volume");
    expect(url.searchParams.get("days")).toBe("7");
  });

  it("passes an abort signal through to fetch", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    const controller = new AbortController();
    await fetchVolume(3, controller.signal);
    expect(mockFetch.mock.calls[0][1]).toEqual({ signal: controller.signal });
  });
});

describe("fetchGlobeNews with a signal", () => {
  it("passes the abort signal through to fetch", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    const controller = new AbortController();
    await fetchGlobeNews("6h", 500, undefined, undefined, "All", controller.signal);
    expect(mockFetch.mock.calls[0][1]).toEqual({ signal: controller.signal });
    expect(new URL(mockFetch.mock.calls[0][0]).searchParams.get("timespan")).toBe("6h");
  });
});

describe("fetchGlobeNews with a topic", () => {
  it("asks the server for the topic's places", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews("24h", 500, undefined, undefined, "Politics");
    const params = new URL(mockFetch.mock.calls[0][0]).searchParams;
    expect(params.get("topic")).toBe("Politics");
    expect(params.get("timespan")).toBe("24h");
  });

  it("sends no topic for All", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews("24h", 500, undefined, undefined, "All");
    expect(new URL(mockFetch.mock.calls[0][0]).searchParams.has("topic")).toBe(false);
  });
});
