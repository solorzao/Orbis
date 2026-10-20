import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import ThreadsRail from "./ThreadsRail";
import {
  toThread,
  toThreadDetail,
  type ApiThread,
  type ApiThreadPlace,
  type Thread,
  type ThreadDetail,
} from "@/lib/threads";

function thread(id: number, over: Partial<ApiThread> = {}): Thread {
  return toThread({
    id,
    title: `Thread ${id}`,
    synopsis: null,
    status: "developing",
    first_seen: "2026-10-18T06:10:00Z",
    last_seen: "2026-10-18T15:00:00Z",
    n_stories: 14,
    n_sources: 9,
    velocity: 4,
    countries: ["YE", "EG", "NL"],
    places: [],
    topic: "conflict",
    lead: null,
    ...over,
  });
}

const place = (name: string, lat: number, lng: number, iso: string): ApiThreadPlace => ({
  lat,
  lng,
  place: name,
  country_code: iso,
  first_seen: "2026-10-18T06:10:00Z",
  n: 3,
});
const SPREAD = [
  place("Yemen", 15.5, 48.5, "YE"),
  place("Suez, Egypt", 30.5, 32.5, "EG"),
  place("Rotterdam, Netherlands", 51.5, 4.5, "NL"),
];

const RED_SEA = thread(7, { title: "Red Sea shipping attacks", places: SPREAD.slice(0, 2) });

function detail(over: Partial<ApiThread> = {}): ThreadDetail {
  return toThreadDetail({
    id: 7,
    title: "Red Sea shipping attacks",
    synopsis: "Outlets in Yemen first reported attacks on ships in the Red Sea.",
    status: "developing",
    first_seen: "2026-10-18T06:10:00Z",
    last_seen: "2026-10-18T15:00:00Z",
    n_stories: 24,
    n_sources: 11,
    velocity: 6,
    countries: ["YE", "EG", "NL"],
    places: SPREAD.slice(0, 2),
    topic: "conflict",
    lead: {
      title: "Ships divert from the Red Sea",
      source_name: "Reuters",
      published_at: "2026-10-18T14:00:00Z",
      image_url: null,
      topic: "conflict",
    },
    entities: [
      { name: "Suez Canal Authority", n: 9 },
      { name: "Houthis", n: 7 },
    ],
    spread: SPREAD,
    timeline: [],
    articles: [],
    ...over,
  });
}

const SELECTED = { id: 7, title: "Red Sea shipping attacks" };
const route = () => screen.getByRole("list", { name: "Spread, in order of first report" });
const stops = () => within(route()).getAllByRole("listitem");
const stopNames = () => stops().map((s) => s.querySelector(".stop-place")!.textContent);

type Props = ComponentProps<typeof ThreadsRail>;
function renderRail(over: Partial<Props> = {}) {
  const props: Props = {
    variant: "rail",
    threads: [RED_SEA],
    status: null,
    loading: false,
    selected: null,
    detail: null,
    lit: null,
    onSelect: vi.fn(),
    ...over,
  };
  return { ...render(<ThreadsRail {...props} />), props };
}

const rows = () =>
  within(screen.getByRole("list", { name: "Developing stories" })).getAllByRole("button");

