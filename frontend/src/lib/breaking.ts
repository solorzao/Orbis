/**
 * Breaking stories (/api/news/breaking): events many outlets have just
 * started covering. The ticker names them and the globe rings their places.
 */
import type { ApiBreakingStory } from "@/lib/api";
import { TOPIC_COLORS } from "@/lib/clustering";
import { cellKey } from "@/lib/cells";
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

/**
 * A stand-in dot for a breaking story's place when the globe has none there
 * (it shows the window's busiest 500 places, and a story breaking somewhere
 * quiet may not be one). It opens like a dot: the panel lists the cell's
 * stories by its lat/lng, and corrects the count from the event's stories
 * once a short page shows the cell's. No topic colour: a breaking story's
 * topic can be mislabelled.
 */
export function breakingPoint(story: BreakingStory): GlobePoint {
  return {
    id: `breaking-${cellKey(story.lat, story.lng)}`,
    lat: story.lat,
    lng: story.lng,
    size: 1,
    color: TOPIC_COLORS.All,
    articles: [],
    isCluster: story.stories > 1,
    count: story.stories,
    locationName: story.place,
    topic: "All",
  };
}

/**
 * The dot a breaking story opens: the globe's dot in the story's own 1° cell
 * (its lat/lng is that cell's centre), else a stand-in (breakingPoint). Not
 * pointAt's nearest dot within 1.5 degrees: that is another place's.
 */
export function breakingDot(points: readonly GlobePoint[], story: BreakingStory): GlobePoint {
  const cell = cellKey(story.lat, story.lng);
  return points.find((p) => cellKey(p.lat, p.lng) === cell) ?? breakingPoint(story);
}
