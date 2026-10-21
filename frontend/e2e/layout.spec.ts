import { test, expect, type Page } from "@playwright/test";
import {
  CAIRO,
  MOCK_LINKS_LIFT,
  MOCK_RELATIONS,
  MOCK_THREADS,
  PARIS,
  hoverPlace,
  mockAllApiRoutes,
  seedLastVisit,
  withBreaking,
  withCairo,
  seedBoard,
} from "./fixtures";

const SIZES = [
  { width: 1920, height: 1080 },
  { width: 1600, height: 900 }, // the layers' widest single line
  { width: 1599, height: 900 }, // the layers stacked, at their widest
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1180, height: 800 }, // the narrowest floating panel
  { width: 1024, height: 768 },
  { width: 824, height: 1024 }, // one-row bar, at its tightest
  { width: 768, height: 1024 }, // two-row bar, a tablet
  { width: 700, height: 800 }, // two-row bar, motto still shown
  { width: 390, height: 844 },
  { width: 360, height: 740 }, // the brand mark alone
  { width: 320, height: 568 }, // the narrowest phone
  { width: 844, height: 390 }, // a phone on its side
];

/** Below this width the side panel is a bottom sheet. */
const SHEET_BELOW = 1180;
/** At this width and below, the layer switcher hides and the capsule drops its chart. */
const NARROW_MAX = 760;

/**
 * The open sheet's height (soft-orbit.css): 46vh, less on short screens so
 * the bottom row above it stays clear of the top bar (two rows below 640px),
 * and never below its 56px tab bar.
 */
function openSheetHeight({ width, height }: { width: number; height: number }) {
  return Math.max(56, Math.min(height * 0.46, height - (width < 640 ? 310 : 260)));
}

// Chrome regions that must never touch. Later PRs add their regions here.
const TOP_BAR = ["brand", "topic-filter", "status-pill", "board-open"];

/** The top bar's regions at a width: the Track search pill from 1180px, its button below. */
function topBarAt(width: number) {
  return [...TOP_BAR, width >= SHEET_BELOW ? "track-search" : "search-open"];
}

/** The regions shown at a width: the side panel (or its reopen pill), the bottom row. */
function regionsAt(width: number, side: "side-panel" | "side-open" = "side-panel") {
  return [...topBarAt(width), side, "timeline", ...(width > NARROW_MAX ? ["layer-switcher"] : [])];
}

type Box = { id: string; x: number; y: number; w: number; h: number };

/**
 * The shown regions' boxes, as Playwright's isVisible and boundingBox report
 * them (shown: a non-empty box, not visibility: hidden; one element per test
 * id), measured in one call into the page. On a busy CI runner each call can
 * take a second or more, and two per region pushed whole tests past 30 s.
 */
async function boxes(page: Page, ids: string[]): Promise<Box[]> {
  return page.evaluate((ids) => {
    const out: { id: string; x: number; y: number; w: number; h: number }[] = [];
    for (const id of ids) {
      const found = document.querySelectorAll(`[data-testid="${id}"]`);
      if (found.length > 1) throw new Error(`${found.length} elements for test id ${id}`);
      const el = found[0];
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0 || getComputedStyle(el).visibility === "hidden") continue;
      out.push({ id, x: r.x, y: r.y, w: r.width, h: r.height });
    }
    return out;
  }, ids);
}

/** Turn the Links layer on and wait until its arcs are drawn: its ready signal. */
async function linksOn(page: Page) {
  await page.getByRole("button", { name: "Links", exact: true }).click();
  await expect(page.getByTestId("globe")).toHaveAttribute(
    "data-arcs",
    String(MOCK_LINKS_LIFT.length),
  );
}

/** Turn the Threads layer on and wait until the rail lists its rows: its ready signal. */
async function threadsOn(page: Page) {
  await page.getByRole("button", { name: "Threads", exact: true }).click();
  await expect(
    page.getByRole("list", { name: "Developing stories" }).getByRole("button"),
  ).toHaveCount(MOCK_THREADS.length);
}

const GAP = 12;
/** How far the capsule's centre may sit from the viewport's: it centres on the page. */
const CENTRED_PX = 2;

