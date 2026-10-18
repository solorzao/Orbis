/**
 * Breaking stories (/api/news/breaking): events many outlets have just
 * started covering. The ticker names them and the globe rings their places.
 */
import type { ApiBreakingStory } from "@/lib/api";
import { cellPoint, dotInCell } from "@/lib/cells";
import type { GlobePoint } from "@/types/news";

/**
 * What the ticker shows of a breaking story. Not first_seen (the server clamps
 * it to the 2-hour window's start, so it is not when the story broke) nor the
 * topic (the stories' dominant tag can be wrong: an accident tagged economy).
 */
export interface BreakingStory {
  headline: string;
  place: string;
  /** The 1° cell's centre, as the cell's globe dot has it. */
  lat: number;
  lng: number;
  /** Distinct outlets on the event in the last 2 hours. */
  outlets: number;
  /** Distinct stories about it among them. */
  stories: number;
}

export function toBreakingStories(api: readonly ApiBreakingStory[]): BreakingStory[] {
  return api.map((s) => ({
    headline: s.headline,
    place: s.place,
    lat: s.lat,
    lng: s.lng,
    outlets: s.outlets,
    stories: s.stories,
  }));
}

/** "17 outlets", "1 outlet". */
export function outletsLabel(n: number): string {
  return `${n} ${n === 1 ? "outlet" : "outlets"}`;
}

/** A breaking story's place, as a stand-in dot (cells cellPoint). */
export function breakingPoint(story: BreakingStory): GlobePoint {
  return cellPoint({ lat: story.lat, lng: story.lng, place: story.place, count: story.stories });
}

/** The dot a breaking story opens: its cell's, else a stand-in (cells dotInCell). */
export function breakingDot(points: readonly GlobePoint[], story: BreakingStory): GlobePoint {
  return dotInCell(points, {
    lat: story.lat,
    lng: story.lng,
    place: story.place,
    count: story.stories,
  });
}
