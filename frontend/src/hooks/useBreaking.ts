"use client";

import { useEffect, useState } from "react";
import { fetchBreaking, retryOnce503 } from "@/lib/api";
import { toBreakingStories, type BreakingStory } from "@/lib/breaking";
import type { Topic } from "@/types/news";

/** How often breaking stories are fetched again: the ingestion cycle is 15 minutes. */
export const BREAKING_REFRESH_MS = 5 * 60_000;

const NONE: BreakingStory[] = [];

/**
 * What is breaking now, for the topic pill, while `enabled` (a live window:
 * not a range or a replay, which look back). Fetched at once, then every 5
 * minutes while the page shows (a hidden tab skips its refreshes and catches
 * up when it shows again); a new topic aborts the last request and ignores
 * its answer, showing none until its own arrive. A 503 is asked once more,
 * after its Retry-After; a failed refresh keeps the last stories; off, there
 * are none.
 */
export function useBreaking(topic: Topic, enabled: boolean): BreakingStory[] {
  const [result, setResult] = useState<{ topic: Topic; stories: BreakingStory[] } | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const load = () => {
      if (document.hidden) return;
      // A 503 (the query timed out, with no earlier list to serve) is asked once more.
      retryOnce503(() => fetchBreaking({ topic, signal: controller.signal }), controller.signal)
        .then((api) => {
          if (!controller.signal.aborted) setResult({ topic, stories: toBreakingStories(api) });
        })
        .catch(() => {}); // keep the last stories; the next refresh tries again
    };
    load();
    const id = setInterval(load, BREAKING_REFRESH_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      controller.abort();
      clearInterval(id);
      document.removeEventListener("visibilitychange", load);
    };
  }, [topic, enabled]);

  if (!enabled) return NONE;
  return result?.topic === topic ? result.stories : NONE;
}
