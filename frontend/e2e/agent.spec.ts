import { test, expect, type Page } from "@playwright/test";
import {
  buildAgentSSE,
  clickPlace,
  gotoStillGlobe,
  mockAllApiRoutes,
  mockAgentRoute,
  MOCK_ARTICLES,
  PARIS,
} from "./fixtures";

/** The agent lives in the side panel's Co-pilot tab (open by default from 1180px). */
async function openCopilot(page: Page) {
  await page.getByTestId("side-tab-copilot").click();
  await expect(page.getByTestId("agent-panel")).toBeVisible();
}

async function askQuestion(page: Page, question: string) {
  const input = page.getByTestId("agent-input");
  await input.fill(question);
  await input.press("Enter");
}

const [CLIMATE, SUMMIT] = MOCK_ARTICLES;

/** An answer that cites two stories and names Paris (the first dot in MOCK_GLOBE_POINTS). */
const PARIS_ANSWER = {
  answer: "France set new carbon targets [1], and EU leaders met in Paris to discuss trade [2].",
  tools: ["semantic_search", "keyword_search"],
  citations: [CLIMATE, SUMMIT].map((a, i) => ({
    index: i + 1,
    title: a.title,
    url: a.source_url,
    source_name: a.source_name,
    lat: a.latitude,
    lng: a.longitude,
  })),
  globe_actions: [{ type: "flyTo" as const, lat: PARIS.lat, lng: PARIS.lng, label: "Paris" }],
};

const contextPills = (page: Page) => page.getByRole("group", { name: "What the co-pilot sees" });

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
    await expect(page.getByText("Ask about the news")).toBeVisible();
    await expect(page.getByText("It searches the stories on the globe")).toBeVisible();
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

  test("the question input shows the focus ring on its pill", async ({ page }) => {
    await openCopilot(page);
    const input = page.getByTestId("agent-input");
    await input.focus();
    await expect(input).toBeFocused();
    const ring = await input.evaluate((el) => getComputedStyle(el.closest("label")!).outlineStyle);
    expect(ring).toBe("solid");
  });

  test("can type and submit a question", async ({ page }) => {
    await openCopilot(page);
    await askQuestion(page, "What is happening in France?");

    // User message should appear
    await expect(page.locator(".msg.user")).toHaveText("What is happening in France?");

    // Assistant response should stream in
    await expect(page.getByText("France recently announced")).toBeVisible({ timeout: 5000 });
  });

  test("send button is disabled when input is empty", async ({ page }) => {
    await openCopilot(page);

    const sendButton = page.getByRole("button", { name: "Ask", exact: true });
    await expect(sendButton).toBeDisabled();
    await page.getByTestId("agent-input").fill("Floods?");
    await expect(sendButton).toBeEnabled();
  });

  test("citations appear after response completes", async ({ page }) => {
    await openCopilot(page);
    await askQuestion(page, "Tell me about climate");

    // The source row, under the answer
    await expect(
      page.getByRole("group", { name: "Sources" }).getByText("France announces new climate policy"),
    ).toBeVisible({ timeout: 5000 });
  });

  test("clear button resets conversation", async ({ page }) => {
    await openCopilot(page);

    // Send a message
    await askQuestion(page, "Test question");
    await expect(page.getByText("Test question")).toBeVisible();

    // Clear conversation
    await page.getByRole("button", { name: "Clear conversation" }).click();

    // Should show empty state again
    await expect(page.getByText("Ask about the news")).toBeVisible();
  });

  test("shows disabled banner when agent returns 503", async ({ page }) => {
    // Override agent route to return 503
    await page.route("**/api/agent/ask/stream", (route) =>
      route.fulfill({ status: 503, body: "Service Unavailable" }),
    );

    await openCopilot(page);
    await askQuestion(page, "Test");

    await expect(page.getByText("temporarily unavailable")).toBeVisible({ timeout: 5000 });
  });

  test("a quick prompt asks its question", async ({ page }) => {
    await openCopilot(page);
    const request = page.waitForRequest("**/api/agent/ask/stream");
    await page
      .getByRole("group", { name: "Suggested questions" })
      .getByRole("button", { name: "What's the biggest story right now?" })
      .click();

    expect((await request).postDataJSON().question).toBe("What's the biggest story right now?");
    await expect(page.locator(".msg.user")).toHaveText("What's the biggest story right now?");
  });

  test("an answer that lands while Stories is open is in view on coming back", async ({ page }) => {
    let release = () => {};
    const released = new Promise<void>((resolve) => (release = resolve));
    const answer = Array.from({ length: 30 }, (_, i) => `Paragraph ${i + 1} on France.`).join(
      "\n\n",
    );
    await page.route("**/api/agent/ask/stream", async (route) => {
      await released;
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: buildAgentSSE({ answer }),
      });
    });

    await openCopilot(page);
    await askQuestion(page, "Tell me everything about France");
    await page.getByTestId("side-tab-stories").click();
    release();
    await expect(page.getByText("Paragraph 30 on France.")).toBeAttached();

    await page.getByTestId("side-tab-copilot").click();
    const log = page.getByTestId("agent-log");
    await expect(page.getByText("Paragraph 30 on France.")).toBeInViewport();
    expect(
      await log.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight),
    ).toBeLessThan(2);
  });

  test("a conversation scrolled back keeps its place across tabs", async ({ page }) => {
    const answer = Array.from({ length: 30 }, (_, i) => `Paragraph ${i + 1} on France.`).join(
      "\n\n",
    );
    await mockAgentRoute(page, { answer });
    await openCopilot(page);
    await askQuestion(page, "Tell me everything about France");
    await expect(page.getByText("Paragraph 30 on France.")).toBeInViewport();

    const log = page.getByTestId("agent-log");
    await log.evaluate((el) => el.scrollTo({ top: 120 }));
    await expect.poll(() => log.evaluate((el) => el.scrollTop)).toBe(120);

    await page.getByTestId("side-tab-stories").click();
    await page.getByTestId("side-tab-copilot").click();
    await expect.poll(() => log.evaluate((el) => el.scrollTop)).toBe(120);
  });
});

