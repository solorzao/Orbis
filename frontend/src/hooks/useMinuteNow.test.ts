import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useMinuteNow } from "./useMinuteNow";

const T = Date.parse("2026-10-20T12:00:40Z");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(T);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useMinuteNow", () => {
  it("is now, to the minute", () => {
    const { result } = renderHook(() => useMinuteNow());
    expect(result.current).toBe(Date.parse("2026-10-20T12:00:00Z"));
  });

  it("moves on as the minutes pass", () => {
    const { result } = renderHook(() => useMinuteNow());
    act(() => {
      vi.setSystemTime(T + 60_000);
      vi.advanceTimersByTime(15_000);
    });
    expect(result.current).toBe(Date.parse("2026-10-20T12:01:00Z"));
  });
});
