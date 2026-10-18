import { describe, it, expect } from "vitest";
import {
  areaPath,
  chartDomain,
  chartPoints,
  dayTicks,
  linePath,
  markerX,
  placeDayLabels,
  rangeForDrag,
  smooth,
  timeForX,
  volumeSeries,
  xForTime,
} from "./volumeChart";

const H = 3_600_000;
// Sunday 11 October 2026, 12:30 UTC
const NOW = Date.UTC(2026, 9, 11, 12, 30);

/** Every number in an SVG path, as [x, y] pairs (M, C and L all take pairs). */
function pathPairs(d: string): [number, number][] {
  const nums = (d.match(/-?\d+(\.\d+)?(e-?\d+)?/g) ?? []).map(Number);
  const pairs: [number, number][] = [];
  for (let i = 0; i < nums.length; i += 2) pairs.push([nums[i], nums[i + 1]]);
  return pairs;
}

describe("chartDomain", () => {
  it("spans the hour seven days ago to the end of the current hour, as /api/news/volume", () => {
    const { start, end } = chartDomain(NOW);
    expect(new Date(start).toISOString()).toBe("2026-10-04T12:00:00.000Z");
    expect(new Date(end).toISOString()).toBe("2026-10-11T13:00:00.000Z");
    expect((end - start) / H).toBe(169);
  });
});

describe("volumeSeries", () => {
  it("puts each hour's count in its slot, zero where the API had nothing", () => {
    const { start, end } = chartDomain(NOW);
    const series = volumeSeries(
      [
        { hour: "2026-10-04T12:00:00Z", count: 4 },
        { hour: "2026-10-11T12:00:00Z", count: 9 },
        { hour: "2026-10-01T00:00:00Z", count: 99 }, // outside the domain
      ],
      start,
      end,
    );
    expect(series).toHaveLength(169);
    expect(series[0]).toBe(4);
    expect(series[168]).toBe(9);
    expect(series.slice(1, 168).every((v) => v === 0)).toBe(true);
  });
});

describe("smooth", () => {
  it("averages each value with its neighbours, fewer at the ends", () => {
    expect(smooth([0, 3, 0, 3, 0], 1)).toEqual([1.5, 1, 2, 1, 1.5]);
    expect(smooth([5, 5, 5], 3)).toEqual([5, 5, 5]);
  });
});

describe("xForTime and timeForX", () => {
  const start = Date.UTC(2026, 9, 4, 12);
  const end = start + 100 * H;

  it("map time linearly across the width", () => {
    expect(xForTime(start, start, end, 500)).toBe(0);
    expect(xForTime(start + 50 * H, start, end, 500)).toBe(250);
    expect(xForTime(end, start, end, 500)).toBe(500);
  });

  it("snaps x to the nearest whole hour, within the domain", () => {
    expect(timeForX(250, start, end, 500)).toBe(start + 50 * H);
    expect(timeForX(252.4, start, end, 500)).toBe(start + 50 * H); // 50.48 h
    expect(timeForX(252.6, start, end, 500)).toBe(start + 51 * H); // 50.52 h
    expect(timeForX(-40, start, end, 500)).toBe(start);
    expect(timeForX(900, start, end, 500)).toBe(end);
  });
});

describe("areaPath and linePath", () => {
  const values = [0, 10, 10, 2, 0, 0, 8, 1];
  const points = chartPoints(values, 160, 40);

  it("place each hour at its centre, zero on the baseline and the peak at the top", () => {
    expect(points).toHaveLength(8);
    expect(points[0]).toEqual({ x: 10, y: 40 });
    expect(points[1]).toEqual({ x: 30, y: 0 });
    expect(points[7].x).toBe(150);
  });

  it("can space the points over more slots than they fill (the current hour left out)", () => {
    expect(chartPoints([4, 2], 100, 10, 4).map((p) => p.x)).toEqual([12.5, 37.5]);
  });

  it("pass through every point", () => {
    const pairs = pathPairs(linePath(points));
    for (const p of points) {
      expect(pairs.some(([x, y]) => Math.abs(x - p.x) < 1e-6 && Math.abs(y - p.y) < 1e-6)).toBe(
        true,
      );
    }
  });

  it("never overshoot: no control point below zero (y > height) or above the peak", () => {
    for (const [, y] of pathPairs(linePath(points))) {
      expect(y).toBeLessThanOrEqual(40 + 1e-9);
      expect(y).toBeGreaterThanOrEqual(-1e-9);
    }
  });

  it("stay flat between equal neighbours (monotone)", () => {
    // Points 1 and 2 are both 10: the segment between them is a straight top.
    const d = linePath(points);
    const segments = d.split("C").slice(1);
    const [c1, c2, end] = pathPairs(segments[1]);
    expect(c1[1]).toBeCloseTo(0);
    expect(c2[1]).toBeCloseTo(0);
    expect(end[1]).toBeCloseTo(0);
  });

  it("close the area down to the baseline", () => {
    const d = areaPath(points, 40);
    expect(d.startsWith(linePath(points))).toBe(true);
    expect(d.endsWith(`L150 40 L10 40 Z`)).toBe(true);
  });

  it("draw nothing without points", () => {
    expect(linePath([])).toBe("");
    expect(areaPath([], 40)).toBe("");
  });
});

