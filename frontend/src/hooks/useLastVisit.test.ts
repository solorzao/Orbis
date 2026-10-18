import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  LAST_VISIT_KEY,
  LAST_VISIT_WRITE_MS,
  forgetLastVisitRead,
  useLastVisit,
} from "./useLastVisit";

const NOW = Date.UTC(2026, 9, 18, 16, 37, 21);
const H = 3_600_000;

function hide() {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(NOW);
  localStorage.clear();
  forgetLastVisitRead(); // a new page load
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

describe("useLastVisit", () => {
  it("reads the last visit stored, as a time", () => {
    localStorage.setItem(LAST_VISIT_KEY, new Date(NOW - 14 * H).toISOString());
    const { result } = renderHook(() => useLastVisit());
    expect(result.current).toBe(NOW - 14 * H);
  });

  it("is null on a first visit, for garbage, and when storage is blocked", () => {
    expect(renderHook(() => useLastVisit()).result.current).toBeNull();

    localStorage.setItem(LAST_VISIT_KEY, "yesterday-ish");
    forgetLastVisitRead();
    expect(renderHook(() => useLastVisit()).result.current).toBeNull();

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    forgetLastVisitRead();
    expect(renderHook(() => useLastVisit()).result.current).toBeNull();
  });

  it("writes now once a minute in, so a visit that crashes still counts", () => {
    renderHook(() => useLastVisit());
    expect(localStorage.getItem(LAST_VISIT_KEY)).toBeNull();
    act(() => void vi.advanceTimersByTime(LAST_VISIT_WRITE_MS));
    expect(LAST_VISIT_WRITE_MS).toBe(60_000);
    expect(localStorage.getItem(LAST_VISIT_KEY)).toBe(new Date(NOW + 60_000).toISOString());
  });

  it("writes now when the page is hidden or left", () => {
    renderHook(() => useLastVisit());
    hide();
    expect(localStorage.getItem(LAST_VISIT_KEY)).toBe(new Date(NOW).toISOString());

    vi.setSystemTime(NOW + 5000);
    window.dispatchEvent(new Event("pagehide"));
    expect(localStorage.getItem(LAST_VISIT_KEY)).toBe(new Date(NOW + 5000).toISOString());
  });

  it("keeps the visit it read: writing now doesn't change what the strip counts from", () => {
    localStorage.setItem(LAST_VISIT_KEY, new Date(NOW - 14 * H).toISOString());
    const { result, rerender } = renderHook(() => useLastVisit());
    hide();
    rerender();
    expect(result.current).toBe(NOW - 14 * H);
  });

  it("never throws when storage is blocked for writing", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderHook(() => useLastVisit());
    expect(() => hide()).not.toThrow();
    expect(() => act(() => void vi.advanceTimersByTime(LAST_VISIT_WRITE_MS))).not.toThrow();
  });

  it("stops writing once unmounted", () => {
    const { unmount } = renderHook(() => useLastVisit());
    unmount();
    hide();
    act(() => void vi.advanceTimersByTime(LAST_VISIT_WRITE_MS));
    expect(localStorage.getItem(LAST_VISIT_KEY)).toBeNull();
  });
});