function expectCentred(timeline: { x: number; w: number }, width: number, state: string) {
  expect(
    Math.abs(timeline.x + timeline.w / 2 - width / 2),
    `${state}: capsule centred`,
  ).toBeLessThanOrEqual(CENTRED_PX);
}

function tooClose(a: Box, b: Box) {
  return !(
    a.x + a.w + GAP <= b.x ||
    b.x + b.w + GAP <= a.x ||
    a.y + a.h + GAP <= b.y ||
    b.y + b.h + GAP <= a.y
  );
}

async function settle(
  page: Page,
  size: { width: number; height: number },
  setup?: (page: Page) => Promise<void>,
) {
  await page.setViewportSize(size);
  // No transitions, so the panel, sheet and bottom row measure at their final place.
  // (Reduced motion also holds the globe still, so a dot can be hovered.)
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockAllApiRoutes(page);
  await setup?.(page); // routes added later win over the defaults
  await page.goto("/");
  await page.getByTestId("topic-filter").waitFor();
  // Measure the settled bar: self-hosted fonts in, status at its final width.
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible({ timeout: 10000 });
}

async function expectApart(page: Page, width: number, state: string, ids: string[]) {
  const b = await boxes(page, ids);
  expect(b.map((r) => r.id).sort(), `${state}: regions shown`).toEqual([...ids].sort());
  for (let i = 0; i < b.length; i++)
    for (let j = i + 1; j < b.length; j++)
      expect(tooClose(b[i], b[j]), `${state}: ${b[i].id} vs ${b[j].id}`).toBe(false);
  // Nothing is cut off by the viewport edge.
  for (const r of b) {
    expect(r.x, `${state}: ${r.id} left edge`).toBeGreaterThanOrEqual(0);
    expect(r.x + r.w, `${state}: ${r.id} right edge`).toBeLessThanOrEqual(width);
  }
  return Object.fromEntries(b.map((r) => [r.id, r])) as Record<string, Box>;
}

