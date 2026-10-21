import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import RecentPlaces from "./RecentPlaces";
import type { LinkEntry, PanelEntry, RelationEntry } from "@/types/news";
import { MAX_PANELS } from "@/lib/panelQuery";
import { toRelation } from "@/lib/relations";
import type { ApiRelation } from "@/lib/api";
import contract from "../../e2e/relations.contract.json";

function relationEntry(relationId: string, createdAt: number): RelationEntry {
  return {
    relationId,
    relation: toRelation(contract.list.relations[0] as ApiRelation), // IR–US, from US: 312
    filter: "all",
    lens: null,
    detail: null,
    detailLoading: true,
    createdAt,
  };
}

describe("RecentPlaces with relations", () => {
  it("holds relations beside places and links, named as reported events", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <RecentPlaces
        places={[]}
        links={[]}
        relations={[relationEntry("r1", 1)]}
        activeId="r1"
        onSelect={onSelect}
        onClose={onClose}
      />,
    );
    const pick = screen.getByRole("button", { pressed: true });
    expect(pick).toHaveTextContent("US ↔ IR · events312");
    expect(pick).toHaveAccessibleName(
      "US ↔ IR · events: United States and Iran, 312 reported events",
    );
    fireEvent.click(pick);
    expect(onSelect).toHaveBeenCalledWith("r1");
    fireEvent.click(
      screen.getByRole("button", { name: "Close United States and Iran reported events" }),
    );
    expect(onClose).toHaveBeenCalledWith("r1");
  });

  it("keeps MAX_PANELS across places, links and relations, the newest", () => {
    const places = [{ ...entry("a", "Paris, France", 5), createdAt: 0 }];
    const links = [linkEntry("l1", 1), linkEntry("l2", 2)];
    const relations = [relationEntry("r3", 3), relationEntry("r4", 4), relationEntry("r5", 5)];
    render(
      <RecentPlaces
        places={places}
        links={links}
        relations={relations}
        activeId={null}
        onSelect={() => {}}
        onClose={() => {}}
      />,
    );
    const picks = screen.getAllByRole("button").filter((b) => b.hasAttribute("aria-pressed"));
    expect(picks.map((b) => b.getAttribute("data-place"))).toEqual(["l1", "l2", "r3", "r4", "r5"]);
  });
});

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

const US = { iso: "US", name: "United States", lat: 39.5, lng: -99.06 };
const IR = { iso: "IR", name: "Iran", lat: 32.52, lng: 54.29 };

function linkEntry(linkId: string, createdAt: number, from = "US"): LinkEntry {
  return {
    linkId,
    link: { a: IR, b: US, n: 41, lift: 1.8, topic: "Politics", tone: -0.3, from },
    query: { startTime: "2026-10-10T00:00:00Z", endTime: "2026-10-11T00:00:00Z", live: true },
    detail: null,
    detailLoading: true,
    explanation: null,
    explaining: false,
    createdAt,
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
    const group = screen.getByRole("group", { name: "Recent places and links" });
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

  it("shows at most the MAX_PANELS (5) newest places", () => {
    expect(MAX_PANELS).toBe(5);
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

  it("holds links too, in the order they were opened, named by their codes from the origin", () => {
    const places = [{ ...entry("a", "Paris, France", 5), createdAt: 1 }];
    const links = [linkEntry("l1", 2), linkEntry("l0", 0, "IR")];
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <RecentPlaces
        places={places}
        links={links}
        activeId="l1"
        onSelect={onSelect}
        onClose={onClose}
      />,
    );
    const picks = screen.getAllByRole("button").filter((b) => b.hasAttribute("aria-pressed"));
    expect(picks.map((b) => b.textContent)).toEqual(["IR ↔ US41", "Paris5", "US ↔ IR41"]);
    expect(picks.map((b) => b.getAttribute("data-place"))).toEqual(["l0", "a", "l1"]);
    expect(picks[2]).toHaveAttribute("aria-pressed", "true");
    expect(picks[2]).toHaveAttribute("title", "United States and Iran");
    // Its visible codes first (label in name, WCAG 2.5.3), then the names in full.
    expect(picks[2]).toHaveAccessibleName("US ↔ IR: United States and Iran, 41 stories");

    fireEvent.click(picks[2]);
    expect(onSelect).toHaveBeenCalledWith("l1");
    fireEvent.click(screen.getByRole("button", { name: "Close United States and Iran" }));
    expect(onClose).toHaveBeenCalledWith("l1");
  });

  it("shows at most MAX_PANELS places and links together, the newest", () => {
    const places = ["a", "b", "c"].map((id, i) => ({
      ...entry(id, `Place ${id}, X`),
      createdAt: i,
    }));
    const links = [linkEntry("l3", 3), linkEntry("l4", 4), linkEntry("l5", 5)];
    render(
      <RecentPlaces
        places={places}
        links={links}
        activeId={null}
        onSelect={() => {}}
        onClose={() => {}}
      />,
    );
    const picks = screen.getAllByRole("button").filter((b) => b.hasAttribute("aria-pressed"));
    expect(picks.map((b) => b.getAttribute("data-place"))).toEqual(["b", "c", "l3", "l4", "l5"]);
  });

  it("renders nothing without places", () => {
    const { container } = render(
      <RecentPlaces places={[]} activeId={null} onSelect={() => {}} onClose={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("puts the tracked entity first: pick it to see its dossier, × to stop tracking", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <RecentPlaces
        places={[PLACES[0]]}
        entity={{ id: "entity", name: "Emmanuel Macron" }}
        activeId="entity"
        onSelect={onSelect}
        onClose={onClose}
      />,
    );
    const group = screen.getByRole("group", { name: "Recent places and links" });
    const picks = within(group)
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("aria-pressed"));
    expect(picks[0]).toHaveAccessibleName("Tracking Emmanuel Macron");
    expect(picks[0]).toHaveAttribute("aria-pressed", "true");
    expect(picks[0]).toHaveAttribute("data-place", "entity");
    fireEvent.click(picks[0]);
    expect(onSelect).toHaveBeenCalledWith("entity");
    fireEvent.click(screen.getByRole("button", { name: "Stop tracking Emmanuel Macron" }));
    expect(onClose).toHaveBeenCalledWith("entity");
  });

  it("shows the tracked entity even with nothing else open", () => {
    render(
      <RecentPlaces
        places={[]}
        entity={{ id: "entity", name: "IAEA" }}
        activeId={null}
        onSelect={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Tracking IAEA" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
