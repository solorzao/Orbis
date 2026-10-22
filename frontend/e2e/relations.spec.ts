import { test, expect, type Page, type Request } from "@playwright/test";
import {
  MOCK_LINKS_LIFT,
  MOCK_RELATIONS,
  MOCK_RELATIONS_CONFLICT,
  MOCK_RELATIONS_COOPERATION,
  MOCK_RELATION_DETAIL,
  NEW_YORK,
  PARIS,
  gotoStillGlobe,
  isRelationDetail,
  isRelationsList,
  mockAgentRoute,
  mockRelations,
  seedBoard,
} from "./fixtures";

/** useGlobePoints' FETCH_DEBOUNCE_MS, which useRelations shares. */
const FETCH_DEBOUNCE_MS = 150;

/** Record each /api/relations request, answering as the backend does. */
async function recordRelations(page: Page) {
  const asked: URLSearchParams[] = [];
  await page.route(isRelationsList, (route) => {
    asked.push(new URL(route.request().url()).searchParams);
    return route.fulfill({ json: mockRelations(route.request().url()) });
  });
  return asked;
}

const globe = (page: Page) => page.getByTestId("globe");
const relationsToggle = (page: Page) =>
  page.getByRole("button", { name: "Relations", exact: true });
const ALL = String(MOCK_RELATIONS.relations.length); // 3
const NOTE = "Relations cover the last 7 days: not available for a range or replay";

/** Relations on, from the keyboard, and its arcs drawn: the layer's ready signal. */
async function relationsOn(page: Page) {
  await relationsToggle(page).press("Enter");
  await expect(globe(page)).toHaveAttribute("data-relation-arcs", ALL);
}

