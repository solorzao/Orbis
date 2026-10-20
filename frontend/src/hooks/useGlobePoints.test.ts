import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useGlobePoints, FETCH_DEBOUNCE_MS } from "./useGlobePoints";
import { fetchGlobeNews, type ApiGlobePoint } from "@/lib/api";
import type { TimeWindow } from "@/lib/timeWindow";
import { TOPIC_COLORS } from "@/lib/clustering";
import type { Topic } from "@/types/news";

vi.mock("@/lib/api", () => ({ fetchGlobeNews: vi.fn() }));
const mockFetch = vi.mocked(fetchGlobeNews);

/** What the hook's `n`th fetch asked for. */
function sent(n: number) {
  return mockFetch.mock.calls[n][0] ?? {};
}

function apiPoint(name: string, topic = "politics"): ApiGlobePoint {
  return {
    lat: 10,
    lng: 20,
    weight: 3,
    article_count: 3,
    top_headline: name,
    topic,
    location_name: name,
  };
}

/** A place with stories on several topics: its mix by article tag, its count their sum. */
function mixedPoint(name: string, topic: string, mix: Record<string, number>): ApiGlobePoint {
  const count = Object.values(mix).reduce((sum, n) => sum + n, 0);
  return { ...apiPoint(name, topic), article_count: count, weight: count, topic_mix: mix };
}

/** All's dots: Paris and New York cover several topics; Lagos has no mix (sent before it). */
const EVERY_TOPIC = [
  mixedPoint("Paris", "environment", { environment: 3, politics: 1, technology: 1 }),
  mixedPoint("New York", "economy", { economy: 6, technology: 2 }),
  mixedPoint("London", "politics", { politics: 3 }),
  { ...apiPoint("Lagos", "politics"), article_count: 2 },
];

