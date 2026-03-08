import { test, expect } from "@playwright/test";

test.describe("About Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/about");
  });

  test("renders page with heading and features", async ({ page }) => {
    await expect(page.locator("h1")).toContainText("Orbis");
    // Should list features
    await expect(page.locator("text=Real-time news data")).toBeVisible();
    await expect(page.locator("text=AI summaries")).toBeVisible();
  });

  test("has a CTA link back to the globe", async ({ page }) => {
    const cta = page.locator("a", { hasText: /explore/i });
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "/");
  });

  test("CTA navigates to home page", async ({ page }) => {
    await page.locator("a", { hasText: /explore/i }).click();
    await expect(page).toHaveURL("/");
  });

  test("lists Orbis Agent as a feature", async ({ page }) => {
    await expect(page.locator("text=Orbis Agent")).toBeVisible();
  });
});
