import { test, expect, type Page } from "@playwright/test";
import {
  mockAllApiRoutes,
  gotoStillGlobe,
  clickPlace,
  MOCK_ARTICLES,
  MOCK_GLOBE_POINTS,
  MOCK_SUMMARY,
  PARIS,
  LONDON,
} from "./fixtures";

const recentPlaces = (page: Page) => page.getByRole("group", { name: "Recent places and links" });

test.describe("News Panel", () => {
  test("panel is not visible on initial load", async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("globe").locator("canvas")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("news-panel")).not.toBeVisible();
  });
});

test.describe("Inspect tab: a place", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  test("clicking a dot opens the side panel on Inspect with the place's stories", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    // Collapsed first, so the click has to open it.
    await page.getByTestId("side-collapse").click();
    await expect(page.getByTestId("side-panel")).not.toBeVisible();

    await clickPlace(page, PARIS);

    const side = page.getByTestId("side-panel");
    await expect(side).toBeVisible();
    await expect(page.getByTestId("side-tab-inspect")).toHaveAttribute("aria-selected", "true");
    const panel = side.getByTestId("news-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByText("3 stories")).toBeVisible();
    await expect(panel.getByText(MOCK_SUMMARY.summary)).toBeVisible();
    for (const article of MOCK_ARTICLES) {
      await expect(panel.getByRole("link", { name: article.title })).toHaveAttribute(
        "href",
        article.source_url,
      );
    }
    await expect(panel.getByRole("article").first().locator(".sent")).toHaveText(/\+0\.60/);
  });

  test("the globe keeps focus when a dot opens the stories", async ({ page }) => {
    await gotoStillGlobe(page);
    await clickPlace(page, PARIS);
    const inSide = await page.evaluate(
      () => !!document.activeElement?.closest('[data-testid="side-panel"]'),
    );
    expect(inSide).toBe(false);
  });

  test("a second dot adds a recent place; the pills switch and close places", async ({ page }) => {
    await gotoStillGlobe(page);
    await clickPlace(page, PARIS);
    await clickPlace(page, LONDON);

    const paris = recentPlaces(page).getByRole("button", { name: /^Paris/ });
    const london = recentPlaces(page).getByRole("button", { name: /^London/ });
    await expect(london).toHaveAttribute("aria-pressed", "true");
    await expect(paris).toHaveAttribute("aria-pressed", "false");

    await paris.click();
    await expect(paris).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByTestId("news-panel").getByRole("heading", { name: "Paris, France" }),
    ).toBeVisible();

    await recentPlaces(page).getByRole("button", { name: "Close London" }).click();
    await expect(london).toHaveCount(0);
  });

  test("filters the stories, then summarizes the selection", async ({ page }) => {
    await gotoStillGlobe(page);
    await clickPlace(page, PARIS);
    const panel = page.getByTestId("news-panel");

    await panel.getByRole("searchbox", { name: "Search headlines" }).fill("paris");
    await expect(panel.getByRole("article")).toHaveCount(2);
    await expect(panel.getByText("2 of 3 stories")).toBeVisible();

    await panel.getByRole("button", { name: /Summarize selection/ }).click();
    await expect(panel.getByText("A mock filtered summary.")).toBeVisible();

    await panel.getByRole("button", { name: "All", exact: true }).click();
    await expect(panel.getByRole("article")).toHaveCount(3);
    await panel.getByRole("button", { name: "Technology" }).click();
    await expect(panel.getByRole("article")).toHaveCount(1);
  });

  test("minimize keeps the place in recent places; close removes it", async ({ page }) => {
    await gotoStillGlobe(page);
    await clickPlace(page, PARIS);

    await page.getByTestId("news-panel").getByRole("button", { name: "Minimize panel" }).click();
    await expect(page.getByTestId("news-panel")).toHaveCount(0);
    const paris = recentPlaces(page).getByRole("button", { name: /^Paris/ });
    await expect(paris).toHaveAttribute("aria-pressed", "false");

    await paris.click();
    await page.getByTestId("news-panel").getByRole("button", { name: "Close panel" }).click();
    await expect(recentPlaces(page)).toHaveCount(0);
    await expect(page.getByText("Click a dot on the globe to see its stories here.")).toBeVisible();
  });

  test("minimize, Escape and close keep keyboard focus in the Inspect tab", async ({ page }) => {
    await gotoStillGlobe(page);
    await clickPlace(page, PARIS);
    await clickPlace(page, LONDON);
    const panel = page.getByTestId("news-panel");
    const london = recentPlaces(page).getByRole("button", { name: /^London/ });

    // Minimize: focus goes to the place's pill, which reopens it.
    await panel.getByRole("button", { name: "Minimize panel" }).focus();
    await page.keyboard.press("Enter");
    await expect(london).toBeFocused();
    await expect(london).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("Enter");
    await expect(london).toHaveAttribute("aria-pressed", "true");

    // Escape from the search box does the same.
    await panel.getByRole("searchbox", { name: "Search headlines" }).focus();
    await page.keyboard.press("Escape");
    await expect(london).toBeFocused();
    await page.keyboard.press("Enter");

    // × on another place: focus goes to the open place's pill.
    await recentPlaces(page).getByRole("button", { name: "Close Paris" }).focus();
    await page.keyboard.press("Enter");
    await expect(london).toBeFocused();

    // Closing the open place leaves no pill to take it: the Inspect panel does.
    await panel.getByRole("button", { name: "Close panel" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("tabpanel", { name: "Inspect" })).toBeFocused();
  });

  test("a long unbroken headline wraps instead of scrolling the panel sideways", async ({
    page,
  }) => {
    await gotoStillGlobe(page, async (p) => {
      await p.route("**/api/news/cluster*", (route) =>
        route.fulfill({
          json: [{ ...MOCK_ARTICLES[0], title: "Breaking".repeat(40) }, ...MOCK_ARTICLES.slice(1)],
        }),
      );
    });
    await clickPlace(page, PARIS);
    const stories = page.getByRole("tabpanel", { name: "Inspect" });
    await expect(stories.getByRole("article")).toHaveCount(3);
    const overflow = await stories.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("Load more appends the next page", async ({ page }) => {
    const TOTAL = 25;
    await gotoStillGlobe(page, async (p) => {
      await p.route("**/api/news?*", (route) =>
        route.fulfill({
          json: MOCK_GLOBE_POINTS.map((pt) =>
            pt === PARIS ? { ...pt, article_count: TOTAL } : pt,
          ),
        }),
      );
      await p.route("**/api/news/cluster*", (route) => {
        const params = new URL(route.request().url()).searchParams;
        const offset = Number(params.get("offset") ?? 0);
        const limit = Number(params.get("limit") ?? 10);
        const n = Math.max(0, Math.min(limit, TOTAL - offset));
        route.fulfill({
          json: Array.from({ length: n }, (_, i) => ({
            ...MOCK_ARTICLES[0],
            id: `story-${offset + i}`,
            title: `Story ${offset + i + 1}`,
          })),
        });
      });
    });
    await clickPlace(page, PARIS);
    const panel = page.getByTestId("news-panel");
    await expect(panel.getByRole("article")).toHaveCount(10);

    const more = panel.getByRole("button", { name: /Load more/ });
    await expect(more).toContainText("15 more");
    await more.click();
    await expect(panel.getByRole("article")).toHaveCount(25);
    await expect(more).toHaveCount(0);
  });
});
