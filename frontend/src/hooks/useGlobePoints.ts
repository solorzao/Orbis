"use client";

import { useEffect, useMemo, useState } from "react";
import type { GlobePoint, Topic } from "@/types/news";
import { fetchGlobeNews, retryOnce503 } from "@/lib/api";
import { apiPointsToGlobePoints, dotSize, getTopicColor } from "@/lib/clustering";
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
 * The dots on screen filtered to `topic` while its own load: the places with
 * its stories (or its colour), each in its colour and counted and sized by
 * them. All keeps the dots as they are.
 */
export function topicPoints(points: GlobePoint[], topic: Topic): GlobePoint[] {
  if (topic === "All") return points;
  const color = getTopicColor(topic);
  return points.flatMap((point) => {
    const stories = point.topicMix?.[topic] ?? 0;
    if (stories <= 0 && point.topic !== topic) return [];
    const count = stories > 0 ? stories : point.count;
    return [{ ...point, topic, color, count, size: dotSize(count), isCluster: count > 1 }];
  });
}

/**
 * The globe's dots for a time window and topic. The server filters by topic
 * (so a topic's quieter places make the cut, and each dot's colour and size
 * are the topic's). A new window or topic cancels the request for the last
 * one and ignores its answer if it comes anyway, so a replay's steps can
 * never land out of order. The last dots stay up while the next load; for a
 * new topic they are filtered to it at once (`provisional`) until its own
 * land, as a cold 7-day window can take a while. The array stays the same
 * until new dots land or the topic changes: a new one makes the globe redraw.
 */
export function useGlobePoints(
  timeWindow: TimeWindow,
  topic: Topic = "All",
): {
  points: GlobePoint[];
  error: boolean;
  /** True until the dots for this window and topic arrive (or fail). */
  loading: boolean;
  /** The dots are the last topic's, filtered to this one on the client until its own land. */
  provisional: boolean;
} {
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { timespan, startTime, endTime } = windowQuery(timeWindow);
    const timer = setTimeout(() => {
      // A 503 (a 7-day read stopped at a cycle's boundary) is asked once more.
      retryOnce503(
        () =>
          fetchGlobeNews({
            timespan,
            limit: GLOBE_LIMIT,
            startTime,
            endTime,
            topic,
            signal: controller.signal,
          }),
        controller.signal,
      )
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

  const provisional = result !== null && result.topic !== topic;
  const points = useMemo(() => {
    if (!result) return NO_POINTS;
    return provisional ? topicPoints(result.points, topic) : result.points;
  }, [result, topic, provisional]);

  return {
    points,
    error: result?.error ?? false,
    loading: result?.window !== timeWindow || result.topic !== topic,
    provisional,
  };
}
