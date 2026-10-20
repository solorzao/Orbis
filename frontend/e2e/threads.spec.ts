import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_THREADS,
  PARIS,
  RED_SEA_SPREAD,
  clickPlace,
  gotoStillGlobe,
  isThreadsList,
  mockAllApiRoutes,
  withThreads,
} from "./fixtures";

const rail = (page: Page) => page.getByTestId("threads-rail");
const rows = (page: Page) =>
  page.getByRole("list", { name: "Developing stories" }).getByRole("button");
const threadsToggle = (page: Page) => page.getByRole("button", { name: "Threads", exact: true });
const globe = (page: Page) => page.getByTestId("globe");
const route = (page: Page) => page.getByRole("list", { name: "Spread, in order of first report" });
const stops = (page: Page) => route(page).locator(".stop-place");
const lit = (page: Page) => route(page).locator(".stop.on .stop-place");
const play = (page: Page) => page.getByTestId("timeline").locator("button.play");

const RED_SEA = "Red Sea shipping attacks";
/** Its arcs: from the first place to each later one. */
const SPREAD_ARCS = String(RED_SEA_SPREAD.length - 1);

/** Threads on and the Red Sea thread open, its arcs drawn: the ready signal. */
async function openRedSea(page: Page) {
  // From the keyboard: a press needs no frames to settle, a click does, and each
  // frame of the software-rendered globe is slow on CI's runners.
  await threadsToggle(page).press("Enter");
  await rows(page).first().press("Enter");
  await expect(rows(page).first()).toHaveAttribute("aria-expanded", "true");
  await expect(globe(page)).toHaveAttribute("data-thread-arcs", SPREAD_ARCS);
}

test.describe("Threads rail", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("the Threads toggle shows the rail with the window's developing stories", async ({
    page,
  }) => {
    const asked: string[] = [];
    await gotoStillGlobe(page, (p) =>
      p.route(isThreadsList, (route) => {
        asked.push(new URL(route.request().url()).search);
        return route.fulfill({ json: MOCK_THREADS });
      }),
    );
    await expect(rail(page)).toHaveCount(0);
    expect(asked).toEqual([]); // nothing fetched while it is off

    await threadsToggle(page).click();
    await expect(threadsToggle(page)).toHaveAttribute("aria-pressed", "true");
    await expect(rail(page)).toBeVisible();
    await expect(rail(page).getByRole("heading", { name: "Threads" })).toBeVisible();
    await expect(rail(page).getByText(`${MOCK_THREADS.length} active`)).toBeVisible();
    await expect(rows(page)).toHaveCount(MOCK_THREADS.length);
    await expect(rows(page).first()).toHaveAccessibleName(
      "Red Sea shipping attacks, Developing, 24 stories, 4 countries, 11 outlets",
    );
    await expect(rows(page).nth(1).locator(".th-status")).toHaveText("Emerging");
    expect(asked).toEqual(["?timespan=24h&limit=20"]);

    // A topic narrows them on the server.
    await page.getByTestId("topic-filter").getByRole("button", { name: "Conflict" }).click();
    await expect.poll(() => asked.at(-1)).toBe("?timespan=24h&topic=Conflict&limit=20");

    await threadsToggle(page).click();
    await expect(rail(page)).toHaveCount(0);
  });

  test("says when a window has no developing stories", async ({ page }) => {
    await gotoStillGlobe(page, (p) =>
      p.route(isThreadsList, (route) => route.fulfill({ json: [] })),
    );
    await threadsToggle(page).click();
    await expect(rail(page).getByText("No developing stories in this window")).toBeVisible();
    await expect(rows(page)).toHaveCount(0);
  });

  test("the rows are a list of buttons, reached with the keyboard", async ({ page }) => {
    await gotoStillGlobe(page);
    await threadsToggle(page).click();
    await expect(rows(page)).toHaveCount(MOCK_THREADS.length);
    await rows(page).first().focus();
    await page.keyboard.press("Tab");
    await expect(rows(page).nth(1)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(rows(page).nth(1)).toHaveAttribute("aria-expanded", "true");
  });
});