test.describe("Co-pilot console", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  test("the context pills show what is on screen and go with the question", async ({ page }) => {
    await gotoStillGlobe(page, (p) => mockAgentRoute(p, PARIS_ANSWER));
    await expect(contextPills(page)).toHaveText(/^Sees\s*Last 24 h, live$/);

    await clickPlace(page, PARIS);
    await page.getByTestId("topic-filter").getByRole("button", { name: "Politics" }).click();
    await openCopilot(page);
    const pills = contextPills(page);
    await expect(pills.getByText("Paris, France")).toBeVisible();
    await expect(pills.getByText("Politics")).toBeVisible();
    await expect(pills.getByText("Last 24 h, live")).toBeVisible();

    const request = page.waitForRequest("**/api/agent/ask/stream");
    await askQuestion(page, "What is happening here?");
    const { context } = (await request).postDataJSON();
    expect(context).toEqual({
      place: "Paris, France",
      topic: "Politics",
      start_time: expect.any(String),
      end_time: expect.any(String),
    });
    expect(Date.parse(context.end_time) - Date.parse(context.start_time)).toBe(24 * 3_600_000);
  });

  test("× leaves a pill out of the next question only", async ({ page }) => {
    await gotoStillGlobe(page, (p) => mockAgentRoute(p, PARIS_ANSWER));
    await clickPlace(page, PARIS);
    await openCopilot(page);

    await page.getByRole("button", { name: "Remove Paris, France from the context" }).click();
    await expect(contextPills(page).getByText("Paris, France")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "What's the biggest story right now?" }),
    ).toBeVisible();

    let request = page.waitForRequest("**/api/agent/ask/stream");
    await askQuestion(page, "Anything new?");
    expect(Object.keys((await request).postDataJSON().context)).toEqual(["start_time", "end_time"]);

    // Back for the next question
    await expect(contextPills(page).getByText("Paris, France")).toBeVisible();
    await expect(page.getByRole("button", { name: "Brief me on Paris, France" })).toBeEnabled();
    request = page.waitForRequest("**/api/agent/ask/stream");
    await page.getByRole("button", { name: "Brief me on Paris, France" }).click();
    const second = (await request).postDataJSON();
    expect(second.question).toBe("Brief me on Paris, France");
    expect(second.context.place).toBe("Paris, France");
  });

  test("citation pills and sources open their story", async ({ page, context }) => {
    await context.route("https://example.com/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<title>Story</title>" }),
    );
    await gotoStillGlobe(page, (p) => mockAgentRoute(p, PARIS_ANSWER));
    await askQuestion(page, "What is happening in France?");

    const answer = page.locator(".msg.bot");
    const cite = answer.getByRole("button", { name: "Source 2" });
    await expect(cite).toHaveText("2");
    await expect(cite).toHaveAttribute("title", `BBC News: ${SUMMIT.title}`);
    let popup = page.waitForEvent("popup");
    await cite.click();
    expect((await popup).url()).toBe(SUMMIT.source_url);

    const sources = page.getByRole("group", { name: "Sources" }).getByRole("button");
    await expect(sources).toHaveText([`1Reuters: ${CLIMATE.title}`, `2BBC News: ${SUMMIT.title}`]);
    popup = page.waitForEvent("popup");
    await sources.first().click();
    expect((await popup).url()).toBe(CLIMATE.source_url);
  });

  test("action pills fly to the place and show its stories", async ({ page }) => {
    const errors: Error[] = [];
    page.on("pageerror", (e) => errors.push(e));
    await gotoStillGlobe(page, (p) => mockAgentRoute(p, PARIS_ANSWER));
    await askQuestion(page, "What is happening in France?");

    const actions = page.getByRole("group", { name: "Suggested actions" });
    await expect(actions.getByRole("button")).toHaveText(["Fly to Paris", "Show stories here"]);
    await actions.getByRole("button", { name: "Fly to Paris" }).click();
    await expect(page.getByTestId("side-tab-copilot")).toHaveAttribute("aria-selected", "true");

    await actions.getByRole("button", { name: "Show stories here" }).click();
    await expect(page.getByTestId("side-tab-stories")).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByTestId("news-panel").getByRole("heading", { name: "Paris, France" }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("Show stories here is hidden when the globe has no dot there", async ({ page }) => {
    await gotoStillGlobe(page, (p) =>
      mockAgentRoute(p, {
        ...PARIS_ANSWER,
        globe_actions: [{ type: "flyTo", lat: -33.87, lng: 151.21, label: "Sydney" }],
      }),
    );
    await askQuestion(page, "And Australia?");

    const actions = page.getByRole("group", { name: "Suggested actions" });
    await expect(actions.getByRole("button")).toHaveText(["Fly to Sydney"]);
  });
});
