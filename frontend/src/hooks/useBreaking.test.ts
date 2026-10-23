import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { BREAKING_REFRESH_MS, useBreaking } from "./useBreaking";
import { ApiError, fetchBreaking, type ApiBreakingStory } from "@/lib/api";
import type { Topic } from "@/types/news";

// The fetch mocked; ApiError and the 503 retry as they are.
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchBreaking: vi.fn(),
}));
const mockFetch = vi.mocked(fetchBreaking);

function story(headline: string): ApiBreakingStory {
  return {
    headline,
    place: "Paris, France",
    lat: 48.5,
    lng: 2.5,
    outlets: 12,
    stories: 4,
    first_seen: "2026-10-18T14:00:00Z",
    topic: "politics",
    lead: {
      title: headline,
      source_name: "AP",
      published_at: "2026-10-18T15:00:00Z",
      image_url: null,
      topic: "politics",
    },
  };
}

function deferred() {
  let resolve!: (v: ApiBreakingStory[]) => void;
  const promise = new Promise<ApiBreakingStory[]>((res) => (resolve = res));
  return { promise, resolve };
}

const headlines = (r: { current: { headline: string }[] }) => r.current.map((s) => s.headline);

interface Props {
  topic: Topic;
  on: boolean;
}
const render = (initialProps: Props) =>
  renderHook(({ topic, on }: Props) => useBreaking(topic, on), { initialProps });

beforeEach(() => {
  vi.useFakeTimers();
  mockFetch.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useBreaking", () => {
  it("fetches the breaking stories for the topic, and again every 5 minutes", async () => {
    mockFetch.mockResolvedValueOnce([story("Riots in Paris")]);
    const { result } = render({ topic: "All", on: true });
    await act(async () => {});
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const { signal, ...query } = mockFetch.mock.calls[0][0];
    expect(query).toEqual({ topic: "All" });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(headlines(result)).toEqual(["Riots in Paris"]);

    mockFetch.mockResolvedValueOnce([story("Riots in Paris"), story("Flood in Lagos")]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BREAKING_REFRESH_MS);
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(headlines(result)).toEqual(["Riots in Paris", "Flood in Lagos"]);
  });

  it("refetches on a new topic, and ignores the last topic's late answer", async () => {
    const all = deferred();
    const conflict = deferred();
    mockFetch.mockReturnValueOnce(all.promise).mockReturnValueOnce(conflict.promise);
    const { result, rerender } = render({ topic: "All", on: true });
    await act(async () => {});
    const firstSignal = mockFetch.mock.calls[0][0].signal!;

    rerender({ topic: "Conflict", on: true });
    expect(firstSignal.aborted).toBe(true);
    expect(mockFetch.mock.calls[1][0]).toMatchObject({ topic: "Conflict" });
    await act(async () => {
      conflict.resolve([story("Shelling resumes")]);
      all.resolve([story("Late, for All")]);
    });
    expect(headlines(result)).toEqual(["Shelling resumes"]);
  });

  it("fetches nothing and shows nothing for a window that isn't live (a range, a replay)", async () => {
    mockFetch.mockResolvedValue([story("Riots in Paris")]);
    const { result, rerender } = render({ topic: "All", on: true });
    await act(async () => {});
    expect(headlines(result)).toEqual(["Riots in Paris"]);

    rerender({ topic: "All", on: false });
    expect(result.current).toEqual([]);
    const calls = mockFetch.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BREAKING_REFRESH_MS * 2);
    });
    expect(mockFetch).toHaveBeenCalledTimes(calls); // no polling while off
  });

  it("stops polling and aborts on unmount", async () => {
    mockFetch.mockResolvedValue([]);
    const { unmount } = render({ topic: "All", on: true });
    await act(async () => {});
    const signal = mockFetch.mock.calls[0][0].signal!;
    unmount();
    expect(signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(BREAKING_REFRESH_MS * 2);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the last stories when a refresh fails", async () => {
    mockFetch.mockResolvedValueOnce([story("Riots in Paris")]);
    const { result } = render({ topic: "All", on: true });
    await act(async () => {});
    mockFetch.mockRejectedValueOnce(new Error("API 503"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BREAKING_REFRESH_MS);
    });
    expect(headlines(result)).toEqual(["Riots in Paris"]);
  });

  it("asks once more after a 503, after its Retry-After", async () => {
    mockFetch
      .mockRejectedValueOnce(new ApiError(503, "Service Unavailable", 15_000))
      .mockResolvedValueOnce([story("Riots in Paris")]);
    const { result } = render({ topic: "All", on: true });
    await act(async () => {});
    expect(result.current).toEqual([]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_999);
    });
    expect(mockFetch).toHaveBeenCalledTimes(1); // not a moment before its Retry-After
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(headlines(result)).toEqual(["Riots in Paris"]);
  });

  it("is empty when nothing is breaking", async () => {
    mockFetch.mockResolvedValueOnce([]);
    const { result } = render({ topic: "All", on: true });
    await act(async () => {});
    expect(result.current).toEqual([]);
  });

  it("never shows the last topic's stories under a new topic", async () => {
    const conflict = deferred();
    mockFetch
      .mockResolvedValueOnce([story("Riots in Paris")])
      .mockReturnValueOnce(conflict.promise);
    const { result, rerender } = render({ topic: "All", on: true });
    await act(async () => {});
    expect(headlines(result)).toEqual(["Riots in Paris"]);
    rerender({ topic: "Conflict", on: true });
    expect(result.current).toEqual([]); // not All's stories (or rings) meanwhile
    await act(async () => conflict.resolve([story("Shelling resumes")]));
    expect(headlines(result)).toEqual(["Shelling resumes"]);
  });

  it("doesn't poll while the page is hidden, and catches up when it shows", async () => {
    mockFetch.mockResolvedValue([story("Riots in Paris")]);
    render({ topic: "All", on: true });
    await act(async () => {});
    expect(mockFetch).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BREAKING_REFRESH_MS * 3);
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});
