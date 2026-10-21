import { describe, it, expect } from "vitest";
import {
  articleSnapshot,
  entitySnapshot,
  linkSnapshot,
  placeSnapshot,
  threadSnapshot,
} from "./boardSnapshots";
import type { CountryLink, GlobePoint, NewsArticle } from "@/types/news";
import type { Thread } from "./threads";
import type { EntityDossier } from "./entities";

const article = (over: Partial<NewsArticle> = {}): NewsArticle => ({
  id: "4f6c2a7e-1d2b-4c3d-9e8f-0a1b2c3d4e5f",
  title: "France announces new climate policy",
  sourceUrl: "https://example.com/france-climate",
  sourceName: "Reuters",
  publishedAt: "2026-10-20T11:00:00Z",
  latitude: 48.8566,
  longitude: 2.3522,
  countryCode: "FR",
  region: "Paris, France",
  topicTags: ["Climate"],
  sentimentScore: 0.4,
  ...over,
});

const point = (over: Partial<GlobePoint> = {}): GlobePoint => ({
  id: "p1",
  lat: 48.5,
  lng: 2.5,
  size: 1,
  color: "#fff",
  articles: [
    article({ publishedAt: "2026-10-20T09:00:00Z" }),
    article({ publishedAt: "2026-10-20T11:30:00Z" }),
  ],
  isCluster: true,
  count: 2,
  locationName: "Paris, France",
  topic: "Climate",
  ...over,
});

describe("pin snapshots", () => {
  it("a place: its name where its dot is, as of its newest story", () => {
    expect(placeSnapshot(point())).toEqual({
      title: "Paris, France",
      place: "Paris, France",
      lat: 48.5,
      lng: 2.5,
      time: "2026-10-20T11:30:00Z",
      url: null,
    });
    // Unnamed, with no stories loaded: its coordinates, and its lead's time.
    const bare = placeSnapshot(
      point({
        locationName: undefined,
        articles: [],
        lead: {
          title: "x",
          sourceName: "y",
          publishedAt: "2026-10-20T08:00:00Z",
          imageUrl: null,
          topic: "All",
          sensitive: false,
        },
      }),
    );
    expect(bare).toMatchObject({
      title: "48.50°, 2.50°",
      place: null,
      time: "2026-10-20T08:00:00Z",
    });
  });

  it("a story: its headline, place, time and web link only", () => {
    expect(articleSnapshot(article())).toEqual({
      title: "France announces new climate policy",
      place: "Paris, France",
      lat: 48.8566,
      lng: 2.3522,
      time: "2026-10-20T11:00:00Z",
      url: "https://example.com/france-climate",
    });
    expect(
      articleSnapshot(article({ region: "", sourceUrl: "javascript:alert(1)" }), "Paris"),
    ).toMatchObject({ place: "Paris", url: null });
  });

  it("a link: its countries in code order, as the server names one", () => {
    const link = {
      a: { iso: "FR", name: "France", lat: 46.6, lng: 2.3 },
      b: { iso: "GB", name: "United Kingdom", lat: 53.9, lng: -2.7 },
      n: 18,
      lift: 2.6,
      topic: "Economy",
      tone: 0.06,
      from: "GB",
    } satisfies CountryLink;
    expect(linkSnapshot(link)).toEqual({
      title: "France and United Kingdom",
      place: null,
      lat: null,
      lng: null,
      time: null,
      url: null,
    });
  });

  it("a thread: its title, first place and last story's time", () => {
    const thread = {
      id: 7,
      title: "Red Sea shipping attacks",
      lastSeen: "2026-10-20T11:40:00Z",
      places: [
        { lat: 15.5, lng: 48.5, place: "Yemen", countryCode: "YE", firstSeen: "x", n: 7 },
        { lat: 30.5, lng: 32.5, place: "Suez, Egypt", countryCode: "EG", firstSeen: "y", n: 6 },
      ],
    } as Thread;
    expect(threadSnapshot(thread)).toEqual({
      title: "Red Sea shipping attacks",
      place: "Yemen",
      lat: 15.5,
      lng: 48.5,
      time: "2026-10-20T11:40:00Z",
      url: null,
    });
    expect(threadSnapshot({ ...thread, places: [] })).toMatchObject({ place: null, lat: null });
  });

  it("a person or organisation: the dossier's name and top place, no time", () => {
    const dossier = {
      name: "Emmanuel Macron",
      type: "person",
      places: [
        { lat: 48.85, lng: 2.35, place: "Paris, France", countryCode: "FR", n: 60, tone: 0 },
      ],
    } as unknown as EntityDossier;
    expect(entitySnapshot(dossier)).toEqual({
      title: "Emmanuel Macron",
      place: "Paris, France",
      lat: 48.85,
      lng: 2.35,
      time: null,
      url: null,
    });
  });
});
