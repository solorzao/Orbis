import { test, expect, type Request } from "@playwright/test";
import { TOPIC_COLORS } from "../src/lib/clustering";
import { gotoStillGlobe, mockAllApiRoutes, mockGlobeNews } from "./fixtures";

/** A request for the globe's dots (/api/news, not /api/news/...), with its topic. */
function globeFetchTopic(req: Request): string | null | undefined {
  const url = new URL(req.url());
  return url.pathname === "/api/news" ? url.searchParams.get("topic") : undefined;
}

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
    const canvas = page.getByTestId("globe").locator("canvas");
    await expect(canvas).toBeVisible({ timeout: 10000 });
  });

  test("the globe loads slim land outlines that browsers cache for good", async ({ page }) => {
    const [res] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/geo/land-110m.v1.geojson")),
      page.reload(),
    ]);
    expect(res.status()).toBe(200);
    expect(res.headers()["cache-control"]).toBe("public, max-age=31536000, immutable");
    const land = (await res.json()) as { features: { properties: Record<string, string> }[] };
    expect(land.features.length).toBeGreaterThan(150);
    expect(land.features.some((f) => f.properties.ISO_A2 === "AQ")).toBe(false);
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

  test("a keyboard-focused topic pill shows its whole focus ring", async ({ page }) => {
    const pill = page.getByRole("button", { name: "Politics" });
    await expect(pill).toBeVisible();
    for (let i = 0; i < 12 && !(await pill.evaluate((el) => el === document.activeElement)); i++) {
      await page.keyboard.press("Tab");
    }
    await expect(pill).toBeFocused();

    const ring = await pill.evaluate((el) => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      // The topics scroller clips its content, outline included.
      const clip = el.closest(".topics-scroll")!.getBoundingClientRect();
      const reach = parseFloat(cs.outlineWidth) + parseFloat(cs.outlineOffset);
      return {
        style: cs.outlineStyle,
        offset: cs.outlineOffset,
        inside:
          r.top - reach >= clip.top - 0.5 &&
          r.bottom + reach <= clip.bottom + 0.5 &&
          r.left - reach >= clip.left - 0.5 &&
          r.right + reach <= clip.right + 0.5,
      };
    });
    expect(ring.style).toBe("solid");
    expect(ring.offset).toBe("-2px");
    expect(ring.inside).toBe(true);
  });

  test("status pill shows the UTC clock and Live once loaded", async ({ page }) => {
    const status = page.getByTestId("status-pill");
    await expect(status).toBeVisible();
    await expect(status.getByText(/^\d{2}:\d{2}$/)).toBeVisible();
    await expect(status.getByText("Live")).toBeVisible({ timeout: 10000 });
  });

  test("the side panel shows the Co-pilot and Inspect tabs", async ({ page }) => {
    await expect(page.getByTestId("side-panel")).toBeVisible();
    await expect(page.getByTestId("side-tab-copilot")).toBeVisible();
    await expect(page.getByTestId("side-tab-inspect")).toBeVisible();
  });

  test("the timeline and the layer switcher are at the bottom", async ({ page }) => {
    await expect(page.getByTestId("timeline")).toBeVisible();
    await expect(page.getByTestId("layer-switcher")).toBeVisible();
  });

  test("has no theme toggle (Soft Orbit is dark only)", async ({ page }) => {
    await expect(page.locator('button[aria-label*="Theme"]')).toHaveCount(0);
    await expect(page.locator("html")).not.toHaveAttribute("data-theme");
  });

  test("About link is visible", async ({ page }) => {
    await expect(page.locator("a", { hasText: "About" })).toBeVisible();
  });

  test("About link navigates to about page", async ({ page }) => {
    const aboutLink = page.locator("a", { hasText: "About" });
    await expect(aboutLink).toBeVisible();
    await aboutLink.click();
    await expect(page).toHaveURL("/about");
  });
});

test.describe("News Panel", () => {
  test("panel is not visible on initial load", async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("news-panel")).not.toBeVisible();
  });
});

test.describe("Topic filter", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  test("a topic filters the dots on screen at once, then the server's land", async ({ page }) => {
    // The server's Politics answer waits until the test has looked at the globe meanwhile.
    let answerPolitics!: () => void;
    const politicsHeld = new Promise<void>((resolve) => (answerPolitics = resolve));
    await gotoStillGlobe(page, (p) =>
      p.route("**/api/news?*", async (route) => {
        const url = route.request().url();
        if (new URL(url).searchParams.get("topic") === "Politics") await politicsHeld;
        await route.fulfill({ json: mockGlobeNews(url) });
      }),
    );
    const globe = page.getByTestId("globe");
    const timeline = page.getByTestId("timeline");
    const status = page.getByTestId("status-pill").getByRole("status");
    const pills = page.getByTestId("topic-filter");
    await expect(globe).toHaveAttribute("data-dots", "3");
    const every = [TOPIC_COLORS.Climate, TOPIC_COLORS.Politics, TOPIC_COLORS.Economy];
    await expect(globe).toHaveAttribute("data-dot-colors", every.sort().join(" "));

    const politics = page.waitForRequest((r) => globeFetchTopic(r) === "Politics");
    await pills.getByRole("button", { name: "Politics" }).press("Enter");
    await politics;
    // While the server's answer is held, the dots on screen are already the topic's:
    // Paris (1 politics story) and London (3), in its colour; New York has none.
    await expect(status).toHaveText("Loading…");
    await expect(globe).toHaveAttribute("data-dots", "2");
    await expect(globe).toHaveAttribute("data-dot-colors", TOPIC_COLORS.Politics);
    await expect(timeline.getByText("4 stories · 2 places")).toBeVisible();

    answerPolitics();
    await expect(status).toHaveText("Live");
    await expect(globe).toHaveAttribute("data-dots", "2");
    await expect(globe).toHaveAttribute("data-dot-colors", TOPIC_COLORS.Politics);

    const all = page.waitForRequest((r) => globeFetchTopic(r) === null);
    await pills.getByRole("button", { name: "All" }).press("Enter");
    await all;
    await expect(globe).toHaveAttribute("data-dots", "3");
    await expect(timeline.getByText("16 stories · 3 places")).toBeVisible();
  });
});
