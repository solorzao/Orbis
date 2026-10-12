import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useLinks } from "./useLinks";
import { FETCH_DEBOUNCE_MS } from "./useGlobePoints";
import { fetchLinks, type ApiLink } from "@/lib/api";
import type { LinkRank } from "@/lib/links";
import type { TimeWindow } from "@/lib/timeWindow";
import type { Topic } from "@/types/news";

vi.mock("@/lib/api", () => ({ fetchLinks: vi.fn() }));
const mockFetch = vi.mocked(fetchLinks);

const US = { iso: "US", name: "United States", lat: 39.8, lng: -98.6 };
const IR = { iso: "IR", name: "Iran", lat: 32.4, lng: 53.7 };

function apiLink(n: number): ApiLink {
  return { a: IR, b: US, n, lift: 1.8, topic: "politics", tone: 0, from: "US" };
}

function deferred() {
  let resolve!: (links: ApiLink[]) => void;
  let reject!: (err: Error) => void;
  const promise = new Promise<ApiLink[]>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const LIVE_24H: TimeWindow = { kind: "live", hours: 24 };
const MONDAY: TimeWindow = {
  kind: "range",
  startTime: "2026-10-05T00:00:00.000Z",
  endTime: "2026-10-06T00:00:00.000Z",
};

interface Props {
  w: TimeWindow;
  topic: Topic;
  rank: LinkRank;
  on: boolean;
}

const render = (initialProps: Props) =>
  renderHook(({ w, topic, rank, on }: Props) => useLinks(w, topic, rank, on), { initialProps });

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
  });

beforeEach(() => {
  vi.useFakeTimers();
  mockFetch.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useLinks", () => {
  it("fetches nothing while the Links layer is off", async () => {
    const { result } = render({ w: LIVE_24H, topic: "All", rank: "lift", on: false });
    await settle();
    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.current).toEqual({ links: [], loading: false, error: false });
  });

  it("fetches the window's links, by rank and topic, once Links is on", async () => {
    mockFetch.mockResolvedValue([apiLink(41)]);
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", rank: "lift", on: false });
    rerender({ w: LIVE_24H, topic: "Politics", rank: "lift", on: true });
    expect(result.current.loading).toBe(true);
    await settle();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const { signal, ...query } = mockFetch.mock.calls[0][0];
    expect(query).toEqual({ window: LIVE_24H, topic: "Politics", rank: "lift", limit: 40 });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(result.current.loading).toBe(false);
    expect(result.current.links.map((l) => [l.n, l.topic])).toEqual([[41, "Politics"]]);
  });

  it("refetches when the rank switches, keeping the last arcs until the new ones land", async () => {
    mockFetch.mockResolvedValueOnce([apiLink(41)]);
    const { result, rerender } = render({ w: MONDAY, topic: "All", rank: "lift", on: true });
    await settle();

    const next = deferred();
    mockFetch.mockReturnValueOnce(next.promise);
    rerender({ w: MONDAY, topic: "All", rank: "count", on: true });
    expect(result.current.loading).toBe(true);
    expect(result.current.links.map((l) => l.n)).toEqual([41]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
      next.resolve([apiLink(90)]);
    });
    expect(mockFetch.mock.calls[1][0]).toMatchObject({ window: MONDAY, rank: "count" });
    expect(result.current.loading).toBe(false);
    expect(result.current.links.map((l) => l.n)).toEqual([90]);
  });

  it("cancels the last request and ignores its late answer", async () => {
    const lift = deferred();
    const count = deferred();
    mockFetch.mockReturnValueOnce(lift.promise).mockReturnValueOnce(count.promise);
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", rank: "lift", on: true });
    await settle();
    const firstSignal = mockFetch.mock.calls[0][0].signal!;

    rerender({ w: LIVE_24H, topic: "All", rank: "count", on: true });
    expect(firstSignal.aborted).toBe(true);
    await settle();
    await act(async () => {
      count.resolve([apiLink(90)]);
      lift.resolve([apiLink(41)]); // late: ignored
    });
    expect(result.current.links.map((l) => l.n)).toEqual([90]);
  });

  it("shows no arcs once Links is off, and a failed load as an error", async () => {
    mockFetch.mockRejectedValueOnce(new Error("API 500"));
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", rank: "lift", on: true });
    await settle();
    expect(result.current).toEqual({ links: [], loading: false, error: true });

    mockFetch.mockResolvedValueOnce([apiLink(41)]);
    rerender({ w: LIVE_24H, topic: "All", rank: "count", on: true });
    await settle();
    expect(result.current.links).toHaveLength(1);

    rerender({ w: LIVE_24H, topic: "All", rank: "count", on: false });
    expect(result.current).toEqual({ links: [], loading: false, error: false });
  });

  it("forgets a failed load when Links turns off, so turning it on again starts afresh", async () => {
    mockFetch.mockRejectedValueOnce(new Error("API 500"));
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", rank: "lift", on: true });
    await settle();
    expect(result.current.error).toBe(true);

    rerender({ w: LIVE_24H, topic: "All", rank: "lift", on: false });
    const next = deferred();
    mockFetch.mockReturnValueOnce(next.promise);
    rerender({ w: LIVE_24H, topic: "All", rank: "lift", on: true });
    // Not the old error (it would be announced): loading, until the refetch lands.
    expect(result.current).toEqual({ links: [], loading: true, error: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
      next.resolve([apiLink(41)]);
    });
    expect(result.current).toMatchObject({ loading: false, error: false });
    expect(result.current.links).toHaveLength(1);
  });
});
