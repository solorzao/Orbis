import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_BREAKING,
  gotoStillGlobe,
  isBreaking,
  mockAllApiRoutes,
  sampleRings,
  withBreaking,
} from "./fixtures";

const ticker = (page: Page) => page.getByTestId("breaking-ticker");
const item = (page: Page) => page.getByTestId("breaking-item");
const [PARIS_STORY, SAN_ANTONIO, ROTTERDAM] = MOCK_BREAKING;

/** The cluster requests a panel makes, by the cell it asks for. */
async function recordCells(page: Page) {
  const cells: { lat: string | null; lng: string | null }[] = [];
  await page.route("**/api/news/cluster*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    cells.push({ lat: params.get("lat"), lng: params.get("lng") });
    return route.fallback();
  });
  return cells;
}

test.describe("Breaking ticker", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("shows what is breaking, one at a time, with next and previous", async ({ page }) => {
    await gotoStillGlobe(page, withBreaking);
    await expect(ticker(page)).toBeVisible();
    await expect(item(page)).toContainText(PARIS_STORY.headline);
    await expect(ticker(page)).toContainText("Paris, France · 23 outlets");
    await expect(ticker(page)).toContainText("1 of 3");
    // The long headline's full text is its tooltip.
    await page.getByRole("button", { name: "Next breaking story" }).click();
    await expect(item(page)).toHaveAttribute("title", SAN_ANTONIO.headline);
    await expect(ticker(page)).toContainText("2 of 3");
    await page.getByRole("button", { name: "Previous breaking story" }).click();
    await page.getByRole("button", { name: "Previous breaking story" }).click();
    await expect(item(page)).toContainText(ROTTERDAM.headline);
    await expect(ticker(page)).toContainText("3 of 3");
  });

  test("a story opens its place in Inspect: by its dot, or where there is none", async ({
    page,
  }) => {
    let cells: { lat: string | null; lng: string | null }[] = [];
    await gotoStillGlobe(page, async (p) => {
      await withBreaking(p);
      cells = await recordCells(p);
    });
    await item(page).click();
    await expect(page.getByTestId("side-tab-inspect")).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByTestId("news-panel").getByRole("heading", { name: "Paris, France" }),
    ).toBeVisible();

    // San Antonio has no dot among the globe's places: it opens all the same.
    await page.getByRole("button", { name: "Next breaking story" }).click();
    await item(page).click();
    await expect(
      page
        .getByTestId("news-panel")
        .getByRole("heading", { name: "Alamodome, Texas, United States" }),
    ).toBeVisible();
    await expect.poll(() => cells.at(-1)).toEqual({ lat: "29.5", lng: "-98.5" });
  });

  test("is hidden when nothing is breaking, and only breaking places pulse", async ({ page }) => {
    await gotoStillGlobe(page); // breaking: [] by default
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-dots", "3");
    await expect(globe).toHaveAttribute("data-rings", "0"); // no dot pulses now
    await expect(ticker(page)).toHaveCount(0);
  });

  test("refetches for a topic pill", async ({ page }) => {
    const asked: (string | null)[] = [];
    await gotoStillGlobe(page, (p) =>
      p.route(isBreaking, (route) => {
        asked.push(new URL(route.request().url()).searchParams.get("topic"));
        return route.fulfill({ json: MOCK_BREAKING });
      }),
    );
    await expect(ticker(page)).toBeVisible();
    expect(asked[0]).toBeNull();
    await page.getByTestId("topic-filter").getByRole("button", { name: "Conflict" }).click();
    await expect.poll(() => asked.at(-1)).toBe("Conflict");
  });

  test("hides during a replay, which looks back", async ({ page }) => {
    await gotoStillGlobe(page, withBreaking);
    await expect(ticker(page)).toBeVisible();
    await page.getByRole("button", { name: "Replay the last 7 days" }).click();
    await expect(ticker(page)).toHaveCount(0);
    await page.getByRole("button", { name: "Stop replay" }).click();
    await expect(ticker(page)).toBeVisible();
  });
});

test.describe("Breaking rings and motion", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  /** Load the globe with three stories breaking, in low-power mode or not. */
  async function load(page: Page, lowPower: "0" | "1", reduced: boolean) {
    await page.addInitScript((v) => localStorage.setItem("orbis-low-power", v), lowPower);
    if (reduced) await page.emulateMedia({ reducedMotion: "reduce" });
    await mockAllApiRoutes(page);
    await withBreaking(page);
    await page.goto("/");
    await expect(ticker(page)).toBeVisible();
    // The globe is built (its ring settings applied) before anything counts its rings.
    await expect(page.getByTestId("globe")).toHaveAttribute("data-ring-repeat", /^\d+$/);
  }

  test("the rings pulse at the breaking places with full motion and full power", async ({
    page,
  }) => {
    await load(page, "0", false);
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-rings", String(MOCK_BREAKING.length));
    await expect(globe).toHaveAttribute("data-ring-repeat", "2500");
    expect(Math.max(...(await sampleRings(page)))).toBeGreaterThan(0);
  });

  for (const [what, lowPower, reduced] of [
    ["reduced motion", "0", true],
    ["low-power mode", "1", false],
  ] as const) {
    test(`with ${what} no ring is drawn, not even once`, async ({ page }) => {
      await load(page, lowPower, reduced);
      const globe = page.getByTestId("globe");
      await expect(globe).toHaveAttribute("data-ring-repeat", "0");
      await expect(globe).toHaveAttribute("data-rings", "0");
      expect(await sampleRings(page)).toEqual(new Array(8).fill(0));
    });
  }

  test("turning low power off brings the rings back at once", async ({ page }) => {
    await load(page, "1", false);
    await expect(page.getByTestId("globe")).toHaveAttribute("data-rings", "0");
    expect(await sampleRings(page, 3)).toEqual([0, 0, 0]);
    // As another tab (or the settings) would: the stored preference changes.
    await page.evaluate(() => {
      localStorage.setItem("orbis-low-power", "0");
      window.dispatchEvent(new StorageEvent("storage", { key: "orbis-low-power" }));
    });
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-ring-repeat", "2500");
    await expect(globe).toHaveAttribute("data-rings", String(MOCK_BREAKING.length));
    expect(Math.max(...(await sampleRings(page)))).toBeGreaterThan(0);
  });
});

test.describe("Breaking on narrow screens", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("the ticker is hidden; the co-pilot offers What's breaking? instead", async ({ page }) => {
    await gotoStillGlobe(page, withBreaking);
    await page.getByTestId("side-tab-copilot").click();
    await expect(
      page.getByRole("group", { name: "Suggested questions" }).getByRole("button", {
        name: "What's breaking?",
      }),
    ).toBeVisible();
    await expect(ticker(page)).toBeHidden();
  });
});
