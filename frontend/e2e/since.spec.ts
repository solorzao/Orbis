import { test, expect, type Page } from "@playwright/test";
import { LAST_VISIT_KEY, MOCK_DELTA, gotoStillGlobe, isDelta, seedLastVisit } from "./fixtures";
import { utcTime, utcWeekday } from "../src/lib/timeWindow";

const strip = (page: Page) => page.getByTestId("since-strip");
const TEXT = "Welcome back. 14 h since your visit: 1,286 new stories, 4 breaking stories.";

/** The `since` each delta request sent. */
async function recordDelta(page: Page) {
  const asked: string[] = [];
  await page.route(isDelta, (route) => {
    asked.push(new URL(route.request().url()).searchParams.get("since") ?? "");
    return route.fulfill({ json: MOCK_DELTA });
  });
  return asked;
}

test.describe("Since your last visit", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("welcomes a visitor back 14 h later, asking from a floored visit", async ({ page }) => {
    let asked: string[] = [];
    await gotoStillGlobe(page, async (p) => {
      await seedLastVisit(p, 14);
      asked = await recordDelta(p);
    });
    await expect(strip(page)).toHaveText(new RegExp(`^${TEXT.replace(/\./g, "\\.")}`));
    // Floored to the quarter hour (within a day), as the server floors it.
    expect(asked).toHaveLength(1);
    const since = new Date(asked[0]);
    expect(since.getUTCMinutes() % 15).toBe(0);
    expect(since.getUTCSeconds()).toBe(0);
    // The timeline marks the visit.
    await expect(page.getByTestId("last-visit-marker")).toBeAttached();
  });

  test("Show sets the timeline to the range since the visit", async ({ page }) => {
    await gotoStillGlobe(page, (p) => seedLastVisit(p, 14));
    await expect(strip(page)).toBeVisible();
    const visit = Date.parse(
      (await page.evaluate((k) => localStorage.getItem(k), LAST_VISIT_KEY))!,
    );
    await strip(page).getByRole("button", { name: "Show" }).click();
    const label = page.getByTestId("timeline-label");
    await expect(label).toHaveText(new RegExp(`^${utcWeekday(visit)} ${utcTime(visit)} – .* UTC$`));
    await expect(
      page.getByRole("group", { name: "Time window presets" }).getByRole("button", { name: "24h" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  test("Top 5 lists the places with the most new stories; one opens in Inspect", async ({
    page,
  }) => {
    await gotoStillGlobe(page, (p) => seedLastVisit(p, 14));
    await strip(page).getByRole("button", { name: "Top 5" }).click();
    const list = strip(page).getByRole("list", { name: "Places with the most new stories" });
    await expect(list.getByRole("button")).toHaveCount(MOCK_DELTA.top.length);
    // The Alamodome has no dot on the globe: it opens all the same.
    await list.getByRole("button", { name: /^Alamodome/ }).click();
    await expect(page.getByTestId("side-tab-inspect")).toHaveAttribute("aria-selected", "true");
    await expect(
      page
        .getByTestId("news-panel")
        .getByRole("heading", { name: "Alamodome, Texas, United States" }),
    ).toBeVisible();
  });

  test("Dismiss hides it for the session", async ({ page }) => {
    await gotoStillGlobe(page, (p) => seedLastVisit(p, 14));
    await strip(page).getByRole("button", { name: "Dismiss" }).click();
    await expect(strip(page)).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible();
    // The visit is 14 h back again (seeded), but the strip stays dismissed.
    await expect(page.getByTestId("last-visit-marker")).toBeAttached();
    await expect(strip(page)).toHaveCount(0);
  });

  test("shows nothing on a first visit, or under an hour after the last", async ({ page }) => {
    let asked: string[] = [];
    await gotoStillGlobe(page, async (p) => {
      asked = await recordDelta(p);
    });
    await expect(page.getByTestId("timeline")).toBeVisible();
    await expect(strip(page)).toHaveCount(0);
    await expect(page.getByTestId("last-visit-marker")).toHaveCount(0);
    expect(asked).toHaveLength(0);
  });

  test("a visit 30 minutes ago brings no strip, only the marker", async ({ page }) => {
    let asked: string[] = [];
    await gotoStillGlobe(page, async (p) => {
      await seedLastVisit(p, 0.5);
      asked = await recordDelta(p);
    });
    await expect(page.getByTestId("last-visit-marker")).toBeAttached();
    await expect(strip(page)).toHaveCount(0);
    expect(asked).toHaveLength(0);
  });
});

test.describe("Since your last visit on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("is a callout card in the co-pilot", async ({ page }) => {
    await gotoStillGlobe(page, (p) => seedLastVisit(p, 14));
    await page.getByTestId("side-tab-copilot").click();
    const callout = page.getByTestId("since-callout");
    await expect(callout).toBeVisible();
    await expect(callout).toContainText("14 h since your visit: 1,286 new stories");
    await expect(strip(page)).toBeHidden();
  });
});