for (const size of SIZES) {
  const sheet = size.width < SHEET_BELOW;

  test(`chrome regions keep ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
    await settle(page, size);
    const side = page.getByTestId("side-panel");
    await expect(side).toHaveAttribute("data-open", String(!sheet)); // the default for the width
    const state = sheet ? "sheet collapsed" : "side panel open";
    const b = await expectApart(page, size.width, state, regionsAt(size.width));

    // The topics may scroll, but a crowded side must not squeeze them to nothing.
    expect(b["topic-filter"]?.w ?? 0, "topic-filter width").toBeGreaterThanOrEqual(200);
    // The last of the top bar, About, keeps the bar's margin (12px on phones, 24px wider).
    const [about] = await boxes(page, ["about-link"]);
    expect(about.x + about.w, "About inside the bar's margin").toBeLessThanOrEqual(
      size.width - (size.width < 640 ? 12 : 24),
    );
    // The Track search: a pill (its placeholder legible) from 1180px, a button below.
    if (!sheet) {
      expect(b["track-search"].w, "search pill width").toBeGreaterThanOrEqual(220);
    }

    if (sheet) {
      // Open, the sheet is at its tallest and the bottom row moves up above it.
      await page.getByTestId("side-collapse").click();
      await expect(side).toHaveAttribute("data-open", "true");
      await expectApart(page, size.width, "sheet open", regionsAt(size.width));
      return;
    }

    // The floating panel clears the top bar by at least 16px...
    const barBottom = Math.max(...topBarAt(size.width).map((id) => b[id].y + b[id].h));
    const panel = b["side-panel"];
    expect(panel.y - barBottom, "side panel below the top bar").toBeGreaterThanOrEqual(16);
    // The bottom row spans the width, its capsule centred on the page under the globe
    // and the topics; the panel ends above it (its 124px bottom against the row's height),
    // so they keep apart vertically.
    expectCentred(b["timeline"], size.width, state);
    expect(b["timeline"].w, "capsule at its full width").toBeCloseTo(640, 0);
    expect(b["timeline"].y - (panel.y + panel.h), "capsule below the panel").toBeGreaterThanOrEqual(
      GAP,
    );

    // Collapsed, the panel gives way to its pill; the capsule stays where it was.
    await page.getByTestId("side-collapse").click();
    await expect(side).toHaveAttribute("data-open", "false");
    const collapsed = await expectApart(
      page,
      size.width,
      "side panel collapsed",
      regionsAt(size.width, "side-open"),
    );
    const timeline = collapsed["timeline"];
    expectCentred(timeline, size.width, "side panel collapsed");
    expect(timeline.w, "capsule at its full width").toBeCloseTo(640, 0);
  });
}

for (const size of SIZES.filter((s) => s.width < SHEET_BELOW)) {
  test(`below ${SHEET_BELOW}px the side panel is a bottom sheet at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await settle(page, size);
    const side = page.getByTestId("side-panel");
    const layers = page.getByTestId("layer-switcher");

    /** The bottom row sits 12px above the sheet, the layers 12px above the capsule. */
    const expectRowAboveSheet = async () => {
      const sheetBox = (await side.boundingBox())!;
      const timeline = (await page.getByTestId("timeline").boundingBox())!;
      expect(sheetBox.y - (timeline.y + timeline.height)).toBeCloseTo(12, 0);
      expectCentred({ x: timeline.x, w: timeline.width }, size.width, "stacked");
      if (size.width > NARROW_MAX) {
        const l = (await layers.boundingBox())!;
        expect(timeline.y - (l.y + l.height)).toBeCloseTo(12, 0);
        expect(l.x + l.width / 2).toBeCloseTo(size.width / 2, 0); // centred over the capsule
      } else {
        await expect(layers).not.toBeVisible();
      }
    };

    // Collapsed: the 56px tab bar along the bottom, tabs in reach, no pill.
    let box = (await side.boundingBox())!;
    expect(box.x).toBe(12);
    expect(box.x + box.width).toBe(size.width - 12);
    expect(box.y + box.height).toBe(size.height - 12);
    expect(box.height).toBe(56);
    await expect(page.getByTestId("side-tab-copilot")).toBeVisible();
    await expect(page.getByTestId("side-open")).not.toBeVisible();
    await expect(page.getByTestId("side-collapse")).toHaveAccessibleName("Expand panel");
    await expectRowAboveSheet();

    // A tab opens it (46vh where there is room), and the bottom row moves up with it.
    await page.getByTestId("side-tab-inspect").click();
    await expect(side).toHaveAttribute("data-open", "true");
    box = (await side.boundingBox())!;
    expect(Math.abs(box.height - openSheetHeight(size))).toBeLessThan(1);
    expect(box.y + box.height).toBe(size.height - 12);
    await expectRowAboveSheet();

    // And folds back to its tab bar, keeping focus on its button (no pill to move to).
    await page.getByTestId("side-collapse").click();
    await expect(side).toHaveAttribute("data-open", "false");
    await expect(page.getByTestId("side-tab-inspect")).toBeVisible();
    await expect(page.getByTestId("side-collapse")).toBeFocused();
  });
}

// The city hover card floats over the globe: it keeps clear of the top bar, the
// side panel and the bottom row like any region. Cairo sits right of the
// globe's centre, beside the panel, so its card must take the other side.
for (const size of SIZES.filter((s) => s.width === 1440 || s.width === 1280)) {
  for (const place of [PARIS, CAIRO]) {
    test(`the hover card for ${place.location_name} keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({
      page,
    }) => {
      await settle(page, size, withCairo);
      await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
      await hoverPlace(page, place);
      await expectApart(page, size.width, `hover card for ${place.location_name}`, [
        ...regionsAt(size.width),
        "hover-card",
      ]);
      const card = (await page.getByTestId("hover-card").boundingBox())!;
      expect(card.y + card.height, "hover card bottom edge").toBeLessThanOrEqual(size.height);
    });
  }
}

// While Links is on, its rank switch floats beside the layers (above them in the
// bottom row, to their right once they stack over the capsule): a region of its
// own that must not move the capsule or touch anything.
for (const size of SIZES.filter((s) => s.width > NARROW_MAX)) {
  test(`the Links rank switch keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await settle(page, size);
    const before = (await page.getByTestId("layer-switcher").boundingBox())!;
    await linksOn(page);
    await expect(page.getByTestId("link-rank")).toBeVisible();
    const regions = [...regionsAt(size.width), "link-rank"];
    const b = await expectApart(page, size.width, "Links on", regions);
    // The layers keep their box, so the capsule keeps its place.
    expect(b["layer-switcher"]).toMatchObject({ x: before.x, y: before.y, w: before.width });
    expectCentred(b["timeline"], size.width, "Links on");
    if (size.width < SHEET_BELOW) {
      await page.getByTestId("side-collapse").click();
      await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
      await expectApart(page, size.width, "Links on, sheet open", regions);
    }
  });
}

