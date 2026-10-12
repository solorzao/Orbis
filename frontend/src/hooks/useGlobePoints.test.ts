import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useGlobePoints, FETCH_DEBOUNCE_MS } from "./useGlobePoints";
import { fetchGlobeNews, type ApiGlobePoint } from "@/lib/api";
import type { TimeWindow } from "@/lib/timeWindow";
import { TOPIC_COLORS } from "@/lib/clustering";
import type { Topic } from "@/types/news";

vi.mock("@/lib/api", () => ({ fetchGlobeNews: vi.fn() }));
const mockFetch = vi.mocked(fetchGlobeNews);

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
    const [timespan, limit, start, end, topic, signal] = mockFetch.mock.calls[0];
    expect([timespan, limit, start, end, topic]).toEqual(["6h", 500, undefined, undefined, "All"]);
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
    expect(mockFetch.mock.calls[0].slice(0, 4)).toEqual([
      "24h",
      500,
      MONDAY.startTime,
      MONDAY.endTime,
    ]);
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
    const mondaySignal = mockFetch.mock.calls[0][5] as AbortSignal;

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
    expect(mockFetch.mock.calls[0][2]).toBe(TUESDAY.startTime);
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

    expect(mockFetch.mock.calls[0][4]).toBe("Health");
    // No second filter on the client: what the server sent is what the globe shows.
    const [lima] = result.current.points;
    expect(result.current.points).toHaveLength(1);
    expect(lima.topic).toBe("Health");
    expect(lima.color).toBe(TOPIC_COLORS.Health);
    expect(lima.count).toBe(2);
  });

  it("refetches when the topic changes, keeping the last points until the new ones land", async () => {
    mockFetch.mockResolvedValueOnce([apiPoint("Paris", "economy"), apiPoint("Lima", "health")]);
    const { result, rerender } = renderHook(({ topic }) => useGlobePoints(LIVE_6H, topic), {
      initialProps: { topic: "All" as Topic },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });

    const politics = deferred();
    mockFetch.mockReturnValueOnce(politics.promise);
    rerender({ topic: "Politics" });
    expect(result.current.loading).toBe(true);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Paris", "Lima"]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(mockFetch.mock.calls[1].slice(0, 5)).toEqual([
      "6h",
      500,
      undefined,
      undefined,
      "Politics",
    ]);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Paris", "Lima"]);

    await act(async () => {
      politics.resolve([apiPoint("Quito", "politics")]);
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.points.map((p) => p.locationName)).toEqual(["Quito"]);
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
    const healthSignal = mockFetch.mock.calls[0][5] as AbortSignal;

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
