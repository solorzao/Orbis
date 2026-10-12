import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { DWELL_MS, clearPreviewCache, rememberBrief, useHoverPreview } from "./useHoverPreview";
import { fetchPlacePreview, type ApiPlacePreview } from "@/lib/api";
import type { TimeWindow } from "@/lib/timeWindow";
import type { GlobePoint, Topic } from "@/types/news";

vi.mock("@/lib/api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api")>()),
  fetchPlacePreview: vi.fn(),
}));
const mockFetch = vi.mocked(fetchPlacePreview);

const LIVE: TimeWindow = { kind: "live", hours: 24 };
const MONDAY: TimeWindow = {
  kind: "range",
  startTime: "2026-10-05T00:00:00.000Z",
  endTime: "2026-10-06T00:00:00.000Z",
};

function point(lat: number, lng: number): GlobePoint {
  return {
    id: `api-${lat}`,
    lat,
    lng,
    size: 1,
    color: "#ab9dff",
    articles: [],
    isCluster: true,
    count: 5,
    topic: "Politics",
  };
}
const PARIS = point(48.5, 2.5);
const LONDON = point(51.5, -0.5);

const preview = (n: number): ApiPlacePreview => ({
  spark: Array(24).fill(n),
  entities: [],
  brief: null,
});

/** A fetch the test settles by hand. */
function deferred() {
  let resolve!: (p: ApiPlacePreview) => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<ApiPlacePreview>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type Props = { p: GlobePoint | null; w: TimeWindow; t: Topic };
const render = (initial: Props) =>
  renderHook(({ p, w, t }: Props) => useHoverPreview(p, w, t), { initialProps: initial });

const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

beforeEach(() => {
  vi.useFakeTimers();
  mockFetch.mockReset();
  clearPreviewCache();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useHoverPreview", () => {
  it("fetches only once the pointer has dwelt on the dot", async () => {
    mockFetch.mockResolvedValue(preview(1));
    const { result } = render({ p: PARIS, w: LIVE, t: "All" });
    expect(result.current).toEqual({ preview: null, loading: true });

    await advance(DWELL_MS - 1);
    expect(mockFetch).not.toHaveBeenCalled();

    await advance(1);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const { signal, ...query } = mockFetch.mock.calls[0][0];
    expect(query).toEqual({ lat: 48.5, lng: 2.5, window: LIVE, topic: "All" });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(result.current).toEqual({ preview: preview(1), loading: false });
  });

  it("does nothing without a dot", async () => {
    const { result } = render({ p: null, w: LIVE, t: "All" });
    await advance(DWELL_MS * 2);
    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.current).toEqual({ preview: null, loading: false });
  });

  it("never asks when the hover moves on before the dwell", async () => {
    const { rerender } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS - 50);
    rerender({ p: null, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("aborts the request when the hover moves on, and ignores its late answer", async () => {
    const paris = deferred();
    mockFetch.mockReturnValueOnce(paris.promise).mockResolvedValueOnce(preview(2));
    const { result, rerender } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    const parisSignal = mockFetch.mock.calls[0][0].signal!;

    rerender({ p: LONDON, w: LIVE, t: "All" });
    expect(parisSignal.aborted).toBe(true);
    await act(async () => paris.resolve(preview(1)));
    expect(result.current).toEqual({ preview: null, loading: true });

    await advance(DWELL_MS);
    expect(result.current).toEqual({ preview: preview(2), loading: false });
  });

  it("keeps one answer per cell, window and topic for the session", async () => {
    mockFetch.mockResolvedValue(preview(1));
    const { result, rerender } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    rerender({ p: null, w: LIVE, t: "All" });

    // Back on Paris (a refreshed point for the same cell): at once, no request.
    rerender({ p: { ...PARIS, id: "api-7", count: 6 }, w: LIVE, t: "All" });
    expect(result.current).toEqual({ preview: preview(1), loading: false });
    await advance(DWELL_MS);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Another window or topic is another answer.
    rerender({ p: PARIS, w: MONDAY, t: "All" });
    expect(result.current.preview).toBeNull();
    await advance(DWELL_MS);
    rerender({ p: PARIS, w: LIVE, t: "Politics" });
    await advance(DWELL_MS);
    expect(mockFetch).toHaveBeenCalledTimes(3);
    expect(mockFetch.mock.calls.map((c) => [c[0].window, c[0].topic])).toEqual([
      [LIVE, "All"],
      [MONDAY, "All"],
      [LIVE, "Politics"],
    ]);
  });

  it("stops loading on an error, and asks again on the next hover", async () => {
    mockFetch.mockRejectedValueOnce(new Error("API 500")).mockResolvedValueOnce(preview(3));
    const { result, rerender } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    expect(result.current).toEqual({ preview: null, loading: false });

    rerender({ p: null, w: LIVE, t: "All" });
    rerender({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(result.current).toEqual({ preview: preview(3), loading: false });
  });
});

describe("rememberBrief", () => {
  it("adds the panel's summary to the place's cached preview", async () => {
    mockFetch.mockResolvedValue(preview(1));
    const { result, rerender } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    expect(result.current.preview?.brief).toBeNull();

    rememberBrief(PARIS, LIVE, "All", "Paris set new carbon targets.");
    rerender({ p: null, w: LIVE, t: "All" });
    rerender({ p: PARIS, w: LIVE, t: "All" });
    expect(result.current.preview?.brief).toBe("Paris set new carbon targets.");
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("fills in a preview fetched later without one (the server's copy may be older)", async () => {
    rememberBrief(PARIS, LIVE, "All", "Paris set new carbon targets.");
    mockFetch.mockResolvedValue(preview(1));
    const { result } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    expect(result.current.preview?.brief).toBe("Paris set new carbon targets.");
  });

  it("keeps to its own window and topic", async () => {
    rememberBrief(PARIS, LIVE, "Politics", "Only for politics.");
    mockFetch.mockResolvedValue(preview(1));
    const { result } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    expect(result.current.preview?.brief).toBeNull();
  });

  it.each([
    "",
    "  ",
    "Summary generation failed.",
    "AI summary unavailable (API key not configured).",
  ])("ignores a summary that isn't one: %j", async (text) => {
    rememberBrief(PARIS, LIVE, "All", text);
    mockFetch.mockResolvedValue(preview(1));
    const { result } = render({ p: PARIS, w: LIVE, t: "All" });
    await advance(DWELL_MS);
    expect(result.current.preview?.brief).toBeNull();
  });
});
