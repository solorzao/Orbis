import { test, expect, type Page } from "@playwright/test";
import {
  LAST_VISIT_KEY,
  MOCK_BREAKING,
  MOCK_DELTA,
  gotoStillGlobe,
  isDelta,
  seedLastVisit,
  withBreaking,
} from "./fixtures";
import { utcTime, utcWeekday } from "../src/lib/timeWindow";
import { floorSince } from "../src/lib/sinceVisit";

const strip = (page: Page) => page.getByTestId("since-strip");
const TEXT = `Welcome back. 14 h since your visit: 1,286 new stories, ${MOCK_BREAKING.length} breaking stories.`;

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
    // None breaking (the default mock): the strip leaves that part out.
    await expect(strip(page).locator(".since-txt")).toHaveText(
      "Welcome back. 14 h since your visit: 1,286 new stories.",
    );
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
    const stored = Date.parse(
      (await page.evaluate((k) => localStorage.getItem(k), LAST_VISIT_KEY))!,
    );
    // From the visit as the strip's counts floor it: within a day, to the quarter hour.
    const visit = floorSince(stored, Date.now());
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

  test("counts the breaking stories when there are some", async ({ page }) => {
    await gotoStillGlobe(page, async (p) => {
      await seedLastVisit(p, 14);
      await withBreaking(p);
    });
    await expect(strip(page).locator(".since-txt")).toHaveText(TEXT);
  });

  test("Dismiss hides it for the session, the focus moving to the topics", async ({ page }) => {
    await gotoStillGlobe(page, (p) => seedLastVisit(p, 14));
    await strip(page).getByRole("button", { name: "Dismiss" }).focus();
    await page.keyboard.press("Enter");
    await expect(strip(page)).toHaveCount(0);
    await expect(
      page.getByTestId("topic-filter").getByRole("button", { name: "All" }),
    ).toBeFocused();
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

  test("is a callout card in the co-pilot, in place of its intro", async ({ page }) => {
    await gotoStillGlobe(page, (p) => seedLastVisit(p, 14));
    await page.getByTestId("side-tab-copilot").click();
    const callout = page.getByTestId("since-callout");
    await expect(callout).toBeVisible();
    await expect(callout).toContainText("14 h since your visit: 1,286 new stories");
    await expect(strip(page)).toBeHidden();
    // The short sheet has room for one: the welcome, not the intro.
    await expect(page.getByText("Ask about the news")).toBeHidden();

    // Dismissed, the focus stays in the co-pilot, and its intro comes back.
    await callout.getByRole("button", { name: "Dismiss" }).focus();
    await page.keyboard.press("Enter");
    await expect(callout).toHaveCount(0);
    await expect(page.getByRole("tabpanel", { name: "Co-pilot" })).toBeFocused();
    await expect(page.getByText("Ask about the news")).toBeVisible();
  });
});