// With Links on in an empty window, its status floats with the rank switch (above it
// from 1180px, left of the layers once they stack): regions that must keep apart too.
for (const size of SIZES.filter((s) => s.width > NARROW_MAX)) {
  test(`the Links status keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await settle(page, size, (p) =>
      p.route(
        (url) => url.pathname === "/api/links",
        (route) => route.fulfill({ json: [] }),
      ),
    );
    await page.getByRole("button", { name: "Links", exact: true }).click();
    await expect(page.getByTestId("links-status")).toBeVisible();
    const regions = [...regionsAt(size.width), "link-rank", "links-status"];
    const b = await expectApart(page, size.width, "Links status", regions);
    expectCentred(b["timeline"], size.width, "Links status");
    if (size.width < SHEET_BELOW) {
      await page.getByTestId("side-collapse").click();
      await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
      await expectApart(page, size.width, "Links status, sheet open", regions);
    }
  });
}

// While Relations is on, its class switch takes the rank switch's place and its
// legend floats above it (centred above the layers below 1180px): regions of
// their own that must not move the capsule or touch the timeline, the bottom
// row, the top bar or the side panel. On a short screen with the sheet open the
// legend gives way (there is no room above the layers); the list in Inspect
// names the lens there.
for (const size of SIZES.filter((s) => s.width > NARROW_MAX)) {
  test(`the Relations switch and legend keep ${GAP}px apart at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await settle(page, size);
    const before = (await page.getByTestId("layer-switcher").boundingBox())!;
    await page.getByRole("button", { name: "Relations", exact: true }).press("Enter");
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-relation-arcs",
      String(MOCK_RELATIONS.relations.length),
    );
    await expect(page.getByTestId("relations-legend")).toBeVisible();
    const regions = [...regionsAt(size.width), "relation-kind", "relations-legend"];
    const b = await expectApart(page, size.width, "Relations on", regions);
    // The layers keep their box, so the capsule keeps its place.
    expect(b["layer-switcher"]).toMatchObject({ x: before.x, y: before.y, w: before.width });
    expectCentred(b["timeline"], size.width, "Relations on");
    // The switch and the legend keep the gap from the viewport's edges too.
    for (const id of ["relation-kind", "relations-legend"]) {
      expect(b[id].x, `${id}: left margin`).toBeGreaterThanOrEqual(GAP);
      expect(size.width - (b[id].x + b[id].w), `${id}: right margin`).toBeGreaterThanOrEqual(GAP);
    }
    if (size.width < SHEET_BELOW) {
      await page.getByTestId("side-collapse").press("Enter");
      await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
      const short = size.height <= 560;
      const open = [
        ...regionsAt(size.width),
        "relation-kind",
        ...(short ? [] : ["relations-legend"]),
      ];
      await expectApart(page, size.width, "Relations on, sheet open", open);
      if (short) expect(await boxes(page, ["relations-legend"]), "legend gives way").toEqual([]);
    }
  });
}

