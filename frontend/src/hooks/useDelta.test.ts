import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useDelta } from "./useDelta";
import { fetchDelta, type ApiDelta } from "@/lib/api";

vi.mock("@/lib/api", () => ({ fetchDelta: vi.fn() }));
const mockFetch = vi.mocked(fetchDelta);

const NOW = Date.UTC(2026, 9, 18, 16, 37, 21);
const H = 3_600_000;

const DELTA: ApiDelta = {
  new_stories: 1286,
  new_places: 212,
  breaking: 4,
  top: [
    {
      lat: 48.5,
      lng: 2.5,
      place: "Paris, France",
      new: 64,
      lead: {
        title: "Riot police clear a Paris square",
        source_name: "Reuters",
        published_at: "2026-10-18T15:00:00Z",
        image_url: null,
        topic: "politics",
      },
    },
  ],
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  mockFetch.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useDelta", () => {
  it("asks once what changed since the visit, floored as the server floors it", async () => {
    mockFetch.mockResolvedValue(DELTA);
    const { result } = renderHook(() => useDelta(NOW - 14 * H - 7 * 60_000));
    await act(async () => {});
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const { signal, ...query } = mockFetch.mock.calls[0][0];
    // 14 h 7 min ago is 02:30:21; within a day it floors to the quarter hour.
    expect(query).toEqual({ since: "2026-10-18T02:30:00.000Z" });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(result.current).toEqual({
      at: NOW,
      newStories: 1286,
      newPlaces: 212,
      breaking: 4,
      top: [
        {
          lat: 48.5,
          lng: 2.5,
          place: "Paris, France",
          new: 64,
          headline: "Riot police clear a Paris square",
        },
      ],
    });
  });

  it("asks nothing on a first visit or a visit under an hour ago", async () => {
    renderHook(() => useDelta(null));
    renderHook(() => useDelta(NOW - 30 * 60_000));
    renderHook(() => useDelta(NOW - 8 * 24 * H));
    await act(async () => {});
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("shows nothing when the request fails", async () => {
    mockFetch.mockRejectedValue(new Error("API 503"));
    const { result } = renderHook(() => useDelta(NOW - 14 * H));
    await act(async () => {});
    expect(result.current).toBeNull();
  });

  it("aborts on unmount", async () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    const { unmount } = renderHook(() => useDelta(NOW - 14 * H));
    const signal = mockFetch.mock.calls[0][0].signal!;
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
