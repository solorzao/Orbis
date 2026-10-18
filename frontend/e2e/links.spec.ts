import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_LINKS_COUNT,
  MOCK_LINKS_LIFT,
  NEW_YORK,
  PARIS,
  clickArc,
  gotoStillGlobe,
  hoverArc,
  hoverPlace,
  isLinksList,
  mockAllApiRoutes,
  mockAgentRoute,
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
    expect(MOCK_LINKS_COUNT.length).not.toBe(MOCK_LINKS_LIFT.length); // so the redraw shows
    await rank.getByRole("button", { name: "Most covered" }).click();
    await expect.poll(() => asked.at(-1)!.get("rank")).toBe("count");
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_COUNT.length));

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

  test("the arc pill is opaque, so an arc behind it never crosses its words", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0")); // glass on
    await gotoStillGlobe(page);
    await linksToggle(page).click();
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );
    const { pill } = await hoverArc(page, MOCK_LINKS_LIFT.find((l) => l.a.iso === "RU")!);
    const background = await pill.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(background).toMatch(/^rgb\(/); // no alpha: opaque
  });

  test("with reduced motion the arcs hold still", async ({ page }) => {
    // At full power, so it is reduced motion that stills them (CI's 4 cores are low-power).
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
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

  test("the dashes pause while the globe is dragged, without redrawing the arcs", async ({
    page,
  }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("globe").locator("canvas")).toBeVisible({ timeout: 10000 });
    await linksToggle(page).click();
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-arc-flow", "true");
    await expect(globe).toHaveAttribute("data-arc-dashed", "true");
    // How many times the arcs were drawn (data set on the globe): a pause redraws none.
    const drawn = await globe.getAttribute("data-arcs-drawn");
    expect(Number(drawn)).toBeGreaterThan(0);

    await page.mouse.move(300, 450); // the canvas, off the globe's chrome
    await page.mouse.down();
    await page.mouse.move(340, 470, { steps: 4 });
    await expect(globe).toHaveAttribute("data-arc-flow", "false");
    // Paused, not redrawn: still dashed (no solid flash), the same arcs.
    await expect(globe).toHaveAttribute("data-arc-dashed", "true");
    await expect(globe).toHaveAttribute("data-arcs-drawn", drawn!);

    await page.mouse.up();
    await expect(globe).toHaveAttribute("data-arc-flow", "true");
    await expect(globe).toHaveAttribute("data-arcs-drawn", drawn!);

    // A click (press and release) redraws nothing either.
    await page.mouse.click(300, 450);
    await expect(globe).toHaveAttribute("data-arc-flow", "true");
    await expect(globe).toHaveAttribute("data-arcs-drawn", drawn!);
  });

  test("a drag ends when the window loses focus mid-press", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("globe").locator("canvas")).toBeVisible({ timeout: 10000 });
    await linksToggle(page).click();
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-arc-flow", "true");
    await page.mouse.move(300, 450);
    await page.mouse.down();
    await expect(globe).toHaveAttribute("data-arc-flow", "false");
    // The release never comes (an alt-tab mid-drag): blur ends the drag.
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await expect(globe).toHaveAttribute("data-arc-flow", "true");
    await page.mouse.up();
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

test.describe("Link hints", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("while Links is on, the hover card counts the countries a place's country is linked to", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    let card = await hoverPlace(page, PARIS);
    await expect(card.getByText("Click to open")).toBeVisible();
    await expect(card.locator(".foot-links")).toHaveCount(0); // Links is off

    await linksToggle(page).click();
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );
    // France: linked to the United Kingdom and Ukraine.
    card = await hoverPlace(page, PARIS);
    await expect(card.locator(".foot-links")).toHaveText("2 linked countries");
  });

  test("the co-pilot offers Show links for places in two countries; it turns Links on", async ({
    page,
  }) => {
    let asked = 0;
    await gotoStillGlobe(page, async (p) => {
      await mockAgentRoute(p, {
        answer: "Markets in Paris and New York reacted to the talks.",
        globe_actions: [
          { type: "flyTo", lat: PARIS.lat, lng: PARIS.lng, label: "Paris" },
          { type: "flyTo", lat: NEW_YORK.lat, lng: NEW_YORK.lng, label: "New York" },
        ],
      });
      await p.route(isLinksList, (route) => {
        asked++;
        return route.fulfill({ json: mockLinks(route.request().url()) });
      });
    });
    const input = page.getByTestId("agent-input");
    await input.fill("How did markets react?");
    await input.press("Enter");

    const actions = page.getByRole("group", { name: "Suggested actions" });
    await expect(actions.getByRole("button")).toHaveText([
      "Fly to Paris",
      "Fly to New York",
      "Show stories here",
      "Show links",
    ]);
    expect(asked).toBe(0);
    // From the keyboard: Enter on the pill.
    const show = actions.getByRole("button", { name: "Show links" });
    await show.focus();
    await page.keyboard.press("Enter");
    await expect(linksToggle(page)).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );
    expect(asked).toBe(1);
    // Links is on now: the pill stays, pressed, with the focus still on it.
    await expect(show).toHaveAttribute("aria-pressed", "true");
    await expect(show).toBeFocused();
    await expect(page.getByTestId("side-tab-copilot")).toHaveAttribute("aria-selected", "true");
  });
});