// Where the layers are hidden, Links on brings a Links ✕ chip above the capsule.
for (const size of SIZES.filter((s) => s.width <= NARROW_MAX)) {
  test(`the Links chip keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
    // Turn Links on where the layers show, then narrow the window.
    await settle(page, { width: 800, height: size.height });
    await linksOn(page);
    await page.setViewportSize(size);
    const chip = page.getByTestId("links-chip");
    await expect(chip).toBeVisible();
    const regions = [...regionsAt(size.width), "links-chip"];
    const b = await expectApart(page, size.width, "Links chip", regions);
    expect(b["timeline"].y - (b["links-chip"].y + b["links-chip"].h)).toBeCloseTo(GAP, 0);
    expect(b["links-chip"].x + b["links-chip"].w / 2).toBeCloseTo(size.width / 2, 0);
    await page.getByTestId("side-collapse").click();
    await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
    await expectApart(page, size.width, "Links chip, sheet open", regions);
  });
}

// The breaking ticker is the bottom row's right track from 1180px: clear of the
// capsule (which stays centred), the side panel above it and the viewport edge.
for (const size of SIZES.filter((s) => s.width >= SHEET_BELOW)) {
  test(`the breaking ticker keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await settle(page, size, withBreaking);
    await expect(page.getByTestId("breaking-ticker")).toBeVisible();
    const regions = [...regionsAt(size.width), "breaking-ticker"];
    const b = await expectApart(page, size.width, "breaking ticker", regions);
    expectCentred(b["timeline"], size.width, "breaking ticker");
    expect(b["timeline"].w, "capsule at its full width").toBeCloseTo(640, 0);
    // Right-aligned in its track, as the layers are left-aligned in theirs.
    const ticker = b["breaking-ticker"];
    expect(size.width - (ticker.x + ticker.w), "ticker at the right edge").toBeCloseTo(24, 0);
  });
}

// "Since your last visit" sits under the brand from 1180px: clear of the brand,
// the topics and the side panel (and the rest of the chrome).
for (const size of SIZES.filter((s) => s.width >= SHEET_BELOW)) {
  test(`the since strip keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
    await settle(page, size, (p) => seedLastVisit(p, 14));
    await expect(page.getByTestId("since-strip")).toBeVisible();
    const regions = [...regionsAt(size.width), "since-strip"];
    const b = await expectApart(page, size.width, "since strip", regions);
    expect(b["since-strip"].x, "since strip at the brand's left edge").toBeCloseTo(24, 0);
    expect(b["since-strip"].y, "since strip under the brand").toBeCloseTo(80, 0);
  });
}

// Threads on, its rail is the left column's from 1180px: under the brand, or under
// the since strip when that shows, one stack so they never overlap, and clear of
// the topics, the side panel and the bottom row (the capsule keeps its place).
for (const size of SIZES.filter((s) => s.width >= SHEET_BELOW)) {
  for (const strip of [false, true]) {
    const state = strip ? "threads rail under the since strip" : "threads rail";
    test(`the ${state} keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
      await settle(page, size, strip ? (p) => seedLastVisit(p, 14) : undefined);
      if (strip) await expect(page.getByTestId("since-strip")).toBeVisible();
      await threadsOn(page);
      const regions = [...regionsAt(size.width), "threads-rail", ...(strip ? ["since-strip"] : [])];
      const b = await expectApart(page, size.width, state, regions);
      const rail = b["threads-rail"];
      expect(rail.x, "rail at the brand's left edge").toBeCloseTo(24, 0);
      if (strip) {
        const since = b["since-strip"];
        expect(rail.y - (since.y + since.h), "rail 12px under the strip").toBeCloseTo(GAP, 0);
      } else {
        expect(rail.y, "rail under the brand").toBeCloseTo(80, 0);
      }
      expect(
        size.height - (rail.y + rail.h),
        "rail ends above the bottom row",
      ).toBeGreaterThanOrEqual(124 - 1);
      expectCentred(b["timeline"], size.width, state);
      expect(b["timeline"].w, "capsule at its full width").toBeCloseTo(640, 0);
    });
  }

  // At its tallest, a thread open under its row and the since strip above,
  // the rail still ends above the bottom row and clear of Links' rank switch.
  test(`the threads rail with a thread open and Links on keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await settle(page, size, (p) => seedLastVisit(p, 14));
    await expect(page.getByTestId("since-strip")).toBeVisible();
    await linksOn(page);
    await threadsOn(page);
    await page
      .getByRole("list", { name: "Developing stories" })
      .getByRole("button")
      .first()
      .click();
    await expect(page.getByRole("list", { name: "Key entities" })).toBeVisible(); // the detail
    const regions = [...regionsAt(size.width), "threads-rail", "since-strip", "link-rank"];
    const b = await expectApart(page, size.width, "thread open, Links on", regions);
    expectCentred(b["timeline"], size.width, "thread open, Links on");
  });
}

// The investigation board's split view from 1180px: on the left under the top
// bar, above the bottom row (whose capsule keeps its place), the other panels
// and the topics hidden, the globe slid right of it. With Links on, it ends
// above the rank switch as the left column does.
for (const size of SIZES.filter((s) => s.width >= SHEET_BELOW)) {
  for (const links of [false, true]) {
    const state = links ? "board view with Links on" : "board view";
    test(`the ${state} keeps ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
      await settle(page, size, seedBoard);
      if (links) await linksOn(page);
      await page.getByTestId("board-open").press("Enter");
      await expect(page.getByTestId("board")).toHaveAttribute("data-edges", "4");
      const regions = [
        ...topBarAt(size.width).filter((id) => id !== "topic-filter"),
        "board",
        "timeline",
        "layer-switcher",
        ...(links ? ["link-rank"] : []),
      ];
      const b = await expectApart(page, size.width, state, regions);
      const board = b["board"];
      expect(board.x, "board at the brand's left edge").toBeCloseTo(24, 0);
      const barBottom = Math.max(...topBarAt(size.width).map((id) => b[id]?.y + b[id]?.h || 0));
      expect(board.y - barBottom, "board below the top bar").toBeGreaterThanOrEqual(16);
      expect(board.w, "board 58% of the width").toBeCloseTo(size.width * 0.58, 0);
      expectCentred(b["timeline"], size.width, state);
      expect(b["timeline"].w, "capsule at its full width").toBeCloseTo(640, 0);
      // The topics and the side panel hide; the globe sits right of the board.
      const hidden = await boxes(page, ["topic-filter", "side-panel"]);
      expect(hidden, "hidden while the board shows").toEqual([]);
      await expect(page.getByTestId("globe")).toHaveAttribute("data-shifted", "true");
    });
  }
}