test.describe("A thread's detail, arcs and replay", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("selecting a thread opens it inline and draws its spread as arcs", async ({ page }) => {
    await gotoStillGlobe(page);
    await openRedSea(page);
    const detail = rail(page).locator(".tdetail");
    await expect(detail.getByText(/Outlets in Yemen first reported/)).toBeVisible();
    await expect(stops(page)).toHaveText(RED_SEA_SPREAD.map((p) => p.place));
    await expect(lit(page)).toHaveCount(RED_SEA_SPREAD.length); // all, when not replaying
    const facts = detail.getByRole("list", { name: "Facts" });
    await expect(facts).toContainText("Outlets11");
    await expect(facts).toContainText("Countries4");
    // Key entities, inert until the tracker (PR 17b): labels, not buttons.
    const entities = detail.getByRole("list", { name: "Key entities" });
    await expect(entities.getByRole("listitem")).toHaveText([
      "Suez Canal Authority",
      "Houthis",
      "Maersk",
    ]);
    await expect(entities.getByRole("button")).toHaveCount(0);
    await expect(play(page)).toHaveAccessibleName(`Replay how ${RED_SEA} spread`);

    // The selected one again closes it, and its arcs go.
    await rows(page).first().click();
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "0");
    await expect(play(page)).toHaveAccessibleName("Replay the last 7 days");
  });

  test("a thread without its synopsis yet shows the lead headline", async ({ page }) => {
    await gotoStillGlobe(page);
    await threadsToggle(page).click();
    await rows(page).nth(1).click(); // the typhoon: no synopsis yet
    await expect(rail(page).getByText("Synopsis pending; showing the lead headline")).toBeVisible();
  });

  test("replay lights the places in order of first report, revealing their arcs one by one", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    await page.emulateMedia({ reducedMotion: "no-preference" }); // steps, not all at once
    await openRedSea(page);
    await expect(globe(page)).toHaveAttribute("data-thread-replay", "");

    await play(page).click();
    // What the globe drew at each step, "places lit:arcs drawn", ends with every place.
    await expect(globe(page)).toHaveAttribute("data-thread-replay", /(^|,)4:3$/);
    // On a slow runner two steps can land in one render: each drawn step lights more
    // places than the last, with an arc to each but the first.
    const steps = (await globe(page).getAttribute("data-thread-replay"))!
      .split(",")
      .map((step) => step.split(":").map(Number));
    expect(steps[0][0]).toBeGreaterThanOrEqual(1);
    for (const [i, [places, arcs]] of steps.entries()) {
      expect(arcs, `step ${i}: an arc to each lit place but the first`).toBe(places - 1);
      if (i > 0) expect(places, `step ${i}: more places lit`).toBeGreaterThan(steps[i - 1][0]);
    }
    // Then every place and arc again, and the button to replay it.
    await expect(play(page)).toHaveAccessibleName(`Replay how ${RED_SEA} spread`);
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", SPREAD_ARCS);
    await expect(lit(page)).toHaveCount(RED_SEA_SPREAD.length);
  });

  test("with reduced motion the replay lights every place at once", async ({ page }) => {
    await gotoStillGlobe(page);
    await openRedSea(page);
    await play(page).click();
    // One step: every place lit and every arc drawn at once.
    await expect(globe(page)).toHaveAttribute("data-thread-replay", "4:3");
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", SPREAD_ARCS);
    await expect(play(page)).toHaveAccessibleName(`Replay how ${RED_SEA} spread`);
  });

  test("the spread's dashes flow with full motion and power, and pause in place on a drag", async ({
    page,
  }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
    await mockAllApiRoutes(page);
    await page.goto("/");
    await expect(globe(page).locator("canvas")).toBeVisible({ timeout: 10000 });
    await openRedSea(page);
    await expect(globe(page)).toHaveAttribute("data-arc-flow", "true");
    await expect(globe(page)).toHaveAttribute("data-arc-dashed", "true");
    // How many times the arcs were drawn: a pause redraws none.
    const drawn = await globe(page).getAttribute("data-arcs-drawn");

    await page.mouse.move(700, 450);
    await page.mouse.down();
    await page.mouse.move(740, 470, { steps: 4 });
    await expect(globe(page)).toHaveAttribute("data-arc-flow", "false");
    await expect(globe(page)).toHaveAttribute("data-arc-dashed", "true");
    await expect(globe(page)).toHaveAttribute("data-arcs-drawn", drawn!);
    await page.mouse.up();
    await expect(globe(page)).toHaveAttribute("data-arc-flow", "true");
    await expect(globe(page)).toHaveAttribute("data-arcs-drawn", drawn!);
  });

  test("with reduced motion the spread's arcs hold still", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("orbis-low-power", "0"));
    await gotoStillGlobe(page);
    await openRedSea(page);
    await expect(globe(page)).toHaveAttribute("data-arc-flow", "false");
    await expect(globe(page)).toHaveAttribute("data-arc-dashed", "false");
  });

  /**
   * Links on, and the US-Iran link opened from the Inspect tab's list, from the
   * keyboard (see openRedSea), ready once its arc is drawn highlighted.
   */
  async function inspectUsIran(page: Page) {
    await page.getByRole("button", { name: "Links", exact: true }).press("Enter");
    await page.getByTestId("side-tab-inspect").press("Enter");
    await page
      .getByRole("list", { name: "Links on the globe" })
      .getByRole("button", { name: /^United States and Iran/ })
      .press("Enter");
    await expect(globe(page)).toHaveAttribute("data-arc-highlight", "IR-US");
  }

  // Links, the link inspector and a thread together: each step waits on a frame of
  // the software-rendered globe, about 2 s a step on CI's runners (two tries ran
  // out of 30 s), so these two get the slow budget.
  test("selecting a thread draws its arcs instead of an inspected link's highlight", async ({
    page,
  }) => {
    test.slow();
    await gotoStillGlobe(page);
    await inspectUsIran(page);

    await threadsToggle(page).press("Enter");
    await rows(page).first().press("Enter");
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", SPREAD_ARCS);
    await expect(globe(page)).toHaveAttribute("data-arc-highlight", "");
    // Closed, the thread gives the inspected link its highlight back.
    await rows(page).first().press("Enter");
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "0");
    await expect(globe(page)).toHaveAttribute("data-arc-highlight", "IR-US");
  });

  test("opening a link closes the selected thread", async ({ page }) => {
    test.slow();
    await gotoStillGlobe(page);
    await openRedSea(page);
    await inspectUsIran(page);
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "0");
    await expect(rows(page).first()).toHaveAttribute("aria-expanded", "false");
  });

  test("the highlight signal is the arc drawn, not the link inspected", async ({ page }) => {
    await gotoStillGlobe(page);
    await inspectUsIran(page);
    // Links off: the inspector stays open, but no arc is drawn to highlight.
    await page.getByRole("button", { name: "Links", exact: true }).press("Enter");
    await expect(globe(page)).toHaveAttribute("data-arcs", "0");
    await expect(globe(page)).toHaveAttribute("data-arc-highlight", "");
    await expect(page.getByTestId("link-inspector")).toBeVisible();
  });

  test("a range closes the selected thread: threads follow the live windows", async ({ page }) => {
    await gotoStillGlobe(page);
    await openRedSea(page);
    await page.getByRole("slider", { name: "Window start" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("timeline-label")).not.toHaveText(/live/);
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "0");
    await expect(
      rail(page).getByText("Threads follow the live windows: pick 1h, 6h, 24h or 7d"),
    ).toBeVisible();
    await expect(play(page)).toHaveAccessibleName("Replay the last 7 days");
  });

  test("all its stories open in Inspect, 20 at a time", async ({ page }) => {
    await gotoStillGlobe(page);
    await openRedSea(page);
    await rail(page).getByRole("button", { name: "All 24 stories" }).click();
    await expect(page.getByTestId("side-tab-inspect")).toHaveAttribute("aria-selected", "true");
    const panel = page.getByTestId("thread-stories");
    await expect(panel.getByRole("heading", { name: RED_SEA })).toBeVisible();
    await expect(panel.getByRole("article")).toHaveCount(20);
    await panel.getByRole("button", { name: "Load more" }).click();
    await expect(panel.getByRole("article")).toHaveCount(24);
    await expect(panel.getByRole("button", { name: "Load more" })).toHaveCount(0);
    await panel.getByRole("button", { name: "Close panel" }).click();
    await expect(panel).toHaveCount(0);
  });
});

