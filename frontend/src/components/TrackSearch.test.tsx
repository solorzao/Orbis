import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import TrackSearch from "./TrackSearch";
import { useTrackSearch } from "@/hooks/useTrackSearch";
import type { SearchResults } from "@/lib/entities";
import type { GlobePoint } from "@/types/news";

vi.mock("@/hooks/useTrackSearch", () => ({ useTrackSearch: vi.fn() }));
const mockSearch = vi.mocked(useTrackSearch);

function dot(name: string, count: number, lat: number, lng: number): GlobePoint {
  return {
    id: name,
    lat,
    lng,
    size: 1,
    color: "#ab9dff",
    articles: [],
    isCluster: true,
    count,
    locationName: name,
    topic: "Politics",
  };
}

const POINTS = [
  dot("Paris, France", 5, 48.85, 2.35),
  dot("Paris, Texas, United States", 2, 33.6, -95.5),
  dot("London, United Kingdom", 3, 51.5, -0.12),
];

const RESULTS: SearchResults = {
  people: [{ type: "person", name: "Paris Hilton", n: 4, capped: false }],
  orgs: [
    { type: "org", name: "Paris Saint-Germain", n: 100, capped: true },
    { type: "org", name: "Paris Hilton", n: 2, capped: false },
  ],
  threads: [{ id: 7, title: "Paris climate talks" }],
};

const answered = (results: SearchResults | null, extra = {}) =>
  mockSearch.mockReturnValue({ results, loading: false, error: false, ...extra });

function setup(over: Partial<Parameters<typeof TrackSearch>[0]> = {}) {
  const props = {
    variant: "bar" as const,
    points: POINTS,
    onPlace: vi.fn(),
    onEntity: vi.fn(),
    onThread: vi.fn(),
    onAnnounce: vi.fn(),
    onDismiss: vi.fn(),
    ...over,
  };
  render(<TrackSearch {...props} />);
  const box = screen.getByRole("combobox", {
    name: "Track a place, person, organisation or thread",
  });
  return { props, box };
}

const type = (box: HTMLElement, value: string) => fireEvent.change(box, { target: { value } });
const key = (box: HTMLElement, k: string) => fireEvent.keyDown(box, { key: k });
const listbox = () => screen.getByRole("listbox", { hidden: true });
const active = (box: HTMLElement) => {
  const id = box.getAttribute("aria-activedescendant");
  return id ? document.getElementById(id) : null;
};

beforeEach(() => {
  mockSearch.mockReset();
  answered(null);
});

