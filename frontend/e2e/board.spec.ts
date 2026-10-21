import { test, expect, type Page } from "@playwright/test";
import { BOARD_KEY, BOARD_PINS, MOCK_LINKS_LIFT, MOCK_THREADS, gotoStillGlobe } from "./fixtures";

const PLACEHOLDER = "Track a place, person, organisation or thread";
const search = (page: Page) => page.getByRole("combobox", { name: PLACEHOLDER });
const option = (page: Page, name: string) =>
  page.getByRole("listbox", { name: "Track results" }).getByRole("option", { name });
const boardButton = (page: Page) => page.getByTestId("board-open");
const badge = (page: Page) => boardButton(page).locator(".board-n");
const globe = (page: Page) => page.getByTestId("globe");
const stored = (page: Page) =>
  page.evaluate(
    (key) =>
      (JSON.parse(localStorage.getItem(key) ?? "{}").pins ?? []).map(
        (p: { item: string }) => p.item,
      ),
    BOARD_KEY,
  );

test.describe("Pinning to the investigation board", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("a place and its story from the place panel, a person from the dossier; the badge counts", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    await expect(badge(page)).toHaveText("0");
    await page.keyboard.press("/");
    await search(page).fill("lond");
    await expect(option(page, "London, United Kingdom, 3 stories")).toBeVisible();
    await search(page).press("Enter");
    const panel = page.getByTestId("news-panel");
    await expect(panel.getByRole("heading", { name: "London, United Kingdom" })).toBeVisible();
    await panel.getByRole("button", { name: "Pin to board", exact: true }).press("Enter");
    await expect(panel.getByRole("button", { name: "Pinned", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await panel
      .getByRole("button", { name: "Pin to board: France announces new climate policy" })
      .press("Enter");
    await expect(badge(page)).toHaveText("2");

    await page.keyboard.press("/");
    await search(page).fill("macron");
    await expect(option(page, "Emmanuel Macron, 42 stories this week")).toBeVisible();
    await search(page).press("ArrowDown");
    await search(page).press("Enter");
    const dossier = page.getByTestId("entity-dossier");
    await dossier.getByRole("button", { name: "Pin to board" }).press("Enter");
    await expect(badge(page)).toHaveText("3");
    await expect(page.getByTestId("hover-announcer")).toContainText(
      "Pinned to the board: Emmanuel Macron.",
    );
    // Kept in this browser, by the ids the server parses.
    expect(await stored(page)).toEqual(["place:51:-1", BOARD_PINS.story, BOARD_PINS.person]);
  });

  test("a link from its inspector and a thread from its detail", async ({ page }) => {
    await gotoStillGlobe(page);
    await page.getByRole("button", { name: "Links", exact: true }).press("Enter");
    await expect(globe(page)).toHaveAttribute("data-arcs", String(MOCK_LINKS_LIFT.length));
    await page.getByTestId("side-tab-copilot").press("ArrowRight"); // to Inspect
    await page
      .getByRole("list", { name: "Links on the globe" })
      .getByRole("button")
      .first()
      .press("Enter");
    const inspector = page.getByTestId("link-inspector");
    await inspector.getByRole("button", { name: "Pin to board" }).press("Enter");
    await expect(inspector.getByRole("button", { name: "Pinned" })).toBeVisible();

    await page.getByRole("button", { name: "Threads", exact: true }).press("Enter");
    const rail = page.getByTestId("threads-rail");
    await rail
      .getByRole("button", { name: new RegExp(`^${MOCK_THREADS[0].title}`) })
      .press("Enter");
    await rail.getByRole("button", { name: "Pin to board" }).press("Enter");
    await expect(badge(page)).toHaveText("2");
    expect(await stored(page)).toEqual(["link:SA-YE", "thread:7"]);
  });
});
