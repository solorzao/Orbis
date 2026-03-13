import { test, expect } from "@playwright/test";
import { mockAllApiRoutes, mockAgentRoute } from "./fixtures";

test.describe("Agent Panel", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await mockAgentRoute(page);
    await page.goto("/");
  });

  test("agent toggle button is visible", async ({ page }) => {
    await expect(page.getByTestId("agent-toggle")).toBeVisible();
  });

  test("clicking toggle opens agent panel", async ({ page }) => {
    await page.getByTestId("agent-toggle").click();
    await expect(page.getByTestId("agent-panel")).toBeVisible();
    await expect(page.locator("text=Orbis Agent")).toBeVisible();
  });

  test("agent panel shows empty state prompt", async ({ page }) => {
    await page.getByTestId("agent-toggle").click();
    await expect(page.locator("text=Ask about the news")).toBeVisible();
    await expect(page.locator("text=Ask questions about global events")).toBeVisible();
  });

  test("close button hides agent panel", async ({ page }) => {
    await page.getByTestId("agent-toggle").click();
    await expect(page.getByTestId("agent-panel")).toBeVisible();

    await page.locator('button[aria-label="Close panel"]').click();
    await expect(page.getByTestId("agent-panel")).not.toBeVisible();
  });

  test("can type and submit a question", async ({ page }) => {
    await page.getByTestId("agent-toggle").click();

    const input = page.getByTestId("agent-input");
    await input.fill("What is happening in France?");
    await input.press("Enter");

    // User message should appear
    await expect(page.locator("text=What is happening in France?")).toBeVisible();

    // Assistant response should stream in
    await expect(page.locator("text=France recently announced")).toBeVisible({ timeout: 5000 });
  });

  test("send button is disabled when input is empty", async ({ page }) => {
    await page.getByTestId("agent-toggle").click();

    const sendButton = page.locator('button[aria-label="Ask"]');
    await expect(sendButton).toBeDisabled();
  });

  test("citations appear after response completes", async ({ page }) => {
    await page.getByTestId("agent-toggle").click();

    const input = page.getByTestId("agent-input");
    await input.fill("Tell me about climate");
    await input.press("Enter");

    // Wait for the citation pill to appear
    await expect(page.locator("text=France announces new climate policy")).toBeVisible({
      timeout: 5000,
    });
  });

  test("clear button resets conversation", async ({ page }) => {
    await page.getByTestId("agent-toggle").click();

    // Send a message
    const input = page.getByTestId("agent-input");
    await input.fill("Test question");
    await input.press("Enter");
    await expect(page.locator("text=Test question")).toBeVisible();

    // Clear conversation
    await page.locator('button[aria-label="Clear conversation"]').click();

    // Should show empty state again
    await expect(page.locator("text=Ask about the news")).toBeVisible();
  });

  test("shows disabled banner when agent returns 503", async ({ page }) => {
    // Override agent route to return 503
    await page.route("**/api/agent/ask/stream", (route) =>
      route.fulfill({ status: 503, body: "Service Unavailable" }),
    );

    await page.getByTestId("agent-toggle").click();

    const input = page.getByTestId("agent-input");
    await input.fill("Test");
    await input.press("Enter");

    await expect(page.locator("text=temporarily unavailable")).toBeVisible({ timeout: 5000 });
  });
});
