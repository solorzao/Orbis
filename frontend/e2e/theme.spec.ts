import { test, expect } from "@playwright/test";
import { mockAllApiRoutes } from "./fixtures";

test.describe("Theme Toggle", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto("/");
  });

  test("theme toggle button is visible", async ({ page }) => {
    const toggle = page.locator('button[aria-label*="Theme"]');
    await expect(toggle).toBeVisible();
  });

  test("clicking toggle switches data-theme attribute", async ({ page }) => {
    const toggle = page.locator('button[aria-label*="Theme"]');
    const html = page.locator("html");

    // Get initial theme
    const initialTheme = await html.getAttribute("data-theme");

    // Click toggle
    await toggle.click();

    // data-theme should change
    const newTheme = await html.getAttribute("data-theme");
    expect(newTheme).not.toBe(initialTheme);
    expect(["light", "dark"]).toContain(newTheme);
  });

  test("theme persists across page reload", async ({ page }) => {
    const toggle = page.locator('button[aria-label*="Theme"]');
    const html = page.locator("html");

    // Switch theme
    await toggle.click();
    const themeAfterToggle = await html.getAttribute("data-theme");

    // Reload and re-mock
    await mockAllApiRoutes(page);
    await page.reload();
    await page.waitForLoadState("domcontentloaded");

    const themeAfterReload = await html.getAttribute("data-theme");
    expect(themeAfterReload).toBe(themeAfterToggle);
  });

  test("About link navigates to about page", async ({ page }) => {
    const aboutLink = page.locator("a", { hasText: "About" });
    await expect(aboutLink).toBeVisible();
    await aboutLink.click();
    await expect(page).toHaveURL("/about");
  });
});
