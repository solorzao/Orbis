import { describe, it, expect } from "vitest";
import { driftLng, durationMs, hexToRgba, pointTooltipHtml, projectedRadius } from "./globeView";
import type { GlobePoint } from "@/types/news";

describe("projectedRadius", () => {
  it("is the on-screen radius of the globe's silhouette (mockup globeGeom)", () => {
    // 900px tall view, 50deg vertical fov, camera 2.5 globe radii above the surface.
    const expected = (450 * Math.tan(Math.asin(1 / 3.5))) / Math.tan((25 * Math.PI) / 180);
    expect(projectedRadius(900, 50, 2.5)).toBeCloseTo(expected, 6);
    expect(projectedRadius(900, 50, 2.5)).toBeCloseTo(287.7, 1);
  });

  it("shrinks as the camera climbs and grows with the viewport", () => {
    expect(projectedRadius(900, 50, 4)).toBeLessThan(projectedRadius(900, 50, 2.5));
    expect(projectedRadius(1800, 50, 2.5)).toBeCloseTo(2 * projectedRadius(900, 50, 2.5), 6);
  });
});

describe("driftLng", () => {
  const PERIOD = 40_000;

  it("swings 5 degrees east and west over one period", () => {
    expect(driftLng(0, PERIOD)).toBeCloseTo(0, 6);
    expect(driftLng(PERIOD / 4, PERIOD)).toBeCloseTo(5, 6);
    expect(driftLng(PERIOD / 2, PERIOD)).toBeCloseTo(0, 6);
    expect(driftLng((3 * PERIOD) / 4, PERIOD)).toBeCloseTo(-5, 6);
    expect(driftLng(PERIOD, PERIOD)).toBeCloseTo(0, 6);
  });

  it("never leaves the +-5 degree band", () => {
    for (let t = 0; t < PERIOD * 2; t += 777) {
      expect(Math.abs(driftLng(t, PERIOD))).toBeLessThanOrEqual(5);
    }
  });
});

describe("durationMs", () => {
  it("reads a CSS duration token in ms or s", () => {
    expect(durationMs("40000ms", 1)).toBe(40000);
    expect(durationMs(" 40s ", 1)).toBe(40000);
  });

  it("falls back when the token is missing or not a duration", () => {
    expect(durationMs("", 40000)).toBe(40000);
    expect(durationMs("slow", 40000)).toBe(40000);
  });
});

describe("hexToRgba", () => {
  it("turns a token hex into an rgba() with the given alpha", () => {
    expect(hexToRgba("#6f78c9", 0.55)).toBe("rgba(111,120,201,0.55)");
    expect(hexToRgba(" #FFFFFF ", 1)).toBe("rgba(255,255,255,1)");
  });
});

describe("pointTooltipHtml", () => {
  const point = (overrides: Partial<GlobePoint> = {}): GlobePoint => ({
    id: "api-0",
    lat: 48.86,
    lng: 2.35,
    size: 1,
    color: "#72ddb2",
    articles: [],
    isCluster: true,
    count: 5,
    topic: "Climate",
    ...overrides,
  });

  it("shows the story count and the place", () => {
    const html = pointTooltipHtml(point({ locationName: "Paris, France" }));
    expect(html).toContain("5 stories");
    expect(html).toContain("Paris, France");
  });

  it("escapes the place name, which comes from news data", () => {
    const html = pointTooltipHtml(point({ locationName: "<img src=x onerror=alert(1)>" }));
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
  });

  it("prints the count as a number, whatever arrives", () => {
    const html = pointTooltipHtml(point({ count: "<b>9</b>" as unknown as number }));
    expect(html).not.toContain("<b>");
    expect(html).toContain("0 stories");
  });

  it("leaves out the place when there is none", () => {
    expect(pointTooltipHtml(point())).not.toContain("•");
  });
});
