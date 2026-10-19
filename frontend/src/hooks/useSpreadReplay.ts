"use client";

import { useCallback, useMemo, useState } from "react";
import { useReplay } from "@/hooks/useReplay";
import { SPREAD_STEP_MS } from "@/lib/threads";

export interface SpreadReplay {
  playing: boolean;
  /** The places lit so far while it plays; null shows them all. */
  lit: number | null;
  start: () => void;
  stop: () => void;
  /** Stop without restoring anything (another thread is selected). */
  reset: () => void;
}

/**
 * "Replay how {title} spread": the selected thread's places lit in order of
 * first report, one every SPREAD_STEP_MS (the first at once), then all of
 * them again. With reduced motion they all light at once, in one step.
 */
export function useSpreadReplay(stops: number, reduced: boolean): SpreadReplay {
  const [lit, setLit] = useState<number | null>(null);
  const steps = useMemo(
    () => (reduced ? [stops] : Array.from({ length: stops }, (_, i) => i + 1)),
    [stops, reduced],
  );
  const replay = useReplay<number | null>(steps, reduced ? 0 : SPREAD_STEP_MS, setLit);
  const { start: play, stop: halt } = replay;

  // Ends on null: every place shown.
  const start = useCallback(() => {
    if (stops > 0) play(null);
  }, [stops, play]);

  const stop = useCallback(() => halt(true), [halt]);

  const reset = useCallback(() => {
    halt(false);
    setLit(null);
  }, [halt]);

  return { playing: replay.playing, lit, start, stop, reset };
}
