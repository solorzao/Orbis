import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchGlobeNews,
  fetchClusterArticles,
  fetchClusterSummary,
  fetchTopics,
  fetchVolume,
  fetchPlacePreview,
  fetchLinks,
  fetchBreaking,
  fetchDelta,
  fetchLinkDetail,
  explainLink,
  isExplainFallback,
  LINK_EXPLAIN_FAILED,
  isSummaryFallback,
  SUMMARY_FALLBACKS,
} from "./api";
import { readFileSync } from "fs";
import path from "path";

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
    await fetchGlobeNews({ timespan: "6h", signal: controller.signal });
    expect(mockFetch.mock.calls[0][1]).toEqual({ signal: controller.signal });
    expect(new URL(mockFetch.mock.calls[0][0]).searchParams.get("timespan")).toBe("6h");
  });
});

describe("fetchGlobeNews with a topic", () => {
  it("asks the server for the topic's places", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews({ timespan: "24h", topic: "Politics" });
    const params = new URL(mockFetch.mock.calls[0][0]).searchParams;
    expect(params.get("topic")).toBe("Politics");
    expect(params.get("timespan")).toBe("24h");
  });

  it("sends no topic for All", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews({ timespan: "24h", topic: "All" });
    expect(new URL(mockFetch.mock.calls[0][0]).searchParams.has("topic")).toBe(false);
  });
});

describe("fetchGlobeNews with a range", () => {
  it("sends the range's bounds and limit", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchGlobeNews({
      limit: 200,
      startTime: "2026-10-05T00:00:00.000Z",
      endTime: "2026-10-06T00:00:00.000Z",
    });
    const params = new URL(mockFetch.mock.calls[0][0]).searchParams;
    expect(params.get("start_time")).toBe("2026-10-05T00:00:00.000Z");
    expect(params.get("end_time")).toBe("2026-10-06T00:00:00.000Z");
    expect(params.get("limit")).toBe("200");
    expect(params.get("timespan")).toBe("24h");
  });
});

describe("fetchPlacePreview", () => {
  it("asks for a live window's preview by its timespan", async () => {
    const preview = { spark: Array(24).fill(0), entities: [], brief: null };
    mockFetch.mockReturnValue(jsonResponse(preview));
    const controller = new AbortController();

    await expect(
      fetchPlacePreview({
        lat: 48.5,
        lng: 2.5,
        window: { kind: "live", hours: 24 },
        topic: "All",
        signal: controller.signal,
      }),
    ).resolves.toEqual(preview);

    const [calledUrl, init] = mockFetch.mock.calls[0];
    const url = new URL(calledUrl);
    expect(url.pathname).toBe("/api/news/preview");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      lat: "48.5",
      lng: "2.5",
      timespan: "24h",
    });
    expect(init.signal).toBe(controller.signal);
  });

  it("sends a range's bounds and the topic", async () => {
    mockFetch.mockReturnValue(jsonResponse({ spark: [], entities: [], brief: null }));
    await fetchPlacePreview({
      lat: 48.5,
      lng: 2.5,
      window: {
        kind: "range",
        startTime: "2026-10-06T00:00:00.000Z",
        endTime: "2026-10-07T00:00:00.000Z",
      },
      topic: "Climate",
    });
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.searchParams.get("start_time")).toBe("2026-10-06T00:00:00.000Z");
    expect(url.searchParams.get("end_time")).toBe("2026-10-07T00:00:00.000Z");
    expect(url.searchParams.get("topic")).toBe("Climate");
  });
});

describe("fetchDelta", () => {
  it("asks what changed since a visit", async () => {
    mockFetch.mockReturnValue(
      jsonResponse({ new_stories: 0, new_places: 0, breaking: 0, top: [] }),
    );
    const controller = new AbortController();
    await fetchDelta({ since: "2026-10-18T02:30:00.000Z", signal: controller.signal });
    const [called, init] = mockFetch.mock.calls[0];
    const url = new URL(called);
    expect(url.pathname).toBe("/api/news/delta");
    expect(url.searchParams.get("since")).toBe("2026-10-18T02:30:00.000Z");
    expect(init.signal).toBe(controller.signal);
  });
});

describe("fetchBreaking", () => {
  it("asks for every topic's breaking stories, or one topic pill's", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchBreaking({ topic: "All" });
    let url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/news/breaking");
    expect([...url.searchParams.keys()]).toEqual([]);

    const controller = new AbortController();
    await fetchBreaking({ topic: "Conflict", signal: controller.signal });
    url = new URL(mockFetch.mock.calls[1][0]);
    expect(url.searchParams.get("topic")).toBe("Conflict");
    expect(mockFetch.mock.calls[1][1].signal).toBe(controller.signal);
  });
});