describe("ThreadsRail", () => {
  it("is a glass panel headed Threads, saying how many are active", () => {
    const threads = Array.from({ length: 12 }, (_, i) => thread(i + 1));
    renderRail({ threads });
    const rail = screen.getByRole("region", { name: "Threads" });
    expect(rail).toHaveClass("glass", "threads");
    expect(rail).toHaveAttribute("data-testid", "threads-rail");
    expect(within(rail).getByRole("heading", { name: "Threads" })).toBeInTheDocument();
    expect(within(rail).getByText("12 active")).toBeInTheDocument();
  });

  it("lists up to 10 threads as buttons, fastest first, as the API orders them", () => {
    const threads = Array.from({ length: 12 }, (_, i) => thread(i + 1));
    renderRail({ threads });
    expect(rows()).toHaveLength(10);
    expect(rows()[0]).toHaveTextContent("Thread 1");
    expect(rows()[9]).toHaveTextContent("Thread 10");
  });

  it("shows each thread's title, stories, status, countries, outlets and velocity", () => {
    const slower = thread(8, { title: "Typhoon nears Luzon", status: "emerging", velocity: 1 });
    renderRail({ threads: [RED_SEA, slower] });
    const [first, second] = rows();
    expect(first).toHaveAccessibleName(
      "Red Sea shipping attacks, Developing, 14 stories, 3 countries, 9 outlets",
    );
    expect(first.querySelector(".th-status")).toHaveAttribute("data-s", "Developing");
    expect(second.querySelector(".th-status")).toHaveAttribute("data-s", "Emerging");
    expect(second).toHaveTextContent("Emerging");
    // The velocity bar: against the fastest listed.
    expect(first.querySelector<HTMLElement>(".bar i")!.style.width).toBe("100%");
    expect(second.querySelector<HTMLElement>(".bar i")!.style.width).toBe("25%");
  });

  it("counts countries as countries, and leaves an open row's numbers to its facts", () => {
    const { props, rerender } = renderRail();
    const meta = () => rows()[0].querySelector(".m")!;
    expect(meta()).toHaveTextContent("3 countries");
    expect(meta()).toHaveTextContent("9 outlets");
    expect(screen.queryByText(/regions?\b/)).toBeNull();

    rerender(<ThreadsRail {...props} selected={SELECTED} detail={detail()} />);
    // Open: the facts say Outlets and Countries; the row's line doesn't repeat them.
    expect(meta()).not.toHaveTextContent("countries");
    expect(meta()).not.toHaveTextContent("outlets");
    expect(meta().querySelector(".th-status")).toHaveTextContent("Developing");
    expect(meta().querySelector(".bar")).not.toBeNull();
    expect(screen.getByRole("list", { name: "Facts" })).toHaveTextContent("Countries3");
  });

  it("says why it lists nothing", () => {
    renderRail({ threads: [], status: "No developing stories in this window" });
    expect(screen.getByText("No developing stories in this window")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Developing stories" })).toBeNull();
    expect(screen.queryByText(/active/)).toBeNull();
  });

  it("says it is loading the first time, without a count", () => {
    renderRail({ threads: [], loading: true });
    expect(screen.getByText("Finding developing stories…")).toBeInTheDocument();
    expect(screen.queryByText(/active/)).toBeNull();
  });

  it("selects a thread, and the selected one again deselects it", () => {
    const { props, rerender } = renderRail();
    fireEvent.click(rows()[0]);
    expect(props.onSelect).toHaveBeenCalledWith({ id: 7, title: "Red Sea shipping attacks" });
    expect(rows()[0]).toHaveAttribute("aria-expanded", "false");

    rerender(<ThreadsRail {...props} selected={{ id: 7, title: "Red Sea shipping attacks" }} />);
    expect(rows()[0]).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(rows()[0]);
    expect(props.onSelect).toHaveBeenLastCalledWith(null);
  });

  it("in the sheet, is the tab's list with its count, no panel of its own", () => {
    renderRail({ variant: "sheet", threads: [RED_SEA] });
    expect(screen.queryByRole("region", { name: "Threads" })).toBeNull();
    expect(screen.getByTestId("threads-sheet")).toHaveTextContent("1 active");
    expect(rows()).toHaveLength(1);
  });
  it("opens the selected thread under its row: synopsis, spread in order, facts", () => {
    renderRail({ selected: SELECTED, detail: detail() });
    const row = rows()[0];
    const panel = document.getElementById(row.getAttribute("aria-controls")!)!;
    expect(panel).toHaveClass("tdetail");
    expect(within(panel).getByText(/Outlets in Yemen first reported/)).toBeInTheDocument();
    expect(panel.querySelector(".syn .ai")).toHaveTextContent("AI");
    expect(stopNames()).toEqual(["Yemen", "Suez, Egypt", "Rotterdam, Netherlands"]);
    // Each stop's first report, for screen readers too (not only in its tooltip).
    expect(stops()[0].querySelector(".sr-only")).toHaveTextContent("first reported Sun 06:10 UTC");
    const facts = within(panel).getByRole("list", { name: "Facts" });
    expect(facts).toHaveTextContent("First seenSun 06:10");
    expect(facts).toHaveTextContent("Outlets11");
    expect(facts).toHaveTextContent("Countries3");
  });

  it("says when the synopsis is pending, showing the lead headline instead", () => {
    renderRail({ selected: SELECTED, detail: detail({ synopsis: null }) });
    expect(screen.getByText("Synopsis pending; showing the lead headline")).toBeInTheDocument();
    expect(screen.getByText("Ships divert from the Red Sea")).toBeInTheDocument();
  });

  it("shows the list's places until the detail arrives", () => {
    renderRail({ selected: SELECTED, detail: null });
    expect(stopNames()).toEqual(["Yemen", "Suez, Egypt"]);
    expect(screen.queryByText("Key entities")).toBeNull();
  });

  it("lights the places a replay has reached, all of them otherwise", () => {
    const { rerender, props } = renderRail({ selected: SELECTED, detail: detail(), lit: 2 });
    expect(stops().map((s) => s.querySelector(".stop")!.classList.contains("on"))).toEqual([
      true,
      true,
      false,
    ]);
    rerender(<ThreadsRail {...props} lit={null} />);
    expect(stops().every((s) => s.querySelector(".stop")!.classList.contains("on"))).toBe(true);
  });

  it("lists its key entities, and opens all its stories", () => {
    const onShowStories = vi.fn();
    renderRail({ selected: SELECTED, detail: detail(), onShowStories });
    const entities = screen.getByRole("list", { name: "Key entities" });
    expect(
      within(entities)
        .getAllByRole("listitem")
        .map((e) => e.textContent),
    ).toEqual(["Suez Canal Authority", "Houthis"]);
    fireEvent.click(screen.getByRole("button", { name: "All 24 stories" }));
    expect(onShowStories).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
  });

  it("holds a selected thread the list doesn't (a chip's) at the top, open", () => {
    const other = { id: 99, title: "Port strike in Antwerp" };
    renderRail({ selected: other, detail: detail({ id: 99, title: "Port strike in Antwerp" }) });
    expect(rows()).toHaveLength(2);
    expect(rows()[0]).toHaveTextContent("Port strike in Antwerp");
    expect(rows()[0]).toHaveAttribute("aria-expanded", "true");
    expect(rows()[1]).toHaveTextContent("Red Sea shipping attacks");
  });

  it("names a chip's thread before its detail arrives", () => {
    renderRail({ selected: { id: 99, title: "Port strike in Antwerp" }, detail: null });
    expect(rows()[0]).toHaveTextContent("Port strike in Antwerp");
    expect(rows()[0]).toHaveAttribute("aria-expanded", "true");
  });
});
