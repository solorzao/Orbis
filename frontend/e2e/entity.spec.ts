import { test, expect, type Page } from "@playwright/test";
import { MOCK_DOSSIERS, PARIS, gotoStillGlobe, hoverPlace, mockAllApiRoutes } from "./fixtures";

const SCRATCH = process.env.ORBIS_SCREENSHOTS; // set to save the PR's screenshots

const PLACEHOLDER = "Track a place, person, organisation or thread";
const search = (page: Page) => page.getByRole("combobox", { name: PLACEHOLDER });
const results = (page: Page) => page.getByRole("listbox", { name: "Track results" });
const globe = (page: Page) => page.getByTestId("globe");
const dossier = (page: Page) => page.getByTestId("entity-dossier");
const heading = (page: Page, name: string) =>
  dossier(page).getByRole("heading", { name, exact: true });

const MACRON = MOCK_DOSSIERS["person:emmanuel macron"];

/** "/" into the Track search, then type: the results' ready signal is the option asked for. */
async function find(page: Page, q: string, option: string) {
  await page.keyboard.press("/");
  await expect(search(page)).toBeFocused();
  await search(page).fill(q);
  await expect(results(page).getByRole("option", { name: option })).toBeVisible();
}

/** Track Emmanuel Macron from the search: his dossier and the globe's focus on him. */
async function trackMacron(page: Page) {
  await find(page, "macron", "Emmanuel Macron, 42 stories this week");
  await search(page).press("ArrowDown");
  await search(page).press("Enter");
  await expect(heading(page, "Emmanuel Macron")).toBeVisible();
  await expect(globe(page)).toHaveAttribute("data-focus-entity", "Emmanuel Macron");
}

