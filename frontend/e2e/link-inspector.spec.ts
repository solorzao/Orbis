import { test, expect, type Page } from "@playwright/test";
import {
  MOCK_LINKS_COUNT,
  MOCK_LINKS_LIFT,
  MOCK_LINK_DETAIL,
  MOCK_LINK_EXPLAIN,
  PARIS,
  clickArc,
  clickPlace,
  gotoStillGlobe,
  mockLinkDetail,
} from "./fixtures";

const IR_US = MOCK_LINKS_LIFT.find((l) => l.a.iso === "IR" && l.b.iso === "US")!;
const HEADING = "United States and Iran";

/** Load the still globe, turn Links on and wait for its arcs. */
async function withLinks(page: Page, setup?: (page: Page) => Promise<void>) {
  await gotoStillGlobe(page, setup);
  await page.getByRole("button", { name: "Links", exact: true }).click();
  await expect(page.getByTestId("globe")).toHaveAttribute(
    "data-arcs",
    String(MOCK_LINKS_LIFT.length),
  );
}

const readouts = (page: Page) =>
  page
    .getByTestId("link-readouts")
    .getByRole("group")
    .evaluateAll((groups) =>
      groups.map((g) => [g.getAttribute("aria-label"), g.querySelector("b")?.textContent]),
    );

