"use client";

import { useEffect, useState } from "react";
import { fetchDelta } from "@/lib/api";
import { floorSince, showSince, type SinceDelta } from "@/lib/sinceVisit";

/**
 * What changed since the last visit (/api/news/delta), asked once at mount
 * when the visit was between 1 hour and 7 days ago, with the visit floored
 * as the server floors it (so visits in one bucket share an edge-cached URL).
 * Null until it answers, on a first visit, and when the request fails.
 */
export function useDelta(lastVisit: number | null): SinceDelta | null {
  const [delta, setDelta] = useState<SinceDelta | null>(null);

  useEffect(() => {
    const now = Date.now();
    if (!showSince(lastVisit, now)) return;
    const controller = new AbortController();
    const since = new Date(floorSince(lastVisit!, now)).toISOString();
    fetchDelta({ since, signal: controller.signal })
      .then((d) => {
        if (controller.signal.aborted) return;
        setDelta({
          at: now,
          newStories: d.new_stories,
          newPlaces: d.new_places,
          breaking: d.breaking,
          top: d.top.map((p) => ({
            lat: p.lat,
            lng: p.lng,
            place: p.place,
            new: p.new,
            headline: p.lead.title,
          })),
        });
      })
      .catch(() => {}); // no strip: it is a welcome, not news
    return () => controller.abort();
  }, [lastVisit]);

  return delta;
}