test.describe("Track search and the entity dossier", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("/ focuses the search; typing shows the results grouped, counted for screen readers", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    await expect(search(page)).toHaveAttribute("aria-expanded", "false");
    await find(page, "par", "Paris, France, 5 stories");
    await expect(search(page)).toHaveAttribute("aria-expanded", "true");
    const groups = results(page).getByRole("group");
    await expect(groups).toHaveCount(3);
    await expect(groups.nth(0)).toHaveAccessibleName("Places");
    await expect(groups.nth(1)).toHaveAccessibleName("People");
    await expect(groups.nth(2)).toHaveAccessibleName("Organisations");
    await expect(groups.nth(1).getByRole("option")).toHaveAccessibleName(
      "Eun-ji Park, 3 stories this week",
    );
    await expect(page.getByTestId("hover-announcer")).toContainText(
      "1 place, 1 person and 1 organisation",
    );
    // A capped count is a floor; a thread is found by its title.
    await search(page).fill("eu");
    await expect(results(page).getByRole("option", { name: /European Union/ })).toContainText(
      "100+",
    );
    await expect(
      results(page).getByRole("group", { name: "Threads" }).getByRole("option"),
    ).toHaveAccessibleName("EU summit on energy prices");
    if (SCRATCH) await page.screenshot({ path: `${SCRATCH}/p17b-search-1440.png` });

    // Escape closes the list, then clears the box.
    await search(page).press("Escape");
    await expect(search(page)).toHaveAttribute("aria-expanded", "false");
    await search(page).press("Escape");
    await expect(search(page)).toHaveValue("");
  });

  test("Enter on a person opens the dossier and focus mode: dimmed dots, arcs, pulses", async ({
    page,
  }) => {
    // Full power and motion, so the places pulse once (CI reports 4 cores: low power).
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible({ timeout: 10000 });

    await trackMacron(page);
    await expect(dossier(page).getByText("Tracking an entity")).toBeVisible();
    await expect(
      dossier(page).getByText("Person. Appears in coverage in 3 countries."),
    ).toBeVisible();
    await expect(dossier(page).getByRole("group", { name: "7 days" })).toHaveText(/140/);
    // Paris has a dot; Brussels and Berlin get stand-ins. Arcs run from his centre to each.
    await expect(globe(page)).toHaveAttribute("data-dots", "5");
    await expect(globe(page)).toHaveAttribute("data-focus-places", String(MACRON.places.length));
    await expect(globe(page)).toHaveAttribute("data-focus-arcs", String(MACRON.places.length));
    await expect(globe(page)).toHaveAttribute("data-focus-pulses", String(MACRON.places.length));
    await expect(page.getByTestId("hover-announcer")).toContainText("Tracking Emmanuel Macron");
    // Its pill among the recent places.
    await expect(
      page.getByRole("button", { name: "Tracking Emmanuel Macron", pressed: true }),
    ).toBeVisible();
  });

  test("a constellation pivot tracks the name, and Stop tracking ends focus mode", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    await trackMacron(page);
    if (SCRATCH) {
      await expect(globe(page)).toHaveAttribute("data-focus-arcs", String(MACRON.places.length));
      await page.screenshot({ path: `${SCRATCH}/p17b-dossier-1440.png` });
    }
    const graph = dossier(page).getByRole("group", { name: "Appears in the same coverage as" });
    // A name the graph can't type is drawn, not trackable.
    await expect(graph.getByRole("button", { name: /Paris/ })).toHaveCount(0);
    await graph.getByRole("button", { name: "Track European Union" }).press("Enter");
    // The new dossier starts on its heading: the node pressed went with the old one.
    await expect(heading(page, "European Union")).toBeFocused();
    await expect(globe(page)).toHaveAttribute("data-focus-entity", "European Union");
    // Capped, and tracked for under a week.
    await expect(dossier(page).getByText("Based on the latest 2,000 mentions.")).toBeVisible();
    await expect(dossier(page).getByRole("group", { name: /^Since / })).toHaveText(/2,140/);

    await dossier(page).getByRole("button", { name: "Stop tracking" }).press("Enter");
    await expect(dossier(page)).toHaveCount(0);
    await expect(globe(page)).not.toHaveAttribute("data-focus-entity");
    await expect(globe(page)).toHaveAttribute("data-focus-arcs", "0");
    await expect(globe(page)).toHaveAttribute("data-dots", "3");
    // Focus stays in the Inspect tab, not lost to the page.
    await expect(page.getByRole("tabpanel", { name: "Inspect" })).toBeFocused();
  });

  test("Escape in the dossier stops tracking", async ({ page }) => {
    await gotoStillGlobe(page);
    await trackMacron(page);
    await dossier(page).getByRole("button", { name: "Stop tracking" }).focus();
    await page.keyboard.press("Escape");
    await expect(globe(page)).not.toHaveAttribute("data-focus-entity");
  });

  test("a hover card's name starts tracking", async ({ page }) => {
    await gotoStillGlobe(page);
    const card = await hoverPlace(page, PARIS);
    await card.getByRole("button", { name: "Track Emmanuel Macron" }).click();
    await expect(heading(page, "Emmanuel Macron")).toBeVisible();
    await expect(globe(page)).toHaveAttribute("data-focus-entity", "Emmanuel Macron");
  });

  test("a place result flies there and opens it", async ({ page }) => {
    await gotoStillGlobe(page);
    await find(page, "lond", "London, United Kingdom, 3 stories");
    await search(page).press("Enter");
    await expect(
      page
        .getByTestId("news-panel")
        .getByRole("heading", { name: "London, United Kingdom", exact: true }),
    ).toBeVisible();
    await expect(search(page)).toHaveValue("");
  });

  test("an unknown name says so, and can still be stopped", async ({ page }) => {
    await gotoStillGlobe(page, (p) =>
      p.route(
        (url) => url.pathname === "/api/search",
        (route) =>
          route.fulfill({
            json: {
              people: [{ type: "person", name: "Gone Name", n: 1, capped: false }],
              orgs: [],
              threads: [],
            },
          }),
      ),
    );
    await find(page, "gone", "Gone Name, 1 story this week");
    await search(page).press("Enter");
    await expect(
      dossier(page).getByText("No person or organisation of that name is in this week's coverage."),
    ).toBeVisible();
    await expect(globe(page)).not.toHaveAttribute("data-focus-entity");
  });
});

test.describe("Track search in the sheet", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the top bar's search button opens it in the sheet; a person opens the dossier", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    const button = page.getByRole("button", { name: "Track search" });
    await button.press("Enter");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
    const box = page.getByTestId("track-search-sheet").getByRole("combobox", { name: PLACEHOLDER });
    await expect(box).toBeFocused();
    await box.fill("macron");
    await expect(
      page.getByRole("option", { name: "Emmanuel Macron, 42 stories this week" }),
    ).toBeVisible();
    if (SCRATCH) await page.screenshot({ path: `${SCRATCH}/p17b-sheet-390.png` });
    await box.press("ArrowDown");
    await box.press("Enter");
    // The search closes, and the sheet's Inspect tab shows the dossier, focused.
    await expect(page.getByTestId("track-search-sheet")).toHaveCount(0);
    await expect(page.getByTestId("side-tab-inspect")).toHaveAttribute("aria-selected", "true");
    await expect(heading(page, "Emmanuel Macron")).toBeFocused();
    await expect(globe(page)).toHaveAttribute("data-focus-entity", "Emmanuel Macron");
  });

  test("Escape on the empty box closes it, back to the button", async ({ page }) => {
    await gotoStillGlobe(page);
    const button = page.getByRole("button", { name: "Track search" });
    await button.press("Enter");
    const box = page.getByTestId("track-search-sheet").getByRole("combobox", { name: PLACEHOLDER });
    await expect(box).toBeFocused();
    await box.press("Escape");
    await expect(page.getByTestId("track-search-sheet")).toHaveCount(0);
    await expect(button).toBeFocused();
  });
});
