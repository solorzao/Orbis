"use client";

import { useEffect, useState } from "react";
import type { GlobePoint, Topic } from "@/types/news";
import { fetchGlobeNews } from "@/lib/api";
import { apiPointsToGlobePoints } from "@/lib/clustering";
import { windowQuery, type TimeWindow } from "@/lib/timeWindow";

/** Quick window changes (keyboard steps, presets) settle before one request goes out. */
export const FETCH_DEBOUNCE_MS = 150;
/** Most dots /api/news returns. */
export const GLOBE_LIMIT = 500;

const NO_POINTS: GlobePoint[] = [];

interface Result {
  window: TimeWindow;
  topic: Topic;
  points: GlobePoint[];
  error: boolean;
}

/**
 * The globe's dots for a time window and topic. The server filters by topic
 * (so a topic's quieter places make the cut, and each dot's colour and size
 * are the topic's). A new window or topic cancels the request for the last
 * one and ignores its answer if it comes anyway, so a replay's steps can
 * never land out of order. The last dots stay up while the next load. The
 * array stays the same until new dots land: a new one makes the globe redraw.
 */
export function useGlobePoints(
  timeWindow: TimeWindow,
  topic: Topic = "All",
): {
  points: GlobePoint[];
  error: boolean;
  /** True until the dots for this window and topic arrive (or fail). */
  loading: boolean;
} {
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { timespan, startTime, endTime } = windowQuery(timeWindow);
    const timer = setTimeout(() => {
      fetchGlobeNews({
        timespan,
        limit: GLOBE_LIMIT,
        startTime,
        endTime,
        topic,
        signal: controller.signal,
      })
        .then((apiPoints) => {
          if (controller.signal.aborted) return;
          setResult({
            window: timeWindow,
            topic,
            points: apiPointsToGlobePoints(apiPoints),
            error: false,
          });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setResult({ window: timeWindow, topic, points: NO_POINTS, error: true });
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [timeWindow, topic]);

  return {
    points: result?.points ?? NO_POINTS,
    error: result?.error ?? false,
    loading: result?.window !== timeWindow || result.topic !== topic,
  };
}
