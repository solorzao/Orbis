import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import RecentPlaces from "./RecentPlaces";
import type { PanelEntry } from "@/types/news";

function entry(panelId: string, locationName: string | undefined, count = 4): PanelEntry {
  return {
    panelId,
    point: {
      id: panelId,
      lat: 48.86,
      lng: 2.35,
      size: 1,
      color: "#72ddb2",
      articles: [],
      isCluster: true,
      count,
      locationName,
      topic: "Climate",
    },
    query: { startTime: "2026-10-10T00:00:00Z", endTime: "2026-10-11T00:00:00Z", live: true },
    articles: [],
    nextOffset: 0,
    clusterSummary: null,
    articlesLoading: false,
    summaryLoading: false,
    createdAt: 0,
  };
}

const PLACES = [
  entry("a", "Paris, France", 5),
  entry("b", "London, United Kingdom", 3),
  entry("c", undefined, 2),
];

describe("RecentPlaces", () => {
  it("shows one pill per open place, named before the comma, with its count", () => {
    render(<RecentPlaces places={PLACES} activeId="a" onSelect={() => {}} onClose={() => {}} />);
    const group = screen.getByRole("group", { name: "Recent places" });
    const picks = within(group)
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("aria-pressed"));
    expect(picks.map((b) => b.textContent)).toEqual(["Paris5", "London3", "48.9°, 2.4°2"]);
    expect(picks[0]).toHaveAttribute("title", "Paris, France");
    // Where focus goes when the open place is minimized (useKeepFocus)
    expect(picks.map((b) => b.getAttribute("data-place"))).toEqual(["a", "b", "c"]);
  });

  it("marks only the active place as pressed", () => {
    render(<RecentPlaces places={PLACES} activeId="b" onSelect={() => {}} onClose={() => {}} />);
    expect(screen.getByRole("button", { name: /^London/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^Paris/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /^London/ }).closest(".pill")).toHaveClass("on");
    expect(screen.getByRole("button", { name: /^Paris/ }).closest(".pill")).not.toHaveClass("on");
  });

  it("selects a place on click", () => {
    const onSelect = vi.fn();
    render(<RecentPlaces places={PLACES} activeId="a" onSelect={onSelect} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /^London/ }));
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("closes a place with its × button", () => {
    const onClose = vi.fn();
    const onSelect = vi.fn();
    render(<RecentPlaces places={PLACES} activeId="a" onSelect={onSelect} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close London" }));
    expect(onClose).toHaveBeenCalledWith("b");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("shows at most the five newest places", () => {
    const many = ["a", "b", "c", "d", "e", "f"].map((id) => entry(id, `Place ${id}, X`));
    render(<RecentPlaces places={many} activeId={null} onSelect={() => {}} onClose={() => {}} />);
    const closers = screen.getAllByRole("button", { name: /^Close/ });
    expect(closers.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Close Place b",
      "Close Place c",
      "Close Place d",
      "Close Place e",
      "Close Place f",
    ]);
  });

  it("renders nothing without places", () => {
    const { container } = render(
      <RecentPlaces places={[]} activeId={null} onSelect={() => {}} onClose={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
