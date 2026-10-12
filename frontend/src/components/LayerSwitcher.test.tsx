import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import LayerSwitcher, { LAYERS } from "./LayerSwitcher";

describe("LayerSwitcher", () => {
  it("is a labelled group of the working layers: Dots and Intensity", () => {
    render(<LayerSwitcher layer="dots" onChange={() => {}} />);
    const group = screen.getByRole("group", { name: "Globe layers" });
    expect(group).toHaveAttribute("data-testid", "layer-switcher");
    expect(group).toHaveClass("pillbar", "layers");
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Dots", "Intensity"]);
    expect(LAYERS.map((l) => l.id)).toEqual(["dots", "intensity"]);
  });

  it("marks only the active layer as pressed", () => {
    const { rerender } = render(<LayerSwitcher layer="dots" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Dots" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Intensity" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    rerender(<LayerSwitcher layer="intensity" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Dots" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Intensity" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("calls onChange with the clicked layer", () => {
    const onChange = vi.fn();
    render(<LayerSwitcher layer="dots" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Intensity" }));
    expect(onChange).toHaveBeenCalledWith("intensity");
    fireEvent.click(screen.getByRole("button", { name: "Dots" }));
    expect(onChange).toHaveBeenLastCalledWith("dots");
  });

  it("can mark a layer unavailable, saying why, and then ignores it", () => {
    const onChange = vi.fn();
    render(
      <LayerSwitcher
        layer="dots"
        onChange={onChange}
        unavailable={{ intensity: "Intensity is off in low-power mode" }}
      />,
    );
    const intensity = screen.getByRole("button", { name: "Intensity" });
    expect(intensity).toHaveAttribute("aria-disabled", "true");
    expect(intensity).toHaveAccessibleDescription("Intensity is off in low-power mode");
    expect(intensity).toHaveAttribute("title", "Intensity is off in low-power mode");
    fireEvent.click(intensity);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Dots" })).not.toHaveAttribute("aria-disabled");
  });
});
