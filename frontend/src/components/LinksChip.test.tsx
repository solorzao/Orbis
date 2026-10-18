import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import LinksChip from "./LinksChip";

describe("LinksChip", () => {
  it("is a small Links ✕ pill that turns Links off", () => {
    const onOff = vi.fn();
    render(<LinksChip status={null} onOff={onOff} />);
    const chip = screen.getByRole("button", { name: "Turn Links off" });
    expect(chip).toHaveAttribute("data-testid", "links-chip");
    expect(chip).toHaveClass("pill", "links-chip");
    expect(chip).toHaveTextContent(/^Links✕$/);
    fireEvent.click(chip);
    expect(onOff).toHaveBeenCalledTimes(1);
  });

  it("carries the Links status where the layers are hidden", () => {
    render(<LinksChip status="No links in this window" onOff={() => {}} />);
    expect(screen.getByRole("button", { name: "Turn Links off" })).toHaveTextContent(
      /^LinksNo links in this window✕$/,
    );
  });
});
