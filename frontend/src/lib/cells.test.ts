import { describe, it, expect } from "vitest";
import { pointAt } from "./cells";
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
