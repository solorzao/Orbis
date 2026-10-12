import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_LINKS_COUNT,
  MOCK_LINKS_LIFT,
  gotoStillGlobe,
  hoverArc,
  isLinksList,
  mockAllApiRoutes,
  mockLinks,
} from "./fixtures";

/** Record each /api/links request, answering as the backend does. */
async function recordLinks(page: Page) {
  const asked: URLSearchParams[] = [];
  await page.route(isLinksList, (route) => {
    asked.push(new URL(route.request().url()).searchParams);
    return route.fulfill({ json: mockLinks(route.request().url()) });
  });
  return asked;
}

const linksToggle = (page: Page) => page.getByRole("button", { name: "Links", exact: true });

test.describe("Links layer", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("Links draws the window's arcs by lift; the switch refetches by count", async ({ page }) => {
    let asked: URLSearchParams[] = [];
    await gotoStillGlobe(page, async (p) => {
      asked = await recordLinks(p);
    });
    const globe = page.getByTestId("globe");
    const links = linksToggle(page);

    // Off by default: nothing fetched, no arcs, no rank switch.
    await expect(links).toHaveAttribute("aria-pressed", "false");
    await expect(globe).toHaveAttribute("data-arcs", "0");
    await expect(page.getByTestId("link-rank")).toHaveCount(0);
    expect(asked).toHaveLength(0);

    await links.click();
    await expect(links).toHaveAttribute("aria-pressed", "true");
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    expect(Object.fromEntries(asked.at(-1)!)).toEqual({
      timespan: "24h",
      rank: "lift",
      limit: "40",
    });
    // Dots stay on under the arcs.
    await expect(page.getByRole("button", { name: "Dots" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(globe).toHaveAttribute("data-dots", "3");

    const rank = page.getByTestId("link-rank");
    await expect(rank.getByRole("button", { name: "Surprising" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await rank.getByRole("button", { name: "Most covered" }).click();
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_COUNT.length));
    expect(asked.at(-1)!.get("rank")).toBe("count");

    // A topic refetches the links for it.
    await page.getByTestId("topic-filter").getByRole("button", { name: "Politics" }).click();
    await expect.poll(() => asked.at(-1)!.get("topic")).toBe("Politics");
    expect(asked.at(-1)!.get("rank")).toBe("count");

    // Off again: the arcs and the switch go.
    await links.click();
    await expect(globe).toHaveAttribute("data-arcs", "0");
    await expect(page.getByTestId("link-rank")).toHaveCount(0);
  });

  test("resting on an arc names it in a pill at the arc's top", async ({ page }) => {
    await gotoStillGlobe(page);
    await linksToggle(page).click();
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );
    const ruUa = MOCK_LINKS_LIFT.find((l) => l.a.iso === "RU" && l.b.iso === "UA")!;
    const { pill, x, y } = await hoverArc(page, ruUa);
    // Most of its stories come from Ukraine: the pill names it first.
    await expect(pill).toHaveText("64 stories link Ukraine and Russia, mostly conflict");
    const box = (await pill.boundingBox())!;
    expect(Math.abs(box.x + box.width / 2 - x)).toBeLessThan(3);
    expect(Math.abs(box.y + box.height / 2 - y)).toBeLessThan(3);

    // Off the arc, the pill goes.
    await page.mouse.move(40, 450);
    await expect(page.getByTestId("arc-pill")).toHaveCount(0);
  });

  test("with reduced motion the arcs hold still", async ({ page }) => {
    await gotoStillGlobe(page);
    await linksToggle(page).click();
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    await expect(globe).toHaveAttribute("data-arc-flow", "false");
  });

  test("with full motion and full power the arcs' dashes flow", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("globe").locator("canvas")).toBeVisible({ timeout: 10000 });
    await linksToggle(page).click();
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    await expect(globe).toHaveAttribute("data-arc-flow", "true");
  });

  test("in low-power mode the arcs hold still", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "1"));
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("globe").locator("canvas")).toBeVisible({ timeout: 10000 });
    await linksToggle(page).click();
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    await expect(globe).toHaveAttribute("data-arc-flow", "false");
  });
});
