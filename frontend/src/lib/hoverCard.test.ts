import { describe, it, expect } from "vitest";
import {
  CARD_EDGE_PX,
  CARD_GAP_PX,
  CARD_OFFSET_PX,
  DOT_CLEARANCE_PX,
  cardCountLabel,
  cardLabel,
  cardMaxHeight,
  dockHoverCard,
  formatAgo,
  leaderPath,
  placeHoverCard,
  reticleRadius,
  sparkPaths,
  topicMixList,
  type Box,
} from "./hoverCard";

const VIEWPORT = { width: 1440, height: 900 };
const CARD = { width: 340, height: 300 };
// The 1440x900 chrome: the top bar, the open side panel and the bottom row.
const TOP_BAR: Box = { left: 24, top: 20, right: 1416, bottom: 62 };
const SIDE_PANEL: Box = { left: 1036, top: 96, right: 1416, bottom: 776 };
const BOTTOM_ROW: Box = { left: 24, top: 776, right: 1416, bottom: 880 };
const CHROME = [TOP_BAR, SIDE_PANEL, BOTTOM_ROW];

const box = (p: { left: number; top: number }, size = CARD): Box => ({
  left: p.left,
  top: p.top,
  right: p.left + size.width,
  bottom: p.top + size.height,
});

/** Whether two boxes come closer than `gap`. */
const tooClose = (a: Box, b: Box, gap = CARD_GAP_PX) =>
  !(
    a.right + gap <= b.left ||
    b.right + gap <= a.left ||
    a.bottom + gap <= b.top ||
    b.bottom + gap <= a.top
  );

function expectInside(card: Box, viewport = VIEWPORT) {
  expect(card.left).toBeGreaterThanOrEqual(CARD_EDGE_PX);
  expect(card.top).toBeGreaterThanOrEqual(CARD_EDGE_PX);
  expect(card.right).toBeLessThanOrEqual(viewport.width - CARD_EDGE_PX);
  expect(card.bottom).toBeLessThanOrEqual(viewport.height - CARD_EDGE_PX);
}

function expectClearOfDot(card: Box, dot: { x: number; y: number }) {
  const dotBox = {
    left: dot.x - DOT_CLEARANCE_PX,
    right: dot.x + DOT_CLEARANCE_PX,
    top: dot.y - DOT_CLEARANCE_PX,
    bottom: dot.y + DOT_CLEARANCE_PX,
  };
  expect(tooClose(card, dotBox, 0)).toBe(false);
}

describe("placeHoverCard", () => {
  const place = (dot: { x: number; y: number }, avoid: Box[] = CHROME, centreX = 720) =>
    box(placeHoverCard({ dot, centreX, card: CARD, viewport: VIEWPORT, avoid }));

  it("sits beside a dot right of the globe's centre, on its right (away from the centre)", () => {
    const card = place({ x: 760, y: 400 }, [TOP_BAR, BOTTOM_ROW]);
    expect(card.left).toBe(760 + CARD_OFFSET_PX);
    expect(card.top).toBe(400 - CARD.height * 0.45);
  });

  it("sits on the left of a dot left of the centre", () => {
    const card = place({ x: 600, y: 400 });
    expect(card.right).toBe(600 - CARD_OFFSET_PX);
    expect(card.top).toBe(400 - CARD.height * 0.45);
  });

  it("never covers the open side panel: a dot near it gets its card on the other side", () => {
    // At 1440 the panel starts at 1036: a card right of this dot would run into it.
    const dot = { x: 820, y: 420 };
    const card = place(dot);
    expect(tooClose(card, SIDE_PANEL)).toBe(false);
    expect(card.right).toBe(dot.x - CARD_OFFSET_PX);
    expectClearOfDot(card, dot);
  });

  it("uses the panel's own box: collapsed to its pill, the right side is free", () => {
    const pill: Box = { left: 1300, top: 96, right: 1416, bottom: 134 };
    const card = place({ x: 820, y: 420 }, [TOP_BAR, pill, BOTTOM_ROW]);
    expect(card.left).toBe(820 + CARD_OFFSET_PX);
  });

  it("keeps clear of the top bar for a dot near the top", () => {
    const dot = { x: 760, y: 90 };
    const card = place(dot);
    expect(tooClose(card, TOP_BAR)).toBe(false);
    expect(card.top).toBe(TOP_BAR.bottom + CARD_GAP_PX);
    expectInside(card);
  });

  it("keeps clear of the bottom row for a dot near the bottom", () => {
    const dot = { x: 760, y: 740 };
    const card = place(dot);
    expect(tooClose(card, BOTTOM_ROW)).toBe(false);
    expect(card.bottom).toBe(BOTTOM_ROW.top - CARD_GAP_PX);
    expectClearOfDot(card, dot);
  });

  it("flips to the right when the left has no room inside the viewport", () => {
    const dot = { x: 200, y: 400 };
    const card = place(dot, CHROME, 720);
    expect(card.left).toBe(dot.x + CARD_OFFSET_PX);
    expectInside(card);
  });

  it("stays 16px inside the viewport with no chrome at all", () => {
    for (const dot of [
      { x: 30, y: 30 },
      { x: 1420, y: 880 },
      { x: 720, y: 10 },
    ]) {
      const card = place(dot, [], 720);
      expectInside(card);
      expectClearOfDot(card, dot);
    }
  });

  it("holds every rule for dots all over a 1280x800 screen", () => {
    const viewport = { width: 1280, height: 800 };
    const chrome: Box[] = [
      { left: 24, top: 20, right: 1256, bottom: 62 },
      { left: 876, top: 96, right: 1256, bottom: 676 },
      { left: 24, top: 676, right: 1256, bottom: 780 },
    ];
    for (let x = 120; x < 870; x += 50) {
      for (let y = 110; y < 650; y += 45) {
        const dot = { x, y };
        const card = box(
          placeHoverCard({ dot, centreX: 640, card: CARD, viewport, avoid: chrome }),
        );
        for (const region of chrome) expect(tooClose(card, region)).toBe(false);
        expectInside(card, viewport);
        expectClearOfDot(card, dot);
      }
    }
  });

  it("falls back to a clamped spot when nothing fits (a tiny window)", () => {
    const viewport = { width: 360, height: 320 };
    const card = box(
      placeHoverCard({
        dot: { x: 180, y: 160 },
        centreX: 180,
        card: CARD,
        viewport,
        avoid: [{ left: 0, top: 0, right: 360, bottom: 320 }],
      }),
    );
    expect(card.left).toBe(CARD_EDGE_PX);
    expect(card.top).toBe(CARD_EDGE_PX);
  });
});

