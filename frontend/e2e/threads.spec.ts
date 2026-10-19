import { test, expect, type Page } from "@playwright/test";
import { MOCK_THREADS, gotoStillGlobe, isThreadsList } from "./fixtures";

const rail = (page: Page) => page.getByTestId("threads-rail");
const rows = (page: Page) =>
  page.getByRole("list", { name: "Developing stories" }).getByRole("button");
const threadsToggle = (page: Page) => page.getByRole("button", { name: "Threads", exact: true });

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
      "Red Sea shipping attacks, Developing, 24 stories, 4 regions, 11 outlets",
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

test.describe("Threads on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("a Threads tab in the sheet lists them", async ({ page }) => {
    await gotoStillGlobe(page);
    await expect(rail(page)).toHaveCount(0);
    await page.getByTestId("side-tab-threads").click();
    await expect(page.getByTestId("side-panel")).toHaveAttribute("data-open", "true");
    const sheet = page.getByTestId("threads-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByText(`${MOCK_THREADS.length} active`)).toBeVisible();
    await expect(rows(page)).toHaveCount(MOCK_THREADS.length);
    await expect(rail(page)).toHaveCount(0);
  });
});
