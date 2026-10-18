import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import BreakingTicker, { ROTATE_MS } from "./BreakingTicker";
import type { BreakingStory } from "@/lib/breaking";

const LONG =
  "A U.S. Military Airman Tragically Dies After Rappelling Accident at UTSA-Navy Game in San Antonio";

const STORIES: BreakingStory[] = [
  {
    headline: LONG,
    place: "Alamodome, Texas, United States",
    lat: 29.5,
    lng: -98.5,
    outlets: 17,
    stories: 7,
  },
  {
    headline: "Riot police clear Paris square",
    place: "Paris, France",
    lat: 48.5,
    lng: 2.5,
    outlets: 12,
    stories: 4,
  },
  {
    headline: "Port strike halts Rotterdam",
    place: "Rotterdam, Netherlands",
    lat: 51.5,
    lng: 4.5,
    outlets: 1,
    stories: 3,
  },
];

const ticker = () => screen.getByTestId("breaking-ticker");
const item = () => screen.getByTestId("breaking-item");

function renderTicker(over: Partial<Parameters<typeof BreakingTicker>[0]> = {}) {
  const onOpen = vi.fn();
  const utils = render(
    <BreakingTicker stories={STORIES} reduced={false} onOpen={onOpen} {...over} />,
  );
  return { ...utils, onOpen };
}

// Wide enough to show it (soft-orbit.css hides it below 1180px).
const widthIs = (w: number) =>
  Object.defineProperty(window, "innerWidth", { configurable: true, value: w });

beforeEach(() => {
  vi.useFakeTimers();
  widthIs(1440);
});
afterEach(() => {
  vi.useRealTimers();
  widthIs(1024);
});

