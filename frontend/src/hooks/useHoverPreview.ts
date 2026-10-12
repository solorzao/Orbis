"use client";

import { useEffect, useState } from "react";
import { fetchPlacePreview, isSummaryFallback, type ApiPlacePreview } from "@/lib/api";
import { cellKey } from "@/lib/cells";
import type { TimeWindow } from "@/lib/timeWindow";
import type { GlobePoint, Topic } from "@/types/news";

/** How long the pointer rests on a dot before its preview is asked for. */
export const DWELL_MS = 400;

// One answer per cell, window and topic, for the session (the page's lifetime).
const cache = new Map<string, ApiPlacePreview>();
// Summaries the panel fetched after a click, by the same key (see rememberBrief).
const briefs = new Map<string, string>();

/** Forget every answer (tests). */
export function clearPreviewCache() {
  cache.clear();
  briefs.clear();
}

/** A preview with the panel's summary as its brief, when it came without one. */
function withBrief(key: string, preview: ApiPlacePreview): ApiPlacePreview {
  const brief = briefs.get(key);
  return brief && !preview.brief ? { ...preview, brief } : preview;
}

/**
 * Keep the summary a click on a place fetched for its panel as the place's
 * brief, for the window and topic it was asked for: the next hover shows it
 * at once, though the server's cached preview (up to five minutes old) may
 * still have none. Empty summaries and the backend's fallback messages
 * ("Summary generation failed.") aren't briefs.
 */
export function rememberBrief(
  place: Pick<GlobePoint, "lat" | "lng">,
  window: TimeWindow,
  topic: Topic,
  summary: string,
) {
  const text = summary.trim();
  if (!text || isSummaryFallback(text)) return;
  const key = previewKey(place, window, topic);
  briefs.set(key, text);
  const cached = cache.get(key);
  if (cached) cache.set(key, withBrief(key, cached));
}

function previewKey(
  point: Pick<GlobePoint, "lat" | "lng">,
  window: TimeWindow,
  topic: Topic,
): string {
  const span =
    window.kind === "live" ? `live${window.hours}` : `${window.startTime}/${window.endTime}`;
  return `${cellKey(point.lat, point.lng)}|${span}|${topic}`;
}

interface Outcome {
  key: string;
  preview: ApiPlacePreview | null;
  failed: boolean;
}

/**
 * The hover card's dwell data (sparkline, names, cached AI brief) for the
 * dot the pointer rests on. It asks once the pointer has stayed DWELL_MS on
 * the dot, so a pointer sweeping across the globe asks for nothing. Each
 * cell, window and topic is asked for once a session; when the hover moves
 * on, a pending request is aborted and the place is asked for again on the
 * next visit. `loading` is true until the answer comes, or fails.
 */
export function useHoverPreview(
  point: GlobePoint | null,
  window: TimeWindow,
  topic: Topic,
): { preview: ApiPlacePreview | null; loading: boolean } {
  const key = point ? previewKey(point, window, topic) : null;
  const lat = point?.lat;
  const lng = point?.lng;
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (key === null || lat === undefined || lng === undefined || cache.has(key)) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setOutcome({ key, preview: null, failed: false }); // loading again after a failure
      fetchPlacePreview({ lat, lng, window, topic, signal: controller.signal })
        .then((answer) => {
          const preview = withBrief(key, answer);
          cache.set(key, preview);
          if (!controller.signal.aborted) setOutcome({ key, preview, failed: false });
        })
        .catch(() => {
          if (!controller.signal.aborted) setOutcome({ key, preview: null, failed: true });
        });
    }, DWELL_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, lat, lng, window, topic]);

  if (key === null) return { preview: null, loading: false };
  const cached = cache.get(key);
  if (cached) return { preview: cached, loading: false };
  const failed = outcome?.key === key && outcome.failed;
  return { preview: null, loading: !failed };
}
