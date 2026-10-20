import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useSpreadReplay } from "./useSpreadReplay";
import { SPREAD_STEP_MS } from "@/lib/threads";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

const render = (stops: number, reduced = false) =>
  renderHook(({ stops, reduced }) => useSpreadReplay(stops, reduced), {
    initialProps: { stops, reduced },
  });

describe("useSpreadReplay", () => {
  it("lights nothing in particular until it plays: every place is shown", () => {
    const { result } = render(4);
    expect(result.current).toMatchObject({ playing: false, lit: null });
  });

  it("lights the places in first-report order, one every 600 ms, then shows them all", () => {
    const { result } = render(4);
    expect(result.current.phase).toBe("idle");
    act(() => result.current.start());
    expect(result.current).toMatchObject({ playing: true, lit: 1, phase: "started" });
    act(() => void vi.advanceTimersByTime(SPREAD_STEP_MS));
    expect(result.current.lit).toBe(2);
    act(() => void vi.advanceTimersByTime(SPREAD_STEP_MS));
    act(() => void vi.advanceTimersByTime(SPREAD_STEP_MS));
    expect(result.current).toMatchObject({ lit: 4, phase: "done" });
    act(() => void vi.advanceTimersByTime(SPREAD_STEP_MS));
    // Every place again; "done" stays until the next replay or another thread.
    expect(result.current).toMatchObject({ playing: false, lit: null, phase: "done" });
  });

  it("with reduced motion lights them all at once, in one step", () => {
    const { result } = render(4, true);
    act(() => result.current.start());
    expect(result.current).toMatchObject({ lit: 4, phase: "done" }); // no "started"
    act(() => void vi.advanceTimersByTime(0));
    expect(result.current).toMatchObject({ playing: false, lit: null, phase: "done" });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops part way, showing every place again, and starts over from the first", () => {
    const { result } = render(4);
    act(() => result.current.start());
    act(() => void vi.advanceTimersByTime(SPREAD_STEP_MS));
    act(() => result.current.stop());
    expect(result.current).toMatchObject({ playing: false, lit: null, phase: "idle" });
    act(() => result.current.start());
    expect(result.current).toMatchObject({ playing: true, lit: 1, phase: "started" });
  });

  it("does nothing for a thread with no places", () => {
    const { result } = render(0);
    act(() => result.current.start());
    expect(result.current).toMatchObject({ playing: false, lit: null });
  });

  it("stops without a word with reset (another thread is selected)", () => {
    const { result } = render(4);
    act(() => result.current.start());
    act(() => void vi.advanceTimersByTime(SPREAD_STEP_MS * 4));
    expect(result.current.phase).toBe("done");
    act(() => result.current.start());
    act(() => result.current.reset());
    expect(result.current).toMatchObject({ playing: false, lit: null, phase: "idle" });
    expect(vi.getTimerCount()).toBe(0);
  });
});
