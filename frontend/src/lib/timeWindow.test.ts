import { describe, it, expect } from "vitest";
import {
  DEFAULT_WINDOW,
  LIVE_PRESETS,
  sameWindow,
  windowBounds,
  windowLabel,
  windowQuery,
  type LiveHours,
  type TimeWindow,
} from "./timeWindow";

// Sunday 11 October 2026, 12:30 UTC
const NOW = Date.UTC(2026, 9, 11, 12, 30, 0);

// Tuesday 14:00 to Wednesday 02:00 UTC: across midnight
const TUE_NIGHT: TimeWindow = {
  kind: "range",
  startTime: "2026-10-13T14:00:00.000Z",
  endTime: "2026-10-14T02:00:00.000Z",
};

describe("DEFAULT_WINDOW", () => {
  it("is the last 24 hours, live", () => {
    expect(DEFAULT_WINDOW).toEqual({ kind: "live", hours: 24 });
  });
});

describe("windowQuery", () => {
  it.each([
    [1, "1h"],
    [6, "6h"],
    [24, "24h"],
    [168, "168h"],
  ] as [LiveHours, string][])("asks for the last %i hours as timespan %s", (hours, timespan) => {
    expect(windowQuery({ kind: "live", hours })).toEqual({ timespan });
  });

  it("passes a range through", () => {
    expect(windowQuery(TUE_NIGHT)).toEqual({
      timespan: "24h",
      startTime: TUE_NIGHT.startTime,
      endTime: TUE_NIGHT.endTime,
    });
  });
});

describe("windowBounds", () => {
  it("ends a live window at now", () => {
    expect(windowBounds({ kind: "live", hours: 6 }, NOW)).toEqual({
      startTime: "2026-10-11T06:30:00.000Z",
      endTime: "2026-10-11T12:30:00.000Z",
    });
    expect(windowBounds({ kind: "live", hours: 168 }, NOW).startTime).toBe(
      "2026-10-04T12:30:00.000Z",
    );
  });

  it("keeps a range as it is", () => {
    expect(windowBounds(TUE_NIGHT, NOW)).toEqual({
      startTime: TUE_NIGHT.startTime,
      endTime: TUE_NIGHT.endTime,
    });
  });
});

describe("windowLabel", () => {
  it.each([
    [1, "Last 1 h, live"],
    [6, "Last 6 h, live"],
    [24, "Last 24 h, live"],
    [168, "Last 7 days, live"],
  ] as [LiveHours, string][])("labels the last %i hours %j", (hours, label) => {
    expect(windowLabel({ kind: "live", hours })).toBe(label);
  });

  it("labels a range across midnight with both days, in UTC", () => {
    expect(windowLabel(TUE_NIGHT)).toBe("Tue 14:00 – Wed 02:00 UTC");
  });

  it("names the day once for a range within one UTC day", () => {
    expect(
      windowLabel({
        kind: "range",
        startTime: "2026-10-13T09:00:00.000Z",
        endTime: "2026-10-13T17:00:00.000Z",
      }),
    ).toBe("Tue 09:00 – 17:00 UTC");
  });
});

describe("presets", () => {
  it("offers 1h, 6h, 24h and 7d", () => {
    expect(LIVE_PRESETS.map((p) => [p.label, p.hours])).toEqual([
      ["1h", 1],
      ["6h", 6],
      ["24h", 24],
      ["7d", 168],
    ]);
  });

  it("matches windows by kind and value", () => {
    expect(sameWindow({ kind: "live", hours: 6 }, { kind: "live", hours: 6 })).toBe(true);
    expect(sameWindow({ kind: "live", hours: 6 }, { kind: "live", hours: 24 })).toBe(false);
    expect(sameWindow(TUE_NIGHT, { ...TUE_NIGHT })).toBe(true);
    expect(sameWindow(TUE_NIGHT, DEFAULT_WINDOW)).toBe(false);
  });
});
