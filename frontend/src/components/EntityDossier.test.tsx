import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import EntityDossier from "./EntityDossier";
import { PinContext } from "./PinButton";
import type { EntityDossier as Dossier, EntityRef } from "@/lib/entities";

const NOW = Date.parse("2026-10-20T12:00:00Z");

function dossier(over: Partial<Dossier> = {}): Dossier {
  return {
    name: "Emmanuel Macron",
    type: "person",
    h24: 12,
    d7: 1406,
    trend: 1.5,
    capped: false,
    cap: 2000,
    countries: 9,
    places: [
      { lat: 48.85, lng: 2.35, place: "Paris, France", countryCode: "FR", n: 60, tone: -0.42 },
      { lat: 52.52, lng: 13.4, place: "Berlin, Germany", countryCode: "DE", n: 15, tone: 0.3 },
    ],
    timeline: [3, 5, 8, 2, 9, 12, 7].map((n, i) => ({
      t: new Date(NOW - (7 - i) * 86_400_000).toISOString(),
      n,
    })),
    coMentions: [
      { name: "European Union", n: 30, types: ["org"] },
      { name: "Olaf Scholz", n: 12, types: ["person"] },
      { name: "Red Sea", n: 5, types: [] },
    ],
    headlines: [
      {
        title: "Macron meets Scholz in Berlin",
        sourceName: "Reuters",
        publishedAt: new Date(NOW - 30 * 60_000).toISOString(),
        sourceUrl: "https://example.com/a",
        place: "Berlin, Germany",
      },
      {
        title: "A story with no usable link",
        sourceName: "Mystery",
        publishedAt: new Date(NOW - 90 * 60_000).toISOString(),
        sourceUrl: "",
        place: "Paris, France",
      },
    ],
    since: "2026-10-01T00:00:00Z",
    ...over,
  };
}

const ENTITY: EntityRef = { name: "Emmanuel Macron", type: "person" };

// The dossier tells ages and the ramp from the time now (the page's minute clock).
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

function setup(over: Partial<Parameters<typeof EntityDossier>[0]> = {}) {
  const props = {
    entity: ENTITY,
    dossier: dossier(),
    loading: false,
    notFound: false,
    error: false,
    onPivot: vi.fn(),
    onPlace: vi.fn(),
    onStop: vi.fn(),
    onMinimize: vi.fn(),
    ...over,
  };
  const view = render(<EntityDossier {...props} />);
  return { props, ...view };
}

