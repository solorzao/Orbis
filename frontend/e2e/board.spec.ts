import { readFile } from "fs/promises";
import { test, expect, type Page } from "@playwright/test";
import {
  BOARD_KEY,
  BOARD_PINS,
  MOCK_LINKS_LIFT,
  MOCK_THREADS,
  gotoStillGlobe,
  isBoard,
  mockAllApiRoutes,
  seedBoard,
} from "./fixtures";
import { decodeShare, encodeShare } from "../src/lib/board";

const SCRATCH = process.env.ORBIS_SCREENSHOTS; // set to save the PR's screenshots

const PLACEHOLDER = "Track a place, person, organisation or thread";
const search = (page: Page) => page.getByRole("combobox", { name: PLACEHOLDER });
const option = (page: Page, name: string) =>
  page.getByRole("listbox", { name: "Track results" }).getByRole("option", { name });
const boardButton = (page: Page) => page.getByTestId("board-open");
const badge = (page: Page) => boardButton(page).locator(".board-n");
const board = (page: Page) => page.getByRole("dialog", { name: "Investigation board" });
const globe = (page: Page) => page.getByTestId("globe");
/** The n-th card (1-based), the focusable part named "{n}. {Kind}…". */
const card = (page: Page, n: number) =>
  board(page).getByRole("group", { name: new RegExp(`^${n}\\. `) });
/** The n-th card's spot on the board, where data-x and data-y say where it is. */
const spot = (page: Page, n: number) =>
  board(page)
    .locator(".pin")
    .nth(n - 1);
const stored = (page: Page) =>
  page.evaluate(
    (key) =>
      (JSON.parse(localStorage.getItem(key) ?? "{}").pins ?? []).map(
        (p: { item: string }) => p.item,
      ),
    BOARD_KEY,
  );

/** Load the app at a share link, with the API mocked and the globe still. */
async function gotoShare(page: Page, ids: string[], setup?: (page: Page) => Promise<void>) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockAllApiRoutes(page);
  await setup?.(page);
  await page.goto(`/?board=${encodeShare(ids)}`);
  await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible({ timeout: 10000 });
}

/** The board open from its top-bar button (the keyboard: no slow clicks on the globe page). */
async function openBoard(page: Page) {
  await boardButton(page).press("Enter");
  await expect(board(page)).toBeVisible();
}

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

