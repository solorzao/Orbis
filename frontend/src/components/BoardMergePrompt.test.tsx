import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import BoardMergePrompt from "./BoardMergePrompt";

function setup(over: Partial<Parameters<typeof BoardMergePrompt>[0]> = {}) {
  const props = { shared: 3, fresh: 3, fit: 3, onAdd: vi.fn(), onKeep: vi.fn(), ...over };
  render(<BoardMergePrompt {...props} />);
  return props;
}

describe("BoardMergePrompt", () => {
  it("asks, as a modal dialog, before adding shared pins to a board that has some", () => {
    setup();
    const dialog = screen.getByRole("dialog", { name: "Add the shared pins to your board?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription(
      "This link shares 3 pins. 3 aren't on your board yet.",
    );
    expect(screen.getByRole("button", { name: "Add to my board" })).toHaveFocus();
  });

  it("adds them, or keeps the board as it is (Escape too)", () => {
    const props = setup();
    fireEvent.click(screen.getByRole("button", { name: "Add to my board" }));
    expect(props.onAdd).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep my board" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(props.onKeep).toHaveBeenCalledTimes(2);
  });

  it("keeps the focus inside while it is open", () => {
    setup();
    const add = screen.getByRole("button", { name: "Add to my board" });
    const keep = screen.getByRole("button", { name: "Keep my board" });
    keep.focus();
    fireEvent.keyDown(keep, { key: "Tab" });
    expect(add).toHaveFocus();
    fireEvent.keyDown(add, { key: "Tab", shiftKey: true });
    expect(keep).toHaveFocus();
  });

  it("says how many fit when the board can't take them all", () => {
    setup({ shared: 5, fresh: 4, fit: 2 });
    expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
      "This link shares 5 pins. 4 aren't on your board yet; 2 fit, as a board holds 20.",
    );
  });

  it("offers only to keep the board when none fit", () => {
    setup({ shared: 2, fresh: 2, fit: 0 });
    expect(screen.queryByRole("button", { name: "Add to my board" })).toBeNull();
    expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
      "This link shares 2 pins. Your board is full (20 pins), so none fit.",
    );
    expect(screen.getByRole("button", { name: "Keep my board" })).toHaveFocus();
  });
});
