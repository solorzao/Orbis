"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

export interface Replay<T> {
  playing: boolean;
  /** The step showing, or null when not playing. */
  index: number | null;
  /** That step's value, or null when not playing. */
  step: T | null;
  /** Play the steps from the first, remembering `current` to come back to. */
  start: (current: T) => void;
  /** Stop; with `restore` (the default), go back to the remembered window. */
  stop: (restore?: boolean) => void;
}

interface Run<T> {
  steps: readonly T[];
  prior: T;
  index: number;
  timer: ReturnType<typeof setInterval>;
}

/**
 * A time-lapse: `apply` each step in turn, one every `intervalMs` (the first
 * at once), then `apply` the window it started from. The steps are fixed when
 * it starts. Stopping, or unmounting, clears the interval.
 */
export function useReplay<T>(
  steps: readonly T[],
  intervalMs: number,
  apply: (step: T) => void,
): Replay<T> {
  const [showing, setShowing] = useState<{ index: number; step: T } | null>(null);
  const run = useRef<Run<T> | null>(null);

  // The interval calls the latest apply, not the one from when it started.
  const applyRef = useRef(apply);
  useLayoutEffect(() => {
    applyRef.current = apply;
  });

  const stop = useCallback((restore = true) => {
    const current = run.current;
    if (!current) return;
    clearInterval(current.timer);
    run.current = null;
    setShowing(null);
    if (restore) applyRef.current(current.prior);
  }, []);

  const start = useCallback(
    (current: T) => {
      if (run.current || steps.length === 0) return;
      const timer = setInterval(() => {
        const r = run.current;
        if (!r) return;
        const next = r.index + 1;
        if (next >= r.steps.length) {
          stop(true);
          return;
        }
        r.index = next;
        setShowing({ index: next, step: r.steps[next] });
        applyRef.current(r.steps[next]);
      }, intervalMs);
      run.current = { steps, prior: current, index: 0, timer };
      setShowing({ index: 0, step: steps[0] });
      applyRef.current(steps[0]);
    },
    [steps, intervalMs, stop],
  );

  useEffect(
    () => () => {
      if (run.current) clearInterval(run.current.timer);
      run.current = null;
    },
    [],
  );

  return {
    playing: showing !== null,
    index: showing?.index ?? null,
    step: showing?.step ?? null,
    start,
    stop,
  };
}