test.describe("The Part of chip", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("a place's story chips its thread; the chip selects it and draws its arcs", async ({
    page,
  }) => {
    await gotoStillGlobe(page, withThreads);
    await clickPlace(page, PARIS);
    const chip = page.getByTestId("news-panel").getByRole("button", {
      name: "Part of: EU summit on energy prices (also in Brussels, Belgium and Berlin, Germany)",
    });
    await expect(chip).toBeVisible();
    await expect(threadsToggle(page)).toHaveAttribute("aria-pressed", "false");

    await chip.click();
    await expect(threadsToggle(page)).toHaveAttribute("aria-pressed", "true");
    const row = rows(page).filter({ hasText: "EU summit on energy prices" });
    await expect(row).toHaveAttribute("aria-expanded", "true");
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "2");
  });
});

test.describe("The Part of chip and the time window", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  const chip = (page: Page) =>
    page
      .getByTestId("news-panel")
      .getByRole("button", { name: /^Part of: EU summit on energy prices/ });

  test("a thread chosen during a day replay stops it, back on the live window", async ({
    page,
  }) => {
    await gotoStillGlobe(page, withThreads);
    await clickPlace(page, PARIS);
    await play(page).click();
    await expect(page.getByTestId("timeline-label")).toHaveText(/^Replay/);

    await chip(page).click();
    await expect(page.getByTestId("timeline-label")).toHaveText("Last 24 h, live");
    await expect(play(page)).toHaveAccessibleName("Replay how EU summit on energy prices spread");
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "2");
  });

  test("a thread chosen under a chosen range stays chosen", async ({ page }) => {
    await gotoStillGlobe(page, withThreads);
    await clickPlace(page, PARIS);
    await page.getByRole("slider", { name: "Window start" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("timeline-label")).not.toHaveText(/live/);

    await chip(page).click();
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "2");
    await expect(rows(page).filter({ hasText: "EU summit on energy prices" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});

test.describe("The Part of chip below 1180px", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("the chip opens the sheet's Threads tab on its thread", async ({ page }) => {
    await gotoStillGlobe(page, withThreads);
    await clickPlace(page, PARIS);
    await page
      .getByTestId("news-panel")
      .getByRole("button", { name: /^Part of: EU summit on energy prices/ })
      .click();
    await expect(page.getByTestId("side-tab-threads")).toHaveAttribute("aria-selected", "true");
    const row = page
      .getByTestId("threads-sheet")
      .getByRole("button", { name: /^EU summit on energy prices/ });
    await expect(row).toHaveAttribute("aria-expanded", "true");
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", "2");
  });
});

test.describe("Threads on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("a Threads tab in the sheet lists them, and opens one there", async ({ page }) => {
    await gotoStillGlobe(page);
    await expect(rail(page)).toHaveCount(0);
    await page.getByTestId("side-tab-threads").click();
    await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
    const sheet = page.getByTestId("threads-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByText(`${MOCK_THREADS.length} active`)).toBeVisible();
    await expect(rows(page)).toHaveCount(MOCK_THREADS.length);
    await expect(rail(page)).toHaveCount(0);

    // A row opens its thread there, and draws its spread.
    await rows(page).first().click();
    await expect(sheet.locator(".tdetail")).toBeVisible();
    await expect(globe(page)).toHaveAttribute("data-thread-arcs", SPREAD_ARCS);

    // Its stories open in Inspect, the focus going with them (the Threads tab hides).
    await sheet.getByRole("button", { name: "All 24 stories" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("thread-stories")).toBeVisible();
    await expect(page.getByRole("tabpanel", { name: "Inspect" })).toBeFocused();
  });
});