test.describe("Inspect tab: a link", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("clicking an arc opens its link: readouts, shared names, stories, then Explain", async ({
    page,
  }) => {
    const detailAsked: URLSearchParams[] = [];
    const explainAsked: Record<string, unknown>[] = [];
    // Explain answers only when the test has seen it loading.
    let answer!: () => void;
    const held = new Promise<void>((resolve) => (answer = resolve));
    await withLinks(page, async (p) => {
      await p.route("**/api/links/detail*", (route) => {
        detailAsked.push(new URL(route.request().url()).searchParams);
        return route.fulfill({ json: mockLinkDetail(route.request().url()) });
      });
      await p.route("**/api/links/explain", async (route) => {
        explainAsked.push(route.request().postDataJSON());
        await held;
        await route.fulfill({ json: MOCK_LINK_EXPLAIN });
      });
    });

    await clickArc(page, IR_US, HEADING);
    await expect(page.getByTestId("side-tab-inspect")).toHaveAttribute("aria-selected", "true");
    const inspector = page.getByTestId("link-inspector");
    await expect(
      inspector.getByText(
        "Named in the same stories. Covered together does not mean cause and effect.",
      ),
    ).toBeVisible();
    await expect(inspector.getByText("covered together, last 24 h")).toBeVisible();
    // Asked for the window it was opened on, by its timespan.
    await expect
      .poll(() => detailAsked.at(-1) && Object.fromEntries(detailAsked.at(-1)!))
      .toEqual({ a: "IR", b: "US", timespan: "24h" });

    await expect(inspector).not.toHaveAttribute("aria-busy");
    expect(await readouts(page)).toEqual([
      ["Stories", "41"],
      ["Lift", "1.8×"],
      ["Topic", "Politics"],
      ["Tone", "−0.32"],
    ]);
    const shared = inspector.getByRole("group", { name: "Shared in coverage" });
    await expect(shared.locator(".pill")).toHaveText([
      "IAEA9",
      "State Department6",
      "Revolutionary Guard4",
      "nuclear talks",
      "sanctions",
      "diplomacy",
    ]);
    const stories = inspector.getByRole("list", { name: "Linking stories" }).getByRole("listitem");
    await expect(stories).toHaveCount(MOCK_LINK_DETAIL.articles.length);
    await expect(stories.first().getByRole("link")).toHaveAttribute(
      "href",
      MOCK_LINK_DETAIL.articles[0].source_url,
    );
    await expect(inspector.getByText("3 of 41")).toBeVisible();

    // A recent pill for the link, and its arc named at the top while it is inspected.
    const pill = page.getByRole("group", { name: "Recent places and links" }).getByRole("button", {
      name: "US ↔ IR: United States and Iran, 41 stories",
    });
    await expect(pill).toHaveAttribute("aria-pressed", "true");
    await expect(pill).toHaveText("US ↔ IR41");
    await page.mouse.move(40, 450); // off the arc: the pill stays for the inspected link
    await expect(page.locator('[data-testid="arc-pill"][data-placed="true"]')).toHaveText(
      "41 stories link United States and Iran, mostly politics",
    );

    // Explain, from the keyboard: the button waits (keeping the focus), then
    // Claude's words come with the AI badge, and the focus with them.
    await inspector.getByRole("button", { name: "AI Explain this link" }).focus();
    await page.keyboard.press("Enter");
    const waiting = inspector.getByRole("button", { name: "AI Explaining…" });
    await expect(waiting).toHaveAttribute("aria-disabled", "true");
    await expect(waiting).toBeFocused();
    answer();
    const explanation = inspector.getByText(MOCK_LINK_EXPLAIN.text);
    await expect(explanation).toBeVisible();
    await expect(explanation.locator(".ai")).toHaveText("AI");
    await expect(inspector.getByTestId("link-explanation")).toBeFocused();
    await expect(inspector.getByRole("button", { name: /Explain/ })).toHaveCount(0);
    // It explains the window the link was opened on: that day's bounds, frozen.
    const body = explainAsked[0];
    expect(Object.keys(body).sort()).toEqual(["a", "b", "end_time", "start_time"]);
    expect(body).toMatchObject({ a: "IR", b: "US" });
    expect(Date.parse(body.end_time as string) - Date.parse(body.start_time as string)).toBe(
      24 * 3_600_000,
    );

    // Closing the link drops its pill and its arc's highlight pill.
    await page.getByRole("button", { name: "Close United States and Iran" }).click();
    await expect(inspector).toHaveCount(0);
    await expect(page.getByTestId("arc-pill")).toHaveCount(0);
    // Nothing open: with Links on, the tab lists the links drawn.
    await expect(page.getByRole("list", { name: "Links on the globe" })).toBeVisible();
  });

  test("a paused explanation shows as plain text, and can be asked again", async ({ page }) => {
    const paused = "AI summaries are paused until 00:00 UTC (daily limit reached).";
    await withLinks(page, (p) =>
      p.route("**/api/links/explain", (route) => route.fulfill({ json: { text: paused } })),
    );
    await clickArc(page, IR_US, HEADING);
    const inspector = page.getByTestId("link-inspector");
    await inspector.getByRole("button", { name: "AI Explain this link" }).click();
    const message = inspector.getByText(paused);
    await expect(message).toBeVisible();
    await expect(message.locator(".ai")).toHaveCount(0);
    await expect(inspector.getByRole("button", { name: "AI Explain this link" })).toBeEnabled();
  });

  test("links and places share the recent pills; each keeps its own view", async ({ page }) => {
    await withLinks(page);
    await clickArc(page, IR_US, HEADING);
    const inspector = page.getByTestId("link-inspector");
    await inspector.getByRole("button", { name: "AI Explain this link" }).click();
    await expect(inspector.getByText(MOCK_LINK_EXPLAIN.text)).toBeVisible();

    await clickPlace(page, PARIS);
    const recent = page.getByRole("group", { name: "Recent places and links" });
    await expect(recent.locator("[data-place]")).toHaveText(["US ↔ IR41", "Paris3"]);
    await expect(inspector).toHaveCount(0);

    // Back to the link: its explanation is still there.
    await recent
      .getByRole("button", { name: "US ↔ IR: United States and Iran, 41 stories" })
      .click();
    await expect(inspector.getByText(MOCK_LINK_EXPLAIN.text)).toBeVisible();

    // Minimize keeps it among the pills, with focus on its pill.
    await inspector.getByRole("button", { name: "Minimize panel" }).click();
    await expect(inspector).toHaveCount(0);
    await expect(
      recent.getByRole("button", { name: "US ↔ IR: United States and Iran, 41 stories" }),
    ).toBeFocused();
  });

  test("from the keyboard alone: Links on, Tab to the Inspect list, Enter opens a link", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    const toggle = page.getByRole("button", { name: "Links", exact: true });
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );

    // The Inspect tab, by the tabs' arrow keys.
    await page.getByTestId("side-tab-copilot").focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("side-tab-inspect")).toHaveAttribute("aria-selected", "true");

    // The links drawn, in rank order (most surprising first): Saudi Arabia and Yemen.
    const list = page.getByRole("list", { name: "Links on the globe" });
    const rows = list.getByRole("button");
    await expect(rows).toHaveCount(MOCK_LINKS_LIFT.length);
    const first = rows.first();
    for (let i = 0; i < 8; i++) {
      if (await first.evaluate((el) => el === document.activeElement)) break;
      await page.keyboard.press("Tab");
    }
    await expect(first).toBeFocused();
    await expect(first).toHaveAccessibleName("Saudi Arabia and Yemen, SA ↔ YE, 46 stories");
    await page.keyboard.press("Enter");
    const heading = page
      .getByTestId("link-inspector")
      .getByRole("heading", { name: "Saudi Arabia and Yemen" });
    await expect(heading).toBeVisible();
    // The row went with the list: the focus is on the inspector's heading, not the page.
    await expect(heading).toBeFocused();
  });

  test("a focused row that drops out of the list hands the focus to the first row", async ({
    page,
  }) => {
    await gotoStillGlobe(page);
    await page.getByRole("button", { name: "Links", exact: true }).click();
    await expect(page.getByTestId("globe")).toHaveAttribute(
      "data-arcs",
      String(MOCK_LINKS_LIFT.length),
    );
    await page.getByTestId("side-tab-inspect").click();
    const rows = page.getByRole("list", { name: "Links on the globe" }).getByRole("button");
    // France and the UK are linked by lift only: a count ranking drops them.
    const frGb = rows.filter({ hasText: "United Kingdom and France" });
    await frGb.focus();
    // The rank changes without the focus moving (as a replay changes the window).
    await page
      .getByTestId("link-rank")
      .getByRole("button", { name: "Most covered" })
      .evaluate((b: HTMLElement) => b.click());
    await expect(rows).toHaveCount(MOCK_LINKS_COUNT.length);
    await expect(rows.first()).toBeFocused();
  });
});

test.describe("Inspect tab: links on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the list gives a phone something to tap: a link opens in the sheet", async ({ page }) => {
    // Links on where the layers show, then a phone's width.
    await page.setViewportSize({ width: 800, height: 844 });
    await gotoStillGlobe(page);
    await page.getByRole("button", { name: "Links", exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("links-chip")).toBeVisible();

    await page.getByTestId("side-tab-inspect").tap();
    await page
      .getByRole("list", { name: "Links on the globe" })
      .getByRole("button", { name: /^United States and Iran/ })
      .tap();
    await expect(
      page.getByTestId("link-inspector").getByRole("heading", { name: HEADING }),
    ).toBeVisible();
  });
});
