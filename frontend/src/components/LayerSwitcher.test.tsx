import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import LayerSwitcher, { LAYERS } from "./LayerSwitcher";

type Props = ComponentProps<typeof LayerSwitcher>;

function renderSwitcher(over: Partial<Props> = {}) {
  const props: Props = {
    layer: "dots",
    onChange: () => {},
    links: false,
    onLinksChange: () => {},
    rank: "lift",
    onRankChange: () => {},
    threads: false,
    onThreadsChange: () => {},
    ...over,
  };
  return render(<LayerSwitcher {...props} />);
}

describe("LayerSwitcher", () => {
  it("is a labelled group of the base layers, then the Links and Threads overlays after a divider", () => {
    renderSwitcher();
    const group = screen.getByRole("group", { name: "Globe layers" });
    expect(group).toHaveAttribute("data-testid", "layer-switcher");
    expect(group).toHaveClass("pillbar", "layers");
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Dots", "Intensity", "Links", "Threads", "Relations"]);
    expect(LAYERS.map((l) => l.id)).toEqual(["dots", "intensity"]);
    expect(group.querySelector(".sep")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Links" })).toHaveClass("tg");
    expect(screen.getByRole("button", { name: "Threads" })).toHaveClass("tg");
    expect(screen.getByRole("button", { name: "Relations" })).toHaveClass("tg");
  });

  it("toggles the Threads overlay; Links and Threads may both be on", () => {
    const onThreadsChange = vi.fn();
    const { rerender } = renderSwitcher({ links: true, onThreadsChange });
    const threads = screen.getByRole("button", { name: "Threads" });
    expect(threads).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(threads);
    expect(onThreadsChange).toHaveBeenCalledWith(true);

    rerender(
      <LayerSwitcher
        layer="dots"
        onChange={() => {}}
        links
        onLinksChange={() => {}}
        rank="lift"
        onRankChange={() => {}}
        threads
        onThreadsChange={onThreadsChange}
      />,
    );
    expect(screen.getByRole("button", { name: "Threads" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Links" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Threads" }));
    expect(onThreadsChange).toHaveBeenLastCalledWith(false);
  });

  it("marks only the active base layer as pressed", () => {
    const { rerender } = renderSwitcher();
    expect(screen.getByRole("button", { name: "Dots" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Intensity" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    rerender(
      <LayerSwitcher
        threads={false}
        onThreadsChange={() => {}}
        layer="intensity"
        onChange={() => {}}
        links={false}
        onLinksChange={() => {}}
        rank="lift"
        onRankChange={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Dots" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Intensity" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("calls onChange with the clicked layer", () => {
    const onChange = vi.fn();
    renderSwitcher({ onChange });
    fireEvent.click(screen.getByRole("button", { name: "Intensity" }));
    expect(onChange).toHaveBeenCalledWith("intensity");
    fireEvent.click(screen.getByRole("button", { name: "Dots" }));
    expect(onChange).toHaveBeenLastCalledWith("dots");
  });

  it("can mark a layer unavailable, saying why, and then ignores it", () => {
    const onChange = vi.fn();
    renderSwitcher({ onChange, unavailable: { intensity: "Intensity is off in low-power mode" } });
    const intensity = screen.getByRole("button", { name: "Intensity" });
    expect(intensity).toHaveAttribute("aria-disabled", "true");
    expect(intensity).toHaveAccessibleDescription("Intensity is off in low-power mode");
    expect(intensity).toHaveAttribute("title", "Intensity is off in low-power mode");
    fireEvent.click(intensity);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Dots" })).not.toHaveAttribute("aria-disabled");
  });

  it("toggles the Links overlay on either base layer, leaving the base layer alone", () => {
    const onChange = vi.fn();
    const onLinksChange = vi.fn();
    const { rerender } = renderSwitcher({ layer: "intensity", onChange, onLinksChange });
    const links = screen.getByRole("button", { name: "Links" });
    expect(links).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(links);
    expect(onLinksChange).toHaveBeenCalledWith(true);
    expect(onChange).not.toHaveBeenCalled();

    rerender(
      <LayerSwitcher
        threads={false}
        onThreadsChange={() => {}}
        layer="intensity"
        onChange={onChange}
        links
        onLinksChange={onLinksChange}
        rank="lift"
        onRankChange={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Links" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Intensity" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Links" }));
    expect(onLinksChange).toHaveBeenLastCalledWith(false);
  });

  it("shows the rank switch only while Links is on: Surprising (lift) or Most covered (count)", () => {
    const onRankChange = vi.fn();
    const { rerender } = renderSwitcher({ onRankChange });
    expect(screen.queryByRole("group", { name: "Rank links" })).toBeNull();

    rerender(
      <LayerSwitcher
        threads={false}
        onThreadsChange={() => {}}
        layer="dots"
        onChange={() => {}}
        links
        onLinksChange={() => {}}
        rank="lift"
        onRankChange={onRankChange}
      />,
    );
    const rank = screen.getByRole("group", { name: "Rank links" });
    expect(rank).toHaveAttribute("data-testid", "link-rank");
    expect(
      within(rank)
        .getAllByRole("button")
        .map((b) => [b.textContent, b.getAttribute("aria-pressed")]),
    ).toEqual([
      ["Surprising", "true"],
      ["Most covered", "false"],
    ]);
    // Outside the layers' pill, so the bottom row keeps its size.
    expect(screen.getByTestId("layer-switcher")).not.toContainElement(rank);

    fireEvent.click(within(rank).getByRole("button", { name: "Most covered" }));
    expect(onRankChange).toHaveBeenCalledWith("count");
    fireEvent.click(within(rank).getByRole("button", { name: "Surprising" }));
    expect(onRankChange).toHaveBeenLastCalledWith("lift");
  });

  it("shows the Links status beside its rank switch, only while Links is on", () => {
    const { rerender } = renderSwitcher({ links: true, linksStatus: "No links in this window" });
    const status = screen.getByTestId("links-status");
    expect(status).toHaveTextContent("No links in this window");
    expect(screen.getByTestId("layer-switcher")).not.toContainElement(status);

    rerender(
      <LayerSwitcher
        threads={false}
        onThreadsChange={() => {}}
        layer="dots"
        onChange={() => {}}
        links
        onLinksChange={() => {}}
        rank="lift"
        onRankChange={() => {}}
        linksStatus={null}
      />,
    );
    expect(screen.queryByTestId("links-status")).toBeNull();

    rerender(
      <LayerSwitcher
        threads={false}
        onThreadsChange={() => {}}
        layer="dots"
        onChange={() => {}}
        links={false}
        onLinksChange={() => {}}
        rank="lift"
        onRankChange={() => {}}
        linksStatus="Links unavailable right now"
      />,
    );
    expect(screen.queryByTestId("links-status")).toBeNull();
  });
});

describe("LayerSwitcher's Relations overlay (the 7-day lens)", () => {
  const LENS = { firstDay: "2026-10-15", lastDay: "2026-10-21", since: "2026-10-15" };
  const toggle = () => screen.getByRole("button", { name: "Relations" });

  it("toggles Relations after Threads, saying what it shows", () => {
    const onRelationsChange = vi.fn();
    const { rerender } = renderSwitcher({ onRelationsChange });
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
    expect(toggle()).toHaveAttribute(
      "title",
      "Reported events between countries over the last 7 days (GDELT)",
    );
    fireEvent.click(toggle());
    expect(onRelationsChange).toHaveBeenCalledWith(true);

    rerender(
      <LayerSwitcher
        layer="dots"
        onChange={() => {}}
        links={false}
        onLinksChange={() => {}}
        rank="lift"
        onRankChange={() => {}}
        threads={false}
        onThreadsChange={() => {}}
        relations
        onRelationsChange={onRelationsChange}
      />,
    );
    expect(toggle()).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(toggle());
    expect(onRelationsChange).toHaveBeenLastCalledWith(false);
  });

  it("shows the class switch and the legend only while Relations is on and available", () => {
    const { rerender } = renderSwitcher({ relationLens: LENS });
    expect(screen.queryByRole("group", { name: "Show relations" })).toBeNull();
    expect(screen.queryByTestId("relations-legend")).toBeNull();

    rerender(
      <LayerSwitcher
        layer="dots"
        onChange={() => {}}
        links={false}
        onLinksChange={() => {}}
        rank="lift"
        onRankChange={() => {}}
        threads={false}
        onThreadsChange={() => {}}
        relations
        relationLens={LENS}
      />,
    );
    const kind = screen.getByRole("group", { name: "Show relations" });
    expect(kind).toHaveAttribute("data-testid", "relation-kind");
    expect(
      within(kind)
        .getAllByRole("button")
        .map((b) => [b.textContent, b.getAttribute("aria-pressed")]),
    ).toEqual([
      ["All", "true"],
      ["Cooperation", "false"],
      ["Conflict", "false"],
    ]);
    // Outside the layers' pill, so the bottom row keeps its size.
    expect(screen.getByTestId("layer-switcher")).not.toContainElement(kind);
    const legend = screen.getByTestId("relations-legend");
    expect(legend).toHaveTextContent("Relations · last 7 days · 15–21 Oct (UTC days)");
    expect(legend).toHaveTextContent(
      "Reported events from news, machine-coded by GDELT. Not verified.",
    );
    expect(legend).toHaveTextContent("Topic filters don't apply to relations.");
    // The class in words beside each swatch: colour never carries it alone.
    expect(within(legend).getByText("Cooperation")).toBeInTheDocument();
    expect(within(legend).getByText("Conflict")).toBeInTheDocument();
  });

  it("says since when, during the first week's ramp", () => {
    renderSwitcher({ relations: true, relationLens: { ...LENS, since: "2026-10-19" } });
    expect(screen.getByTestId("relations-legend")).toHaveTextContent(
      "Relations · since 19 Oct (UTC)",
    );
  });

  it("names the last 7 days while the lens loads", () => {
    renderSwitcher({ relations: true, relationLens: null });
    expect(screen.getByTestId("relations-legend")).toHaveTextContent(/^Relations · last 7 days/);
  });

  it("switches the class shown", () => {
    const onRelationKindChange = vi.fn();
    renderSwitcher({ relations: true, relationLens: LENS, onRelationKindChange });
    const kind = screen.getByRole("group", { name: "Show relations" });
    fireEvent.click(within(kind).getByRole("button", { name: "Conflict" }));
    expect(onRelationKindChange).toHaveBeenCalledWith("conflict");
  });

  it("says why it draws nothing, beside the legend", () => {
    renderSwitcher({
      relations: true,
      relationLens: LENS,
      relationsStatus: "No reported events between countries in the last 7 days",
    });
    const status = screen.getByTestId("relations-status");
    expect(status).toHaveTextContent("No reported events between countries in the last 7 days");
    expect(screen.getByTestId("layer-switcher")).not.toContainElement(status);
  });

  it("is unavailable under a range or a replay: described, pressed state kept, inert", () => {
    const onRelationsChange = vi.fn();
    const note = "Relations cover the last 7 days: not available for a range or replay";
    renderSwitcher({
      relations: true,
      onRelationsChange,
      relationLens: LENS,
      relationsStatus: "Relations couldn't load",
      relationsUnavailable: note,
    });
    expect(toggle()).toHaveAttribute("aria-disabled", "true");
    expect(toggle()).toHaveAttribute("aria-pressed", "true");
    expect(toggle()).toHaveAccessibleDescription(note);
    fireEvent.click(toggle());
    expect(onRelationsChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("relation-kind")).toBeNull();
    expect(screen.queryByTestId("relations-legend")).toBeNull();
    expect(screen.queryByTestId("relations-status")).toBeNull();
  });
});
