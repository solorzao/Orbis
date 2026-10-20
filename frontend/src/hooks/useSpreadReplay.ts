"use client";

import { useCallback, useMemo, useState } from "react";
import { useReplay } from "@/hooks/useReplay";
import { SPREAD_STEP_MS, type ReplayPhase } from "@/lib/threads";

export interface SpreadReplay {
  playing: boolean;
  /** The places lit so far while it plays; null shows them all. */
  lit: number | null;
  /** For the announcer: "started", then "done" (every place lit) until the next replay. */
  phase: ReplayPhase;
  start: () => void;
  stop: () => void;
  /** Stop without restoring anything, and forget the last replay (another thread). */
  reset: () => void;
}

/**
 * "Replay how {title} spread": the selected thread's places lit in order of
 * first report, one every SPREAD_STEP_MS (the first at once), then all of
 * them again. With reduced motion they all light at once, in one step.
 */
export function useSpreadReplay(stops: number, reduced: boolean): SpreadReplay {
  const [lit, setLit] = useState<number | null>(null);
  const [phase, setPhase] = useState<ReplayPhase>("idle");
  const steps = useMemo(
    () => (reduced ? [stops] : Array.from({ length: stops }, (_, i) => i + 1)),
    [stops, reduced],
  );
  const apply = useCallback(
    (k: number | null) => {
      setLit(k);
      if (k !== null && k >= stops) setPhase("done");
    },
    [stops],
  );
  const replay = useReplay<number | null>(steps, reduced ? 0 : SPREAD_STEP_MS, apply);
  const { start: play, stop: halt } = replay;

  // Ends on null: every place shown.
  const start = useCallback(() => {
    if (stops === 0) return;
    setPhase("started");
    play(null);
  }, [stops, play]);

  // Stopped part way: nothing to say ("done" stays when it ran to the end).
  const stop = useCallback(() => {
    if (replay.playing) setPhase("idle");
    halt(true);
  }, [halt, replay.playing]);

  const reset = useCallback(() => {
    halt(false);
    setLit(null);
    setPhase("idle");
  }, [halt]);

  return { playing: replay.playing, lit, phase, start, stop, reset };
}
