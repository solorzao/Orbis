import { test, expect, type Page } from "@playwright/test";
import { mockAllApiRoutes, mockAgentRoute } from "./fixtures";

/** The agent lives in the side panel's Co-pilot tab (open by default from 1180px). */
async function openCopilot(page: Page) {
  await page.getByTestId("side-tab-copilot").click();
  await expect(page.getByTestId("agent-panel")).toBeVisible();
}

test.describe("Agent Panel", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await mockAgentRoute(page);
    await page.goto("/");
  });

  test("the Co-pilot tab is open by default on a wide screen", async ({ page }) => {
    await expect(page.getByTestId("side-tab-copilot")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("side-panel").getByTestId("agent-panel")).toBeVisible();
  });

  test("the Co-pilot tab brings the agent back from Stories", async ({ page }) => {
    await page.getByTestId("side-tab-stories").click();
    await expect(page.getByTestId("agent-panel")).not.toBeVisible();
    await page.getByTestId("side-tab-copilot").click();
    await expect(page.getByTestId("agent-panel")).toBeVisible();
  });

  test("the tabs work from the keyboard", async ({ page }) => {
    const copilot = page.getByTestId("side-tab-copilot");
    await copilot.focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("side-tab-stories")).toBeFocused();
    await expect(page.getByTestId("side-tab-stories")).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Home");
    await expect(copilot).toBeFocused();
    await expect(page.getByTestId("agent-panel")).toBeVisible();
  });

  test("the panel fades out on collapse before it hides", async ({ page }) => {
    const side = page.getByTestId("side-panel");
    await page.getByTestId("side-collapse").click();
    // Still visible while it fades (visibility waits for the fade)...
    expect(await side.evaluate((el) => getComputedStyle(el).visibility)).toBe("visible");
    // ...then hidden.
    await expect(side).not.toBeVisible();
  });

  test("with reduced motion the panel hides at once", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const side = page.getByTestId("side-panel");
    await page.getByTestId("side-collapse").click();
    expect(await side.evaluate((el) => getComputedStyle(el).visibility)).toBe("hidden");
  });

  test("agent panel shows empty state prompt", async ({ page }) => {
    await openCopilot(page);
    await expect(page.locator("text=Ask about the news")).toBeVisible();
    await expect(page.locator("text=Ask questions about global events")).toBeVisible();
  });

  test("the collapse button hides the agent and the pill brings it back", async ({ page }) => {
    await openCopilot(page);

    await page.getByTestId("side-collapse").click();
    await expect(page.getByTestId("agent-panel")).not.toBeVisible();
    const pill = page.getByTestId("side-open");
    await expect(pill).toBeVisible();
    await expect(pill).toBeFocused();

    await pill.click();
    await expect(page.getByTestId("agent-panel")).toBeVisible();
    await expect(page.getByTestId("side-tab-copilot")).toBeFocused();
  });

  test("the question input shows the focus ring", async ({ page }) => {
    await openCopilot(page);
    const input = page.getByTestId("agent-input");
    await input.focus();
    await expect(input).toBeFocused();
    expect(await input.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
  });

  test("can type and submit a question", async ({ page }) => {
    await openCopilot(page);

    const input = page.getByTestId("agent-input");
    await input.fill("What is happening in France?");
    await input.press("Enter");

    // User message should appear
    await expect(page.locator("text=What is happening in France?")).toBeVisible();

    // Assistant response should stream in
    await expect(page.locator("text=France recently announced")).toBeVisible({ timeout: 5000 });
  });

  test("send button is disabled when input is empty", async ({ page }) => {
    await openCopilot(page);

    const sendButton = page.locator('button[aria-label="Ask"]');
    await expect(sendButton).toBeDisabled();
  });

  test("citations appear after response completes", async ({ page }) => {
    await openCopilot(page);

    const input = page.getByTestId("agent-input");
    await input.fill("Tell me about climate");
    await input.press("Enter");

    // Wait for the citation pill to appear
    await expect(page.locator("text=France announces new climate policy")).toBeVisible({
      timeout: 5000,
    });
  });

  test("clear button resets conversation", async ({ page }) => {
    await openCopilot(page);

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

    await openCopilot(page);

    const input = page.getByTestId("agent-input");
    await input.fill("Test");
    await input.press("Enter");

    await expect(page.locator("text=temporarily unavailable")).toBeVisible({ timeout: 5000 });
  });
});
