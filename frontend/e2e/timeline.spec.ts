import { test, expect, type Page, type Request } from "@playwright/test";
import { gotoStillGlobe } from "./fixtures";

/** A request for the globe's dots (/api/news, not /api/news/...). */
function isGlobeFetch(req: Request) {
  return new URL(req.url()).pathname === "/api/news";
}

function params(req: Request) {
  return new URL(req.url()).searchParams;
}

async function gotoTimeline(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await gotoStillGlobe(page);
  const timeline = page.getByTestId("timeline");
  await expect(timeline).toBeVisible();
  // The chart is drawn once the volume is in: eight day labels, the last "Today".
  await expect(timeline.locator("svg text").last()).toHaveText("Today");
  return timeline;
}

test.describe("Timeline capsule", () => {
  test("shows the 7-day volume, the live window and the story count", async ({ page }) => {
    const timeline = await gotoTimeline(page);
    // A day label for each UTC day the chart shows six hours or more of, Today always.
    const labels = await timeline.locator("svg text").allTextContents();
    expect(labels.length).toBeGreaterThanOrEqual(7);
    expect(labels.length).toBeLessThanOrEqual(8);
    expect(labels.at(-1)).toBe("Today");
    await expect(timeline.getByRole("img")).toHaveAttribute(
      "aria-label",
      /^Story volume over 7 days; [\d,]+ stories, busiest hour \w{3} \d{2}:00 UTC; highlighted: Last 24 h, live$/,
    );
    await expect(page.getByTestId("timeline-label")).toHaveText("Last 24 h, live");
    // The mocked dots: 5 + 8 + 3 stories in 3 places.
    await expect(timeline.getByText("16 stories · 3 places")).toBeVisible();
    await expect(timeline.getByRole("button", { name: "24h" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("a preset switches the label and refetches the globe for that window", async ({ page }) => {
    const timeline = await gotoTimeline(page);

    const sixHours = page.waitForRequest(
      (r) => isGlobeFetch(r) && params(r).get("timespan") === "6h",
    );
    await timeline.getByRole("button", { name: "6h" }).click();
    await sixHours;
    await expect(page.getByTestId("timeline-label")).toHaveText("Last 6 h, live");
    await expect(timeline.getByRole("button", { name: "6h" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    const week = page.waitForRequest(
      (r) => isGlobeFetch(r) && params(r).get("timespan") === "168h",
    );
    await timeline.getByRole("button", { name: "7d" }).click();
    await week;
    await expect(page.getByTestId("timeline-label")).toHaveText("Last 7 days, live");
  });

  test("dragging across the chart picks a range of whole hours", async ({ page }) => {
    const timeline = await gotoTimeline(page);
    const chart = (await page.getByTestId("timeline-chart").boundingBox())!;

    const ranged = page.waitForRequest((r) => isGlobeFetch(r) && params(r).has("start_time"));
    const y = chart.y + chart.height / 2;
    await page.mouse.move(chart.x + chart.width * 0.3, y);
    await page.mouse.down();
    await page.mouse.move(chart.x + chart.width * 0.45, y, { steps: 5 });
    await page.mouse.move(chart.x + chart.width * 0.6, y, { steps: 5 });
    await page.mouse.up();

    const req = await ranged;
    const start = Date.parse(params(req).get("start_time")!);
    const end = Date.parse(params(req).get("end_time")!);
    expect(start % 3_600_000).toBe(0);
    expect(end % 3_600_000).toBe(0);
    // 30% of 169 hours: about 51 hours.
    expect(Math.round((end - start) / 3_600_000)).toBeGreaterThanOrEqual(49);
    expect(Math.round((end - start) / 3_600_000)).toBeLessThanOrEqual(53);
    await expect(page.getByTestId("timeline-label")).toHaveText(
      /^\w{3} \d{2}:00 – (\w{3} )?\d{2}:00 UTC$/,
    );
    // No preset is on for a range; the status pill no longer says Live.
    await expect(timeline.getByRole("button", { pressed: true })).toHaveCount(0);
    await expect(page.getByTestId("status-pill").getByText("Live")).toHaveCount(0);
  });

  test("replay steps through the days and stops when pressed again", async ({ page }) => {
    const timeline = await gotoTimeline(page);
    const days: string[] = [];
    page.on("request", (r) => {
      if (isGlobeFetch(r) && params(r).has("start_time")) days.push(params(r).get("start_time")!);
    });

    await timeline.getByRole("button", { name: "Replay the last 7 days" }).click();
    const stop = timeline.getByRole("button", { name: "Stop replay" });
    await expect(stop).toBeVisible();
    await expect(page.getByTestId("timeline-label")).toHaveText(/^Replay · \w{3}$/);
    await expect(timeline.getByRole("status")).toHaveText(/^Showing \w{3}$/);
    // The status pill says Replay for the whole run, not each step's Loading…
    await expect(page.getByTestId("status-pill").getByRole("status")).toHaveText("Replay");

    // A day every 1.6 s, each a whole UTC day, one after the other.
    await expect.poll(() => days.length, { timeout: 6000 }).toBeGreaterThanOrEqual(2);
    const [first, second] = days.map(Date.parse);
    expect(first % 86_400_000).toBe(0);
    expect(second - first).toBe(86_400_000);

    const live = page.waitForRequest(
      (r) => isGlobeFetch(r) && params(r).get("timespan") === "24h" && !params(r).has("start_time"),
    );
    await stop.click();
    await live;
    await expect(timeline.getByRole("button", { name: "Replay the last 7 days" })).toBeVisible();
    await expect(page.getByTestId("timeline-label")).toHaveText("Last 24 h, live");
    await expect(page.getByTestId("status-pill").getByText("Live")).toBeVisible();
  });
});

/** Pin low-power mode ("1" on, "0" off) so a 4-core CI runner can't switch it on by itself. */
async function setLowPower(page: Page, on: boolean) {
  await page.addInitScript(
    (value) => window.localStorage.setItem("orbis-low-power", value),
    on ? "1" : "0",
  );
}

test.describe("Layer switcher", () => {
  test("Intensity is unavailable in low-power mode and says why", async ({ page }) => {
    await setLowPower(page, true);
    await gotoTimeline(page);
    const intensity = page.getByTestId("layer-switcher").getByRole("button", { name: "Intensity" });
    await expect(intensity).toHaveAttribute("aria-disabled", "true");
    await expect(intensity).toHaveAttribute("title", /low-power/);
  });

  test("switches the globe between Dots and Intensity", async ({ page }) => {
    await setLowPower(page, false);
    await gotoTimeline(page);
    const layers = page.getByTestId("layer-switcher");
    const dots = layers.getByRole("button", { name: "Dots" });
    const intensity = layers.getByRole("button", { name: "Intensity" });
    await expect(dots).toHaveAttribute("aria-pressed", "true");

    await intensity.click();
    await expect(intensity).toHaveAttribute("aria-pressed", "true");
    await expect(dots).toHaveAttribute("aria-pressed", "false");

    await dots.click();
    await expect(dots).toHaveAttribute("aria-pressed", "true");
  });

  test("during a replay on the main-thread path, each day's dots show over the held heatmap", async ({
    page,
  }) => {
    await setLowPower(page, false);
    // Force the main-thread path, whatever GPU the runner has.
    await page.addInitScript(() =>
      Object.defineProperty(navigator, "gpu", { value: undefined, configurable: true }),
    );
    const timeline = await gotoTimeline(page);
    const globe = page.getByTestId("globe");
    await expect(globe).toHaveAttribute("data-dots", "3");

    await page.getByTestId("layer-switcher").getByRole("button", { name: "Intensity" }).click();
    await expect(globe).toHaveAttribute("data-dots", "0"); // the heatmap alone

    await timeline.getByRole("button", { name: "Replay the last 7 days" }).click();
    await expect(globe).toHaveAttribute("data-dots", "3"); // the day's places, over it

    await timeline.getByRole("button", { name: "Stop replay" }).click();
    await expect(globe).toHaveAttribute("data-dots", "0");
  });
});
