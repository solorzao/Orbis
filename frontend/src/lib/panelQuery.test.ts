import { describe, it, expect } from "vitest";
import {
  MAX_PANELS,
  panelQuery,
  queryWindow,
  queryWindowWords,
  recentToEvict,
  samePanelQuery,
} from "./panelQuery";
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

describe("queryWindow", () => {
  it("is the window a panel was opened on: a live preset, or the range", () => {
    const live = panelQuery(
      "Politics",
      { kind: "live", hours: 6 },
      Date.parse("2026-10-12T14:30:00Z"),
    );
    expect(queryWindow(live)).toEqual({ kind: "live", hours: 6 });
    const range = {
      kind: "range" as const,
      startTime: "2026-10-06T00:00:00.000Z",
      endTime: "2026-10-07T00:00:00.000Z",
    };
    expect(queryWindow(panelQuery("All", range, 0))).toEqual(range);
  });
});

describe("recentToEvict", () => {
  const place = (panelId: string, createdAt: number) => ({ panelId, createdAt });
  const link = (linkId: string, createdAt: number) => ({ linkId, createdAt });

  it("makes room for one more by the oldest place or link, once MAX_PANELS are open", () => {
    expect(MAX_PANELS).toBe(5);
    const places = [place("p1", 1), place("p3", 3)];
    const links = [link("l0", 0), link("l2", 2)];
    expect(recentToEvict(places, links)).toBeNull(); // 4 open: room for a fifth
    expect(recentToEvict([...places, place("p4", 4)], links)).toBe("l0");
    expect(
      recentToEvict(
        [place("p0", 0), place("p4", 4)],
        [...links.slice(1), link("l5", 5), link("l6", 6)],
      ),
    ).toBe("p0");
  });

  const relation = (relationId: string, createdAt: number) => ({ relationId, createdAt });

  it("counts relations among them, and evicts the oldest of all three", () => {
    const places = [place("p1", 1), place("p3", 3)];
    const links = [link("l2", 2)];
    const relations = [relation("r4", 4)];
    expect(recentToEvict(places, links, relations)).toBeNull(); // 4 open
    expect(recentToEvict(places, links, [relation("r0", 0), ...relations])).toBe("r0");
    expect(recentToEvict(places, links, [...relations, relation("r5", 5)])).toBe("p1");
  });
});

describe("queryWindowWords", () => {
  it("says the window a panel or link was opened on", () => {
    expect(queryWindowWords(panelQuery("All", DEFAULT_WINDOW, NOW))).toBe("last 24 h");
    expect(queryWindowWords(panelQuery("All", { kind: "live", hours: 168 }, NOW))).toBe(
      "last 7 days",
    );
    const range = { startTime: "2026-10-08T12:00:00.000Z", endTime: "2026-10-09T12:00:00.000Z" };
    expect(queryWindowWords(panelQuery("All", { kind: "range", ...range }, NOW))).toBe(
      "Thu 12:00 – Fri 12:00 UTC",
    );
  });
});