test("on a very short screen the open sheet keeps at least its 56px tab bar", async ({ page }) => {
  const size = { width: 900, height: 300 }; // 100vh - 260px would be 40px
  await settle(page, size);
  await page.getByTestId("side-tab-inspect").click();
  const side = page.getByTestId("side-panel");
  await expect(side).toHaveAttribute("data-open", "true");
  const box = (await side.boundingBox())!;
  expect(box.height).toBe(openSheetHeight(size));
  expect(box.height).toBe(56);
  await expect(page.getByTestId("side-tab-copilot")).toBeVisible();
});

test.describe("before hydration (server HTML, no JavaScript)", () => {
  test.use({ javaScriptEnabled: false });

  test("from 1180px the side panel shows open, with no reopen pill", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const side = page.getByTestId("side-panel");
    await expect(side).not.toHaveAttribute("data-open");
    await expect(side).toBeVisible();
    await expect(page.getByTestId("side-open")).not.toBeVisible();
    // The capsule is already centred, below it.
    const panel = (await side.boundingBox())!;
    const timeline = (await page.getByTestId("timeline").boundingBox())!;
    expectCentred({ x: timeline.x, w: timeline.width }, 1440, "before hydration");
    expect(timeline.y - (panel.y + panel.height)).toBeGreaterThanOrEqual(GAP);
  });

  test("below 1180px the sheet shows folded to its tab bar", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const side = page.getByTestId("side-panel");
    await expect(side).not.toHaveAttribute("data-open");
    const box = (await side.boundingBox())!;
    expect(box.height).toBe(56);
    expect(box.y + box.height).toBe(844 - 12);
    const timeline = (await page.getByTestId("timeline").boundingBox())!;
    expect(box.y - (timeline.y + timeline.height)).toBeCloseTo(12, 0);
  });
});
