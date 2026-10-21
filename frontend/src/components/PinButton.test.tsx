import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import PinButton, { PinContext, type PinControls } from "./PinButton";
import type { PinSnapshot } from "@/lib/board";

const SNAP: PinSnapshot = {
  title: "Paris, France",
  place: "Paris, France",
  lat: 48.5,
  lng: 2.5,
  time: null,
  url: null,
};

function setup(
  controls: Partial<PinControls>,
  props: Partial<Parameters<typeof PinButton>[0]> = {},
) {
  const value: PinControls = { has: () => false, full: false, toggle: vi.fn(), ...controls };
  render(
    <PinContext.Provider value={value}>
      <PinButton item="place:48:2" snapshot={() => SNAP} {...props} />
    </PinContext.Provider>,
  );
  return value;
}

describe("PinButton", () => {
  it("shows nothing without a board, or without an id to pin", () => {
    const { container } = render(<PinButton item="place:48:2" snapshot={() => SNAP} />);
    expect(container).toBeEmptyDOMElement();
    setup({}, { item: null });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("pins to the board", () => {
    const controls = setup({});
    const button = screen.getByRole("button", { name: "Pin to board" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    expect(controls.toggle).toHaveBeenCalledWith("place:48:2", SNAP);
  });

  it("is pressed and says Pinned when the item is in; pressing it again unpins", () => {
    const controls = setup({ has: (item) => item === "place:48:2" });
    const button = screen.getByRole("button", { name: "Pinned" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(button);
    expect(controls.toggle).toHaveBeenCalledWith("place:48:2", SNAP);
  });

  it("is disabled with a note when the board is full", () => {
    const controls = setup({ full: true });
    const button = screen.getByRole("button", { name: "Board full" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(
      "The board holds 20 pins. Remove one to pin another.",
    );
    fireEvent.click(button);
    expect(controls.toggle).not.toHaveBeenCalled();
  });

  it("a pinned item can still be unpinned on a full board", () => {
    setup({ full: true, has: () => true });
    expect(screen.getByRole("button", { name: "Pinned" })).not.toHaveAttribute("aria-disabled");
  });

  it("compact, it is an icon named for what it pins", () => {
    setup({}, { compact: true, label: "France announces new climate policy" });
    const button = screen.getByRole("button", {
      name: "Pin to board: France announces new climate policy",
    });
    expect(button).toHaveAttribute("title", "Pin to board");
  });
});
