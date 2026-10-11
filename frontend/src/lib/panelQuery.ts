import type { PanelQuery, Topic } from "@/types/news";

/**
 * Hours the live globe covers: the page asks for this timespan, and the
 * backend's live dots count stories with published_at >= now minus it.
 */
export const LIVE_WINDOW_HOURS = 24;

/**
 * The query a panel keeps from the moment its dot is clicked: the active
 * topic and the globe's window, or live, the last LIVE_WINDOW_HOURS up to
 * `nowMs`. Fixed bounds keep the panel's pages and summary on the stories the
 * dot counted, whatever the topic or window becomes afterwards.
 */
export function panelQuery(
  activeTopic: Topic,
  window: { startTime: string; endTime: string } | null,
  nowMs: number,
): PanelQuery {
  const topic = activeTopic !== "All" ? activeTopic : undefined;
  if (window) return { topic, startTime: window.startTime, endTime: window.endTime };
  return {
    topic,
    startTime: new Date(nowMs - LIVE_WINDOW_HOURS * 3_600_000).toISOString(),
    endTime: new Date(nowMs).toISOString(),
  };
}
