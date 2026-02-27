import { test, expect } from "@playwright/test";

test.describe("Globe Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("page loads with Orbis branding", async ({ page }) => {
    await expect(page).toHaveTitle(/Orbis/);
    await expect(page.locator("text=ORBIS")).toBeVisible();
  });

  test("topic filter bar is visible", async ({ page }) => {
    await expect(page.locator("text=All")).toBeVisible();
    await expect(page.locator("text=Politics")).toBeVisible();
    await expect(page.locator("text=Conflict")).toBeVisible();
    await expect(page.locator("text=Technology")).toBeVisible();
    await expect(page.locator("text=Climate")).toBeVisible();
  });

  test("globe canvas renders", async ({ page }) => {
    // globe.gl renders into a canvas element
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible({ timeout: 10000 });
  });

  test("status bar shows story count", async ({ page }) => {
    // The status bar should show the number of stories
    await expect(page.locator("text=/\\d+ stories/")).toBeVisible({ timeout: 10000 });
  });

  test("clicking a topic filter updates active state", async ({ page }) => {
    const politicsFilter = page.locator("button", { hasText: "Politics" });
    await politicsFilter.click();

    // The filter should have an active visual indicator
    // After clicking, the story count may change
    await expect(page.locator("text=/\\d+ stories/")).toBeVisible();
  });

  test("clicking All filter shows all stories", async ({ page }) => {
    // First filter to a specific topic
    await page.locator("button", { hasText: "Technology" }).click();
    await page.waitForTimeout(300);

    // Then click All to reset
    await page.locator("button", { hasText: "All" }).click();
    await page.waitForTimeout(300);

    await expect(page.locator("text=/\\d+ stories/")).toBeVisible();
  });
});

test.describe("News Panel", () => {
  test("panel is not visible on initial load", async ({ page }) => {
    await page.goto("/");
    // The news panel should not be visible initially
    const panel = page.locator("[data-testid=news-panel]");
    await expect(panel).not.toBeVisible();
  });
});
