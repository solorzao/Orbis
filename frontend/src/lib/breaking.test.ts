import { describe, it, expect } from "vitest";
import { breakingDot, breakingPoint, outletsLabel, toBreakingStories } from "./breaking";
import { TOPIC_COLORS } from "./clustering";
import type { ApiBreakingStory } from "./api";

const LEAD = {
  title: "Rescue teams reach the site",
  source_name: "AP",
  published_at: "2026-10-18T15:40:00Z",
  image_url: null,
  topic: "economy",
};

function apiStory(over: Partial<ApiBreakingStory> = {}): ApiBreakingStory {
  return {
    headline: "A U.S. Military Airman Dies After Rappelling Accident at UTSA-Navy Game",
    place: "Alamodome, Texas, United States",
    lat: 29.5,
    lng: -98.5,
    outlets: 17,
    stories: 7,
    first_seen: "2026-10-18T14:00:00Z",
    topic: "economy",
    lead: LEAD,
    ...over,
  };
}

describe("toBreakingStories", () => {
  it("keeps what the ticker shows, in the order the API ranks them", () => {
    const stories = toBreakingStories([apiStory(), apiStory({ headline: "Second", outlets: 9 })]);
    expect(stories).toEqual([
      {
        headline: "A U.S. Military Airman Dies After Rappelling Accident at UTSA-Navy Game",
        place: "Alamodome, Texas, United States",
        lat: 29.5,
        lng: -98.5,
        outlets: 17,
        stories: 7,
      },
      expect.objectContaining({ headline: "Second", outlets: 9 }),
    ]);
  });

  it("leaves out first_seen (clamped to the window's start) and the topic (can be mislabelled)", () => {
    const [story] = toBreakingStories([apiStory()]);
    expect(story).not.toHaveProperty("firstSeen");
    expect(story).not.toHaveProperty("first_seen");
    expect(story).not.toHaveProperty("topic");
  });
});

describe("outletsLabel", () => {
  it("counts outlets", () => {
    expect(outletsLabel(17)).toBe("17 outlets");
    expect(outletsLabel(1)).toBe("1 outlet");
  });
});

describe("breakingPoint", () => {
  it("stands in for a place the globe has no dot for: its cell, named by the story's place", () => {
    const [story] = toBreakingStories([apiStory()]);
    const point = breakingPoint(story);
    expect(point).toMatchObject({
      lat: 29.5,
      lng: -98.5,
      locationName: "Alamodome, Texas, United States",
      count: 7, // the event's stories: the panel corrects it once a short page shows the cell's
      topic: "All", // a breaking story's topic can be mislabelled: no colour claim
      color: TOPIC_COLORS.All,
      articles: [],
    });
    expect(point.id).toBe(breakingPoint(story).id); // the same cell, the same id
  });
});

describe("breakingDot", () => {
  const dot = (lat: number, lng: number, name: string) => ({
    id: name,
    lat,
    lng,
    size: 1,
    color: "#fff",
    articles: [],
    isCluster: true,
    count: 40,
    topic: "Politics" as const,
    locationName: name,
  });
  const [story] = toBreakingStories([apiStory({ lat: 29.5, lng: -98.5 })]);

  it("is the globe's dot in the story's cell", () => {
    const points = [dot(30.2, -97.7, "Austin"), dot(29.5, -98.5, "San Antonio")];
    expect(breakingDot(points, story).locationName).toBe("San Antonio");
  });

  it("never a neighbouring cell's dot (pointAt's nearest would be): it stands in instead", () => {
    const points = [dot(30.2, -97.7, "Austin")]; // within 1.5 degrees, another cell
    expect(breakingDot(points, story)).toEqual(breakingPoint(story));
  });
});
