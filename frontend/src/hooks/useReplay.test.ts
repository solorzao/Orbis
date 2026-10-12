import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useReplay } from "./useReplay";

const STEPS: readonly string[] = ["d-2", "d-1", "today"];
const STEP_MS = 1600;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function setup() {
  const apply = vi.fn();
  const hook = renderHook(() => useReplay(STEPS, STEP_MS, apply));
  return { apply, hook };
}

describe("useReplay", () => {
  it("starts on the first step at once", () => {
    const { apply, hook } = setup();
    expect(hook.result.current.playing).toBe(false);
    expect(hook.result.current.index).toBeNull();

    act(() => hook.result.current.start("live"));

    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply).toHaveBeenLastCalledWith("d-2");
    expect(hook.result.current.playing).toBe(true);
    expect(hook.result.current.index).toBe(0);
    expect(hook.result.current.step).toBe("d-2");
  });

  it("advances one step per interval, then restores the window it started from", () => {
    const { apply, hook } = setup();
    act(() => hook.result.current.start("live"));

    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(apply).toHaveBeenLastCalledWith("d-1");
    expect(hook.result.current.index).toBe(1);

    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(apply).toHaveBeenLastCalledWith("today");
    expect(hook.result.current.index).toBe(2);

    // The last step shows for a full interval too.
    act(() => vi.advanceTimersByTime(STEP_MS - 1));
    expect(apply).toHaveBeenCalledTimes(3);
    act(() => vi.advanceTimersByTime(1));
    expect(apply).toHaveBeenLastCalledWith("live");
    expect(hook.result.current.playing).toBe(false);
    expect(hook.result.current.index).toBeNull();
    expect(hook.result.current.step).toBeNull();

    act(() => vi.advanceTimersByTime(10 * STEP_MS));
    expect(apply).toHaveBeenCalledTimes(4);
  });

  it("stops on demand and restores the prior window", () => {
    const { apply, hook } = setup();
    act(() => hook.result.current.start("live"));
    act(() => vi.advanceTimersByTime(STEP_MS));

    act(() => hook.result.current.stop());

    expect(apply).toHaveBeenLastCalledWith("live");
    expect(hook.result.current.playing).toBe(false);
    act(() => vi.advanceTimersByTime(10 * STEP_MS));
    expect(apply).toHaveBeenCalledTimes(3); // d-2, d-1, live
  });

  it("can stop without restoring, when the visitor picks another window", () => {
    const { apply, hook } = setup();
    act(() => hook.result.current.start("live"));

    act(() => hook.result.current.stop(false));

    expect(apply).toHaveBeenCalledTimes(1);
    expect(hook.result.current.playing).toBe(false);
    act(() => vi.advanceTimersByTime(10 * STEP_MS));
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("does nothing when stopped while not playing", () => {
    const { apply, hook } = setup();
    act(() => hook.result.current.stop());
    expect(apply).not.toHaveBeenCalled();
  });

  it("clears its interval on unmount", () => {
    const { apply, hook } = setup();
    act(() => hook.result.current.start("live"));
    hook.unmount();

    act(() => vi.advanceTimersByTime(10 * STEP_MS));
    expect(apply).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("plays the steps it started with, even if they change meanwhile", () => {
    const apply = vi.fn();
    const hook = renderHook(({ steps }) => useReplay(steps, STEP_MS, apply), {
      initialProps: { steps: ["a", "b"] },
    });
    act(() => hook.result.current.start("live"));
    hook.rerender({ steps: ["x", "y", "z"] });

    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(apply).toHaveBeenLastCalledWith("b");
    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(apply).toHaveBeenLastCalledWith("live");
  });

  it("reports playing and stopped in the same update as the step it applies", () => {
    const apply = vi.fn();
    const onPlayingChange = vi.fn();
    const hook = renderHook(() => useReplay(STEPS, STEP_MS, apply, onPlayingChange));

    act(() => hook.result.current.start("live"));
    expect(onPlayingChange.mock.calls).toEqual([[true]]);
    // Called before the first step is applied, so no render sees the step without it.
    expect(onPlayingChange.mock.invocationCallOrder[0]).toBeLessThan(
      apply.mock.invocationCallOrder[0],
    );

    act(() => vi.advanceTimersByTime(STEPS.length * STEP_MS));
    expect(onPlayingChange.mock.calls).toEqual([[true], [false]]);

    act(() => hook.result.current.start("live"));
    act(() => hook.result.current.stop(false));
    expect(onPlayingChange.mock.calls).toEqual([[true], [false], [true], [false]]);
  });
});
