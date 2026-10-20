import { describe, it, expect } from "vitest";
import { useRef, useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { useKeepFocus } from "./useKeepFocus";

/** Places as pills, each with a × that closes it; "a" can also be minimized. */
function Harness({ initial = ["a", "b"], active = "a" }: { initial?: string[]; active?: string }) {
  const regionRef = useRef<HTMLDivElement>(null);
  const keepFocus = useKeepFocus(regionRef);
  const [places, setPlaces] = useState(initial);
  const [open, setOpen] = useState<string | null>(active);
  return (
    <>
      <button type="button">Outside</button>
      <div ref={regionRef} tabIndex={-1} data-testid="region">
        {places.map((id) => (
          <span key={id}>
            <button type="button" data-place={id}>
              Place {id}
            </button>
            <button
              type="button"
              onClick={() => {
                keepFocus(id === open ? null : open);
                setPlaces((p) => p.filter((x) => x !== id));
                if (id === open) setOpen(null);
              }}
            >
              Close {id}
            </button>
          </span>
        ))}
        {open && (
          <button
            type="button"
            onClick={() => {
              keepFocus(open);
              setOpen(null);
            }}
          >
            Minimize {open}
          </button>
        )}
      </div>
    </>
  );
}

function press(name: string) {
  const button = screen.getByRole("button", { name });
  button.focus();
  fireEvent.click(button);
}

describe("useKeepFocus", () => {
  it("moves focus to the place's pill when the focused control goes", () => {
    render(<Harness />);
    press("Minimize a");
    expect(screen.getByRole("button", { name: "Place a" })).toHaveFocus();
  });

  it("moves focus to the remaining active place's pill", () => {
    render(<Harness />);
    press("Close b");
    expect(screen.getByRole("button", { name: "Place a" })).toHaveFocus();
  });

  it("falls back to the region when no pill is left to take it", () => {
    render(<Harness />);
    press("Close a");
    expect(screen.getByTestId("region")).toHaveFocus();
  });

  it("leaves focus alone when it was outside the region", () => {
    render(<Harness />);
    screen.getByRole("button", { name: "Outside" }).focus();
    fireEvent.click(screen.getByRole("button", { name: "Close b" }));
    expect(screen.getByRole("button", { name: "Outside" })).toHaveFocus();
  });

  it("leaves focus alone when the focused control survives", () => {
    render(<Harness />);
    const pill = screen.getByRole("button", { name: "Place b" });
    pill.focus();
    fireEvent.click(screen.getByRole("button", { name: "Close a" })); // clicked without focus
    expect(pill).toHaveFocus();
  });

  it("leaves focus alone when it moved outside the region before the change rendered", () => {
    // A handler that removes the focused control and sends focus elsewhere itself.
    function JumpOut() {
      const regionRef = useRef<HTMLDivElement>(null);
      const outsideRef = useRef<HTMLButtonElement>(null);
      const keepFocus = useKeepFocus(regionRef);
      const [shown, setShown] = useState(true);
      return (
        <>
          <button type="button" ref={outsideRef}>
            Elsewhere
          </button>
          <div ref={regionRef} tabIndex={-1} data-testid="region">
            {shown && (
              <button
                type="button"
                onClick={() => {
                  keepFocus(null);
                  setShown(false);
                  outsideRef.current?.focus();
                }}
              >
                Go
              </button>
            )}
          </div>
        </>
      );
    }
    render(<JumpOut />);
    press("Go");
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });

  it("catches focus a change takes from another region (a tab the change hides)", () => {
    function Tabs() {
      const regionRef = useRef<HTMLDivElement>(null);
      const sourceRef = useRef<HTMLDivElement>(null);
      const keepFocus = useKeepFocus(regionRef, sourceRef);
      const [tab, setTab] = useState<"threads" | "inspect">("threads");
      return (
        <>
          <div ref={sourceRef} hidden={tab !== "threads"}>
            <button
              type="button"
              onClick={() => {
                keepFocus(null);
                setTab("inspect");
              }}
            >
              All stories
            </button>
          </div>
          <div ref={regionRef} tabIndex={-1} hidden={tab !== "inspect"} data-testid="inspect">
            Stories
          </div>
        </>
      );
    }
    render(<Tabs />);
    const button = screen.getByRole("button", { name: "All stories" });
    button.focus();
    fireEvent.click(button);
    // Still on the button, but in a hidden tab: lost all the same.
    expect(screen.getByTestId("inspect")).toHaveFocus();
  });
});
