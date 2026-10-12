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
    ...over,
  };
  return render(<LayerSwitcher {...props} />);
}

describe("LayerSwitcher", () => {
  it("is a labelled group of the base layers, then the Links overlay after a divider", () => {
    renderSwitcher();
    const group = screen.getByRole("group", { name: "Globe layers" });
    expect(group).toHaveAttribute("data-testid", "layer-switcher");
    expect(group).toHaveClass("pillbar", "layers");
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Dots", "Intensity", "Links"]);
    expect(LAYERS.map((l) => l.id)).toEqual(["dots", "intensity"]);
    expect(group.querySelector(".sep")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Links" })).toHaveClass("tg");
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
});
