import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useThread, useThreads } from "./useThreads";
import { FETCH_DEBOUNCE_MS } from "./useGlobePoints";
import { fetchThread, fetchThreads, type ApiThread, type ApiThreadDetail } from "@/lib/threads";
import type { TimeWindow } from "@/lib/timeWindow";
import type { Topic } from "@/types/news";

vi.mock("@/lib/threads", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/threads")>()),
  fetchThreads: vi.fn(),
  fetchThread: vi.fn(),
}));
const mockList = vi.mocked(fetchThreads);
const mockOne = vi.mocked(fetchThread);

function apiThread(id: number, title = `Thread ${id}`): ApiThread {
  return {
    id,
    title,
    synopsis: null,
    status: "developing",
    first_seen: "2026-10-18T06:10:00Z",
    last_seen: "2026-10-18T15:00:00Z",
    n_stories: 14,
    n_sources: 9,
    velocity: 4,
    countries: ["YE", "EG"],
    places: [],
    topic: "conflict",
    lead: null,
  };
}

function apiDetail(id: number): ApiThreadDetail {
  return { ...apiThread(id), entities: [], spread: [], timeline: [], articles: [] };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (err: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const LIVE_24H: TimeWindow = { kind: "live", hours: 24 };
const LIVE_6H: TimeWindow = { kind: "live", hours: 6 };
const MONDAY: TimeWindow = {
  kind: "range",
  startTime: "2026-10-05T00:00:00.000Z",
  endTime: "2026-10-06T00:00:00.000Z",
};

interface Props {
  w: TimeWindow;
  topic: Topic;
  on: boolean;
}
const render = (initialProps: Props) =>
  renderHook(({ w, topic, on }: Props) => useThreads(w, topic, on), { initialProps });

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(FETCH_DEBOUNCE_MS);
  });

const titles = (r: { current: { threads: { title: string }[] } }) =>
  r.current.threads.map((t) => t.title);

beforeEach(() => {
  vi.useFakeTimers();
  mockList.mockReset();
  mockOne.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useThreads", () => {
  it("fetches nothing while the Threads layer is off", async () => {
    const { result } = render({ w: LIVE_24H, topic: "All", on: false });
    await settle();
    expect(mockList).not.toHaveBeenCalled();
    expect(result.current).toEqual({ threads: [], loading: false, error: false });
  });

  it("fetches a live window's threads by topic once Threads is on", async () => {
    mockList.mockResolvedValue([apiThread(1, "Red Sea shipping")]);
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", on: false });
    rerender({ w: LIVE_24H, topic: "Conflict", on: true });
    expect(result.current.loading).toBe(true);
    await settle();
    expect(mockList).toHaveBeenCalledTimes(1);
    const { signal, ...query } = mockList.mock.calls[0][0];
    expect(query).toEqual({ hours: 24, topic: "Conflict" });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(result.current.loading).toBe(false);
    expect(titles(result)).toEqual(["Red Sea shipping"]);
  });

  it("has none for a range (threads follow the live windows), and fetches none", async () => {
    const { result } = render({ w: MONDAY, topic: "All", on: true });
    await settle();
    expect(mockList).not.toHaveBeenCalled();
    expect(result.current).toEqual({ threads: [], loading: false, error: false });
  });

  it("refetches on a new window or topic, keeping the last threads while it loads", async () => {
    const next = deferred<ApiThread[]>();
    mockList.mockResolvedValueOnce([apiThread(1, "First")]).mockReturnValueOnce(next.promise);
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", on: true });
    await settle();
    rerender({ w: LIVE_6H, topic: "All", on: true });
    await settle();
    expect(mockList.mock.calls[1][0]).toMatchObject({ hours: 6 });
    expect(result.current.loading).toBe(true);
    expect(titles(result)).toEqual(["First"]);
    await act(async () => next.resolve([apiThread(2, "Second")]));
    expect(titles(result)).toEqual(["Second"]);
  });

  it("aborts a superseded request and ignores its late answer", async () => {
    const slow = deferred<ApiThread[]>();
    mockList.mockReturnValueOnce(slow.promise).mockResolvedValueOnce([apiThread(2, "Politics")]);
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", on: true });
    await settle();
    const firstSignal = mockList.mock.calls[0][0].signal!;
    rerender({ w: LIVE_24H, topic: "Politics", on: true });
    expect(firstSignal.aborted).toBe(true);
    await settle();
    await act(async () => slow.resolve([apiThread(1, "Late")]));
    expect(titles(result)).toEqual(["Politics"]);
  });

  it("reports an error, and forgets it once turned off", async () => {
    mockList.mockRejectedValue(new Error("API 500"));
    const { result, rerender } = render({ w: LIVE_24H, topic: "All", on: true });
    await settle();
    expect(result.current).toEqual({ threads: [], loading: false, error: true });
    rerender({ w: LIVE_24H, topic: "All", on: false });
    rerender({ w: LIVE_24H, topic: "All", on: true });
    expect(result.current.error).toBe(false);
    expect(result.current.loading).toBe(true);
  });
});

describe("useThread", () => {
  const renderOne = (id: number | null) =>
    renderHook(({ id }: { id: number | null }) => useThread(id), { initialProps: { id } });

  it("fetches nothing without a thread", async () => {
    const { result } = renderOne(null);
    await act(async () => {});
    expect(mockOne).not.toHaveBeenCalled();
    expect(result.current).toEqual({ detail: null, loading: false, error: false });
  });

  it("fetches the selected thread's detail", async () => {
    mockOne.mockResolvedValue(apiDetail(7));
    const { result } = renderOne(7);
    expect(result.current.loading).toBe(true);
    await act(async () => {});
    expect(mockOne.mock.calls[0][0]).toMatchObject({ id: 7 });
    expect(result.current.loading).toBe(false);
    expect(result.current.detail?.id).toBe(7);
  });

  it("never shows the last thread's detail for a new one, and ignores its late answer", async () => {
    const slow = deferred<ApiThreadDetail>();
    mockOne.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(apiDetail(8));
    const { result, rerender } = renderOne(7);
    await act(async () => {});
    rerender({ id: 8 });
    expect(mockOne.mock.calls[0][0].signal!.aborted).toBe(true);
    await act(async () => {});
    await act(async () => slow.resolve(apiDetail(7)));
    expect(result.current.detail?.id).toBe(8);
    rerender({ id: null });
    expect(result.current.detail).toBeNull();
  });

  it("adopts the thread a merged id now answers as", async () => {
    // Thread 7 was merged into 9: the API answers with 9, the thread to select.
    mockOne.mockResolvedValue(apiDetail(9));
    const onMerged = vi.fn();
    const { result } = renderHook(() => useThread(7, onMerged));
    await act(async () => {});
    expect(onMerged).toHaveBeenCalledTimes(1);
    expect(onMerged).toHaveBeenCalledWith(9);
    expect(result.current.detail?.id).toBe(9);
  });

  it("calls back only when the id changed", async () => {
    mockOne.mockResolvedValue(apiDetail(7));
    const onMerged = vi.fn();
    renderHook(() => useThread(7, onMerged));
    await act(async () => {});
    expect(onMerged).not.toHaveBeenCalled();
  });

  it("reports a thread that couldn't load", async () => {
    mockOne.mockRejectedValue(new Error("API 404"));
    const { result } = renderOne(99);
    await act(async () => {});
    expect(result.current).toEqual({ detail: null, loading: false, error: true });
  });
});