describe("fetchLinks", () => {
  it("asks for a live window's links by its timespan, rank and limit", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await fetchLinks({ window: { kind: "live", hours: 6 }, topic: "All", rank: "lift" });
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/links");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      timespan: "6h",
      rank: "lift",
      limit: "40",
    });
  });

  it("sends a range's bounds and the topic pill, and passes the signal on", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    const controller = new AbortController();
    await fetchLinks({
      window: {
        kind: "range",
        startTime: "2026-10-06T00:00:00.000Z",
        endTime: "2026-10-07T00:00:00.000Z",
      },
      topic: "Climate",
      rank: "count",
      limit: 20,
      signal: controller.signal,
    });
    const [called, init] = mockFetch.mock.calls[0];
    expect(Object.fromEntries(new URL(called).searchParams)).toEqual({
      start_time: "2026-10-06T00:00:00.000Z",
      end_time: "2026-10-07T00:00:00.000Z",
      topic: "Climate",
      rank: "count",
      limit: "20",
    });
    expect(init.signal).toBe(controller.signal);
  });
});

const LIVE_QUERY = {
  startTime: "2026-10-11T12:00:00.000Z",
  endTime: "2026-10-12T12:00:00.000Z",
  live: true,
  hours: 24 as const,
};
const RANGE_QUERY = {
  topic: "Climate" as const,
  startTime: "2026-10-06T00:00:00.000Z",
  endTime: "2026-10-07T00:00:00.000Z",
  live: false,
};

describe("fetchLinkDetail", () => {
  it("asks for a link opened on a live window by its timespan (one URL for everyone)", async () => {
    mockFetch.mockReturnValue(jsonResponse({}));
    await fetchLinkDetail({ a: "US", b: "IR", query: LIVE_QUERY });
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/links/detail");
    expect(Object.fromEntries(url.searchParams)).toEqual({ a: "US", b: "IR", timespan: "24h" });
  });

  it("asks for a range's link by its bounds and topic", async () => {
    mockFetch.mockReturnValue(jsonResponse({}));
    await fetchLinkDetail({ a: "IR", b: "US", query: RANGE_QUERY });
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      a: "IR",
      b: "US",
      start_time: RANGE_QUERY.startTime,
      end_time: RANGE_QUERY.endTime,
      topic: "Climate",
    });
  });
});

describe("explainLink", () => {
  it("posts the pair and the link's frozen window and topic", async () => {
    mockFetch.mockReturnValue(jsonResponse({ text: "Talks." }));
    await expect(explainLink({ a: "US", b: "IR", query: RANGE_QUERY })).resolves.toEqual({
      text: "Talks.",
    });
    const [called, init] = mockFetch.mock.calls[0];
    expect(new URL(called).pathname).toBe("/api/links/explain");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({
      a: "US",
      b: "IR",
      start_time: RANGE_QUERY.startTime,
      end_time: RANGE_QUERY.endTime,
      topic: "Climate",
    });
  });

  it("sends a live link's bounds as fixed when it was opened, without a topic for All", async () => {
    mockFetch.mockReturnValue(jsonResponse({ text: "Talks." }));
    await explainLink({ a: "US", b: "IR", query: LIVE_QUERY });
    expect(JSON.parse(mockFetch.mock.calls[0][1].body)).toEqual({
      a: "US",
      b: "IR",
      start_time: LIVE_QUERY.startTime,
      end_time: LIVE_QUERY.endTime,
    });
  });

  it("throws on a non-OK response (the ai rate limit's 429)", async () => {
    mockFetch.mockReturnValue(jsonResponse(null, 429));
    await expect(explainLink({ a: "US", b: "IR", query: LIVE_QUERY })).rejects.toThrow("API 429");
  });
});

describe("isExplainFallback", () => {
  it("knows the summary fallbacks and the not-enough-coverage message", () => {
    // links.py returns NOT_ENOUGH_COVERAGE as the text when no headline is left.
    const source = readFileSync(
      path.resolve(__dirname, "../../../backend/app/services/links.py"),
      "utf8",
    );
    const notEnough = /NOT_ENOUGH_COVERAGE = "([^"]+)"/.exec(source)?.[1];
    expect(notEnough).toBeTruthy();
    expect(isExplainFallback(notEnough!)).toBe(true);
    for (const message of SUMMARY_FALLBACKS) expect(isExplainFallback(message)).toBe(true);
    expect(isExplainFallback(LINK_EXPLAIN_FAILED)).toBe(true);
    expect(isExplainFallback("Coverage links the two over nuclear talks.")).toBe(false);
  });
});

describe("isSummaryFallback", () => {
  it("knows every message the backend sends instead of a summary", () => {
    // ai_summary.py raises SummaryUnavailable with the text the panel shows.
    const source = readFileSync(
      path.resolve(__dirname, "../../../backend/app/services/ai_summary.py"),
      "utf8",
    );
    const messages = [...source.matchAll(/SummaryUnavailable\(\s*"([^"]+)"/g)].map((m) => m[1]);
    expect(messages.length).toBeGreaterThanOrEqual(4);
    expect([...new Set(messages)].sort()).toEqual([...SUMMARY_FALLBACKS].sort());
  });

  it("tells a fallback from a summary", () => {
    expect(isSummaryFallback("Summary generation failed.")).toBe(true);
    expect(isSummaryFallback(" Summary generation failed. ")).toBe(true);
    expect(isSummaryFallback("Talks resumed in Cairo.")).toBe(false);
  });
});
