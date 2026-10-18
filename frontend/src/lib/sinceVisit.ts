/**
 * "Since your last visit" (/api/news/delta): when the strip shows, the visit
 * it counts from as the server floors it, and what it says.
 */
import { HOUR_MS, type TimeWindow } from "@/lib/timeWindow";
import { dotInCell } from "@/lib/cells";
import type { GlobePoint } from "@/types/news";

const MIN_MS = 60_000;
const DAY_MS = 24 * HOUR_MS;

/** The strip shows for a last visit at least this long ago... */
export const SINCE_MIN_MS = HOUR_MS;
/** ...and at most this long ago (the stories the server keeps). */
export const SINCE_MAX_MS = 7 * DAY_MS;

/** A new place the delta lists: a 1° cell, its new stories and its lead's headline. */
export interface SincePlace {
  lat: number;
  lng: number;
  place: string;
  new: number;
  headline: string;
}

/** What changed since a visit, as of `at` (when it was asked). */
export interface SinceDelta {
  at: number;
  newStories: number;
  newPlaces: number;
  breaking: number;
  top: SincePlace[];
}

/** Whether the strip shows: a last visit between 1 hour and 7 days ago (null: a first visit). */
export function showSince(lastVisit: number | null, now: number): boolean {
  if (lastVisit === null) return false;
  const away = now - lastVisit;
  return away >= SINCE_MIN_MS && away <= SINCE_MAX_MS;
}

/**
 * The visit floored in UTC as /api/news/delta floors it: to the quarter hour
 * within 24 hours of now, the hour within 72, 6 hours beyond, and never more
 * than 7 days back (a visit ahead of the clock counts as now). It changes no
 * answer, but visits in one bucket send one URL, which the edge cache shares.
 */
export function floorSince(since: number, now: number): number {
  const start = Math.min(Math.max(since, now - SINCE_MAX_MS), now);
  const away = now - start;
  const step = away <= DAY_MS ? 15 * MIN_MS : away <= 3 * DAY_MS ? HOUR_MS : 6 * HOUR_MS;
  return start - (start % step);
}

/** How long ago the visit was: "14 h", or "3 d" from two days. */
export function sinceAgo(lastVisit: number, now: number): string {
  const hours = Math.floor((now - lastVisit) / HOUR_MS);
  return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}

const count = (n: number, one: string, many: string) =>
  `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;

/** "14 h since your visit: 1,286 new stories, 4 breaking stories." (no breaking part at 0). */
export function sinceSummary(
  ago: string,
  { newStories, breaking }: { newStories: number; breaking: number },
): string {
  const parts = [count(newStories, "new story", "new stories")];
  if (breaking > 0) parts.push(count(breaking, "breaking story", "breaking stories"));
  return `${ago} since your visit: ${parts.join(", ")}.`;
}

/** Show: the time window from the last visit, floored as the strip's counts are, to now. */
export function sinceRange(lastVisit: number, now: number): TimeWindow {
  return {
    kind: "range",
    startTime: new Date(floorSince(lastVisit, now)).toISOString(),
    endTime: new Date(now).toISOString(),
  };
}

/**
 * The dot that opens a top place: the globe's dot in its cell, else a
 * stand-in counting its new stories (dotInCell).
 */
export function sinceDot(points: readonly GlobePoint[], place: SincePlace): GlobePoint {
  return dotInCell(points, {
    lat: place.lat,
    lng: place.lng,
    place: place.place,
    count: place.new,
  });
}

/** sessionStorage: the strip dismissed for this session. */
const DISMISSED_KEY = "orbis-since-dismissed";

export function readSinceDismissed(): boolean {
  try {
    return sessionStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false; // storage blocked: the strip shows, and Dismiss hides it for the page
  }
}

export function writeSinceDismissed(): void {
  try {
    sessionStorage.setItem(DISMISSED_KEY, "1");
  } catch {
    // storage blocked: dismissed for this page only
  }
}
