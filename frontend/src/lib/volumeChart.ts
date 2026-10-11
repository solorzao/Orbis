/**
 * Geometry for the timeline's 7-day story-volume chart (pure, so it is unit
 * tested; TimelineCapsule draws it). Times are epoch milliseconds, days and
 * hours are UTC.
 */
import { HOUR_MS, utcWeekday } from "@/lib/timeWindow";

const DAY_MS = 24 * HOUR_MS;

/** Days the chart covers, as GET /api/news/volume?days=7. */
export const CHART_DAYS = 7;

/**
 * The chart's span: from the hour seven days ago to the end of the current
 * hour, the same hours /api/news/volume returns (one slot per hour).
 */
export function chartDomain(now: number): { start: number; end: number } {
  const hour = Math.floor(now / HOUR_MS) * HOUR_MS;
  return { start: hour - CHART_DAYS * DAY_MS, end: hour + HOUR_MS };
}

/** One count per hour of [start, end); hours the API did not return count 0. */
export function volumeSeries(
  points: readonly { hour: string; count: number }[],
  start: number,
  end: number,
): number[] {
  const series = new Array<number>(Math.round((end - start) / HOUR_MS)).fill(0);
  for (const p of points) {
    const i = Math.round((Date.parse(p.hour) - start) / HOUR_MS);
    if (i >= 0 && i < series.length) series[i] = p.count;
  }
  return series;
}

/** Each value averaged with up to `radius` neighbours on each side (fewer at the ends). */
export function smooth(values: readonly number[], radius: number): number[] {
  return values.map((_, i) => {
    let sum = 0;
    let n = 0;
    for (let k = Math.max(0, i - radius); k <= Math.min(values.length - 1, i + radius); k++) {
      sum += values[k];
      n++;
    }
    return sum / n;
  });
}

export function xForTime(t: number, start: number, end: number, width: number): number {
  return ((t - start) / (end - start)) * width;
}

/** The whole hour nearest to `x`, kept within [start, end]. */
export function timeForX(x: number, start: number, end: number, width: number): number {
  const hours = Math.round(((x / width) * (end - start)) / HOUR_MS);
  return Math.min(end, Math.max(start, start + hours * HOUR_MS));
}

/** Pointer travel (px) below which a drag on the chart counts as a click. */
const CLICK_PX = 3;

/**
 * The range a drag from x0 to x1 picks (either direction): whole hours, at
 * least one, within [start, end]. A click picks the hour under the pointer.
 */
export function rangeForDrag(
  x0: number,
  x1: number,
  start: number,
  end: number,
  width: number,
): { startTime: string; endTime: string } {
  let a: number;
  let b: number;
  if (Math.abs(x1 - x0) < CLICK_PX) {
    const hours = Math.floor(((Math.min(x0, x1) / width) * (end - start)) / HOUR_MS);
    a = Math.min(end - HOUR_MS, Math.max(start, start + hours * HOUR_MS));
    b = a + HOUR_MS;
  } else {
    a = timeForX(Math.min(x0, x1), start, end, width);
    b = timeForX(Math.max(x0, x1), start, end, width);
    if (b - a < HOUR_MS) {
      if (a + HOUR_MS <= end) b = a + HOUR_MS;
      else a = b - HOUR_MS;
    }
  }
  return { startTime: new Date(a).toISOString(), endTime: new Date(b).toISOString() };
}

export interface ChartPoint {
  x: number;
  y: number;
}

/** A point per value, at its slot's centre; zero on the baseline (y = height), the peak at y = 0. */
export function chartPoints(
  values: readonly number[],
  width: number,
  height: number,
): ChartPoint[] {
  const max = Math.max(0, ...values);
  const step = width / values.length;
  return values.map((v, i) => ({
    x: (i + 0.5) * step,
    y: max > 0 ? height - (v / max) * height : height,
  }));
}

const fmt = (n: number) => String(Math.round(n * 100) / 100);
const sign = (n: number) => (n < 0 ? -1 : 1);

/**
 * A smooth curve through the points: a monotone cubic (Steffen's tangents),
 * so it never overshoots between two points. Every control point stays
 * between its segment's ends, so the area never dips below zero.
 */
export function linePath(points: readonly ChartPoint[]): string {
  if (points.length === 0) return "";
  const n = points.length;
  const slope = (i: number) => (points[i + 1].y - points[i].y) / (points[i + 1].x - points[i].x);
  const tangents = points.map((p, i) => {
    if (n < 2) return 0;
    if (i === 0) return slope(0);
    if (i === n - 1) return slope(n - 2);
    const s0 = slope(i - 1);
    const s1 = slope(i);
    const h0 = p.x - points[i - 1].x;
    const h1 = points[i + 1].x - p.x;
    const mid = (s0 * h1 + s1 * h0) / (h0 + h1);
    return (sign(s0) + sign(s1)) * Math.min(Math.abs(s0), Math.abs(s1), 0.5 * Math.abs(mid)) || 0;
  });
  let d = `M${fmt(points[0].x)} ${fmt(points[0].y)}`;
  for (let i = 0; i < n - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const third = (b.x - a.x) / 3;
    d +=
      ` C${fmt(a.x + third)} ${fmt(a.y + tangents[i] * third)}` +
      ` ${fmt(b.x - third)} ${fmt(b.y - tangents[i + 1] * third)} ${fmt(b.x)} ${fmt(b.y)}`;
  }
  return d;
}

/** The curve closed down to the baseline (y = height), for the area fill. */
export function areaPath(points: readonly ChartPoint[], height: number): string {
  if (points.length === 0) return "";
  const first = points[0];
  const last = points[points.length - 1];
  return `${linePath(points)} L${fmt(last.x)} ${fmt(height)} L${fmt(first.x)} ${fmt(height)} Z`;
}

export interface DayTick {
  /** The UTC day's midnight. */
  dayStart: number;
  /** Where the label goes: the middle of the part of the day the chart shows. */
  t: number;
  /** Hours of the day the chart shows (the first day and today are partial). */
  hours: number;
  /** "Sun", or "Today" for the current UTC day. */
  label: string;
}

/** A tick per UTC day [start, end) touches, oldest first; the last is "Today". */
export function dayTicks(start: number, end: number): DayTick[] {
  const ticks: DayTick[] = [];
  const lastDay = Math.floor((end - 1) / DAY_MS) * DAY_MS;
  for (let day = Math.floor(start / DAY_MS) * DAY_MS; day <= lastDay; day += DAY_MS) {
    const from = Math.max(day, start);
    const to = Math.min(day + DAY_MS, end);
    ticks.push({
      dayStart: day,
      t: (from + to) / 2,
      hours: (to - from) / HOUR_MS,
      label: day === lastDay ? "Today" : utcWeekday(day),
    });
  }
  return ticks;
}