test.describe("Relations layer", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("Relations draws the lens, labelled, and turns Links off", async ({ page }) => {
    let asked: URLSearchParams[] = [];
    await gotoStillGlobe(page, async (p) => {
      asked = await recordRelations(p);
    });
    const links = page.getByRole("button", { name: "Links", exact: true });
    await links.press("Enter");
    await expect(globe(page)).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    await relationsOn(page);
    // One arc overlay at a time: Relations on turned Links off.
    await expect(links).toHaveAttribute("aria-pressed", "false");
    await expect(globe(page)).toHaveAttribute("data-arcs", "0");
    await expect(globe(page)).toHaveAttribute("data-relation-labels", ALL);
    // The fixed lens: the class and the cap, and no window at all.
    expect(asked.map((q) => Object.fromEntries(q))).toEqual([{ kind: "all", limit: "40" }]);
    const legend = page.getByTestId("relations-legend");
    await expect(legend).toContainText("Relations · last 7 days");
    await expect(legend).toContainText("Not verified");
    await expect(legend).toContainText("Topic filters don't apply");

    // And Links on turns Relations off.
    await links.press("Enter");
    await expect(relationsToggle(page)).toHaveAttribute("aria-pressed", "false");
    await expect(globe(page)).toHaveAttribute("data-relation-arcs", "0");
  });

  test("the co-pilot's Show links turns Relations off too", async ({ page }) => {
    await gotoStillGlobe(page, (p) =>
      mockAgentRoute(p, {
        answer: "Markets in Paris and New York reacted to the talks.",
        globe_actions: [
          { type: "flyTo", lat: PARIS.lat, lng: PARIS.lng, label: "Paris" },
          { type: "flyTo", lat: NEW_YORK.lat, lng: NEW_YORK.lng, label: "New York" },
        ],
      }),
    );
    await relationsOn(page);
    const input = page.getByTestId("agent-input");
    await input.fill("How did markets react?");
    await input.press("Enter");
    await page
      .getByRole("group", { name: "Suggested actions" })
      .getByRole("button", { name: "Show links" })
      .press("Enter");
    await expect(globe(page)).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    await expect(relationsToggle(page)).toHaveAttribute("aria-pressed", "false");
    await expect(globe(page)).toHaveAttribute("data-relation-arcs", "0");
  });

  test("the class switch refetches; the timeline doesn't", async ({ page }) => {
    let asked: URLSearchParams[] = [];
    await gotoStillGlobe(page, async (p) => {
      asked = await recordRelations(p);
    });
    await relationsOn(page);
    await page
      .getByTestId("relation-kind")
      .getByRole("button", { name: "Conflict" })
      .press("Enter");
    await expect.poll(() => asked.at(-1)?.get("kind")).toBe("conflict");
    await expect(globe(page)).toHaveAttribute(
      "data-relation-arcs",
      String(MOCK_RELATIONS_CONFLICT.relations.length),
    );
    await page
      .getByTestId("relation-kind")
      .getByRole("button", { name: "Cooperation" })
      .press("Enter");
    await expect.poll(() => asked.at(-1)?.get("kind")).toBe("cooperation");
    await expect(globe(page)).toHaveAttribute(
      "data-relation-arcs",
      String(MOCK_RELATIONS_COOPERATION.relations.length),
    );

    // A new live window: the globe refetches its dots, the lens nothing.
    const fetched = asked.length;
    const sixHours = page.waitForRequest(
      (r: Request) =>
        new URL(r.url()).pathname === "/api/news" &&
        new URL(r.url()).searchParams.get("timespan") === "6h",
    );
    await page.getByTestId("timeline").getByRole("button", { name: "6h" }).press("Enter");
    await sixHours;
    await expect(page.getByTestId("timeline-label")).toHaveText("Last 6 h, live");
    // Proving a request isn't made needs a wait: past the hooks' 150 ms fetch
    // debounce (FETCH_DEBOUNCE_MS), which a relations refetch would sit behind too.
    await page.waitForTimeout(3 * FETCH_DEBOUNCE_MS);
    expect(asked).toHaveLength(fetched);
  });

  test("a range makes the lens unavailable, and a live window brings it back", async ({ page }) => {
    await gotoStillGlobe(page);
    await relationsOn(page);
    await page.getByRole("slider", { name: "Window start" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("timeline-label")).not.toHaveText(/live/);
    await expect(relationsToggle(page)).toHaveAttribute("aria-disabled", "true");
    await expect(relationsToggle(page)).toHaveAccessibleDescription(NOTE);
    await expect(globe(page)).toHaveAttribute("data-relation-arcs", "0");

    await page.getByTestId("timeline").getByRole("button", { name: "24h" }).press("Enter");
    await expect(globe(page)).toHaveAttribute("data-relation-arcs", ALL);
  });

  test("a relation is labelled on focus, and opens from the list", async ({ page }) => {
    await gotoStillGlobe(page);
    await relationsOn(page);
    await page.getByTestId("side-tab-inspect").press("Enter");
    const row = page.locator("[data-relation]").first();
    await row.focus();
    await expect(globe(page)).toHaveAttribute("data-relation-highlight", "IR-US");
    await expect(page.getByTestId("arc-pill")).toContainText("reported events");

    await row.press("Enter");
    const inspector = page.getByTestId("relation-inspector");
    await expect(inspector.getByRole("heading", { name: "United States and Iran" })).toBeVisible();
    await expect(inspector).toContainText("Not verified facts");
    await expect(inspector.getByRole("list", { name: "Reported events by class" })).toContainText(
      "Verbal conflict",
    );
    await expect(inspector.locator("[data-day]")).toHaveCount(7);
    // The sample whose URL isn't a web URL is text, never a link.
    await expect(inspector.getByText("Gulf shipping warnings traded")).toBeVisible();
    await expect(
      inspector.getByRole("link", { name: "Gulf shipping warnings traded" }),
    ).toHaveCount(0);
  });

  test("an opened pair's arc and row take its detail's fresher numbers", async ({ page }) => {
    // The list answered before the last cycle (59); the detail is fetched fresh (65).
    const stale = {
      ...MOCK_RELATIONS,
      relations: MOCK_RELATIONS.relations.map((r, i) => (i === 0 ? { ...r, n: 59 } : r)),
    };
    await gotoStillGlobe(page, async (p) => {
      await p.route(isRelationsList, (route) => route.fulfill({ json: stale }));
      await p.route(isRelationDetail, (route) =>
        route.fulfill({ json: { ...MOCK_RELATION_DETAIL, n: 65 } }),
      );
    });
    await relationsOn(page);
    await page.getByTestId("side-tab-inspect").press("Enter");
    const row = page.locator('[data-relation="IR-US"]');
    await expect(row).toHaveAccessibleName(/: 59 reported events/);

    await row.press("Enter");
    const inspector = page.getByTestId("relation-inspector");
    await expect(inspector.getByRole("group", { name: "Events" })).toHaveText(/65/);
    await expect(page.getByTestId("arc-pill")).toContainText("65 reported events");
    await inspector.getByRole("button", { name: "Minimize panel" }).press("Enter");
    await expect(row).toHaveAccessibleName(/: 65 reported events/);
  });

  test("another focus mutes the arcs and their labels", async ({ page }) => {
    await gotoStillGlobe(page, seedBoard);
    await relationsOn(page);
    await expect(globe(page)).toHaveAttribute("data-relation-labels", ALL);
    await page.getByTestId("board-open").press("Enter");
    await expect(globe(page)).toHaveAttribute("data-relation-muted", "true");
    await expect(globe(page)).toHaveAttribute("data-relation-highlight", "");
    // Muted labels aren't rendered at all: the count is what's in the DOM (I6.8).
    await expect(globe(page)).toHaveAttribute("data-relation-labels", "0");
  });
});

test.describe("Relations on a phone (decision 13)", () => {
  // The layers hide at 760px and below, as for Links: turn it on wider first.
  test.use({ viewport: { width: 1180, height: 800 } });

  test("the Relations ✕ chip turns it off at 390 wide", async ({ page }) => {
    await gotoStillGlobe(page);
    await relationsOn(page);
    await page.setViewportSize({ width: 390, height: 844 });
    const chip = page.getByTestId("links-chip");
    await expect(chip).toBeVisible();
    await expect(chip).toHaveAccessibleName("Turn Relations off");
    await chip.press("Enter");
    await expect(globe(page)).toHaveAttribute("data-relation-arcs", "0");
  });
});