describe("EntityDossier", () => {
  it("names the entity, its type and how many countries cover it", () => {
    setup();
    const panel = screen.getByTestId("entity-dossier");
    expect(within(panel).getByText("Tracking an entity")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Emmanuel Macron" })).toBeInTheDocument();
    expect(screen.getByText("Person. Appears in coverage in 9 countries.")).toBeInTheDocument();
  });

  it("calls an organisation one, and one country one", () => {
    setup({ dossier: dossier({ type: "org", countries: 1 }) });
    expect(screen.getByText("Organisation. Appears in coverage in 1 country.")).toBeInTheDocument();
  });

  it("reads out the last 24 hours, the week and the trend", () => {
    setup();
    expect(screen.getByRole("group", { name: "24 h" })).toHaveTextContent("12");
    expect(screen.getByRole("group", { name: "7 days" })).toHaveTextContent("1,406");
    expect(screen.getByRole("group", { name: "Trend" })).toHaveTextContent("1.5×");
    expect(screen.getByText("last 7 days")).toBeInTheDocument(); // the timeline
  });

  it("says since when, while tracking holds less than a week", () => {
    setup({ dossier: dossier({ since: "2026-10-18T06:00:00Z" }) });
    expect(screen.getByRole("group", { name: "Since 18 Oct" })).toHaveTextContent("1,406");
    expect(screen.queryByRole("group", { name: "7 days" })).toBeNull();
    // The readout's label, and the timeline's.
    expect(screen.getAllByText("since 18 Oct")).toHaveLength(2);
    expect(screen.queryByText("last 7 days")).toBeNull();
  });

  it("notes the cap only when the window had more mentions than it read", () => {
    setup();
    expect(screen.queryByText("Based on the latest 2,000 mentions.")).toBeNull();
    setup({ dossier: dossier({ capped: true }) });
    expect(screen.getByText("Based on the latest 2,000 mentions.")).toBeInTheDocument();
  });

  it("draws the names in the same coverage; a trackable one pivots by click or Enter", () => {
    const { props } = setup();
    const graph = screen.getByRole("group", { name: "Appears in the same coverage as" });
    const eu = within(graph).getByRole("button", { name: "Track European Union" });
    fireEvent.click(eu);
    expect(props.onPivot).toHaveBeenCalledWith({ name: "European Union", type: "org" });
    fireEvent.keyDown(within(graph).getByRole("button", { name: "Track Olaf Scholz" }), {
      key: "Enter",
    });
    expect(props.onPivot).toHaveBeenLastCalledWith({ name: "Olaf Scholz", type: "person" });
    // A name the graph can't type is drawn, but can't be tracked.
    expect(within(graph).queryByRole("button", { name: /Red Sea/ })).toBeNull();
    expect(within(graph).getByText("Red Sea")).toBeInTheDocument();
  });

  it("lists the top places with their tone; a place opens", () => {
    const { props } = setup();
    const places = screen.getByRole("group", { name: "Top places" });
    fireEvent.click(within(places).getByRole("button", { name: "Paris, France" }));
    expect(props.onPlace).toHaveBeenCalledWith(dossier().places[0]);
    expect(within(places).getByText("−0.42")).toBeInTheDocument(); // formatScore's minus
  });

  it("links the latest headlines only to web pages", () => {
    setup();
    const list = screen.getByRole("list", { name: "Latest headlines" });
    expect(
      within(list).getByRole("link", { name: "Macron meets Scholz in Berlin" }),
    ).toHaveAttribute("href", "https://example.com/a");
    expect(within(list).queryByRole("link", { name: "A story with no usable link" })).toBeNull();
    expect(within(list).getByText("A story with no usable link")).toBeInTheDocument();
    expect(within(list).getByText("30 min ago")).toBeInTheDocument();
  });

  it("keeps the headlines' ages current as time passes", () => {
    setup();
    const list = screen.getByRole("list", { name: "Latest headlines" });
    expect(within(list).getByText("30 min ago")).toBeInTheDocument();
    act(() => {
      vi.setSystemTime(NOW + 5 * 60_000);
      vi.advanceTimersByTime(30_000);
    });
    expect(within(list).getByText("35 min ago")).toBeInTheDocument();
  });

  it("stops tracking by its button or Escape", () => {
    const { props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Stop tracking" }));
    expect(props.onStop).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByRole("heading", { name: "Emmanuel Macron" }), { key: "Escape" });
    expect(props.onStop).toHaveBeenCalledTimes(2);
  });

  it("minimizes, keeping the tracking", () => {
    const { props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Minimize panel" }));
    expect(props.onMinimize).toHaveBeenCalled();
    expect(props.onStop).not.toHaveBeenCalled();
  });

  it("says when no person or organisation has the name, and can still stop", () => {
    const { props } = setup({ dossier: null, notFound: true, entity: { name: "Nobody" } });
    expect(screen.getByRole("heading", { name: "Nobody" })).toBeInTheDocument();
    expect(
      screen.getByText("No person or organisation of that name is in this week's coverage."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop tracking" }));
    expect(props.onStop).toHaveBeenCalled();
  });

  it("shows it is loading, and when it failed", () => {
    const { unmount } = setup({ dossier: null, loading: true });
    expect(screen.getByTestId("entity-dossier")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Fetching coverage…")).toBeInTheDocument();
    unmount();
    setup({ dossier: null, error: true });
    expect(screen.getByText("Couldn't load this dossier.")).toBeInTheDocument();
  });

  it("never says linked", () => {
    const { container } = setup({ dossier: dossier({ capped: true }) });
    expect(container.textContent).not.toMatch(/linked/i);
  });
});

describe("EntityDossier pin", () => {
  function renderPinned(over: Partial<Parameters<typeof EntityDossier>[0]>) {
    const toggle = vi.fn();
    render(
      <PinContext.Provider value={{ has: () => false, full: false, toggle }}>
        <EntityDossier
          entity={{ name: "emmanuel macron" }}
          dossier={dossier()}
          loading={false}
          notFound={false}
          error={false}
          onPivot={vi.fn()}
          onPlace={vi.fn()}
          onStop={vi.fn()}
          onMinimize={vi.fn()}
          {...over}
        />
      </PinContext.Provider>,
    );
    return toggle;
  }

  it("pins the person or organisation by the dossier's name", () => {
    const toggle = renderPinned({});
    fireEvent.click(screen.getByRole("button", { name: "Pin to board" }));
    expect(toggle).toHaveBeenCalledWith(
      "entity:person:Emmanuel Macron",
      expect.objectContaining({ title: "Emmanuel Macron", place: "Paris, France" }),
    );
  });

  it("has nothing to pin until the dossier lands", () => {
    renderPinned({ dossier: null, loading: true });
    expect(screen.queryByRole("button", { name: "Pin to board" })).toBeNull();
  });
});
