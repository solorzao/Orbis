import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import EntityPills from "./EntityPills";

const ENTITIES = [
  { name: "Suez Canal Authority", n: 9 },
  { name: "Houthis", n: 7 },
];

describe("EntityPills", () => {
  it("lists the entities as inert pills while nothing tracks them", () => {
    render(<EntityPills entities={ENTITIES} />);
    const list = screen.getByRole("list", { name: "Key entities" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((e) => e.textContent),
    ).toEqual(["Suez Canal Authority", "Houthis"]);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("makes each a button once given onTrack", () => {
    const onTrack = vi.fn();
    render(<EntityPills entities={ENTITIES} onTrack={onTrack} />);
    fireEvent.click(screen.getByRole("button", { name: "Track Houthis" }));
    expect(onTrack).toHaveBeenCalledWith("Houthis");
  });

  it("renders nothing without entities", () => {
    const { container } = render(<EntityPills entities={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