describe("dockHoverCard", () => {
  const viewport = { width: 390, height: 844 };
  const topBar: Box = { left: 12, top: 12, right: 378, bottom: 100 };
  const bottomRow: Box = { left: 12, top: 700, right: 378, bottom: 764 };
  const sheet: Box = { left: 12, top: 776, right: 378, bottom: 832 };

  it("docks full width minus 24px, 12px above the bottom row and the sheet", () => {
    const dock = dockHoverCard({ viewport, below: [topBar], above: [bottomRow, sheet] });
    expect(dock).toEqual({
      left: 12,
      width: 390 - 24,
      bottom: 844 - (700 - 12),
      maxHeight: 700 - 12 - (100 + 12),
    });
  });

  it("rises with an open sheet, and its height shrinks to fit under the top bar", () => {
    const openSheet: Box = { left: 12, top: 444, right: 378, bottom: 832 };
    const raisedRow: Box = { left: 12, top: 368, right: 378, bottom: 432 };
    const dock = dockHoverCard({ viewport, below: [topBar], above: [raisedRow, openSheet] });
    expect(dock.bottom).toBe(844 - (368 - 12));
    expect(dock.maxHeight).toBe(368 - 12 - 112);
  });

  it("uses the screen's edges when there is no chrome", () => {
    expect(dockHoverCard({ viewport, below: [], above: [] })).toEqual({
      left: 12,
      width: 366,
      bottom: 12,
      maxHeight: 844 - 24,
    });
  });
});

describe("reticleRadius", () => {
  it("closes from 22px to 14px over 380ms as it locks on", () => {
    expect(reticleRadius(0, false)).toBe(22);
    expect(reticleRadius(190, false)).toBeGreaterThan(14);
    expect(reticleRadius(190, false)).toBeLessThan(22 - 4); // eased out: most of it early
    expect(reticleRadius(380, false)).toBe(14);
    expect(reticleRadius(5000, false)).toBe(14);
  });

  it("is still with reduced motion", () => {
    expect(reticleRadius(0, true)).toBe(14);
  });
});

describe("leaderPath", () => {
  it("curves from the reticle's outer edge to the card's near side", () => {
    const card: Box = { left: 808, top: 265, right: 1148, bottom: 565 };
    // Right of the dot: starts r + 11 to its right, ends on the card's left edge at the dot's height.
    expect(leaderPath({ x: 760, y: 400 }, 14, card)).toBe(
      "M785 400 C 796.5 400, 796.5 400, 808 400",
    );
  });

  it("ends on the right edge of a card on the left, kept 30px inside its corners", () => {
    const card: Box = { left: 372, top: 300, right: 712, bottom: 600 };
    expect(leaderPath({ x: 760, y: 120 }, 14, card)).toBe(
      "M735 120 C 723.5 120, 723.5 330, 712 330",
    );
  });
});

