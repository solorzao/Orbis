import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, act } from "@testing-library/react";
import Sky from "./Sky";

// A 2D context that records where stars land.
function recordingContext() {
  const arcs: [number, number, number][] = [];
  const ctx = {
    arcs,
    globalAlpha: 1,
    fillStyle: "",
    setTransform: vi.fn(),
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn((x: number, y: number, r: number) => arcs.push([x, y, r])),
  };
  return ctx;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Sky", () => {
  it("renders a decorative canvas behind everything", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = render(<Sky />);
    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
    expect(canvas).toHaveAttribute("aria-hidden", "true");
    expect(canvas).toHaveClass("sky");
  });

  it("renders without a 2D context (jsdom, blocked canvas)", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    expect(() => render(<Sky />)).not.toThrow();
  });

  it("draws 260 stars on mount", () => {
    const ctx = recordingContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      ctx as unknown as CanvasRenderingContext2D,
    );
    render(<Sky />);
    expect(ctx.arcs).toHaveLength(260);
  });

  it("redraws once per burst of resizes, 150 ms after the last, with the same stars", () => {
    const ctx = recordingContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      ctx as unknown as CanvasRenderingContext2D,
    );
    render(<Sky />);
    const first = ctx.arcs.slice();

    act(() => {
      window.dispatchEvent(new Event("resize"));
      vi.advanceTimersByTime(100);
      window.dispatchEvent(new Event("resize"));
      vi.advanceTimersByTime(149);
    });
    expect(ctx.arcs).toHaveLength(260);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(ctx.arcs).toHaveLength(520);
    // Seeded: the same viewport gives the same sky, so nothing jumps.
    expect(ctx.arcs.slice(260)).toEqual(first);
  });

  it("stops listening for resizes after unmount", () => {
    const ctx = recordingContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      ctx as unknown as CanvasRenderingContext2D,
    );
    const { unmount } = render(<Sky />);
    unmount();
    act(() => {
      window.dispatchEvent(new Event("resize"));
      vi.advanceTimersByTime(500);
    });
    expect(ctx.arcs).toHaveLength(260);
  });
});
