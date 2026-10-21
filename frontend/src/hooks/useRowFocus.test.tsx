import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { useRowFocus } from "./useRowFocus";

/** A list of rows keyed by data-row, as LinkList and RelationList render theirs. */
function Rows({ keys }: { keys: string[] }) {
  const { boxRef, onFocus, onBlur } = useRowFocus(keys, "data-row");
  return (
    <div ref={boxRef} tabIndex={-1} data-testid="box" onFocus={onFocus} onBlur={onBlur}>
      {keys.map((k) => (
        <button key={k} type="button" data-row={k}>
          {k}
        </button>
      ))}
    </div>
  );
}

const row = (name: string) => screen.getByRole("button", { name });

describe("useRowFocus: a list's focus while its rows change", () => {
  it("stays on a focused row that is still listed", () => {
    const { rerender } = render(<Rows keys={["RU-UA", "IR-US"]} />);
    row("IR-US").focus();
    rerender(<Rows keys={["IR-US", "SA-YE"]} />);
    expect(row("IR-US")).toHaveFocus();
  });

  it("moves to the first row when the focused row drops out", () => {
    const { rerender } = render(<Rows keys={["RU-UA", "IR-US"]} />);
    row("IR-US").focus();
    rerender(<Rows keys={["SA-YE", "RU-UA"]} />);
    expect(row("SA-YE")).toHaveFocus();
  });

  it("moves to the list itself when no rows are left", () => {
    const { rerender } = render(<Rows keys={["RU-UA", "IR-US"]} />);
    row("IR-US").focus();
    rerender(<Rows keys={[]} />);
    expect(screen.getByTestId("box")).toHaveFocus();
  });

  it("leaves the focus alone when it is outside the list", () => {
    const elsewhere = document.createElement("button");
    document.body.appendChild(elsewhere);
    const { rerender } = render(<Rows keys={["RU-UA", "IR-US"]} />);
    elsewhere.focus();
    rerender(<Rows keys={["SA-YE"]} />);
    expect(elsewhere).toHaveFocus();
    elsewhere.remove();
  });
});
