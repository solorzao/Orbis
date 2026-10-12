import { test, expect, type Request } from "@playwright/test";
import {
  CAIRO,
  MOCK_PREVIEW,
  PARIS,
  clickPlace,
  gotoStillGlobe,
  hoverPlace,
  tapPlace,
  withCairo,
} from "./fixtures";

const isPreview = (r: Request) => new URL(r.url()).pathname === "/api/news/preview";

test.describe("City hover card", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  test("resting on a dot shows its card: place, stories and lead headline", async ({ page }) => {
    await gotoStillGlobe(page);
    const card = await hoverPlace(page, PARIS);

    await expect(card.getByText("Paris, France")).toBeVisible();
    await expect(card.getByText("5 stories, last 24 h")).toBeVisible();
    await expect(card.getByText("France announces new climate policy")).toBeVisible();
    await expect(card.getByText("Reuters")).toBeVisible();
    await expect(card.getByText("Click to open")).toBeVisible();
    // Screen readers hear its label from a live region that is always there.
    await expect(page.getByTestId("hover-announcer")).toHaveText(
      "Paris, France: 5 stories. France announces new climate policy",
    );
    await expect(card).not.toHaveAttribute("aria-live");
    // The lead's image, loaded without a referrer.
    const img = card.locator(".thumb img");
    await expect(img).toBeVisible();
    await expect(img).toHaveAttribute("referrerpolicy", "no-referrer");
    // The reticle locks onto the dot, with a leader to the card.
    await expect(page.locator("svg.hud circle").first()).toBeAttached();
    await expect(page.locator("svg.hud path.leader")).toBeAttached();
  });

  test("the sparkline, names and AI brief follow after the dwell, from one request", async ({
    page,
  }) => {
    const previews: Request[] = [];
    page.on("request", (r) => {
      if (isPreview(r)) previews.push(r);
    });
    await gotoStillGlobe(page);
    const card = await hoverPlace(page, PARIS);

    await expect(card.getByTestId("hover-spark")).toBeVisible();
    await expect(card.getByText("Emmanuel Macron")).toBeVisible();
    await expect(card.locator(".brief")).toContainText(MOCK_PREVIEW.brief.slice(0, 40));
    await expect(card.locator(".brief .ai")).toHaveText("AI");

    expect(previews).toHaveLength(1);
    const url = new URL(previews[0].url());
    expect(url.searchParams.get("timespan")).toBe("24h");
    expect(Number(url.searchParams.get("lat"))).toBeCloseTo(PARIS.lat, 3);
    expect(url.searchParams.has("topic")).toBe(false);
  });

  test("a conflict lead's image is veiled until Show, and the card stays for it", async ({
    page,
  }) => {
    await gotoStillGlobe(page, withCairo);
    const card = await hoverPlace(page, CAIRO);
    const thumb = card.locator(".thumb");
    await expect(thumb).toHaveClass(/veiled/);
    // Only the image is blurred: the veil's label stays sharp enough to read.
    await expect(thumb.locator("img")).toHaveCSS("filter", /blur/);
    await expect(thumb).toHaveCSS("filter", "none");
    await expect(thumb.locator(".veil")).toHaveCSS("filter", "none");

    await card.getByRole("button", { name: /Conflict image hidden/ }).click();
    await expect(thumb).not.toHaveClass(/veiled/);
    await expect(thumb.locator("img")).toBeVisible();
    await expect(card).toBeVisible();
    await expect(card.getByRole("button", { name: /Conflict image hidden/ })).toHaveCount(0);
  });

  test("Escape hides the card", async ({ page }) => {
    await gotoStillGlobe(page);
    const card = await hoverPlace(page, PARIS);
    await page.keyboard.press("Escape");
    await expect(card).toHaveCount(0);
    await expect(page.getByTestId("hover-card")).toHaveCount(0);
    await expect(page.getByTestId("hover-announcer")).toHaveText("");
  });

  test("clicking the dot still opens its stories, and the card gives way", async ({ page }) => {
    await gotoStillGlobe(page);
    await clickPlace(page, PARIS);
    await expect(page.getByTestId("hover-card")).toHaveCount(0);
  });
});

test.describe("City hover card on a touch screen", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("a tap docks the card above the bottom row; Open stories opens the panel", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    const card = await tapPlace(page, PARIS);
    await expect(card).toHaveClass(/docked/);
    await expect(card.getByText("Click to open")).toHaveCount(0);

    // Full width less 12px a side, 12px above the bottom row.
    const box = (await card.boundingBox())!;
    expect(box.x).toBe(12);
    expect(box.width).toBe(390 - 24);
    const timeline = (await page.getByTestId("timeline").boundingBox())!;
    expect(timeline.y - (box.y + box.height)).toBeCloseTo(12, 0);
    const bar = (await page.getByTestId("topic-filter").boundingBox())!;
    expect(box.y).toBeGreaterThanOrEqual(bar.y + bar.height + 12);

    await card.getByRole("button", { name: "Open stories" }).tap();
    await expect(
      page.getByTestId("news-panel").getByRole("heading", { name: "Paris, France", exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("hover-card")).toHaveCount(0);
  });
});
