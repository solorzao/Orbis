import { describe, it, expect } from "vitest";
import { cellKey, cellPoint, dotInCell, pointAt } from "./cells";
import { TOPIC_COLORS } from "./clustering";
import type { GlobePoint } from "@/types/news";

/** A dot at a 1° cell's centre, as /api/news returns them. */
function dot(id: string, lat: number, lng: number): GlobePoint {
  return {
    id,
    lat,
    lng,
    size: 1,
    color: "#fff",
    articles: [],
    isCluster: false,
    count: 3,
    topic: "All",
  };
}

const madrid = dot("madrid", 40.5, -3.5);
const lisbon = dot("lisbon", 38.5, -9.5);
const fiji = dot("fiji", -17.5, 179.5);

describe("pointAt", () => {
  it("finds the dot in the same 1° cell", () => {
    expect(pointAt([lisbon, madrid], 40.4168, -3.7038)).toBe(madrid);
    // a cell edge belongs to the cell above it, as FLOOR does
    expect(pointAt([madrid], 40, -3)).toBe(madrid);
  });

  it("else takes the nearest dot within 1.5°", () => {
    const near = dot("near", 41.5, -2.5); // the next cell north-east
    const far = dot("far", 42.5, -1.5);
    expect(pointAt([far, near], 40.9, -3.1)).toBe(near);
    expect(pointAt([madrid], 39.2, -3.5)).toBe(madrid); // 1.3° south
  });

  it("is null when no dot is within 1.5°", () => {
    expect(pointAt([madrid, lisbon], 48.85, 2.35)).toBeNull();
    expect(pointAt([], 40.4, -3.7)).toBeNull();
  });

  it("measures across the antimeridian", () => {
    expect(pointAt([fiji], -17.6, -179.6)).toBe(fiji);
  });
});

describe("cellKey", () => {
  it("names a point's 1° cell, floored as the backend groups them", () => {
    expect(cellKey(48.5, 2.5)).toBe("48:2");
    expect(cellKey(48.99, 2.01)).toBe("48:2");
    expect(cellKey(-0.5, -74.5)).toBe("-1:-75");
  });
});

describe("dotInCell", () => {
  const dot = (lat: number, lng: number, name: string): GlobePoint => ({
    id: name,
    lat,
    lng,
    size: 1,
    color: "#fff",
    articles: [],
    isCluster: true,
    count: 40,
    topic: "Politics",
    locationName: name,
  });
  const cell = { lat: 29.5, lng: -98.5, place: "San Antonio, Texas", count: 7 };

  it("is the globe's dot in the cell", () => {
    const points = [dot(30.2, -97.7, "Austin"), dot(29.5, -98.5, "San Antonio")];
    expect(dotInCell(points, cell).locationName).toBe("San Antonio");
  });

  it("is never a neighbouring cell's dot (pointAt's nearest would be): a stand-in instead", () => {
    expect(dotInCell([dot(30.2, -97.7, "Austin")], cell)).toEqual(cellPoint(cell));
  });

  it("stands in with the cell's place and count, and no topic colour", () => {
    expect(cellPoint(cell)).toMatchObject({
      lat: 29.5,
      lng: -98.5,
      locationName: "San Antonio, Texas",
      count: 7,
      topic: "All",
      color: TOPIC_COLORS.All,
      articles: [],
    });
    expect(cellPoint(cell).id).toBe(cellPoint({ ...cell, count: 3 }).id); // one id per cell
  });
});