/** A fetch the test settles by hand. */
function deferred() {
  let resolve!: (points: ApiGlobePoint[]) => void;
  let reject!: (err: Error) => void;
  const promise = new Promise<ApiGlobePoint[]>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const LIVE_6H: TimeWindow = { kind: "live", hours: 6 };
const MONDAY: TimeWindow = {
  kind: "range",
  startTime: "2026-10-05T00:00:00.000Z",
  endTime: "2026-10-06T00:00:00.000Z",
};
const TUESDAY: TimeWindow = {
  kind: "range",
  startTime: "2026-10-06T00:00:00.000Z",
  endTime: "2026-10-07T00:00:00.000Z",
};

beforeEach(() => {
  vi.useFakeTimers();
  mockFetch.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useGlobePoints", () => {
  it("fetches the window's points after a short debounce", async () => {
    mockFetch.mockResolvedValue([apiPoint("Paris")]);
    const { result } = renderHook(() => useGlobePoints(LIVE_6H));
    expect(result.current.loading).toBe(true);
    expect(mockFetch).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const { signal, ...query } = sent(0);
    expect(query).toEqual({ timespan: "6h", limit: 500, topic: "All" });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe(false);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Paris"]);
  });

  it("sends a range's bounds", async () => {
    mockFetch.mockResolvedValue([]);
    renderHook(() => useGlobePoints(MONDAY));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    expect(sent(0)).toMatchObject({
      timespan: "24h",
      limit: 500,
      startTime: MONDAY.startTime,
      endTime: MONDAY.endTime,
    });
  });

  it("keeps the last points while the next window loads", async () => {
    mockFetch.mockResolvedValueOnce([apiPoint("Paris")]);
    const { result, rerender } = renderHook(({ w }) => useGlobePoints(w), {
      initialProps: { w: MONDAY },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });

    const next = deferred();
    mockFetch.mockReturnValueOnce(next.promise);
    rerender({ w: TUESDAY });
    expect(result.current.loading).toBe(true);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Paris"]);
    expect(result.current.provisional).toBe(false); // the same topic: the last dots as they were

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
      next.resolve([apiPoint("Lima")]);
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Lima"]);
  });

  it("never shows a slower answer for a window that has moved on (no out-of-order frames)", async () => {
    const monday = deferred();
    const tuesday = deferred();
    mockFetch.mockReturnValueOnce(monday.promise).mockReturnValueOnce(tuesday.promise);
    const { result, rerender } = renderHook(({ w }) => useGlobePoints(w), {
      initialProps: { w: MONDAY },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    const mondaySignal = sent(0).signal!;

    rerender({ w: TUESDAY });
    expect(mondaySignal.aborted).toBe(true); // the earlier request is cancelled
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
      tuesday.resolve([apiPoint("Tuesday")]);
    });
    await act(async () => {
      monday.resolve([apiPoint("Monday")]); // arrives late anyway
    });

    expect(result.current.points.map((p) => p.locationName)).toEqual(["Tuesday"]);
    expect(result.current.loading).toBe(false);
  });

  it("skips a window replaced within the debounce", async () => {
    mockFetch.mockResolvedValue([]);
    const { rerender } = renderHook(({ w }) => useGlobePoints(w), {
      initialProps: { w: MONDAY },
    });
    rerender({ w: TUESDAY });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(sent(0).startTime).toBe(TUESDAY.startTime);
  });

  it("reports an error with no points", async () => {
    mockFetch.mockRejectedValue(new Error("API 500"));
    const { result } = renderHook(() => useGlobePoints(LIVE_6H));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    expect(result.current.error).toBe(true);
    expect(result.current.points).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("asks the server for the topic's places, coloured and sized as it counts them", async () => {
    mockFetch.mockResolvedValue([{ ...apiPoint("Lima", "health"), article_count: 2 }]);
    const { result } = renderHook(() => useGlobePoints(LIVE_6H, "Health"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });

    expect(sent(0).topic).toBe("Health");
    // No second filter on the client: what the server sent is what the globe shows.
    const [lima] = result.current.points;
    expect(result.current.points).toHaveLength(1);
    expect(lima.topic).toBe("Health");
    expect(lima.color).toBe(TOPIC_COLORS.Health);
    expect(lima.count).toBe(2);
  });

  it("refetches when the topic changes, showing the topic's dots on screen until its own land", async () => {
    mockFetch.mockResolvedValueOnce([
      apiPoint("Paris", "economy"),
      apiPoint("Lima", "health"),
      apiPoint("Quito", "politics"),
    ]);
    const { result, rerender } = renderHook(({ topic }) => useGlobePoints(LIVE_6H, topic), {
      initialProps: { topic: "All" as Topic },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    expect(result.current.provisional).toBe(false);

    const politics = deferred();
    mockFetch.mockReturnValueOnce(politics.promise);
    rerender({ topic: "Politics" });
    expect(result.current.loading).toBe(true);
    expect(result.current.provisional).toBe(true);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Quito"]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(sent(1)).toMatchObject({ timespan: "6h", topic: "Politics" });
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Quito"]);

    await act(async () => {
      politics.resolve([apiPoint("Quito", "politics"), apiPoint("Bogota", "politics")]);
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.provisional).toBe(false);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Quito", "Bogota"]);
  });

  it("filters the dots on screen to a new topic at once: its places, colour and counts", async () => {
    mockFetch.mockResolvedValueOnce(EVERY_TOPIC);
    const { result, rerender } = renderHook(({ topic }) => useGlobePoints(LIVE_6H, topic), {
      initialProps: { topic: "All" as Topic },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    const every = result.current.points;

    mockFetch.mockReturnValue(deferred().promise); // the server takes its time
    rerender({ topic: "Politics" });

    // At once: before the debounce, let alone the server's answer.
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const shown = result.current.points;
    // The places with Politics stories (Lagos has no mix, but is a Politics place),
    // each counted and sized by them, in the Politics colour.
    expect(shown.map((p) => [p.locationName, p.count])).toEqual([
      ["Paris", 1],
      ["London", 3],
      ["Lagos", 2],
    ]);
    for (const point of shown) {
      expect(point.topic).toBe("Politics");
      expect(point.color).toBe(TOPIC_COLORS.Politics);
      expect(point.size).toBeCloseTo(0.4 + point.count * 0.15);
      expect(point.isCluster).toBe(point.count > 1);
    }
    expect(shown[0].lead).toBe(every[0].lead); // the rest of the place as it was

    // Another topic before Politics lands: filtered from the loaded dots again.
    rerender({ topic: "Technology" });
    expect(result.current.points.map((p) => [p.locationName, p.count])).toEqual([
      ["Paris", 1],
      ["New York", 2],
    ]);
    expect(result.current.points.every((p) => p.color === TOPIC_COLORS.Technology)).toBe(true);
    // None of the dots on screen has Health stories: none until its own land.
    rerender({ topic: "Health" });
    expect(result.current.points).toEqual([]);
    expect(result.current.provisional).toBe(true);
  });

  it("keeps one provisional array while the topic loads", async () => {
    mockFetch.mockResolvedValueOnce(EVERY_TOPIC);
    const { result, rerender } = renderHook(({ topic }) => useGlobePoints(LIVE_6H, topic), {
      initialProps: { topic: "All" as Topic },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });

    mockFetch.mockReturnValue(deferred().promise);
    rerender({ topic: "Politics" });
    const shown = result.current.points;
    rerender({ topic: "Politics" }); // a re-render of the page: the globe must not redraw
    expect(result.current.points).toBe(shown);
  });

  it("going back to All shows the dots on screen as they are until All's land", async () => {
    mockFetch.mockResolvedValueOnce([apiPoint("Quito", "politics")]);
    const { result, rerender } = renderHook(({ topic }) => useGlobePoints(LIVE_6H, topic), {
      initialProps: { topic: "Politics" as Topic },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    const politics = result.current.points;

    const all = deferred();
    mockFetch.mockReturnValueOnce(all.promise);
    rerender({ topic: "All" });
    expect(result.current.points).toBe(politics); // unchanged: no redraw
    expect(result.current.provisional).toBe(true);
    expect(result.current.loading).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
      all.resolve(EVERY_TOPIC);
    });
    expect(result.current.provisional).toBe(false);
    expect(result.current.loading).toBe(false);
    expect(result.current.points.map((p) => p.locationName)).toEqual([
      "Paris",
      "New York",
      "London",
      "Lagos",
    ]);
  });

  it("never shows a slower answer for the topic before", async () => {
    const health = deferred();
    const politics = deferred();
    mockFetch.mockReturnValueOnce(health.promise).mockReturnValueOnce(politics.promise);
    const { result, rerender } = renderHook(({ topic }) => useGlobePoints(LIVE_6H, topic), {
      initialProps: { topic: "Health" as Topic },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    const healthSignal = sent(0).signal!;

    rerender({ topic: "Politics" });
    expect(healthSignal.aborted).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
      politics.resolve([apiPoint("Quito", "politics")]);
    });
    await act(async () => {
      health.resolve([apiPoint("Lima", "health")]); // arrives late anyway
    });

    expect(result.current.points.map((p) => p.locationName)).toEqual(["Quito"]);
    expect(result.current.loading).toBe(false);
  });

  it("keeps the same array, and fetches nothing, while the window and topic stay", async () => {
    mockFetch.mockResolvedValue([apiPoint("Lima", "health")]);
    const { result, rerender } = renderHook(({ topic }) => useGlobePoints(LIVE_6H, topic), {
      initialProps: { topic: "Health" as Topic },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    const health = result.current.points;

    // A re-render of the page (a co-pilot chunk, a panel change) must not hand
    // the globe a new array: that would redraw the dots and recompute Intensity.
    rerender({ topic: "Health" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    expect(result.current.points).toBe(health);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
