import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import ArcLabels from "./ArcLabels";
import { arcApex } from "@/lib/links";
import type { Relation } from "@/lib/relations";

const US = { iso: "US", name: "United States", lat: 39.5, lng: -99.06 };

function rel(i: number, kind: Relation["kind"] = "conflict"): Relation {
  return {
    a: { iso: `X${i}`, name: `Country ${i}`, lat: 10 + i, lng: 20 + i },
    b: US,
    n: 10 * (i + 1),
    outlets: 3,
    mentions: 100 * (i + 1),
    quad: {
      verbal_cooperation: kind === "cooperation" ? 10 * (i + 1) : 0,
      material_cooperation: 0,
      verbal_conflict: kind === "conflict" ? 10 * (i + 1) : 0,
      material_conflict: 0,
    },
    kind,
    goldstein: -1,
    tone: -1,
    from: "US",
  };
}

const SEVEN = Array.from({ length: 7 }, (_, i) => rel(i, i % 2 ? "cooperation" : "conflict"));

let frames: Map<number, FrameRequestCallback>;
let nextId: number;

beforeEach(() => {
  frames = new Map();
  nextId = 1;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    frames.set(nextId, cb);
    return nextId++;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
    frames.delete(id);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function runFrame() {
  const pending = [...frames.values()];
  frames.clear();
  act(() => pending.forEach((cb) => cb(1000)));
}

const tags = () => [...document.querySelectorAll(".arc-tag")].map((t) => t.textContent);

describe("ArcLabels (decision 6: the 5 strongest arcs labelled)", () => {
  it("labels the 5 strongest of 7, the class in words, from the acting country", () => {
    render(
      <ArcLabels relations={SEVEN} muted={false} yieldTo={null} project={() => ({ x: 1, y: 2 })} />,
    );
    expect(tags()).toEqual([
      "US–X6 · 70 · conflict",
      "US–X5 · 60 · cooperation",
      "US–X4 · 50 · conflict",
      "US–X3 · 40 · cooperation",
      "US–X2 · 30 · conflict",
    ]);
    // Hidden from screen readers: the keyboard list and the inspector say it to everyone.
    expect(screen.getByTestId("arc-labels")).toHaveAttribute("aria-hidden", "true");
  });

  it("reports how many labels it renders in the DOM (data-relation-labels)", () => {
    const onCount = vi.fn();
    const project = () => ({ x: 1, y: 2 });
    const { rerender } = render(
      <ArcLabels
        relations={SEVEN}
        muted={false}
        yieldTo={null}
        project={project}
        onCount={onCount}
      />,
    );
    expect(onCount).toHaveBeenLastCalledWith(5);
    rerender(
      <ArcLabels
        relations={SEVEN}
        muted={false}
        yieldTo="US-X6"
        project={project}
        onCount={onCount}
      />,
    );
    expect(onCount).toHaveBeenLastCalledWith(4);
    rerender(
      <ArcLabels relations={SEVEN} muted yieldTo={null} project={project} onCount={onCount} />,
    );
    expect(onCount).toHaveBeenLastCalledWith(0);
  });

  it("renders none while another focus mutes the arcs, and runs no frame loop", () => {
    const { container } = render(
      <ArcLabels relations={SEVEN} muted yieldTo={null} project={() => ({ x: 1, y: 2 })} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(frames.size).toBe(0);
  });

  it("renders none on a phone, where CSS hides them anyway, and runs no frame loop", () => {
    const onCount = vi.fn();
    const project = vi.fn(() => ({ x: 1, y: 2 }));
    const { container } = render(
      <ArcLabels
        relations={SEVEN}
        muted={false}
        yieldTo={null}
        project={project}
        narrow
        onCount={onCount}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(onCount).toHaveBeenLastCalledWith(0);
    expect(frames.size).toBe(0);
    expect(project).not.toHaveBeenCalled();
  });

  it("yields the inspected arc's label to its pill", () => {
    render(
      <ArcLabels
        relations={SEVEN}
        muted={false}
        yieldTo="US-X6"
        project={() => ({ x: 1, y: 2 })}
      />,
    );
    expect(tags()).toEqual([
      "US–X5 · 60 · cooperation",
      "US–X4 · 50 · conflict",
      "US–X3 · 40 · cooperation",
      "US–X2 · 30 · conflict",
    ]);
  });

  it("places each at its arc's apex in one frame loop, hiding one on the far side", () => {
    const strongest = SEVEN[6];
    const apex = arcApex(US, strongest.a);
    const project = vi.fn((lat: number) => (lat === apex.lat ? null : { x: 300, y: 200 }));
    render(<ArcLabels relations={SEVEN} muted={false} yieldTo={null} project={project} />);
    expect(frames.size).toBe(1);
    runFrame();
    const [first, second] = document.querySelectorAll<HTMLElement>(".arc-tag");
    expect(first).not.toHaveAttribute("data-placed"); // its apex faces away
    expect(second).toHaveAttribute("data-placed", "true");
    expect(second.style.left).toBe("300px");
    expect(second.style.top).toBe("200px");
    expect(frames.size).toBe(1); // the loop goes on
  });
});