test.describe("The investigation board", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("shows its pins as cards with typed edges, mirrored on the globe", async ({ page }) => {
    await gotoStillGlobe(page, seedBoard);
    await expect(badge(page)).toHaveText("5");
    await openBoard(page);
    await expect(board(page).getByRole("button", { name: "Close board" })).toBeFocused();
    await expect(board(page).getByText("5 pins, mirrored on the globe")).toBeVisible();
    await expect(card(page, 1)).toHaveAccessibleName(
      "1. Story, Paris, France: France announces new climate policy",
    );
    // The edges from /api/board/links, each with its label.
    await expect(board(page)).toHaveAttribute("data-edges", "4");
    await expect(board(page).locator(".elabel")).toHaveText([
      "same thread",
      "shared: Emmanuel Macron",
      "covered together: France and United Kingdom",
      "covered together: France and United Kingdom",
    ]);
    await expect(
      board(page).getByRole("list", { name: "Edge types" }).getByRole("listitem"),
    ).toHaveText([
      "Same thread",
      "Shared names",
      "Same place",
      "Covered together",
      "Close in time",
    ]);
    // The globe mirrors it beside the board: three pinned places, one arc between two of them.
    await expect(globe(page)).toHaveAttribute("data-shifted", "true");
    await expect(globe(page)).toHaveAttribute("data-board-places", "3");
    await expect(globe(page)).toHaveAttribute("data-board-arcs", "1");
    await expect(page.getByTestId("side-panel")).toBeHidden();
    if (SCRATCH) await page.screenshot({ path: `${SCRATCH}/p18b-board-1440.png` });

    // Escape closes it, back to its button; the globe comes back.
    await page.keyboard.press("Escape");
    await expect(board(page)).toHaveCount(0);
    await expect(boardButton(page)).toBeFocused();
    await expect(globe(page)).toHaveAttribute("data-board-places", "0");
    await expect(globe(page)).not.toHaveAttribute("data-shifted");
  });

  test("cards move with the arrow keys and the pointer, and keep their places", async ({
    page,
  }) => {
    // Two loads of the globe page.
    test.slow();
    await gotoStillGlobe(page, seedBoard);
    await openBoard(page);
    await expect(spot(page, 1)).toHaveAttribute("data-x", "0.50");
    await card(page, 1).press("ArrowRight");
    await card(page, 1).press("Shift+ArrowDown");
    await expect(spot(page, 1)).toHaveAttribute("data-x", "0.52");
    await expect(spot(page, 1)).toHaveAttribute("data-y", "0.10");
    await expect(page.getByTestId("board-announcer")).toContainText(
      "Pin 1 moved: 52% across, 10% down",
    );
    // One drag with the pointer: the fourth card, from the left edge, to the right.
    const box = (await card(page, 4).boundingBox())!;
    await page.mouse.move(box.x + 30, box.y + 50);
    await page.mouse.down();
    await page.mouse.move(box.x + 230, box.y + 20, { steps: 4 });
    await page.mouse.up();
    await expect(spot(page, 4)).not.toHaveAttribute("data-x", "0.00");
    const x4 = await spot(page, 4).getAttribute("data-x");
    const y4 = await spot(page, 4).getAttribute("data-y");

    await page.reload();
    await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible({ timeout: 10000 });
    await openBoard(page);
    await expect(spot(page, 1)).toHaveAttribute("data-x", "0.52");
    await expect(spot(page, 1)).toHaveAttribute("data-y", "0.10");
    await expect(spot(page, 4)).toHaveAttribute("data-x", x4!);
    await expect(spot(page, 4)).toHaveAttribute("data-y", y4!);
  });

  test("Analyze shows the memo; a citation chip focuses its pin", async ({ page }) => {
    await gotoStillGlobe(page, seedBoard);
    await openBoard(page);
    const asked = page.waitForRequest((r) => isBoard("analyze")(new URL(r.url())));
    await board(page).getByRole("button", { name: "Analyze" }).press("Enter");
    // Each pin goes with its saved title, place and time.
    const body = (await asked).postDataJSON();
    expect(body.items[0]).toMatchObject({
      item: BOARD_PINS.story,
      snapshot: { title: "France announces new climate policy", place: "Paris, France" },
    });
    expect(body.items).toHaveLength(5);
    const memo = board(page).getByRole("region", { name: "Analysis memo" });
    await expect(memo.getByRole("heading")).toHaveText([
      "Possible connections",
      "Contradictions",
      "Open questions",
    ]);
    if (SCRATCH) await page.screenshot({ path: `${SCRATCH}/p18b-memo-1440.png` });
    await memo.getByRole("button", { name: "Pin 4: Emmanuel Macron" }).press("Enter");
    await expect(card(page, 4)).toBeFocused();
    // Every card, the focused one among them, is in full view: on the canvas, none under the memo.
    const seen = await page.evaluate(() => {
      const box = (el: Element) => el.getBoundingClientRect();
      const field = box(document.querySelector('[data-testid="board-field"]')!);
      const memo = box(document.querySelector('[data-testid="board-memo"]')!);
      return Array.from(document.querySelectorAll(".pin-card")).map((el) => {
        const c = box(el);
        const inField =
          c.left >= field.left &&
          c.right <= field.right &&
          c.top >= field.top &&
          c.bottom <= field.bottom;
        const underMemo = !(
          c.right <= memo.left ||
          memo.right <= c.left ||
          c.bottom <= memo.top ||
          memo.bottom <= c.top
        );
        return inField && !underMemo;
      });
    });
    expect(seen).toEqual([true, true, true, true, true]);
  });

  test("Export downloads the board as orbis-board.md", async ({ page }) => {
    await gotoStillGlobe(page, seedBoard);
    await openBoard(page);
    await expect(board(page)).toHaveAttribute("data-edges", "4"); // the edges are in
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      board(page).getByRole("button", { name: "Export" }).press("Enter"),
    ]);
    expect(download.suggestedFilename()).toBe("orbis-board.md");
    const text = await readFile(await download.path(), "utf8");
    expect(text).toContain("# Orbis investigation board");
    expect(text).toContain("1. **Story:** France announces new climate policy");
    expect(text).toContain("   - Link: <https://example.com/france-climate>");
    expect(text).toContain("- 1 and 2: same thread");
  });
});

