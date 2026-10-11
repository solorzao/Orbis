import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { build, slimLand, SOURCE, TARGET } from "./slim-geojson.mjs";

const feature = (iso, extra = {}) => ({
  type: "Feature",
  properties: { ISO_A2: iso, NAME: `Country ${iso}`, POP_EST: 1, ...extra },
  bbox: [0, 0, 1, 1],
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 0],
      ],
    ],
  },
});

describe("slimLand", () => {
  const slim = slimLand({
    type: "FeatureCollection",
    bbox: [-180, -90, 180, 90],
    features: [feature("FR"), feature("AQ"), feature("-99")],
  });

  it("drops Antarctica", () => {
    expect(slim.features.map((f) => f.properties.ISO_A2)).toEqual(["FR", "-99"]);
  });

  it("keeps only ISO_A2 and the geometry", () => {
    expect(slim).toEqual({
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { ISO_A2: "FR" }, geometry: feature("FR").geometry },
        { type: "Feature", properties: { ISO_A2: "-99" }, geometry: feature("-99").geometry },
      ],
    });
  });
});

describe("public/geo/land-110m.v1.geojson", () => {
  // Windows checkouts with core.autocrlf turn the final newline into CRLF.
  const shipped = readFileSync(TARGET, "utf8").replace(/\r\n$/, "\n");

  it("is exactly what scripts/slim-geojson.mjs builds from three-globe's Natural Earth file", () => {
    expect(shipped).toBe(build());
  });

  it("has every country but Antarctica, each with only ISO_A2", () => {
    const source = JSON.parse(readFileSync(SOURCE, "utf8"));
    const land = JSON.parse(shipped);
    expect(land.features).toHaveLength(source.features.length - 1);
    expect(land.features.some((f) => f.properties.ISO_A2 === "AQ")).toBe(false);
    for (const f of land.features) expect(Object.keys(f.properties)).toEqual(["ISO_A2"]);
  });
});