test.describe("Arc pill below 1180px", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("a mouse resting on an arc still shows its pill", async ({ page }) => {
    await gotoStillGlobe(page);
    await linksToggle(page).click();
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );
    const { pill } = await hoverArc(page, MOCK_LINKS_LIFT.find((l) => l.a.iso === "RU")!);
    await expect(pill).toBeVisible();
  });
});

test.describe("Arc pill on a touch screen", () => {
  test.use({ viewport: { width: 1024, height: 768 }, hasTouch: true, isMobile: true });

  test("shows no pill: a touch screen can't hover (as the hover card)", async ({ page }) => {
    await gotoStillGlobe(page);
    await linksToggle(page).click();
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );
    // The inspected link would have its pill at its arc's top: on a touch
    // screen there is none, and no frame loop placing it.
    const irUs = MOCK_LINKS_LIFT.find((l) => l.a.iso === "IR" && l.b.iso === "US")!;
    await clickArc(page, irUs, "United States and Iran");
    await expect(page.getByTestId("link-inspector")).toBeVisible();
    await expect(page.getByTestId("arc-pill")).toHaveCount(0);
  });
});

test.describe("Arc flow on a touch screen", () => {
  test.use({ viewport: { width: 1024, height: 768 }, hasTouch: true, isMobile: true });

  test("is off by default, even at full power and full motion", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("globe").locator("canvas")).toBeVisible({ timeout: 10000 });
    await linksToggle(page).click();
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    await expect(globe).toHaveAttribute("data-arc-flow", "false");
  });
});

test.describe("Links status", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  for (const [what, answer, status] of [
    ["an empty window", { json: [] }, "No links in this window"],
    ["a failed load", { status: 500, json: { detail: "boom" } }, "Links unavailable right now"],
  ] as const) {
    test(`${what} says so beside the rank switch, and to screen readers`, async ({ page }) => {
      await gotoStillGlobe(page, (p) => p.route(isLinksList, (route) => route.fulfill(answer)));
      await linksToggle(page).click();
      await expect(linksToggle(page)).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("links-status")).toHaveText(status);
      await expect(page.getByTestId("hover-announcer")).toContainText(status);
      await expect(page.getByTestId("globe")).toHaveAttribute("data-arcs", "0");

      // Off: the status goes with it.
      await linksToggle(page).click();
      await expect(page.getByTestId("links-status")).toHaveCount(0);
      await expect(page.getByTestId("hover-announcer")).not.toContainText(status);
    });
  }
});

test.describe("Links on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  /** The co-pilot answers with places in France and the US, so it offers Show links. */
  async function showLinks(page: Page, setup?: (page: Page) => Promise<void>) {
    await gotoStillGlobe(page, async (p) => {
      await mockAgentRoute(p, {
        answer: "Markets in Paris and New York reacted to the talks.",
        globe_actions: [
          { type: "flyTo", lat: PARIS.lat, lng: PARIS.lng, label: "Paris" },
          { type: "flyTo", lat: NEW_YORK.lat, lng: NEW_YORK.lng, label: "New York" },
        ],
      });
      await setup?.(p);
    });
    // The layers are hidden on a phone: no switch to turn Links off.
    await expect(page.getByTestId("layer-switcher")).toBeHidden();
    await expect(page.getByTestId("links-chip")).toHaveCount(0);
    await page.getByTestId("side-tab-copilot").tap();
    const input = page.getByTestId("agent-input");
    await input.fill("How did markets react?");
    await input.press("Enter");
    await page.getByRole("button", { name: "Show links" }).tap();
  }

  test("Show links brings a Links ✕ chip; tapping it turns Links off", async ({ page }) => {
    await showLinks(page);
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    const chip = page.getByTestId("links-chip");
    await expect(chip).toBeVisible();
    await expect(chip).toHaveText("Links✕");
    await expect(chip).toHaveAccessibleName("Turn Links off");

    await chip.tap();
    await expect(globe).toHaveAttribute("data-arcs", "0");
    await expect(chip).toHaveCount(0);
    // The chip is gone: focus goes to the timeline's play button, not the page.
    await expect(page.getByRole("button", { name: "Replay the last 7 days" })).toBeFocused();
    // Links is off again, so the co-pilot offers it again.
    await expect(page.getByRole("button", { name: "Show links" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  test("the chip says when the window has no links", async ({ page }) => {
    await showLinks(page, (p) => p.route(isLinksList, (route) => route.fulfill({ json: [] })));
    await expect(page.getByTestId("links-chip")).toHaveText("LinksNo links in this window✕");
    await expect(page.getByTestId("hover-announcer")).toContainText("No links in this window");
  });
});