describe("topicMixList", () => {
  it("lists the topics in the pills' order, each with its share", () => {
    expect(topicMixList({ Conflict: 2, Politics: 3, Health: 5 })).toEqual([
      { topic: "Politics", count: 3, share: 0.3 },
      { topic: "Conflict", count: 2, share: 0.2 },
      { topic: "Health", count: 5, share: 0.5 },
    ]);
  });

  it("is empty for no topics", () => {
    expect(topicMixList({})).toEqual([]);
    expect(topicMixList(undefined)).toEqual([]);
  });
});

describe("formatAgo", () => {
  const now = Date.parse("2026-10-12T14:30:00Z");
  it.each([
    ["2026-10-12T14:29:40Z", "just now"],
    ["2026-10-12T14:18:00Z", "12 min ago"],
    ["2026-10-12T12:30:00Z", "2 h ago"],
    ["2026-10-12T12:05:00Z", "2 h 25 min ago"],
    ["2026-10-10T13:00:00Z", "2 d ago"],
    ["2026-10-12T14:35:00Z", "just now"], // a clock running ahead
  ])("%s is %s", (at, label) => {
    expect(formatAgo(at, now)).toBe(label);
  });
});

describe("cardCountLabel", () => {
  it("counts the stories in the window", () => {
    expect(cardCountLabel(37, { kind: "live", hours: 24 })).toBe("37 stories, last 24 h");
    expect(cardCountLabel(1, { kind: "live", hours: 1 })).toBe("1 story, last 1 h");
    expect(cardCountLabel(5, { kind: "live", hours: 168 })).toBe("5 stories, last 7 days");
    expect(
      cardCountLabel(5, {
        kind: "range",
        startTime: "2026-10-06T14:00:00.000Z",
        endTime: "2026-10-07T02:00:00.000Z",
      }),
    ).toBe("5 stories, Tue 14:00 – Wed 02:00 UTC");
  });
});

describe("sparkPaths", () => {
  it("draws the line and its filled area across the width, peaks at the top", () => {
    const { line, area } = sparkPaths([0, 4, 2], 100, 30);
    expect(line).toBe("M0.0 28.0 L50.0 2.0 L100.0 15.0");
    expect(area).toBe(`${line} L100 30 L0 30 Z`);
  });

  it("keeps an empty day on the baseline", () => {
    expect(sparkPaths([0, 0, 0], 100, 30).line).toBe("M0.0 28.0 L50.0 28.0 L100.0 28.0");
  });
});

describe("cardLabel", () => {
  const base = {
    id: "api-0",
    lat: 48.5,
    lng: 2.5,
    size: 1,
    color: "#72ddb2",
    articles: [],
    isCluster: true,
    count: 5,
    topic: "Climate" as const,
    locationName: "Paris, France",
  };
  const lead = {
    title: "France announces new climate policy",
    sourceName: "Reuters",
    publishedAt: "2026-10-12T14:18:00Z",
    imageUrl: null,
    topic: "Climate" as const,
    sensitive: false,
  };

  it("names the place, its stories and its lead headline", () => {
    expect(cardLabel({ ...base, lead })).toBe(
      "Paris, France: 5 stories. France announces new climate policy",
    );
  });

  it("is shorter without a lead, and counts one story", () => {
    expect(cardLabel({ ...base, count: 1 })).toBe("Paris, France: 1 story");
  });

  it("names a place without a name by its coordinates", () => {
    expect(cardLabel({ ...base, locationName: undefined })).toBe("48.5°, 2.5°: 5 stories");
  });
});

// ── 5. The floating card fits between the top bar and the bottom row ──
describe("cardMaxHeight", () => {
  it("is the room between the top bar and the bottom row, 12px clear of each", () => {
    expect(cardMaxHeight({ viewport: VIEWPORT, below: [TOP_BAR], above: [BOTTOM_ROW] })).toBe(
      BOTTOM_ROW.top - CARD_GAP_PX - (TOP_BAR.bottom + CARD_GAP_PX),
    );
  });

  it("keeps 16px from the viewport's edges without chrome", () => {
    expect(cardMaxHeight({ viewport: VIEWPORT, below: [], above: [] })).toBe(
      VIEWPORT.height - 2 * CARD_EDGE_PX,
    );
  });
});
