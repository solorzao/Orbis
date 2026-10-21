"use client";

import { useEffect, useState } from "react";
import type { CountryLink, Topic } from "@/types/news";
import { fetchLinks, retryOnce503 } from "@/lib/api";
import { LINKS_LIMIT, toCountryLinks, type LinkRank } from "@/lib/links";
import type { TimeWindow } from "@/lib/timeWindow";
import { FETCH_DEBOUNCE_MS } from "@/hooks/useGlobePoints";

const NO_LINKS: CountryLink[] = [];

interface Result {
  window: TimeWindow;
  topic: Topic;
  rank: LinkRank;
  links: CountryLink[];
  error: boolean;
}

/**
 * The Links layer's arcs for a window, topic and rank, fetched only while the
 * layer is on (`enabled`). It follows useGlobePoints: a new window, topic or
 * rank cancels the last request and ignores its answer if it comes anyway,
 * and the last arcs stay up while the next load; a 503 is asked once more.
 * Off, there are no arcs.
 */
export function useLinks(
  timeWindow: TimeWindow,
  topic: Topic,
  rank: LinkRank,
  enabled: boolean,
): { links: CountryLink[]; loading: boolean; error: boolean } {
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      // A 503 (a 7-day read stopped at a cycle's boundary) is asked once more.
      retryOnce503(
        () =>
          fetchLinks({
            window: timeWindow,
            topic,
            rank,
            limit: LINKS_LIMIT,
            signal: controller.signal,
          }),
        controller.signal,
      )
        .then((api) => {
          if (controller.signal.aborted) return;
          setResult({ window: timeWindow, topic, rank, links: toCountryLinks(api), error: false });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setResult({ window: timeWindow, topic, rank, links: NO_LINKS, error: true });
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, timeWindow, topic, rank]);

  // Off forgets the last answer: turned on again, an old error must not be
  // shown (and announced) before the new request answers.
  if (!enabled && result !== null) setResult(null);
  if (!enabled) return { links: NO_LINKS, loading: false, error: false };
  const current =
    result !== null &&
    result.window === timeWindow &&
    result.topic === topic &&
    result.rank === rank;
  return {
    links: result?.links ?? NO_LINKS,
    error: result?.error ?? false,
    loading: !current,
  };
}
