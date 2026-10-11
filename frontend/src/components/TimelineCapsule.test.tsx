import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import TimelineCapsule from "./TimelineCapsule";
import { fetchVolume } from "@/lib/api";
import { DEFAULT_WINDOW, type TimeWindow } from "@/lib/timeWindow";

vi.mock("@/lib/api", () => ({ fetchVolume: vi.fn() }));

const H = 3_600_000;
// Sunday 11 October 2026, 12:30 UTC: the chart runs from Sun 4 Oct 12:00 to 13:00 today.
const NOW = Date.UTC(2026, 9, 11, 12, 30);
const CHART_START = Date.UTC(2026, 9, 4, 12);
const iso = (ms: number) => new Date(ms).toISOString();

const mockFetchVolume = vi.mocked(fetchVolume);

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
  vi.setSystemTime(NOW);
  mockFetchVolume.mockReset();
  mockFetchVolume.mockResolvedValue([
    { hour: "2026-10-04T12:00:00Z", count: 3 },
    { hour: "2026-10-11T12:00:00Z", count: 31 },
  ]);
});

afterEach(() => {
  vi.useRealTimers();
});

function renderCapsule(window: TimeWindow = DEFAULT_WINDOW, onChange = vi.fn()) {
  const utils = render(
    <TimelineCapsule timeWindow={window} onChange={onChange} stories={1234} places={56} />,
  );
  return { ...utils, onChange };
}

/** The chart, 676px wide from x = 0: four pixels an hour over the 169 hours. */
function chart() {
  const el = screen.getByTestId("timeline-chart");
  vi.spyOn(el, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    right: 676,
    bottom: 62,
    width: 676,
    height: 62,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
  return el;
}

describe("TimelineCapsule", () => {
  it("is a labelled capsule with the replay button, chart and meta", async () => {
    renderCapsule();
    await act(async () => {});
    const capsule = screen.getByTestId("timeline");
    expect(capsule).toHaveClass("pillbar", "timeline");
    expect(capsule).toHaveAccessibleName("Time window and replay");
    expect(within(capsule).getByRole("button", { name: "Replay the last 7 days" })).toHaveClass(
      "aurora-btn",
      "play",
    );
    expect(within(capsule).getByRole("img").getAttribute("aria-label")).toMatch(
      /^Story volume over 7 days; 34 stories, busiest hour Sun 12:00 UTC; highlighted: Last 24 h, live$/,
    );
    expect(within(capsule).getByText("1,234 stories · 56 places")).toBeInTheDocument();
  });

  it("fetches the 7-day volume on mount and every 15 minutes, and stops on unmount", async () => {
    const { unmount } = renderCapsule();
    expect(mockFetchVolume).toHaveBeenCalledTimes(1);
    expect(mockFetchVolume.mock.calls[0][0]).toBe(7);
    const signal = mockFetchVolume.mock.calls[0][1] as AbortSignal;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 60_000);
    });
    expect(mockFetchVolume).toHaveBeenCalledTimes(2);

    unmount();
    expect(signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(30 * 60_000);
    expect(mockFetchVolume).toHaveBeenCalledTimes(2);
  });

  it("draws the area and the day labels, Sun … Today", async () => {
    renderCapsule();
    await act(async () => {});
    const svg = screen.getByRole("img");
    expect(svg.querySelectorAll("path")).toHaveLength(2); // fill and stroke
    expect(Array.from(svg.querySelectorAll("text")).map((t) => t.textContent)).toEqual([
      "Sun",
      "Mon",
      "Tue",
      "Wed",
      "Thu",
      "Fri",
      "Sat",
      "Today",
    ]);
  });

  it("shows the current window's label", () => {
    const { rerender } = renderCapsule({ kind: "live", hours: 6 });
    expect(screen.getByTestId("timeline-label")).toHaveTextContent("Last 6 h, live");
    rerender(
      <TimelineCapsule
        timeWindow={{
          kind: "range",
          startTime: iso(Date.UTC(2026, 9, 6, 14)),
          endTime: iso(Date.UTC(2026, 9, 7, 2)),
        }}
        onChange={vi.fn()}
        stories={0}
        places={0}
      />,
    );
    expect(screen.getByTestId("timeline-label")).toHaveTextContent("Tue 14:00 – Wed 02:00 UTC");
  });

  it("presets set a live window and show which is on", () => {
    const { onChange } = renderCapsule({ kind: "live", hours: 6 });
    const presets = screen.getByRole("group", { name: "Time window presets" });
    const buttons = within(presets).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["1h", "6h", "24h", "7d"]);
    expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual([
      "false",
      "true",
      "false",
      "false",
    ]);

    fireEvent.click(within(presets).getByRole("button", { name: "7d" }));
    expect(onChange).toHaveBeenLastCalledWith({ kind: "live", hours: 168 });
    fireEvent.click(within(presets).getByRole("button", { name: "1h" }));
    expect(onChange).toHaveBeenLastCalledWith({ kind: "live", hours: 1 });
  });

  it("dragging across the chart selects a range snapped to whole hours", () => {
    const { onChange } = renderCapsule();
    const el = chart();
    // 4px an hour: x 41 -> 10.25 h -> 10 h; x 129 -> 32.25 h -> 32 h.
    fireEvent.pointerDown(el, { pointerId: 1, button: 0, clientX: 41 });
    fireEvent.pointerMove(el, { pointerId: 1, clientX: 90 });
    expect(onChange).not.toHaveBeenCalled(); // the globe fetches once, on release
    fireEvent.pointerUp(el, { pointerId: 1, clientX: 129 });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({
      kind: "range",
      startTime: iso(CHART_START + 10 * H),
      endTime: iso(CHART_START + 32 * H),
    });
  });

  it("keyboard users move the window's start and end with two range inputs", () => {
    const window: TimeWindow = {
      kind: "range",
      startTime: iso(CHART_START + 10 * H),
      endTime: iso(CHART_START + 32 * H),
    };
    const { onChange } = renderCapsule(window);
    const start = screen.getByRole("slider", { name: "Window start" });
    const end = screen.getByRole("slider", { name: "Window end" });
    expect(start).toHaveValue("10");
    expect(end).toHaveValue("32");
    expect(start).toHaveAttribute("aria-valuetext", "Sun 22:00 UTC");

    fireEvent.change(start, { target: { value: "12" } });
    expect(onChange).toHaveBeenLastCalledWith({
      kind: "range",
      startTime: iso(CHART_START + 12 * H),
      endTime: iso(CHART_START + 32 * H),
    });
    fireEvent.change(end, { target: { value: "40" } });
    expect(onChange).toHaveBeenLastCalledWith({
      kind: "range",
      startTime: iso(CHART_START + 10 * H),
      endTime: iso(CHART_START + 40 * H),
    });
    // The start never passes the end: at least an hour stays selected.
    fireEvent.change(start, { target: { value: "50" } });
    expect(onChange).toHaveBeenLastCalledWith({
      kind: "range",
      startTime: iso(CHART_START + 31 * H),
      endTime: iso(CHART_START + 32 * H),
    });
  });
});