test.describe("Share links", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("open the board on a fresh profile, the pins resolved; Share link makes one", async ({
    page,
  }) => {
    // The last is a place the server no longer knows: a stand-in from its id.
    const ids = [BOARD_PINS.thread, BOARD_PINS.person, "place:-34:151"];
    await gotoShare(page, ids);
    await expect(board(page)).toBeVisible();
    await expect(card(page, 1)).toHaveAccessibleName("1. Thread, Yemen: Red Sea shipping attacks");
    await expect(card(page, 2)).toHaveAccessibleName("2. Person, Paris, France: Emmanuel Macron");
    await expect(card(page, 3)).toHaveAccessibleName("3. Place: -33.5°, 151.5°");
    await expect(badge(page)).toHaveText("3");
    // The link is read once: a reload doesn't ask again.
    expect(new URL(page.url()).searchParams.has("board")).toBe(false);

    await board(page).getByRole("button", { name: "Share link" }).press("Enter");
    const link = await board(page).getByRole("textbox", { name: "Share link" }).inputValue();
    expect(decodeShare(new URL(link).searchParams.get("board"))).toEqual(ids);
  });

  test("ask before adding to a board that has pins", async ({ page }) => {
    await gotoShare(page, [BOARD_PINS.thread, BOARD_PINS.link], (p) =>
      seedBoard(p, [BOARD_PINS.story]),
    );
    const prompt = page.getByRole("dialog", { name: "Add the shared pins to your board?" });
    await expect(prompt).toHaveAttribute("aria-modal", "true");
    await expect(prompt).toContainText("This link shares 2 pins. 2 aren't on your board yet.");
    await expect(badge(page)).toHaveText("1");
    await expect(prompt.getByRole("button", { name: "Add to my board" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(board(page)).toBeVisible();
    await expect(badge(page)).toHaveText("3");
  });
});

test.describe("The board below 1180px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("is a list in the sheet, each pin with its edges", async ({ page }) => {
    await gotoStillGlobe(page, seedBoard);
    await boardButton(page).press("Enter");
    const list = page.getByTestId("board-list");
    await expect(list).toHaveAttribute("data-edges", "4");
    await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
    const rows = list.getByRole("list", { name: "Pins" }).getByRole("listitem", { name: /^\d\./ });
    await expect(rows).toHaveCount(5);
    await expect(
      rows.first().getByRole("list", { name: "Connections of pin 1" }).getByRole("listitem"),
    ).toHaveText([
      "same thread: 2. Red Sea shipping attacks",
      "shared: Emmanuel Macron: 4. Emmanuel Macron",
      "covered together: France and United Kingdom: 5. France and United Kingdom",
    ]);
    await expect(globe(page)).toHaveAttribute("data-board-places", "3");
    if (SCRATCH) await page.screenshot({ path: `${SCRATCH}/p18b-list-390.png` });
    // A tab picked gives the sheet back to the tabs.
    await page.getByTestId("side-tab-copilot").press("Enter");
    await expect(list).toHaveCount(0);
    await expect(globe(page)).toHaveAttribute("data-board-places", "0");
  });
});