describe("TrackSearch", () => {
  it("is a collapsed combobox until something is typed", () => {
    const { box } = setup();
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(box).toHaveAttribute("aria-autocomplete", "list");
    expect(box).toHaveAttribute("aria-controls", listbox().id);
    expect(box).toHaveAttribute("placeholder", "Track a place, person, organisation or thread");
    expect(screen.getByText("/")).toBeInTheDocument(); // the kbd hint
  });

  it("lists the loaded places at once, before the server answers", () => {
    mockSearch.mockReturnValue({ results: null, loading: true, error: false });
    const { box } = setup();
    type(box, "par");
    expect(box).toHaveAttribute("aria-expanded", "true");
    const places = within(listbox()).getByRole("group", { name: "Places" });
    expect(
      within(places)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Paris, France5", "Paris, Texas, United States2"]);
    expect(screen.getByText("Searching people, organisations and threads…")).toBeInTheDocument();
    expect(mockSearch).toHaveBeenLastCalledWith("par");
  });

  it("groups the results: Places, People, Organisations, Threads, the same name in two", () => {
    answered(RESULTS);
    const { box } = setup();
    type(box, "paris");
    const groups = within(listbox()).getAllByRole("group");
    const names = ["Places", "People", "Organisations", "Threads"];
    expect(groups).toHaveLength(names.length);
    names.forEach((name, i) => expect(groups[i]).toHaveAccessibleName(name));
    expect(within(groups[1]).getByRole("option")).toHaveAccessibleName(
      "Paris Hilton, 4 stories this week",
    );
    expect(
      within(groups[2])
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Paris Saint-Germain100+", "Paris Hilton2"]);
    expect(within(groups[3]).getByRole("option")).toHaveAccessibleName("Paris climate talks");
  });

  it("moves through every option with the arrow keys, wrapping round", () => {
    answered(RESULTS);
    const { box } = setup();
    type(box, "paris");
    expect(active(box)).toBeNull();
    key(box, "ArrowDown");
    expect(active(box)).toHaveAccessibleName("Paris, France, 5 stories");
    expect(active(box)).toHaveAttribute("aria-selected", "true");
    key(box, "ArrowDown");
    key(box, "ArrowDown");
    expect(active(box)).toHaveAccessibleName("Paris Hilton, 4 stories this week");
    key(box, "ArrowUp");
    expect(active(box)).toHaveAccessibleName("Paris, Texas, United States, 2 stories");
    key(box, "ArrowUp");
    key(box, "ArrowUp");
    expect(active(box)).toHaveAccessibleName("Paris climate talks"); // wrapped to the last
    expect(screen.getAllByRole("option").filter((o) => o.ariaSelected === "true")).toHaveLength(1);
  });

  it("Enter chooses the active option: a person tracks them, and the box empties", () => {
    answered(RESULTS);
    const { box, props } = setup();
    type(box, "paris");
    for (let i = 0; i < 3; i++) key(box, "ArrowDown");
    key(box, "Enter");
    expect(props.onEntity).toHaveBeenCalledWith({ name: "Paris Hilton", type: "person" });
    expect(box).toHaveValue("");
    expect(box).toHaveAttribute("aria-expanded", "false");
  });

  it("chooses an organisation, a thread or a place by click too", () => {
    answered(RESULTS);
    const { box, props } = setup();
    type(box, "paris");
    fireEvent.click(screen.getByRole("option", { name: "Paris Hilton, 2 stories this week" }));
    expect(props.onEntity).toHaveBeenCalledWith({ name: "Paris Hilton", type: "org" });
    type(box, "paris");
    fireEvent.click(screen.getByRole("option", { name: "Paris climate talks" }));
    expect(props.onThread).toHaveBeenCalledWith({ id: 7, title: "Paris climate talks" });
    type(box, "paris");
    fireEvent.click(screen.getByRole("option", { name: "Paris, France, 5 stories" }));
    expect(props.onPlace).toHaveBeenCalledWith(POINTS[0]);
  });

  it("Enter with no active option takes the first", () => {
    answered(RESULTS);
    const { box, props } = setup();
    type(box, "lond");
    key(box, "Enter");
    expect(props.onPlace).toHaveBeenCalledWith(POINTS[2]);
  });

  it("Escape closes the list, then clears the box, then leaves", () => {
    answered(RESULTS);
    const { box, props } = setup();
    type(box, "paris");
    key(box, "Escape");
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(box).toHaveValue("paris");
    key(box, "Escape");
    expect(box).toHaveValue("");
    expect(props.onDismiss).not.toHaveBeenCalled();
    key(box, "Escape");
    expect(props.onDismiss).toHaveBeenCalledTimes(1);
    // ArrowDown opens it again on what it holds.
    type(box, "paris");
    key(box, "Escape");
    key(box, "ArrowDown");
    expect(box).toHaveAttribute("aria-expanded", "true");
  });

  it("announces how many of each it found once they settle, and nothing while closed", () => {
    answered(RESULTS);
    const { box, props } = setup();
    type(box, "paris");
    expect(props.onAnnounce).toHaveBeenLastCalledWith(
      "2 places, 1 person, 2 organisations and 1 thread",
    );
    key(box, "Escape");
    expect(props.onAnnounce).toHaveBeenLastCalledWith("");
  });

  it("says when nothing matched, and when the server couldn't answer", () => {
    answered({ people: [], orgs: [], threads: [] });
    const { box, props } = setup();
    type(box, "zzz");
    expect(screen.getByText("No matches")).toBeInTheDocument();
    expect(props.onAnnounce).toHaveBeenLastCalledWith("No matches");
    answered(null, { error: true });
    type(box, "zzzz");
    expect(screen.getByText("Search unavailable right now")).toBeInTheDocument();
    expect(props.onAnnounce).toHaveBeenLastCalledWith("Search unavailable right now");
    // The places still found are said first.
    type(box, "paris");
    expect(props.onAnnounce).toHaveBeenLastCalledWith("2 places. Search unavailable right now");
  });

  it("says nothing more once it is gone (the sheet's search closes)", () => {
    answered(RESULTS);
    const onAnnounce = vi.fn();
    const { unmount } = render(
      <TrackSearch
        variant="sheet"
        points={POINTS}
        onPlace={vi.fn()}
        onEntity={vi.fn()}
        onThread={vi.fn()}
        onAnnounce={onAnnounce}
      />,
    );
    type(screen.getByRole("combobox"), "paris");
    expect(onAnnounce).toHaveBeenLastCalledWith("2 places, 1 person, 2 organisations and 1 thread");
    unmount();
    expect(onAnnounce).toHaveBeenLastCalledWith("");
  });

  it("in the sheet: no kbd hint, a close button, and it can take the focus as it opens", () => {
    const { props, box } = setup({ variant: "sheet", autoFocus: true });
    expect(screen.queryByText("/")).toBeNull();
    expect(box).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Close search" }));
    expect(props.onDismiss).toHaveBeenCalled();
  });
});
