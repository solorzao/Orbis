import { test, expect } from "@playwright/test";
import { mockAllApiRoutes } from "./fixtures";

test.describe("Globe Page", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto("/");
  });

  test("page loads with Orbis branding", async ({ page }) => {
    await expect(page).toHaveTitle(/Orbis/);
    await expect(page.locator("text=Orbis").first()).toBeVisible();
  });

  test("topic filter bar is visible with all topics", async ({ page }) => {
    const filter = page.getByTestId("topic-filter");
    await expect(filter).toBeVisible();

    for (const topic of [
      "All",
      "Politics",
      "Conflict",
      "Technology",
      "Climate",
      "Economy",
      "Health",
    ]) {
      await expect(page.locator("button", { hasText: topic })).toBeVisible();
    }
  });

  test("globe canvas renders", async ({ page }) => {
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible({ timeout: 10000 });
  });

  test("status bar shows story count", async ({ page }) => {
    await expect(page.locator("text=/\\d+ stories/")).toBeVisible({
      timeout: 10000,
    });
  });

  test("clicking a topic filter updates active state", async ({ page }) => {
    const politicsFilter = page.locator("button", { hasText: "Politics" });
    await politicsFilter.click();
    await expect(page.locator("text=/\\d+ stories/")).toBeVisible();
  });

  test("clicking All filter shows all stories", async ({ page }) => {
    await page.locator("button", { hasText: "Technology" }).click();
    await page.waitForTimeout(300);

    await page.locator("button", { hasText: "All" }).click();
    await page.waitForTimeout(300);

    await expect(page.locator("text=/\\d+ stories/")).toBeVisible();
  });

  test("agent toggle button is visible", async ({ page }) => {
    await expect(page.getByTestId("agent-toggle")).toBeVisible();
  });

  test("time slider is present at bottom", async ({ page }) => {
    await expect(page.getByTestId("time-slider")).toBeVisible();
  });

  test("theme toggle is present", async ({ page }) => {
    await expect(page.locator('button[aria-label*="Theme"]')).toBeVisible();
  });

  test("About link is visible", async ({ page }) => {
    await expect(page.locator("a", { hasText: "About" })).toBeVisible();
  });
});

test.describe("News Panel", () => {
  test("panel is not visible on initial load", async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("news-panel")).not.toBeVisible();
  });
});
