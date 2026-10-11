import { describe, it, expect } from "vitest";
import { LIVE_WINDOW_HOURS, panelQuery, samePanelQuery } from "./panelQuery";

const NOW = Date.UTC(2026, 9, 11, 12, 30, 0);

describe("panelQuery", () => {
  it("pins a live panel to the last 24 hours up to the click, as the live dots count", () => {
    expect(LIVE_WINDOW_HOURS).toBe(24);
    expect(panelQuery("All", null, NOW)).toEqual({
      topic: undefined,
      startTime: "2026-10-10T12:30:00.000Z",
      endTime: "2026-10-11T12:30:00.000Z",
      live: true,
    });
  });

  it("keeps the globe's window when one is selected", () => {
    const window = { startTime: "2026-10-08T12:00:00.000Z", endTime: "2026-10-09T12:00:00.000Z" };
    expect(panelQuery("Conflict", window, NOW)).toEqual({
      topic: "Conflict",
      ...window,
      live: false,
    });
  });

  it("filters by the active topic, not by 'All'", () => {
    expect(panelQuery("Climate", null, NOW).topic).toBe("Climate");
    expect(panelQuery("All", null, NOW).topic).toBeUndefined();
  });
});

describe("samePanelQuery", () => {
  const day = { startTime: "2026-10-08T12:00:00.000Z", endTime: "2026-10-09T12:00:00.000Z" };

  it("matches live panels on topic alone: their bounds move with each click", () => {
    expect(
      samePanelQuery(panelQuery("All", null, NOW), panelQuery("All", null, NOW + 60_000)),
    ).toBe(true);
    expect(samePanelQuery(panelQuery("All", null, NOW), panelQuery("Health", null, NOW))).toBe(
      false,
    );
  });

  it("matches windowed panels on topic and window", () => {
    expect(samePanelQuery(panelQuery("Health", day, NOW), panelQuery("Health", day, NOW))).toBe(
      true,
    );
    const nextDay = { startTime: day.endTime, endTime: "2026-10-10T12:00:00.000Z" };
    expect(samePanelQuery(panelQuery("Health", day, NOW), panelQuery("Health", nextDay, NOW))).toBe(
      false,
    );
  });

  it("never matches a live panel with a windowed one", () => {
    expect(samePanelQuery(panelQuery("All", null, NOW), panelQuery("All", day, NOW))).toBe(false);
  });
});
