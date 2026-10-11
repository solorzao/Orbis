import { test, expect, type Page } from "@playwright/test";
import { mockAllApiRoutes } from "./fixtures";

const SIZES = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 768, height: 1024 }, // one-row bar, at its tightest
  { width: 700, height: 800 }, // two-row bar, motto still shown
  { width: 390, height: 844 },
];

/** Below this width the side panel is a bottom sheet. */
const SHEET_BELOW = 1180;

// Chrome regions that must never touch. Later PRs add their regions here.
// The time slider is the old one until PR 10's bottom row replaces it.
const REGIONS = ["brand", "topic-filter", "status-pill", "side-panel", "time-slider"];
const TOP_BAR = ["brand", "topic-filter", "status-pill"];

type Box = { id: string; x: number; y: number; w: number; h: number };

async function boxes(page: Page) {
  const out: Box[] = [];
  for (const id of REGIONS) {
    const el = page.getByTestId(id);
    if (!(await el.isVisible())) continue;
    const b = await el.boundingBox();
    if (b) out.push({ id, x: b.x, y: b.y, w: b.width, h: b.height });
  }
  return out;
}

const GAP = 12;
function tooClose(a: Box, b: Box) {
  return !(
    a.x + a.w + GAP <= b.x ||
    b.x + b.w + GAP <= a.x ||
    a.y + a.h + GAP <= b.y ||
    b.y + b.h + GAP <= a.y
  );
}

async function settle(page: Page, size: { width: number; height: number }) {
  await page.setViewportSize(size);
  // No transitions, so the panel and sheet measure at their final size.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockAllApiRoutes(page);
  await page.goto("/");
  await page.getByTestId("topic-filter").waitFor();
  // Measure the settled bar: self-hosted fonts in, status at its final width.
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible({ timeout: 10000 });
}

async function expectApart(page: Page, width: number, state: string) {
  const b = await boxes(page);
  expect(b.map((r) => r.id).sort(), `${state}: regions shown`).toEqual([...REGIONS].sort());
  for (let i = 0; i < b.length; i++)
    for (let j = i + 1; j < b.length; j++)
      expect(tooClose(b[i], b[j]), `${state}: ${b[i].id} vs ${b[j].id}`).toBe(false);
  // Nothing is cut off by the viewport edge.
  for (const r of b) {
    expect(r.x, `${state}: ${r.id} left edge`).toBeGreaterThanOrEqual(0);
    expect(r.x + r.w, `${state}: ${r.id} right edge`).toBeLessThanOrEqual(width);
  }
  return b;
}

for (const size of SIZES) {
  const sheet = size.width < SHEET_BELOW;

  test(`chrome regions keep ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
    await settle(page, size);
    const side = page.getByTestId("side-panel");
    await expect(side).toHaveAttribute("data-open", String(!sheet)); // the default for the width
    const b = await expectApart(page, size.width, sheet ? "sheet collapsed" : "side panel open");

    // The topics may scroll, but a crowded side must not squeeze them to nothing.
    const topics = b.find((r) => r.id === "topic-filter");
    expect(topics?.w ?? 0, "topic-filter width").toBeGreaterThanOrEqual(200);

    if (sheet) {
      // Open, the sheet is at its tallest and the time slider moves up above it.
      await page.getByTestId("side-collapse").click();
      await expect(side).toHaveAttribute("data-open", "true");
      await expectApart(page, size.width, "sheet open");
    } else {
      // The floating panel clears the top bar by at least 16px.
      const barBottom = Math.max(...b.filter((r) => TOP_BAR.includes(r.id)).map((r) => r.y + r.h));
      const panel = b.find((r) => r.id === "side-panel")!;
      expect(panel.y - barBottom, "side panel below the top bar").toBeGreaterThanOrEqual(16);
    }
  });
}

for (const size of SIZES.filter((s) => s.width < SHEET_BELOW)) {
  test(`below ${SHEET_BELOW}px the side panel is a bottom sheet at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await settle(page, size);
    const side = page.getByTestId("side-panel");

    // Collapsed: the 56px tab bar along the bottom, tabs in reach, no pill.
    let box = (await side.boundingBox())!;
    expect(box.x).toBe(12);
    expect(box.x + box.width).toBe(size.width - 12);
    expect(box.y + box.height).toBe(size.height - 12);
    expect(box.height).toBe(56);
    await expect(page.getByTestId("side-tab-copilot")).toBeVisible();
    await expect(page.getByTestId("side-open")).not.toBeVisible();
    await expect(page.getByTestId("side-collapse")).toHaveAccessibleName("Expand panel");

    // A tab opens it to 46vh, and the time slider sits 12px above it.
    await page.getByTestId("side-tab-stories").click();
    await expect(side).toHaveAttribute("data-open", "true");
    box = (await side.boundingBox())!;
    expect(Math.abs(box.height - size.height * 0.46)).toBeLessThan(1);
    expect(box.y + box.height).toBe(size.height - 12);
    const slider = (await page.getByTestId("time-slider").boundingBox())!;
    expect(box.y - (slider.y + slider.height)).toBeCloseTo(12, 0);

    // And folds back to its tab bar, keeping focus on its button (no pill to move to).
    await page.getByTestId("side-collapse").click();
    await expect(side).toHaveAttribute("data-open", "false");
    await expect(page.getByTestId("side-tab-stories")).toBeVisible();
    await expect(page.getByTestId("side-collapse")).toBeFocused();
  });
}
