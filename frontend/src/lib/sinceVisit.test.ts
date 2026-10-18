import { describe, it, expect, vi, afterEach } from "vitest";
import {
  floorSince,
  readSinceDismissed,
  showSince,
  sinceAgo,
  sinceRange,
  sinceSummary,
  writeSinceDismissed,
} from "./sinceVisit";

const MIN = 60_000;
const H = 60 * MIN;
const D = 24 * H;
// Sunday 18 October 2026, 16:37:21 UTC
const NOW = Date.UTC(2026, 9, 18, 16, 37, 21);
const iso = (ms: number) => new Date(ms).toISOString();

describe("showSince", () => {
  it("shows for a last visit at least 1 hour and at most 7 days ago", () => {
    expect(showSince(null, NOW)).toBe(false); // a first visit
    expect(showSince(NOW - 59 * MIN, NOW)).toBe(false);
    expect(showSince(NOW - H, NOW)).toBe(true);
    expect(showSince(NOW - 14 * H, NOW)).toBe(true);
    expect(showSince(NOW - 7 * D, NOW)).toBe(true);
    expect(showSince(NOW - 7 * D - MIN, NOW)).toBe(false);
    expect(showSince(NOW + 5 * MIN, NOW)).toBe(false); // a clock ahead
  });
});

describe("floorSince", () => {
  it("floors to the quarter hour within 24 hours, as the server does", () => {
    expect(iso(floorSince(Date.UTC(2026, 9, 18, 2, 44, 59), NOW))).toBe("2026-10-18T02:30:00.000Z");
    // Exactly 24 h back is still within the first tier.
    const day = NOW - D; // 2026-10-17T16:37:21Z
    expect(iso(floorSince(day, NOW))).toBe("2026-10-17T16:30:00.000Z");
  });

  it("floors to the hour beyond 24 hours, up to 72", () => {
    expect(iso(floorSince(NOW - D - MIN, NOW))).toBe("2026-10-17T16:00:00.000Z");
    expect(iso(floorSince(NOW - 3 * D, NOW))).toBe("2026-10-15T16:00:00.000Z");
  });

  it("floors to 6 hours beyond 72 hours, and never further back than 7 days", () => {
    expect(iso(floorSince(NOW - 3 * D - MIN, NOW))).toBe("2026-10-15T12:00:00.000Z");
    expect(iso(floorSince(NOW - 30 * D, NOW))).toBe("2026-10-11T12:00:00.000Z");
  });

  it("takes a visit ahead of the clock as now", () => {
    expect(iso(floorSince(NOW + 10 * MIN, NOW))).toBe("2026-10-18T16:30:00.000Z");
  });
});

describe("sinceAgo", () => {
  it("is hours under two days, then days", () => {
    expect(sinceAgo(NOW - 14 * H - 20 * MIN, NOW)).toBe("14 h");
    expect(sinceAgo(NOW - 47 * H, NOW)).toBe("47 h");
    expect(sinceAgo(NOW - 50 * H, NOW)).toBe("2 d");
  });
});

describe("sinceSummary", () => {
  it("says how long and what is new, breaking stories only when there are some", () => {
    expect(sinceSummary("14 h", { newStories: 1286, breaking: 4 })).toBe(
      "14 h since your visit: 1,286 new stories, 4 breaking stories.",
    );
    expect(sinceSummary("14 h", { newStories: 1286, breaking: 0 })).toBe(
      "14 h since your visit: 1,286 new stories.",
    );
    expect(sinceSummary("2 d", { newStories: 1, breaking: 1 })).toBe(
      "2 d since your visit: 1 new story, 1 breaking story.",
    );
  });
});

describe("sinceRange", () => {
  it("is the window from the last visit to now", () => {
    expect(sinceRange(NOW - 14 * H, NOW)).toEqual({
      kind: "range",
      startTime: iso(NOW - 14 * H),
      endTime: iso(NOW),
    });
  });
});

describe("the strip's dismissal", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("lasts the session", () => {
    expect(readSinceDismissed()).toBe(false);
    writeSinceDismissed();
    expect(readSinceDismissed()).toBe(true);
  });

  it("works without storage (blocked): not dismissed, and no error", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readSinceDismissed()).toBe(false);
    expect(() => writeSinceDismissed()).not.toThrow();
  });
});