describe("dayTicks", () => {
  it("labels each UTC day the domain touches, Sun … Today", () => {
    const { start, end } = chartDomain(NOW);
    const ticks = dayTicks(start, end);
    expect(ticks.map((t) => t.label)).toEqual([
      "Sun",
      "Mon",
      "Tue",
      "Wed",
      "Thu",
      "Fri",
      "Sat",
      "Today",
    ]);
    // The first day shows from 12:00, today until 13:00: labels sit mid-way of what shows.
    expect(ticks[0]).toMatchObject({ dayStart: Date.UTC(2026, 9, 4), hours: 12 });
    expect(ticks[0].t).toBe(Date.UTC(2026, 9, 4, 18));
    expect(ticks[1]).toMatchObject({ dayStart: Date.UTC(2026, 9, 5), hours: 24 });
    expect(ticks[1].t).toBe(Date.UTC(2026, 9, 5, 12));
    expect(ticks[7]).toMatchObject({ dayStart: Date.UTC(2026, 9, 11), hours: 13 });
    expect(ticks[7].t).toBe(Date.UTC(2026, 9, 11, 6, 30));
  });

  it("uses UTC days whatever the local time zone", () => {
    // 23:30 UTC: still Sunday in UTC, Monday in zones east of it.
    const { start, end } = chartDomain(Date.UTC(2026, 9, 11, 23, 30));
    expect(dayTicks(start, end).at(-1)).toMatchObject({
      label: "Today",
      dayStart: Date.UTC(2026, 9, 11),
    });
  });
});

describe("rangeForDrag", () => {
  const start = Date.UTC(2026, 9, 4, 12);
  const end = start + 100 * H; // 500px: 5px an hour

  it("snaps both ends to whole hours, either way round", () => {
    expect(rangeForDrag(101, 149, start, end, 500)).toEqual({
      startTime: new Date(start + 20 * H).toISOString(),
      endTime: new Date(start + 30 * H).toISOString(),
    });
    expect(rangeForDrag(149, 101, start, end, 500)).toEqual(
      rangeForDrag(101, 149, start, end, 500),
    );
  });

  it("makes a click or a short drag the hour under the pointer", () => {
    expect(rangeForDrag(103, 104, start, end, 500)).toEqual({
      startTime: new Date(start + 20 * H).toISOString(),
      endTime: new Date(start + 21 * H).toISOString(),
    });
  });

  it("keeps at least an hour inside the chart at its right edge", () => {
    expect(rangeForDrag(499, 520, start, end, 500)).toEqual({
      startTime: new Date(end - H).toISOString(),
      endTime: new Date(end).toISOString(),
    });
  });

  it("stays within the chart", () => {
    expect(rangeForDrag(-50, 900, start, end, 500)).toEqual({
      startTime: new Date(start).toISOString(),
      endTime: new Date(end).toISOString(),
    });
  });
});

describe("placeDayLabels", () => {
  const W = 400;
  const place = (now: number) => {
    const { start, end } = chartDomain(now);
    return placeDayLabels(dayTicks(start, end), (t) => xForTime(t, start, end, W), W);
  };
  const halfWidth = (label: string) => (label.length * 6.6) / 2;

  it("labels every day with room for it", () => {
    expect(place(NOW).map((l) => l.tick.label)).toEqual([
      "Sun",
      "Mon",
      "Tue",
      "Wed",
      "Thu",
      "Fri",
      "Sat",
      "Today",
    ]);
  });

  it("never lets two labels overlap: early in the UTC day, the day before Today gives way", () => {
    // 02:10 UTC: Today shows three hours, squeezed against yesterday's label.
    const labels = place(Date.UTC(2026, 9, 12, 2, 10));
    expect(labels.map((l) => l.tick.label)).toEqual([
      "Mon",
      "Tue",
      "Wed",
      "Thu",
      "Fri",
      "Sat",
      "Today",
    ]);
    for (let i = 1; i < labels.length; i++) {
      const gap = labels[i].x - labels[i - 1].x;
      expect(gap).toBeGreaterThanOrEqual(
        halfWidth(labels[i].tick.label) + halfWidth(labels[i - 1].tick.label),
      );
    }
  });

  it("keeps every label inside the chart", () => {
    for (const now of [NOW, Date.UTC(2026, 9, 12, 0, 20), Date.UTC(2026, 9, 12, 23, 50)]) {
      for (const l of place(now)) {
        expect(l.x - halfWidth(l.tick.label)).toBeGreaterThanOrEqual(0);
        expect(l.x + halfWidth(l.tick.label)).toBeLessThanOrEqual(W);
      }
    }
  });
});

describe("markerX", () => {
  const start = Date.UTC(2026, 9, 11, 12);
  const end = start + 169 * 3_600_000;

  it("places a time on the chart, as the window band is placed", () => {
    expect(markerX(start, start, end, 676)).toBe(0);
    expect(markerX(start + 14 * 3_600_000, start, end, 676)).toBeCloseTo(56);
    expect(markerX(end, start, end, 676)).toBe(676);
  });

  it("is null for a time off the chart (the last visit more than 7 days ago)", () => {
    expect(markerX(start - 1, start, end, 676)).toBeNull();
    expect(markerX(end + 1, start, end, 676)).toBeNull();
  });
});
