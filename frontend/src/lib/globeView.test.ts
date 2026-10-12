import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";
import {
  HEATMAP,
  HEAT_COLORS,
  driftLng,
  durationMs,
  heatColor,
  heatmapPoints,
  hexToRgba,
  pointTooltipHtml,
  projectedRadius,
  ringRepeatMs,
} from "./globeView";
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

describe("ringRepeatMs", () => {
  it("pulses every 2.5 s with full motion", () => {
    expect(ringRepeatMs({ reduced: false, lowPower: false })).toBe(2500);
  });

  it.each([
    { reduced: true, lowPower: false },
    { reduced: false, lowPower: true },
    { reduced: true, lowPower: true },
  ])("emits one ring and stops when reduced=$reduced, lowPower=$lowPower", (motion) => {
    expect(ringRepeatMs(motion)).toBe(0);
  });
});

describe("heatmapPoints", () => {
  const places = Array.from({ length: 300 }, (_, i) => ({ id: i, count: (i * 37) % 101 }));

  it("uses every place where WebGPU computes the heatmap", () => {
    expect(heatmapPoints(places, { gpu: true })).toHaveLength(300);
  });

  it("keeps the busiest places on the main-thread fallback, busiest first", () => {
    const heat = heatmapPoints(places, { gpu: false });
    expect(heat).toHaveLength(HEATMAP.maxPointsWithoutGpu);
    expect(HEATMAP.maxPointsWithoutGpu).toBe(60);
    const counts = heat.map((p) => p.count);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
    const quietestKept = Math.min(...counts);
    const dropped = places.filter((p) => !heat.includes(p));
    expect(dropped.every((p) => p.count <= quietestKept)).toBe(true);
  });

  it("leaves the input alone", () => {
    const copy = [...places];
    heatmapPoints(places, { gpu: false });
    expect(places).toEqual(copy);
  });

  it("matches the mockup's heatmap settings", () => {
    expect(HEATMAP).toMatchObject({
      bandwidth: 1.8,
      colorSaturation: 1.8,
      baseAltitude: 0.006,
      topAltitude: 0.04,
    });
  });
});

describe("heatColor", () => {
  // three-globe reads "rgba(r, g, b, a)" with whole-number channels.
  const RGBA = /^rgba\((\d+),(\d+),(\d+),([\d.]+)\)$/;
  const parse = (c: string) => {
    const m = RGBA.exec(c);
    if (!m) throw new Error(`not rgba(): ${c}`);
    return { rgb: [Number(m[1]), Number(m[2]), Number(m[3])], a: Number(m[4]) };
  };
  const rgbOf = (hex: string) => {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };

  it("is clear where there is no heat, so the land shows through", () => {
    expect(parse(heatColor(0)).a).toBe(0);
  });

  it("grows more opaque with the heat, never less", () => {
    let last = -1;
    for (let i = 0; i <= 100; i++) {
      const { a } = parse(heatColor(i / 100));
      expect(a).toBeGreaterThanOrEqual(last);
      last = a;
    }
    expect(last).toBeGreaterThan(0.9);
  });

  it("runs periwinkle, then lavender, to near-white at the peak", () => {
    expect(parse(heatColor(0.35)).rgb).toEqual(rgbOf(HEAT_COLORS.periwinkle));
    expect(parse(heatColor(0.7)).rgb).toEqual(rgbOf(HEAT_COLORS.lavender));
    expect(parse(heatColor(1)).rgb).toEqual(rgbOf(HEAT_COLORS.peak));
  });

  it("clamps outside 0-1", () => {
    expect(heatColor(-1)).toBe(heatColor(0));
    expect(heatColor(2)).toBe(heatColor(1));
  });

  it("uses the Soft Orbit tokens, not the surge colour", () => {
    // The canvas can't read CSS variables; this keeps the literals equal to them.
    const css = readFileSync(path.resolve(__dirname, "../app/tokens.css"), "utf8");
    const token = (name: string) =>
      css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6});`))?.[1].toLowerCase();
    expect(HEAT_COLORS.periwinkle).toBe(token("accent-periwinkle"));
    expect(HEAT_COLORS.lavender).toBe(token("accent-lavender"));
    expect(HEAT_COLORS.peak).toBe(token("text-primary"));
    const warning = token("signal-warning");
    expect(warning).toBeTruthy();
    expect(Object.values(HEAT_COLORS)).not.toContain(warning);
  });
});
