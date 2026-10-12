import type { PanelQuery, Topic } from "@/types/news";
import { windowBounds, type TimeWindow } from "@/lib/timeWindow";

/** Places open at once in the Stories tab (Recent places); a new one closes the oldest. */
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
