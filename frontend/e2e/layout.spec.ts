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

// Chrome regions that must never touch. Later PRs add their regions here.
const REGIONS = ["brand", "topic-filter", "status-pill"];

async function boxes(page: Page) {
  const out: { id: string; x: number; y: number; w: number; h: number }[] = [];
  for (const id of REGIONS) {
    const el = page.getByTestId(id);
    if (!(await el.isVisible())) continue;
    const b = await el.boundingBox();
    if (b) out.push({ id, x: b.x, y: b.y, w: b.width, h: b.height });
  }
  return out;
}

const GAP = 12;
function tooClose(a: { x: number; y: number; w: number; h: number }, b: typeof a) {
  return !(
    a.x + a.w + GAP <= b.x ||
    b.x + b.w + GAP <= a.x ||
    a.y + a.h + GAP <= b.y ||
    b.y + b.h + GAP <= a.y
  );
}

for (const size of SIZES) {
  test(`chrome regions keep ${GAP}px apart at ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size);
    await mockAllApiRoutes(page);
    await page.goto("/");
    await page.getByTestId("topic-filter").waitFor();
    // Measure the settled bar: self-hosted fonts in, status at its final width.
    await page.evaluate(async () => {
      await document.fonts.ready;
    });
    await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible({ timeout: 10000 });
    const b = await boxes(page);
    for (let i = 0; i < b.length; i++)
      for (let j = i + 1; j < b.length; j++)
        expect(tooClose(b[i], b[j]), `${b[i].id} vs ${b[j].id}`).toBe(false);
    // Nothing is cut off by the viewport edge.
    for (const r of b) {
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.x + r.w).toBeLessThanOrEqual(size.width);
    }
    // The topics may scroll, but a crowded side must not squeeze them to nothing.
    const topics = b.find((r) => r.id === "topic-filter");
    expect(topics?.w ?? 0, "topic-filter width").toBeGreaterThanOrEqual(200);
  });
}
