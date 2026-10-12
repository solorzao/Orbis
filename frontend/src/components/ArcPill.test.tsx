import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import ArcPill from "./ArcPill";
import { arcApex } from "@/lib/links";
import type { CountryLink } from "@/types/news";

const US = { iso: "US", name: "United States", lat: 39.8, lng: -98.6 };
const IR = { iso: "IR", name: "Iran", lat: 32.4, lng: 53.7 };
const LINK: CountryLink = {
  a: IR,
  b: US,
  n: 41,
  lift: 1.8,
  topic: "Politics",
  tone: -0.2,
  from: "US",
};

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

describe("ArcPill", () => {
  it("renders nothing, and runs no frame loop, without a link", () => {
    const { container } = render(<ArcPill link={null} project={() => ({ x: 1, y: 2 })} />);
    expect(container).toBeEmptyDOMElement();
    expect(frames.size).toBe(0);
  });

  it("names the link at its arc's apex, following the globe each frame", () => {
    const project = vi.fn(() => ({ x: 640, y: 300 }));
    render(<ArcPill link={LINK} project={project} />);
    const pill = screen.getByTestId("arc-pill");
    expect(pill).toHaveTextContent("41 stories link United States and Iran, mostly politics");
    expect(pill.querySelector(".num")).toHaveTextContent("41");
    expect(pill).toHaveAttribute("aria-hidden", "true"); // the inspector says it for everyone
    expect(pill).not.toHaveAttribute("data-placed"); // not placed before its first frame

    runFrame();
    const apex = arcApex(US, IR);
    expect(project).toHaveBeenCalledWith(apex.lat, apex.lng, apex.altitude);
    expect(pill.style.left).toBe("640px");
    expect(pill.style.top).toBe("300px");
    expect(pill).toHaveAttribute("data-placed", "true");

    project.mockReturnValue({ x: 700, y: 320 });
    runFrame();
    expect(pill.style.left).toBe("700px");
  });

  it("hides while the apex is on the globe's far side", () => {
    const project = vi.fn<() => { x: number; y: number } | null>(() => ({ x: 640, y: 300 }));
    render(<ArcPill link={LINK} project={project} />);
    runFrame();
    project.mockReturnValue(null);
    runFrame();
    expect(screen.getByTestId("arc-pill")).not.toHaveAttribute("data-placed");
  });

  it("stops its frame loop when the link goes", () => {
    const { rerender } = render(<ArcPill link={LINK} project={() => ({ x: 1, y: 2 })} />);
    expect(frames.size).toBe(1);
    rerender(<ArcPill link={null} project={() => ({ x: 1, y: 2 })} />);
    expect(frames.size).toBe(0);
    expect(screen.queryByTestId("arc-pill")).toBeNull();
  });
});
