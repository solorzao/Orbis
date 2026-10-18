import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import SinceStrip from "./SinceStrip";
import type { SinceDelta } from "@/lib/sinceVisit";

const NOW = Date.UTC(2026, 9, 18, 16, 37, 21);
const H = 3_600_000;

const DELTA: SinceDelta = {
  at: NOW,
  newStories: 1286,
  newPlaces: 212,
  breaking: 4,
  top: [
    {
      lat: 48.5,
      lng: 2.5,
      place: "Paris, France",
      new: 64,
      headline: "Riot police clear a square",
    },
    { lat: 29.5, lng: -98.5, place: "San Antonio, Texas", new: 31, headline: "Airman dies" },
  ],
};

function renderStrip(over: Partial<Parameters<typeof SinceStrip>[0]> = {}) {
  const props = {
    lastVisit: NOW - 14 * H,
    delta: DELTA,
    onShow: vi.fn(),
    onOpen: vi.fn(),
    onDismiss: vi.fn(),
    ...over,
  };
  render(<SinceStrip {...props} />);
  return props;
}

describe("SinceStrip", () => {
  it("welcomes back with the time away, the new stories and the breaking ones", () => {
    renderStrip();
    const strip = screen.getByTestId("since-strip");
    expect(strip).toHaveClass("pillbar", "since");
    expect(strip).toHaveAttribute("aria-label", "Since your last visit");
    expect(strip).toHaveTextContent(
      "Welcome back. 14 h since your visit: 1,286 new stories, 4 breaking stories.",
    );
  });

  it("leaves out breaking stories when there are none", () => {
    renderStrip({ delta: { ...DELTA, breaking: 0 } });
    expect(screen.getByTestId("since-strip")).toHaveTextContent(
      "Welcome back. 14 h since your visit: 1,286 new stories.",
    );
  });

  it("Show sets the window from the visit to now", () => {
    const { onShow } = renderStrip();
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(onShow).toHaveBeenCalledTimes(1);
  });

  it("Top 5 lists the places with the most new stories; one opens", () => {
    const { onOpen } = renderStrip();
    const toggle = screen.getByRole("button", { name: "Top 5" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("list", { name: "Places with the most new stories" })).toBeNull();
    // What it controls exists, hidden while closed.
    const controlled = document.getElementById(toggle.getAttribute("aria-controls")!);
    expect(controlled).not.toBeNull();
    expect(controlled).not.toBeVisible();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Places with the most new stories" });
    const rows = within(list).getAllByRole("button");
    expect(rows.map((r) => r.textContent)).toEqual([
      "Paris, France64Riot police clear a square",
      "San Antonio, Texas31Airman dies",
    ]);
    fireEvent.click(rows[1]);
    expect(onOpen).toHaveBeenCalledWith(DELTA.top[1]);
  });

  it("has no Top 5 when nothing is new", () => {
    renderStrip({ delta: { ...DELTA, newStories: 0, top: [] } });
    expect(screen.queryByRole("button", { name: "Top 5" })).toBeNull();
  });

  it("dismisses", () => {
    const { onDismiss } = renderStrip();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("is a callout card in the co-pilot on narrow screens", () => {
    renderStrip({ variant: "callout" });
    const card = screen.getByTestId("since-callout");
    expect(card).toHaveClass("callout", "since-callout");
    expect(card).not.toHaveClass("pillbar");
    expect(card).toHaveTextContent("14 h since your visit: 1,286 new stories");
    expect(screen.queryByTestId("since-strip")).toBeNull();
  });
});
