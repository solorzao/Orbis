import { test, expect, type Page, type Request } from "@playwright/test";
import {
  MOCK_RELATIONS,
  MOCK_RELATIONS_CONFLICT,
  gotoStillGlobe,
  isRelationsList,
  mockRelations,
  seedBoard,
} from "./fixtures";

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
    await relationsOn(page);
    await expect(globe(page)).toHaveAttribute("data-relation-labels", ALL);
    // The fixed lens: the class and the cap, and no window at all.
    expect(asked.map((q) => Object.fromEntries(q))).toEqual([{ kind: "all", limit: "40" }]);
    const legend = page.getByTestId("relations-legend");
    await expect(legend).toContainText("Relations · last 7 days");
    await expect(legend).toContainText("Not verified");
    await expect(legend).toContainText("Topic filters don't apply");

    await page.getByRole("button", { name: "Links", exact: true }).press("Enter");
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
