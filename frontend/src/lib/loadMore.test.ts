import { describe, it, expect } from "vitest";
import {
  appendPage,
  countAfterPage,
  nextPage,
  FILTERED_LOAD_MORE_LIMIT,
  FIRST_PAGE_LIMIT,
  LOAD_MORE_LIMIT,
} from "./loadMore";

// NewsPanel shows "Load more" while this holds.
const buttonShown = (loaded: number, count: number) => loaded > 0 && loaded < count;

describe("nextPage", () => {
  it("asks for the page after the stories already loaded", () => {
    expect(nextPage(30, false)).toEqual({ offset: 30, limit: LOAD_MORE_LIMIT });
  });

  it("pages on with bigger pages while in-panel filters are on", () => {
    expect(nextPage(60, true)).toEqual({ offset: 60, limit: FILTERED_LOAD_MORE_LIMIT });
    expect(FILTERED_LOAD_MORE_LIMIT).toBeLessThanOrEqual(50); // the endpoint's cap
  });
});

describe("countAfterPage", () => {
  it("keeps the dot's count after a full page, so Load more stays", () => {
    expect(countAfterPage(120, 30, LOAD_MORE_LIMIT, LOAD_MORE_LIMIT)).toBe(120);
    expect(buttonShown(30, 120)).toBe(true);
  });

  it("drops the count to what is loaded after a short page, hiding Load more", () => {
    expect(countAfterPage(120, 45, 15, LOAD_MORE_LIMIT)).toBe(45);
    expect(buttonShown(45, 45)).toBe(false);
  });

  it("drops the count to what is loaded after an empty page", () => {
    expect(countAfterPage(120, 30, 0, LOAD_MORE_LIMIT)).toBe(30);
  });

  it("applies to the first page too: a short one offers no Load more", () => {
    // A dot counting 50 stories of which 3 carry the active topic.
    expect(countAfterPage(50, 3, 3, FIRST_PAGE_LIMIT)).toBe(3);
    expect(countAfterPage(50, FIRST_PAGE_LIMIT, FIRST_PAGE_LIMIT, FIRST_PAGE_LIMIT)).toBe(50);
  });

  it("pages through a cell well past the first Load more", () => {
    // A dot counting 120 stories whose list (deduplicated) holds 95.
    const available = 95;
    let loaded = 10;
    let count = 120;
    let clicks = 0;
    while (buttonShown(loaded, count)) {
      const { offset, limit } = nextPage(loaded, clicks % 2 === 1);
      const received = Math.max(0, Math.min(limit, available - offset));
      loaded += received;
      count = countAfterPage(count, loaded, received, limit);
      clicks += 1;
    }
    expect(loaded).toBe(available);
    expect(count).toBe(available);
    expect(clicks).toBeGreaterThan(2);
  });
});

describe("appendPage", () => {
  const story = (id: string) => ({ id });

  it("appends the page after the stories already loaded", () => {
    expect(appendPage([story("a"), story("b")], [story("c")])).toEqual([
      story("a"),
      story("b"),
      story("c"),
    ]);
  });

  it("drops stories already loaded: a batch ingested since the click shifts the pages", () => {
    expect(appendPage([story("a"), story("b")], [story("b"), story("c")])).toEqual([
      story("a"),
      story("b"),
      story("c"),
    ]);
  });
});
