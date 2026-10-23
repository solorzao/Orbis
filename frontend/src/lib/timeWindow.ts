/**
 * The globe's time window: the last N hours up to now ("live"), or a fixed
 * range picked on the timeline. The globe fetch, the panels (frozen at click
 * time, see panelQuery) and the timeline all read this one value.
 */

export type LiveHours = 1 | 6 | 24 | 168;

export type TimeWindow =
  { kind: "live"; hours: LiveHours } | { kind: "range"; startTime: string; endTime: string };

export const DEFAULT_WINDOW: TimeWindow = { kind: "live", hours: 24 };

/** The timeline's presets, shortest first. */
export const LIVE_PRESETS: readonly { label: string; hours: LiveHours }[] = [
  { label: "1h", hours: 1 },
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
];

export const HOUR_MS = 3_600_000;

/**
 * Query params for /api/news. A live window asks for its timespan, which the
 * backend counts back from its own now (so no `now` here); a range sends its
 * bounds, and the backend then ignores the timespan.
 */
export function windowQuery(w: TimeWindow): {
  timespan: string;
  startTime?: string;
  endTime?: string;
} {
  if (w.kind === "range") return { timespan: "24h", startTime: w.startTime, endTime: w.endTime };
  return { timespan: `${w.hours}h` };
}

/** Concrete bounds, e.g. for panel queries frozen at click time. */
export function windowBounds(w: TimeWindow, now: number): { startTime: string; endTime: string } {
  if (w.kind === "range") return { startTime: w.startTime, endTime: w.endTime };
  return {
    startTime: new Date(now - w.hours * HOUR_MS).toISOString(),
    endTime: new Date(now).toISOString(),
  };
}

export function sameWindow(a: TimeWindow, b: TimeWindow): boolean {
  if (a.kind === "live") return b.kind === "live" && a.hours === b.hours;
  return b.kind === "range" && a.startTime === b.startTime && a.endTime === b.endTime;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

/** "Tue", the UTC weekday of `ms`. */
export function utcWeekday(ms: number): string {
  return WEEKDAYS[new Date(ms).getUTCDay()];
}

/** "14:00", the UTC time of `ms`. */
export function utcTime(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** "Tue 14:00 UTC", for a single instant (the timeline's range inputs). */
export function utcLabel(ms: number): string {
  return `${utcWeekday(ms)} ${utcTime(ms)} UTC`;
}

const utcDay = (ms: number) => Math.floor(ms / (24 * HOUR_MS));

/** "Last 6 h, live", "Last 7 days, live" or "Tue 14:00 – Wed 02:00 UTC". */
export function windowLabel(w: TimeWindow): string {
  if (w.kind === "live") return w.hours === 168 ? "Last 7 days, live" : `Last ${w.hours} h, live`;
  const start = Date.parse(w.startTime);
  const end = Date.parse(w.endTime);
  const from = `${utcWeekday(start)} ${utcTime(start)}`;
  const to = utcDay(start) === utcDay(end) ? utcTime(end) : `${utcWeekday(end)} ${utcTime(end)}`;
  return `${from} – ${to} UTC`;
}