describe("BreakingTicker", () => {
  it("reads Breaking · headline · place · outlets · n of N", () => {
    renderTicker();
    expect(ticker()).toHaveAttribute("aria-label", "Breaking stories");
    expect(ticker()).toHaveClass("pillbar", "breaking");
    expect(ticker()).toHaveTextContent(
      `Breaking${LONG}Alamodome, Texas, United States · 17 outlets1 of 3`,
    );
  });

  it("ellipsises a long headline to one line, its full text in the tooltip", () => {
    renderTicker();
    const headline = screen.getByText(LONG);
    expect(headline).toHaveClass("breaking-head"); // one line, ellipsised (soft-orbit.css)
    expect(item()).toHaveAttribute("title", LONG);
  });

  it("counts outlets, one or many", () => {
    renderTicker({ stories: [STORIES[2]] });
    expect(ticker()).toHaveTextContent("Rotterdam, Netherlands · 1 outlet");
  });

  it("rotates every 6 s, round to the first", () => {
    renderTicker();
    expect(item()).toHaveTextContent(LONG);
    act(() => void vi.advanceTimersByTime(ROTATE_MS - 1));
    expect(item()).toHaveTextContent(LONG);
    act(() => void vi.advanceTimersByTime(1));
    expect(item()).toHaveTextContent("Riot police clear Paris square");
    expect(ticker()).toHaveTextContent("2 of 3");
    act(() => void vi.advanceTimersByTime(ROTATE_MS));
    expect(item()).toHaveTextContent("Port strike halts Rotterdam");
    act(() => void vi.advanceTimersByTime(ROTATE_MS));
    expect(item()).toHaveTextContent(LONG);
  });

  it("pauses while hovered or focused", () => {
    renderTicker();
    fireEvent.mouseEnter(ticker());
    act(() => void vi.advanceTimersByTime(ROTATE_MS * 3));
    expect(item()).toHaveTextContent(LONG);
    fireEvent.mouseLeave(ticker());
    act(() => void vi.advanceTimersByTime(ROTATE_MS));
    expect(item()).toHaveTextContent("Riot police clear Paris square");

    fireEvent.focus(item());
    act(() => void vi.advanceTimersByTime(ROTATE_MS * 3));
    expect(item()).toHaveTextContent("Riot police clear Paris square");
    fireEvent.blur(item());
    act(() => void vi.advanceTimersByTime(ROTATE_MS));
    expect(item()).toHaveTextContent("Port strike halts Rotterdam");
  });

  it("doesn't rotate on its own with reduced motion, and is then a polite live region", () => {
    renderTicker({ reduced: true });
    act(() => void vi.advanceTimersByTime(ROTATE_MS * 5));
    expect(item()).toHaveTextContent(LONG);
    expect(screen.getByTestId("breaking-live")).toHaveAttribute("aria-live", "polite");
  });

  it("is quiet to screen readers while it rotates on its own", () => {
    renderTicker();
    expect(screen.getByTestId("breaking-live")).toHaveAttribute("aria-live", "off");
  });

  it("steps with previous and next, wrapping round", () => {
    renderTicker();
    fireEvent.click(screen.getByRole("button", { name: "Next breaking story" }));
    expect(item()).toHaveTextContent("Riot police clear Paris square");
    fireEvent.click(screen.getByRole("button", { name: "Previous breaking story" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous breaking story" }));
    expect(item()).toHaveTextContent("Port strike halts Rotterdam");
    expect(ticker()).toHaveTextContent("3 of 3");
  });

  it("opens the story shown", () => {
    const { onOpen } = renderTicker();
    fireEvent.click(screen.getByRole("button", { name: "Next breaking story" }));
    fireEvent.click(item());
    expect(onOpen).toHaveBeenCalledWith(STORIES[1]);
  });

  it("has no counter or arrows for a single story", () => {
    renderTicker({ stories: [STORIES[1]] });
    expect(ticker()).not.toHaveTextContent("1 of 1");
    expect(screen.queryByRole("button", { name: "Next breaking story" })).toBeNull();
  });

  it("is hidden when nothing is breaking", () => {
    const { container } = renderTicker({ stories: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it("starts again at the first when the stories change under it", () => {
    const { rerender, onOpen } = renderTicker();
    fireEvent.click(screen.getByRole("button", { name: "Next breaking story" }));
    fireEvent.click(screen.getByRole("button", { name: "Next breaking story" }));
    expect(ticker()).toHaveTextContent("3 of 3");
    rerender(<BreakingTicker stories={STORIES.slice(0, 2)} reduced={false} onOpen={onOpen} />);
    expect(ticker()).toHaveTextContent("1 of 2");
    expect(item()).toHaveTextContent(LONG);
  });

  it("keeps the story shown when a refresh still lists it", () => {
    const { rerender, onOpen } = renderTicker();
    fireEvent.click(screen.getByRole("button", { name: "Next breaking story" }));
    // The 5-minute refresh: a new list, the Paris story now first.
    rerender(<BreakingTicker stories={[STORIES[1], STORIES[0]]} reduced={false} onOpen={onOpen} />);
    expect(item()).toHaveTextContent("Riot police clear Paris square");
    expect(ticker()).toHaveTextContent("1 of 2");
  });

  it("says which story of how many in the item's name", () => {
    renderTicker();
    expect(item()).toHaveAccessibleName(
      `${LONG}, Alamodome, Texas, United States, 17 outlets, 1 of 3`,
    );
    renderTicker({ stories: [STORIES[1]] });
    expect(screen.getAllByTestId("breaking-item")[1]).toHaveAccessibleName(
      "Riot police clear Paris square, Paris, France, 12 outlets",
    );
  });

  it("runs no timer while CSS hides it (below 1180px)", () => {
    widthIs(1024);
    renderTicker();
    act(() => void vi.advanceTimersByTime(ROTATE_MS * 3));
    expect(item()).toHaveTextContent(LONG);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("doesn't stay paused by a hover the stories took away", () => {
    const { rerender, onOpen } = renderTicker();
    fireEvent.mouseEnter(ticker());
    // Nothing breaking for a while: the ticker goes, and the pointer with it.
    rerender(<BreakingTicker stories={[]} reduced={false} onOpen={onOpen} />);
    rerender(<BreakingTicker stories={STORIES} reduced={false} onOpen={onOpen} />);
    act(() => void vi.advanceTimersByTime(ROTATE_MS));
    expect(item()).toHaveTextContent("Riot police clear Paris square");
  });

  it("stays paused while the item keeps the focus as the stories change", () => {
    const { rerender, onOpen } = renderTicker();
    act(() => item().focus());
    // Down to one story: the arrows go, the item keeps the focus.
    rerender(<BreakingTicker stories={[STORIES[0]]} reduced={false} onOpen={onOpen} />);
    expect(item()).toHaveFocus();
    rerender(<BreakingTicker stories={STORIES} reduced={false} onOpen={onOpen} />);
    act(() => void vi.advanceTimersByTime(ROTATE_MS * 2));
    expect(item()).toHaveTextContent(LONG);
    expect(screen.getByTestId("breaking-live")).toHaveAttribute("aria-live", "polite");
  });

  it("doesn't stay paused by a focus the stories took away", () => {
    const { rerender, onOpen } = renderTicker();
    act(() => screen.getByRole("button", { name: "Next breaking story" }).focus());
    // Down to one story: the arrows go, and the focus with them (no blur).
    rerender(<BreakingTicker stories={[STORIES[0]]} reduced={false} onOpen={onOpen} />);
    rerender(<BreakingTicker stories={STORIES} reduced={false} onOpen={onOpen} />);
    act(() => void vi.advanceTimersByTime(ROTATE_MS));
    expect(item()).toHaveTextContent("Riot police clear Paris square");
  });
});
