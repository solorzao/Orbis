import { describe, it, expect } from "vitest";
import { panelQuery, samePanelQuery } from "./panelQuery";
import { DEFAULT_WINDOW, type TimeWindow } from "./timeWindow";

const NOW = Date.UTC(2026, 9, 11, 12, 30, 0);
const LIVE_6H: TimeWindow = { kind: "live", hours: 6 };

describe("panelQuery", () => {
  it("pins a live panel to the preset's hours up to the click, as the live dots count", () => {
    expect(panelQuery("All", DEFAULT_WINDOW, NOW)).toEqual({
      topic: undefined,
      startTime: "2026-10-10T12:30:00.000Z",
      endTime: "2026-10-11T12:30:00.000Z",
      live: true,
      hours: 24,
    });
    expect(panelQuery("All", LIVE_6H, NOW)).toMatchObject({
      startTime: "2026-10-11T06:30:00.000Z",
      endTime: "2026-10-11T12:30:00.000Z",
      hours: 6,
    });
    expect(panelQuery("All", { kind: "live", hours: 168 }, NOW).startTime).toBe(
      "2026-10-04T12:30:00.000Z",
    );
  });

  it("keeps the globe's range when one is selected", () => {
    const range = { startTime: "2026-10-08T12:00:00.000Z", endTime: "2026-10-09T12:00:00.000Z" };
    expect(panelQuery("Conflict", { kind: "range", ...range }, NOW)).toEqual({
      topic: "Conflict",
      ...range,
      live: false,
    });
  });

  it("filters by the active topic, not by 'All'", () => {
    expect(panelQuery("Climate", DEFAULT_WINDOW, NOW).topic).toBe("Climate");
    expect(panelQuery("All", DEFAULT_WINDOW, NOW).topic).toBeUndefined();
  });
});

describe("samePanelQuery", () => {
  const day: TimeWindow = {
    kind: "range",
    startTime: "2026-10-08T12:00:00.000Z",
    endTime: "2026-10-09T12:00:00.000Z",
  };

  it("matches live panels on topic and hours: their bounds move with each click", () => {
    expect(
      samePanelQuery(
        panelQuery("All", DEFAULT_WINDOW, NOW),
        panelQuery("All", DEFAULT_WINDOW, NOW + 60_000),
      ),
    ).toBe(true);
    expect(
      samePanelQuery(
        panelQuery("All", DEFAULT_WINDOW, NOW),
        panelQuery("Health", DEFAULT_WINDOW, NOW),
      ),
    ).toBe(false);
    expect(
      samePanelQuery(panelQuery("All", DEFAULT_WINDOW, NOW), panelQuery("All", LIVE_6H, NOW)),
    ).toBe(false);
  });

  it("matches ranged panels on topic and range", () => {
    expect(samePanelQuery(panelQuery("Health", day, NOW), panelQuery("Health", day, NOW))).toBe(
      true,
    );
    const nextDay: TimeWindow = {
      kind: "range",
      startTime: "2026-10-09T12:00:00.000Z",
      endTime: "2026-10-10T12:00:00.000Z",
    };
    expect(samePanelQuery(panelQuery("Health", day, NOW), panelQuery("Health", nextDay, NOW))).toBe(
      false,
    );
  });

  it("never matches a live panel with a ranged one", () => {
    expect(
      samePanelQuery(panelQuery("All", DEFAULT_WINDOW, NOW), panelQuery("All", day, NOW)),
    ).toBe(false);
  });
});
