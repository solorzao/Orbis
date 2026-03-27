import { test, expect } from "@playwright/test";
import { mockAllApiRoutes } from "./fixtures";

test.describe("Time Slider", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("time-slider")).toBeVisible({ timeout: 10000 });
  });

  test("time slider is visible with story count", async ({ page }) => {
    await expect(page.locator("text=/\\d+ stories/")).toBeVisible();
    await expect(page.locator("text=/\\d+ locations/")).toBeVisible();
  });

  test("shows LIVE status on initial load", async ({ page }) => {
    // Wait for loading to finish
    await expect(page.locator("text=LIVE")).toBeVisible({ timeout: 10000 });
  });

  test("shows Today label by default", async ({ page }) => {
    await expect(page.locator('button[aria-label="Today"]')).toBeVisible();
  });

  test("preset buttons are visible", async ({ page }) => {
    // Presets are duplicated for desktop/mobile — use .first()
    await expect(page.locator("button", { hasText: "1h" }).first()).toBeVisible();
    await expect(page.locator("button", { hasText: "6h" }).first()).toBeVisible();
    await expect(page.locator("button", { hasText: "12h" }).first()).toBeVisible();
  });

  test("clicking a preset shows Reset button", async ({ page }) => {
    await page.locator("button", { hasText: "6h" }).first().click();
    await expect(page.locator("button", { hasText: "Reset" })).toBeVisible();
  });

  test("Reset button restores full range", async ({ page }) => {
    // Click preset first
    await page.locator("button", { hasText: "1h" }).first().click();
    await expect(page.locator("button", { hasText: "Reset" })).toBeVisible();

    // Click reset
    await page.locator("button", { hasText: "Reset" }).click();
    await expect(page.locator("button", { hasText: "Reset" })).not.toBeVisible();
  });

  test("clicking Yesterday chip navigates to yesterday", async ({ page }) => {
    const ydayChip = page.locator('button[aria-label="Yesterday"]');
    await expect(ydayChip).toBeVisible();
    await ydayChip.click();

    // Verify the Yesterday chip is now active
    await expect(ydayChip).toHaveClass(/text-blue-400/);
  });

  test("Today chip is active by default", async ({ page }) => {
    const todayChip = page.locator('button[aria-label="Today"]');
    await expect(todayChip).toBeVisible();
    // Today chip should have the active styling (blue text)
    await expect(todayChip).toHaveClass(/text-blue-400/);
  });

  test("clicking Today chip from yesterday navigates back", async ({ page }) => {
    // Go to yesterday
    const ydayChip = page.locator('button[aria-label="Yesterday"]');
    await ydayChip.click();
    await expect(ydayChip).toHaveClass(/text-blue-400/);

    // Go back to today
    const todayChip = page.locator('button[aria-label="Today"]');
    await todayChip.click();

    await expect(todayChip).toHaveClass(/text-blue-400/);
  });

  test("day selector chips are visible", async ({ page }) => {
    // Should have 7 day chips (Today + 6 days back)
    const todayChip = page.locator('button[aria-label="Today"]');
    const ydayChip = page.locator('button[aria-label="Yesterday"]');
    await expect(todayChip).toBeVisible();
    await expect(ydayChip).toBeVisible();
  });
});
