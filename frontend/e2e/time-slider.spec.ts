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
    await expect(page.locator("text=Today")).toBeVisible();
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

  test("previous day button navigates to yesterday", async ({ page }) => {
    const prevButton = page.locator('button[aria-label="Previous day"]');
    await expect(prevButton).toBeVisible();
    await prevButton.click();

    await expect(page.locator("text=Yesterday")).toBeVisible();
  });

  test("next day button is disabled on Today", async ({ page }) => {
    const nextButton = page.locator('button[aria-label="Next day"]');
    await expect(nextButton).toBeDisabled();
  });

  test("next day button navigates back to Today from Yesterday", async ({
    page,
  }) => {
    // Go to yesterday
    await page.locator('button[aria-label="Previous day"]').click();
    await expect(page.locator("text=Yesterday")).toBeVisible();

    // Go back to today
    const nextButton = page.locator('button[aria-label="Next day"]');
    await expect(nextButton).toBeEnabled();
    await nextButton.click();

    await expect(page.locator("text=Today")).toBeVisible();
  });

  test("navigating multiple days back shows date label", async ({ page }) => {
    // Go back 2 days
    const prevButton = page.locator('button[aria-label="Previous day"]');
    await prevButton.click();
    await prevButton.click();

    // Should show a formatted date (not "Today" or "Yesterday")
    await expect(page.locator("text=Today")).not.toBeVisible();
    await expect(page.locator("text=Yesterday")).not.toBeVisible();
  });
});
