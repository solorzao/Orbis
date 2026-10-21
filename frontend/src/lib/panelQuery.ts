import type { PanelQuery, Topic } from "@/types/news";
import { windowBounds, windowLabel, type TimeWindow } from "@/lib/timeWindow";

/**
 * Places, links and relations open at once in the Inspect tab (its recent
 * pills); a new one closes the oldest.
 */
export const MAX_PANELS = 5;

/**
 * The query a panel keeps from the moment its dot is clicked: the active
 * topic and the globe's window, its bounds fixed then (a live window, the
 * preset's hours up to `nowMs`). Fixed bounds keep the panel's pages and
 * summary on the stories the dot counted, whatever the topic or window
 * becomes afterwards.
 */
export function panelQuery(activeTopic: Topic, window: TimeWindow, nowMs: number): PanelQuery {
  const topic = activeTopic !== "All" ? activeTopic : undefined;
  const bounds = windowBounds(window, nowMs);
  if (window.kind === "range") return { topic, ...bounds, live: false };
  return { topic, ...bounds, live: true, hours: window.hours };
}

/** The window a panel was opened on: its live preset, or its range. */
export function queryWindow(query: PanelQuery): TimeWindow {
  return query.live && query.hours
    ? { kind: "live", hours: query.hours }
    : { kind: "range", startTime: query.startTime, endTime: query.endTime };
}

/**
 * Whether a panel opened with query `a` shows what a click making `b` asks
 * for: the same topic, and both live over the same hours (their bounds differ
 * only by when they were clicked) or the same range.
 */
export function samePanelQuery(a: PanelQuery, b: PanelQuery): boolean {
  if (a.topic !== b.topic || a.live !== b.live) return false;
  if (a.live) return a.hours === b.hours;
  return a.startTime === b.startTime && a.endTime === b.endTime;
}

/**
 * The place, link or relation to close so one more can open: the oldest of
 * them once MAX_PANELS are open, else null.
 */
export function recentToEvict(
  places: readonly { panelId: string; createdAt: number }[],
  links: readonly { linkId: string; createdAt: number }[],
  relations: readonly { relationId: string; createdAt: number }[] = [],
): string | null {
  if (places.length + links.length + relations.length < MAX_PANELS) return null;
  const all = [
    ...places.map((p) => ({ id: p.panelId, createdAt: p.createdAt })),
    ...links.map((l) => ({ id: l.linkId, createdAt: l.createdAt })),
    ...relations.map((r) => ({ id: r.relationId, createdAt: r.createdAt })),
  ];
  return all.reduce((oldest, r) => (r.createdAt < oldest.createdAt ? r : oldest)).id;
}

/** The window a panel or link was opened on, in words: "last 24 h", "last 7 days" or its range. */
export function queryWindowWords(query: PanelQuery): string {
  const w = queryWindow(query);
  if (w.kind === "range") return windowLabel(w);
  return w.hours === 168 ? "last 7 days" : `last ${w.hours} h`;
}
